"""Classify Windows ETW events from trace-offline.ps1. Standard library only."""
import argparse
import ctypes
import hashlib
import ipaddress
import json
import ntpath
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import median
from xml.etree import ElementTree as ET


NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"
PROCESS = "Microsoft-Windows-Kernel-Process"
NETWORK = "Microsoft-Windows-Kernel-Network"
TCPIP = "Microsoft-Windows-TCPIP"
AFD = "Microsoft-Windows-Winsock-AFD"
DNS = "Microsoft-Windows-DNS-Client"
TCP_GUID = "{9a280ac0-c8e0-11d1-84e2-00c04fb998a2}"
UDP_GUID = "{bf3a50c5-a9c9-4988-a005-2df0b7c80f80}"


def epoch(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def read(directory: Path, name: str):
    return json.loads((directory / name).read_text("utf-8-sig"))


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def native_root(path: str) -> str:
    drive, tail = ntpath.splitdrive(path)
    buf = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.QueryDosDeviceW(drive, buf, len(buf)):
        raise ctypes.WinError()
    return buf.value + tail


def destination(value: str, dns: bool = False) -> str:
    address = value.strip().lower().rstrip(".")
    if not address:
        return "unknown"
    if dns and address == "localhost":
        return "loopback"
    if address.startswith("[") and "]" in address:
        address = address[1:address.index("]")]
    elif address.count(":") == 1 and "." in address:
        address = address.split(":")[0]
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return "loopback" if ip.is_loopback else "external"
    except ValueError:
        return "external" if dns else "unknown"


def activity(provider, eid, pid, data):
    if provider == TCPIP and eid in (1018, 1019, 1020, 1021, 1029, 1033, 1034):
        return int(data["ProcessId"], 0), "transport", destination(data.get("RemoteAddress", ""))
    if provider == DNS and eid in (3006, 3008):
        return pid, "dns", destination(data.get("QueryName", ""), dns=True)
    if provider == NETWORK and eid in (10, 12, 14, 16, 26, 28, 30, 32, 42, 58):
        return int(data["PID"]), "transport", destination(data.get("daddr", ""))
    if provider == AFD and eid in (4, 5, 21, 22, 1007, 1013, 1018, 1021):
        # New manifests emit entry and completion. Count the attempted call,
        # including one which never reaches the wire. Ignore completion echoes.
        if eid >= 1000 and data.get("EnterExit") != "0":
            return None
        return pid, "socket", destination(data.get("Address", ""))
    return None


def records(path: Path):
    iterator = ET.iterparse(path, events=("start", "end"))
    _, root = next(iterator)
    correction = None
    for action, element in iterator:
        if action != "end" or element.tag != NS + "Event":
            continue
        system = element.find(NS + "System")
        provider = system.find(NS + "Provider").attrib
        eid = int(system.findtext(NS + "EventID"))
        clock = epoch(system.find(NS + "TimeCreated").get("SystemTime"))
        pid = int(system.find(NS + "Execution").get("ProcessID"))
        data = {v.get("Name"): (v.text or "").strip() for v in element.findall(NS + "EventData/" + NS + "Data")}
        if provider.get("Guid", "").lower() == "{9e814aad-3204-11d2-9a82-006008a86939}" and "StartTime" in data:
            # tracerpt can round its displayed UTC offset down by one minute.
            start = int(data["StartTime"]) / 10**7 - 11644473600
            correction = start - clock
            yield start, "header", eid, pid, data
        elif correction is not None:
            name = provider.get("Name", "")
            # WPR's kernel NetworkTrace keyword produces classic TCP/IP and
            # UDP/IP events. EventID is zero and Opcode identifies the action.
            guid = element.findtext(".//{*}EventGuid", "").lower()
            if guid in (TCP_GUID, UDP_GUID):
                opcode = int(system.findtext(NS + "Opcode"))
                name, eid = NETWORK, opcode
                if guid == UDP_GUID and opcode in (10, 26):
                    eid = opcode + 32
                elif guid == UDP_GUID:
                    name = ""  # receive and other non-outbound UDP opcodes
            yield clock + correction, name, eid, pid, data
        root.clear()


def ordered_records(source, arm, boot, stop, issues, calibration):
    """Order relevant events across CPU buffers, calibrating old appended ETLs."""
    headers, rows, offsets = [], [], []
    first = epoch(arm["before"]["utc"])
    legacy_boot = arm.get("collector") is None and arm["mode"] != "Rehearsal"
    for ts, provider, eid, pid, data in source:
        if provider == "header":
            headers.append((ts, provider, eid, pid, data))
            continue
        native = None
        if provider == PROCESS and eid in (1, 2):
            field = "CreateTime" if eid == 1 else "ExitTime"
            if field in data:
                native = epoch(data[field])
                if legacy_boot and eid == 1 and boot <= native <= stop:
                    offsets.append(native - ts)
            payload = {k: data[k] for k in ("ProcessID", "ParentProcessID", "ImageName") if k in data}
        elif activity(provider, eid, pid, data) is not None:
            payload = {k: data[k] for k in ("Address", "daddr", "PID", "EnterExit", "QueryName",
                                             "ProcessId", "RemoteAddress") if k in data}
        else:
            continue
        rows.append((ts, provider, eid, pid, payload, native))

    shift = median(offsets) if offsets else 0.
    calibration["legacyPostBootStartAnchors"] = len(offsets)
    if abs(shift) > 1 and (len(offsets) < 3 or max(offsets) - min(offsets) > 1):
        issues.append("Inconsistent post-boot process clock anchors")
        shift = 0.
    calibration["legacyPostBootShiftSeconds"] = round(shift, 6) if offsets else None
    timed = []
    ambiguous = False
    for ts, provider, eid, pid, data, native in rows:
        if native is not None:
            ts = native
        elif abs(shift) > 1 and boot <= ts + shift <= stop:
            if first <= ts < boot:
                ambiguous = True
                continue
            ts += shift
        timed.append((ts, provider, eid, pid, data))
    if ambiguous:
        issues.append("Pre-boot and post-boot event clocks overlap")
    yield from headers
    yield from sorted(timed, key=lambda record: record[0])


def usable_routes(snapshot):
    if "routeInterfaces" not in snapshot:
        return snapshot["defaultRoutes"]  # legacy counts cannot exclude stale routes
    states = snapshot["routeInterfaces"]
    if len(states) != snapshot["defaultRoutes"] or any(r["state"] not in ("Connected", "Disconnected") for r in states):
        return None
    return sum(r["state"] == "Connected" for r in states)


def report(directory: Path) -> dict:
    arm = read(directory, "arm.json")
    before = read(directory, "before-workload.json")
    after = read(directory, "after-workload.json")
    stopped = read(directory, "stopped.json")
    workload = read(directory, "workload.json")
    changes = read(directory, "network-history.json")["events"]
    mode = arm["mode"]
    start, end = epoch(workload["start"]), epoch(workload["end"])
    boot = epoch(before["bootUtc"])
    since = start if mode == "Rehearsal" else boot
    issues = []
    if mode == "Rehearsal":
        issues.append("Current-session rehearsal")
    else:
        if not (before["bootType"] == 0 and before["bootRecord"] != arm["before"]["bootRecord"]
                and epoch(arm["before"]["utc"]) < boot <= start and abs(epoch(before["bootEventUtc"]) - boot) < 120):
            issues.append("Fresh full Windows boot unverified")
        for snap in (before, after, stopped):
            if snap["bootRecord"] != before["bootRecord"] or snap["bootUtc"] != before["bootUtc"]:
                issues.append("Boot changed during capture")
            routes = usable_routes(snap)
            if mode == "Connected" and not (snap["internet"] and routes):
                issues.append("Working internet unverified")
            if mode == "Disconnected" and (routes != 0 or any(snap[k] for k in ("internet", "physicalLinks", "profiles"))):
                issues.append("Disconnected condition unverified")
                if "routeInterfaces" not in snap and routes:
                    issues.append("Legacy default routes lack interface state")
        for change in changes:
            if (boot if mode == "Disconnected" else epoch(before["utc"])) <= epoch(change["utc"]) <= end:
                issues.append("Windows recorded a network profile transition")
    if not (workload["completed"] is True and workload["offline"] is True
            and epoch(before["utc"]) <= start < end <= epoch(after["utc"])):
        issues.append("Incomplete offline workload")

    roots = [ntpath.normcase(path) + "\\" for path in (arm["runtime"], native_root(arm["runtime"]))]
    processes = {}
    last_exit = {}
    snapshots = {}
    for filename in ("processes.json", "processes-final.json"):
        if (directory / filename).exists():
            for p in read(directory, filename):
                if p["image"]:
                    snapshots.setdefault(int(p["pid"]), []).append(p)
    counts = {key: Counter() for key in ("assistant", "background", "unattributed")}
    images, samples = [], []
    controls = set()
    headers = []
    first_process = None
    latest = 0.
    calibration = {}
    observed_providers = Counter()
    source = records(directory / "events.xml")
    for ts, provider, eid, pid, d in ordered_records(source, arm, boot, epoch(stopped["utc"]), issues, calibration):
        if provider == "header":
            headers.append(d)
            continue
        latest = max(latest, ts)
        if ts < since or ts > end:
            continue
        if ts >= start:
            observed_providers[provider] += 1
        if provider == PROCESS and eid in (1, 2):
            proc = int(d["ProcessID"])
            if eid == 2:
                processes.pop(proc, None)
                last_exit[proc] = ts
                continue
            first_process = ts if first_process is None else min(first_process, ts)
            image = ntpath.normcase(d["ImageName"])
            parent = int(d["ParentProcessID"])
            base = ntpath.basename(image)
            launcher = start <= ts <= end and proc == workload["launcher"] and base == "powershell.exe"
            managed = any(image.startswith(root) for root in roots)
            inherited = processes.get(parent, (False, ""))[0]
            owned = managed or inherited or launcher
            processes[proc] = (owned, base)
            if owned:
                images.append({"pid": proc, "parent": parent, "image": base})
                if launcher:
                    controls.add("launcher")
                if managed and proc == workload["desktop"] and base == "python.exe":
                    controls.add("desktop")
                if managed and inherited and base in ("ollama.exe", "llama-server.exe"):
                    controls.add(base)
            continue
        event = activity(provider, eid, pid, d)
        if event is None:
            continue
        owner, kind, dest = event
        identity = processes.get(owner)
        if identity is None and owner in snapshots:
            candidates = [p for p in snapshots[owner] if last_exit.get(owner, 0) < epoch(p["created"]) <= ts]
            if candidates:
                image = ntpath.normcase(max(candidates, key=lambda p: p["created"])["image"])
                identity = (any(image.startswith(root) for root in roots), ntpath.basename(image))
        if identity is None and owner in (0, 4):
            identity = (False, "System")
        bucket = "unattributed" if identity is None else "assistant" if identity[0] else "background"
        counts[bucket][kind + "." + dest] += 1
        if (kind == "dns" and owner == workload["dnsControl"]
                and d.get("QueryName", "").rstrip(".") == workload.get("dnsName", "stylus-control.invalid")):
            controls.add("dns")
        if (provider == AFD and eid in (21, 22, 1007, 1013) and owner == workload.get("observer")
                and dest == "loopback" and d.get("Address", "").endswith(":" + str(workload["udpPort"]))):
            controls.add("udp")
        if bucket == "assistant":
            if dest == "loopback" and owner == workload["desktop"]:
                if kind == "socket" and d.get("Address", "").endswith(":" + str(workload["port"])):
                    controls.add("socket")
                if kind == "transport" and (provider != TCPIP or (eid == 1033 and
                        d.get("RemoteAddress", "").endswith(":" + str(workload["port"])))):
                    controls.add("transport")
            if dest != "loopback" and len(samples) < 50:
                samples.append({"pid": owner, "image": identity[1], "event": eid, "kind": kind, "destination": dest})

    if not headers or any(int(h["EventsLost"]) or int(h["BuffersLost"]) for h in headers):
        issues.append("Missing ETW header or lost events/buffers")
    source_events_lost = {}
    if arm.get("collector") == "wpr-boot-v1":
        if not headers or any(h["SessionNameString"] != "Relogger" for h in headers):
            issues.append("Expected a merged WPR recording")
        loss_file = directory / "source-loss.json"
        sessions = read(directory, loss_file.name)["sessions"] if loss_file.exists() else []
        source_events_lost = {s["Name"]: s.get("EventsLost") for s in sessions}
        prefix = "wpr_initiated_stylustrace-" + arm["run"].lower() + "_"
        named = {s["Name"].lower() for s in sessions if s["Name"].lower().startswith(prefix)}
        if (not any(n.endswith("_stylusevents") for n in named)
                or not any(n.endswith("_wpr system collector") for n in named)
                or any(s.get("EventsLost") is None or int(s["EventsLost"]) != 0 for s in sessions)):
            issues.append("Original WPR session loss counters missing or nonzero")
    elif any(h["SessionNameString"] != "NetTrace-StylusTrace-" + arm["run"] for h in headers):
        issues.append("Unexpected ETW session")
    if latest < end or (mode != "Rehearsal" and (first_process is None or first_process > boot + 120)):
        issues.append("Capture does not span boot/workload")
    required = {"desktop", "launcher", "ollama.exe", "llama-server.exe", "socket", "transport", "dns"}
    if arm.get("collector") == "wpr-boot-v1":
        required.add("udp")
    if required - controls:
        issues.append("Missing positive controls: " + ", ".join(sorted(required - controls)))
    if any(v for k, v in counts["unattributed"].items() if not k.endswith(".loopback")):
        issues.append("Unattributed external or unparsed activity")
    if any(v for k, v in counts["assistant"].items() if k.endswith(".unknown")):
        issues.append("Unparsed assistant destination")
    external = sum(v for k, v in counts["assistant"].items() if k.endswith(".external"))
    status = "fail" if external else "inconclusive" if issues else "pass"
    return dict(run=arm["run"], mode=mode, bootUtc=before["bootUtc"], bootRecord=before["bootRecord"],
                bootType=before["bootType"], start=workload["start"], end=workload["end"],
                internet=before["internet"], status=status, issues=sorted(set(issues)),
                observedAssistantExternalEvents=external, counts=counts, controls=sorted(controls),
                workloadProviderEvents=observed_providers,
                clockCalibration=calibration, zeroExternalVerified=None if status == "inconclusive" else status == "pass",
                processes=images, findings=samples, eventsLost=[int(h["EventsLost"]) for h in headers],
                buffersLost=[int(h["BuffersLost"]) for h in headers], sourceEventsLost=source_events_lost,
                etlSha256=sha(directory / "traffic.etl"))


def pair(left: dict, right: dict) -> bool:
    return ({left["mode"], right["mode"]} == {"Disconnected", "Connected"}
            and all(r["status"] == "pass" for r in (left, right))
            and left["bootUtc"] != right["bootUtc"] and left["etlSha256"] != right["etlSha256"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="+")
    folders = parser.parse_args().directory
    if len(folders) not in (1, 2):
        parser.error("supply one capture or two boot captures")
    results = []
    for folder in folders:
        result = report(folder)
        (folder / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(result["mode"], result["status"], result["issues"])
        results.append(result)
    if len(results) == 2:
        same_machine = read(folders[0], "arm.json")["machine"] == read(folders[1], "arm.json")["machine"]
        raise SystemExit(0 if same_machine and pair(*results) else 1)
    raise SystemExit(0 if result["status"] == "pass" else 1)
