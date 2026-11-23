"""Windows acceptance logic for process-attributed ETW evidence (no network needed)."""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("trace_report", Path(__file__).resolve().parents[1]
                                              / "packaging/windows/trace_report.py")
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)


def utc(seconds):
    return datetime.fromtimestamp(seconds, UTC).isoformat()


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.directory / "traffic.etl").write_bytes(b"synthetic")
        snapshot = dict(utc=utc(199), bootUtc=utc(100), bootRecord=5, bootType=0,
                        bootEventUtc=utc(101), internet=True, defaultRoutes=1, physicalLinks=1, profiles=1)
        self.docs = {
            "arm.json": dict(before=dict(utc=utc(90), bootRecord=2), mode="Connected", run="fixture",
                             runtime=r"C:\profile\runtime"),
            "before-workload.json": snapshot, "after-workload.json": {**snapshot, "utc": utc(249)},
            "stopped.json": {**snapshot, "utc": utc(250)}, "network-history.json": {"events": []},
            "workload.json": dict(start=utc(200), end=utc(240), completed=True, offline=True, port=4567,
                                  launcher=10, desktop=20, dnsControl=30),
        }
        self.header = dict(EventsLost="0", BuffersLost="0", SessionNameString="NetTrace-StylusTrace-fixture")
        self.events = [(90, "header", 0, 0, self.header)]
        for ts, pid, parent, image in [
            (101, 40, 4, r"C:\Windows\System32\services.exe"),
            (201, 30, 40, r"C:\Windows\powershell.exe"), (202, 10, 40, r"C:\Windows\powershell.exe"),
            (203, 11, 10, r"C:\profile\runtime\ollama\ollama.exe"),
            (204, 12, 11, r"C:\profile\runtime\ollama\lib\ollama\llama-server.exe"),
            (205, 20, 40, r"C:\profile\runtime\python\python.exe"),
        ]:
            self.process(ts, pid, parent, image)
        self.events += [
            (206, trace.AFD, 1021, 20, {"Address": "127.0.0.1:4567", "EnterExit": "0"}),
            (207, trace.NETWORK, 10, 4, {"PID": "20", "daddr": "::1"}),
            (208, trace.DNS, 3006, 30, {"QueryName": "stylus-control.invalid"}),
            (241, trace.PROCESS, 2, 4, {"ProcessID": 40}),
        ]

    def process(self, ts, pid, parent, image):
        self.events.append((ts, trace.PROCESS, 1, 4, dict(ProcessID=pid, ParentProcessID=parent, ImageName=image)))

    def score(self):
        with (patch.object(trace, "read", side_effect=lambda _, name: self.docs[name]),
              patch.object(trace, "records", return_value=iter(self.events)),
              patch.object(trace, "native_root", return_value=r"\Device\Volume1\profile\runtime")):
            return trace.report(self.directory)

    def test_two_distinct_full_boot_modes_required(self):
        connected = self.score()
        self.assertEqual(connected["status"], "pass")
        self.docs["arm.json"]["mode"] = "Disconnected"
        self.assertEqual(self.score()["status"], "inconclusive")
        for name in ("before-workload.json", "after-workload.json", "stopped.json"):
            self.docs[name].update(internet=False, physicalLinks=0, profiles=0, defaultRoutes=0)
        offline = self.score()
        self.assertEqual(offline["status"], "pass")
        self.assertFalse(trace.pair(connected, offline))
        self.assertTrue(trace.pair(connected, {**offline, "bootUtc": utc(501), "etlSha256": "different"}))
        self.docs["before-workload.json"]["bootType"] = 2
        self.assertEqual(self.score()["status"], "inconclusive")

    def test_blocked_connect_and_cached_dns_from_short_lived_descendant_fail(self):
        self.process(209, 77, 20, r"C:\Windows\helper.exe")
        self.events += [
            (210, trace.AFD, 1018, 77, {"Address": "[2001:db8::1]:443", "EnterExit": "0"}),
            (211, trace.DNS, 3006, 77, {"QueryName": "update.invalid"}),
            (212, trace.PROCESS, 2, 4, {"ProcessID": 77}),
        ]
        self.process(213, 77, 40, r"C:\unrelated\ollama.exe")
        self.events.append((214, trace.NETWORK, 42, 4, {"PID": "77", "daddr": "192.0.2.5"}))
        report = self.score()
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["observedAssistantExternalEvents"], 2)
        self.assertEqual(report["counts"]["background"]["transport.external"], 1)

    def test_empty_loss_unknown_and_network_change_are_inconclusive(self):
        for field in ("EventsLost", "BuffersLost"):
            with patch.dict(self.header, {field: "1"}):
                self.assertEqual(self.score()["status"], "inconclusive")
        self.events.append((215, trace.NETWORK, 10, 4, {"PID": "999", "daddr": "192.0.2.1"}))
        self.assertEqual(self.score()["status"], "inconclusive")
        self.events.pop()
        self.docs["network-history.json"]["events"] = [dict(utc=utc(220), id=10001)]
        self.assertEqual(self.score()["status"], "inconclusive")
        self.events.clear()
        self.assertEqual(self.score()["status"], "inconclusive")

    def test_address_formats_do_not_allow_private_or_malformed_peers(self):
        for value in ("[::1]:123", "[::ffff:127.0.0.7]:42", "127.0.0.2:80"):
            self.assertEqual(trace.destination(value), "loopback")
        self.assertEqual(trace.destination("10.0.0.1:80"), "external")
        self.assertEqual(trace.destination("garbled"), "unknown")

    def test_cross_boot_qpc_reset_and_unordered_buffers(self):
        for index, (ts, provider, eid, pid, data) in enumerate(self.events):
            if provider == "header":
                continue
            fields = dict(data)
            if provider == trace.PROCESS:
                fields["CreateTime" if eid == 1 else "ExitTime"] = utc(ts)
            self.events[index] = (ts - 238212, provider, eid, pid, fields)
        # The historical PID and the pre-boot transport must stay outside the
        # measured interval. Native timestamps independently anchor the restart.
        self.events.append((91, trace.NETWORK, 10, 4, {"PID": "20", "daddr": "192.0.2.1"}))
        self.events.reverse()
        self.assertEqual(self.score()["status"], "pass")
        self.events = [e for e in self.events if e[1] != trace.NETWORK or e[0] == 91]
        result = self.score()
        self.assertIn("Missing positive controls: transport", result["issues"])
        self.assertFalse(result["observedAssistantExternalEvents"])

    def test_disconnected_route_requires_observed_interface_state(self):
        def snapshot(state):
            return {"defaultRoutes": 1, "routeInterfaces": [{"state": state}]}
        self.assertEqual(trace.usable_routes(snapshot("Disconnected")), 0)
        self.assertEqual(trace.usable_routes(snapshot("Connected")), 1)
        self.assertIsNone(trace.usable_routes(snapshot("Unknown")))
        self.assertIsNone(trace.usable_routes({"defaultRoutes": 2, "routeInterfaces": []}))
        self.assertEqual(trace.usable_routes({"defaultRoutes": 1}), 1)

    def test_independent_transport_witness_uses_outbound_driver_pid_and_model_port(self):
        data = {"ProcessId": "0x14", "RemoteAddress": "127.0.0.1:4567"}
        self.events = [e for e in self.events if e[1] != trace.NETWORK]
        self.events.append((207, trace.TCPIP, 1017, 4, data))  # inbound accept
        self.assertNotIn("transport", self.score()["controls"])
        self.events.append((208, trace.TCPIP, 1033, 4, {**data, "RemoteAddress": "127.0.0.1:777"}))
        self.assertNotIn("transport", self.score()["controls"])
        self.events.append((209, trace.TCPIP, 1033, 4, data))
        self.assertEqual(self.score()["status"], "pass")
        self.events.append((210, trace.TCPIP, 1034, 4, {**data, "RemoteAddress": "[2001:db8::1]:443"}))
        self.assertEqual(self.score()["status"], "fail")

    def test_merged_capture_requires_udp_binding_and_original_loss_counters(self):
        self.docs["arm.json"]["collector"] = "wpr-boot-v1"
        self.header["SessionNameString"] = "Relogger"
        self.docs["workload.json"].update(observer=30, udpPort=7000)
        self.assertIn("Missing positive controls: udp", self.score()["issues"])
        self.events.append((209, trace.AFD, 1007, 30, {"Address": "127.0.0.1:7000", "EnterExit": "0"}))
        self.assertEqual(self.score()["status"], "inconclusive")
        (self.directory / "source-loss.json").touch()
        sessions = [{"Name": "WPR_initiated_StylusTrace-fixture_boottr_" + label, "EventsLost": 0}
                    for label in ("StylusEvents", "WPR System Collector")]
        self.docs["source-loss.json"] = {"sessions": sessions}
        self.assertEqual(self.score()["status"], "pass")
        sessions[0]["EventsLost"] = 1
        self.assertEqual(self.score()["status"], "inconclusive")

    def test_tracerpt_clock_uses_native_header_and_payload_pid(self):
        # This Windows build renders +07:59 for an actual +08:00 offset.
        path = self.directory / "events.xml"
        def event(provider, eid, seconds, fields):
            return (f'<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System>'
                    f'<Provider {provider}/><EventID>{eid}</EventID>'
                    f'<TimeCreated SystemTime="1970-01-01T08:00:{seconds:02}+07:59"/>'
                    '<Execution ProcessID="4"/></System><EventData>'
                    + ''.join(f'<Data Name="{k}">{v}</Data>' for k, v in fields.items())
                    + '</EventData></Event>')
        header = event('Guid="{9e814aad-3204-11d2-9a82-006008a86939}"', 0, 0,
                       {"StartTime": 11644473600 * 10**7})
        net = event('Name="Microsoft-Windows-Kernel-Network"', 10, 15, {"PID": 20, "daddr": "::1"})
        path.write_text("<Events>" + header + net + "</Events>", encoding="utf-8")
        _, (ts, *row) = list(trace.records(path))
        self.assertEqual(ts, 15.)
        self.assertEqual(trace.activity(*row), (20, "transport", "loopback"))
        for header_offset in ("+07:59", "+08:00"):
            with self.subTest(header_offset=header_offset):
                xml = header.replace("+07:59", header_offset) + net + net.replace("+07:59", "+08:00")
                path.write_text("<Events>" + xml + "</Events>", encoding="utf-8")
                self.assertEqual([ts for ts, *_ in trace.records(path)], [0., 15., 15.])


@unittest.skipUnless(os.name == "nt", "requires Windows PowerShell")
class TraceControllerTests(unittest.TestCase):
    def test_wpr_boot_output_names(self):
        helper = Path(__file__).resolve().parents[1] / "packaging/windows/resolve-boot-etl.ps1"
        for names, expected in [
            (["StylusTrace-fixture"], b"StylusTrace-fixture"),
            (["-force"], b"-force"),
            (["traffic.etl", "-force"], b"traffic.etl"),
            (["logger.etl"], None),
            (["StylusTrace-fixture", "-force"], None),
        ]:
            with self.subTest(names=names), tempfile.TemporaryDirectory(prefix="trace test ") as tmp:
                directory = Path(tmp)
                for name in names:
                    (directory / name).write_bytes(name.encode())
                result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
                                         str(helper), "-Directory", tmp, "-RunId", "fixture"],
                                        capture_output=True, timeout=30)
                self.assertEqual(result.returncode == 0, names != ["StylusTrace-fixture", "-force"])
                target = directory / "traffic.etl"
                self.assertEqual(target.read_bytes() if target.exists() else None, expected)

    def test_premature_finish_preserves_recording(self):
        shell = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
        profile = subprocess.check_output(shell + ["[Environment]::GetFolderPath('LocalApplicationData')"],
                                          text=True).strip()
        root = Path(profile) / "StylusJarvis/traces"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="test-finish-", dir=root) as temporary:
            folder = Path(temporary)
            (folder / "arm.json").write_text(json.dumps(dict(
                mode="Disconnected", run=folder.name, machine=os.environ["COMPUTERNAME"],
                collector="wpr-boot-v1")), encoding="utf-8")
            journal = folder / "workload.json"
            for completed in (None, False, "true", True):
                with self.subTest(completed=completed):
                    if completed is not None:
                        journal.write_text(json.dumps({"completed": completed}), encoding="utf-8")
                    after = folder / "after-workload.json"
                    if completed is True:
                        after.unlink()  # completed journal, but Run has not saved its final snapshot
                    else:
                        after.write_text("{}", encoding="utf-8")
                    before = set(folder.iterdir())
                    command = ("function wpr.exe { throw 'Unexpected recorder call' }\n"
                               "& .\\packaging\\windows\\trace-offline.ps1 -Action Finish "
                               f"-Mode Disconnected -RunId {folder.name}")
                    result = subprocess.run(shell + [command], cwd=Path(__file__).resolve().parents[1],
                                            capture_output=True, text=True, timeout=30)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Finish requires a completed workload", result.stderr)
                    self.assertEqual(set(folder.iterdir()), before)


@unittest.skipUnless(os.name == "nt" and os.environ.get("STYLUS_BOOT_ACCEPTANCE") == "1",
                     "requires two recorded cold boots on the Windows target")
class RecordedWindowsPair(unittest.TestCase):
    def test_offline_stack_across_distinct_cold_boots(self):
        root = Path(os.environ["LOCALAPPDATA"]) / "StylusJarvis/traces"
        directories = [root / os.environ.get("STYLUS_DISCONNECTED_RUN", "cold-disconnected-06"),
                       root / os.environ.get("STYLUS_CONNECTED_RUN", "cold-connected-01")]
        self.assertEqual(*(trace.read(folder, "arm.json")["machine"] for folder in directories))
        results = []
        for folder in directories:
            result = trace.report(folder)
            self.assertEqual(result["status"], "pass", (result["issues"], result["findings"]))
            self.assertEqual(result["etlSha256"], trace.read(folder, "report.json")["etlSha256"])
            results.append(result)
        self.assertTrue(trace.pair(*results))
