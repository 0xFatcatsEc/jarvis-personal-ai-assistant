"""Windows schema-6/7 migration, encrypted restore, and rollback rehearsal."""
import argparse
import asyncio
import hashlib
import io
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import winreg
import zipfile
from pathlib import Path

PREVIOUS = "aa1c7fb"
REPO = Path(__file__).resolve().parents[2]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


async def worker(action: str, root: Path, wheel: Path) -> dict[str, object]:
    from datetime import UTC, datetime, timedelta
    from threading import Event
    from uuid import uuid4

    sys.path.insert(0, str(wheel))
    from stylus_jarvis.contracts.messages import Failure, State
    from stylus_jarvis.memory.service import FactDraft, Origin
    from stylus_jarvis.storage.database import Database
    from stylus_jarvis.storage.repositories import Repositories

    record = root / "fixture.json"
    live = root / "upgrade" / "data" / "jarvis.sqlite3"
    database = root / "rollback" / "data" / live.name if action == "rollback" else live

    async def inspect(db: Database, expected_schema: int, *, restored: bool = False) -> None:
        repo = Repositories(db)
        data = json.loads(record.read_bytes())
        scope = await repo.select("fixture-owner", data["project"], 1, data["conversation"])
        require(await db.call(lambda c: c.execute("SELECT max(version) FROM migrations").fetchone()[0])
                == expected_schema, "Unexpected SQLite schema")
        messages = [row[1:] for row in await repo.history(scope)]
        require(messages == [("user", "What did we decide?", "completed"),
                             ("assistant", "Use the retained plan.", "completed")], "Conversation changed")
        retained = await repo.get_fact(scope, data["retained"])
        require(retained.text == "Use the retained plan.", "Reference fact changed")
        excerpt = await repo.resolve_locator(scope, retained.source, retained.revision, retained.locator)
        require((excerpt.excerpt, excerpt.start, excerpt.end) == ("Use the retained plan.", 0, 22), "Citation changed")
        ids = {fact.id for fact in await repo.recall_facts(scope)}
        require(ids == ({data["retained"]} if restored else {data["retained"], data["forgotten"]}),
                "Unexpected remembered facts")
        if restored:
            try:
                await repo.confirm_fact(scope, FactDraft(scope, "Cancelled plan", origin=Origin.INFERRED),
                                        confirmed=True)
            except Failure:
                pass
            else:
                raise RuntimeError("Forgotten memory returned")

    db = Database(database)
    await db.open()
    try:
        if action == "seed":
            project = root / "project"
            project.mkdir()
            source = project / "decision.txt"
            source.write_bytes(b"Use the retained plan.")
            repo = Repositories(db)
            scope = await repo.select("fixture-owner", await repo.register("fixture-owner", project), 1)
            turn, _ = await repo.begin(scope, uuid4(), "What did we decide?", "0" * 64)
            await repo.finish(scope, turn.key, State.COMPLETED, "Use the retained plan.", None)
            revision = await repo.approve_source(scope, source)
            loc, = await repo.extract_locators(scope, revision.source_id, revision.revision_id)
            retained = await repo.confirm_fact(scope, FactDraft(scope, loc.excerpt, locator=loc.id), confirmed=True)
            forgotten = await repo.confirm_fact(scope, FactDraft(scope, "Cancelled plan"), confirmed=True)
            record.write_text(json.dumps({"project": scope.project, "conversation": scope.conversation,
                                          "retained": retained.id, "forgotten": forgotten.id}), encoding="utf-8")
            await inspect(db, 6)
            return {"schema": 6}
        if action == "rollback":
            await inspect(db, 6)
            return {"schema": 6, "conversation_fact_and_citation_reopened": True}

        from stylus_jarvis.storage.snapshots import configure, snapshot, SnapshotSchedule
        from stylus_jarvis.storage.staged_restore import stage_restore

        await inspect(db, 7)
        backups, independent, key = root / "backups", root / "independent", root / "keys" / "recovery.key"
        backups.mkdir()
        independent.mkdir()
        key.parent.mkdir()
        configure(root / "upgrade", backups, key)
        clock = datetime(2026, 11, 24, tzinfo=UTC)
        schedule = SnapshotSchedule(db, root / "upgrade", lambda code: None, now=lambda: clock)
        await asyncio.to_thread(schedule.check)
        receipt = json.loads((root / "upgrade" / "config" / "snapshot-receipt.json").read_bytes())
        oldest = backups / receipt["snapshot"]
        data = json.loads(record.read_bytes())
        repo = Repositories(db)
        scope = await repo.select("fixture-owner", data["project"], 1, data["conversation"])
        await repo.forget_fact(scope, data["forgotten"], expected_version=1, confirmed=True)
        await repo.confirm_fact(scope, FactDraft(scope, "After the recovery point"), confirmed=True)
        sequence = await db.call(lambda c: c.execute("SELECT sequence FROM memory_ledger_binding").fetchone()[0])
        latest = await asyncio.to_thread(snapshot, db, root / "upgrade", independent, key, Event())
        (root / "project" / "decision.txt").unlink()
        status = await asyncio.to_thread(schedule.status, scope)
        require(status.sources == (("decision.txt", False),), "Missing original not reported")
        quarantined = await asyncio.to_thread(stage_restore, oldest, key, root / "quarantine")
        require(quarantined.status == "quarantined" and not (root / "quarantine" / "data").exists(),
                "Incomplete coverage did not quarantine")

        recovery_point = datetime.fromisoformat(receipt["at"])
        incident = clock + timedelta(hours=23, minutes=59)
        start = time.perf_counter()
        staged = root / "clean"
        report = await asyncio.to_thread(stage_restore, oldest, key, staged, latest_ledger_set=independent / latest,
                                         expected_sequence=sequence)
        require(report.status == "ready_for_review" and report.removed_facts == 1, "Later deletion not replayed")
        recovered = Database(staged / "data" / live.name)
        await recovered.open()
        try:
            await inspect(recovered, 7, restored=True)
        finally:
            await recovered.close()
        elapsed = time.perf_counter() - start
        loss_window = (incident - recovery_point).total_seconds()
        require(elapsed <= 1800 and 0 <= loss_window <= 86400, "Recovery target missed")
        return {"schema": 7, "restore_seconds": round(elapsed, 3),
                "simulated_recovery_point_age_seconds": loss_window,
                "conversation_fact_and_citation_reopened": True, "missing_original_reported": True,
                "missing_coverage_quarantined": True, "later_deletions_replayed": report.removed_facts}
    finally:
        await db.close()


def build(source: Path, output: Path, constraint: Path) -> Path:
    subprocess.run(["uv", "build", "--offline", "--wheel", "--python", sys.executable, "--build-constraint", constraint.name,
                    "--out-dir", str(output), str(source)], cwd=constraint.parent, check=True)
    wheel, = output.glob("*.whl")
    return wheel


def run(output: Path) -> None:
    from datetime import UTC, datetime

    require(os.name == "nt", "Windows target required")
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as bios:
        model = winreg.QueryValueEx(bios, "SystemProductName")[0]
    require(model == "Thin A15 B7UC", "Run on the MSI Thin A15 qualification target")
    with tempfile.TemporaryDirectory(prefix="stylus-rehearsal-") as temp:
        root = Path(temp).resolve()
        previous = root / "previous"
        source = root / "candidate"
        archive = subprocess.check_output(["git", "-c", "core.autocrlf=false", "archive", "--format=zip",
                                          PREVIOUS, "src/stylus_jarvis", "pyproject.toml"], cwd=REPO)
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            zipped.extractall(previous)
        shutil.copytree(REPO / "src" / "stylus_jarvis", source / "src" / "stylus_jarvis",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copyfile(REPO / "pyproject.toml", source / "pyproject.toml")
        constraint = root / "build-constraints.txt"
        constraint.write_text("setuptools==84.2.1\n", encoding="ascii")
        previous_wheel = build(previous, root / "previous-wheel", constraint)
        current_wheel = build(source, root / "current-wheel", constraint)

        def examine(action: str, wheel: Path) -> dict[str, object]:
            result = subprocess.check_output([sys.executable, "-I", "-B", __file__, "--worker", action,
                                              "--root", str(root), "--wheel", str(wheel)], timeout=1800)
            return json.loads(result)

        seed = examine("seed", previous_wheel)
        upgrade = examine("upgrade", current_wheel)
        snapshot_file, = (root / "upgrade" / "data").glob("*.pre-7-*.sqlite3")
        rollback_db = root / "rollback" / "data" / "jarvis.sqlite3"
        rollback_db.parent.mkdir(parents=True)
        shutil.copyfile(snapshot_file, rollback_db)
        start = time.perf_counter()
        rollback = examine("rollback", previous_wheel)
        report = {"format": 1, "fixture": "phase2-recovery-v1", "target": model,
                  "recorded_at_utc": datetime.now(UTC).isoformat(), "windows": platform.version(),
                  "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                  "previous_commit": PREVIOUS, "schema_path": [seed["schema"], upgrade["schema"], rollback["schema"]],
                  "previous_wheel_sha256": hashlib.sha256(previous_wheel.read_bytes()).hexdigest(),
                  "candidate_wheel_sha256": hashlib.sha256(current_wheel.read_bytes()).hexdigest(),
                  "pre_upgrade_snapshot_sha256": hashlib.sha256(snapshot_file.read_bytes()).hexdigest(),
                  "restore": upgrade, "rollback": rollback | {"seconds": round(time.perf_counter() - start, 3)}}
    with output.open("x", encoding="utf-8") as target:
        json.dump(report, target, indent=2)
        target.write("\n")
    print(f"PASS: recorded MSI restore and schema 6 → 7 → 6 rollback in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", choices=("seed", "upgrade", "rollback"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--wheel", type=Path)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(asyncio.run(worker(args.worker, args.root, args.wheel))))
    elif args.output:
        run(args.output.resolve())
    else:
        parser.error("--output is required")
