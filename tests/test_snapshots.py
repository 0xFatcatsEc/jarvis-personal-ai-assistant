import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from unittest.mock import patch

from stylus_jarvis.contracts.messages import Code, Failure
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories
from stylus_jarvis.storage.snapshots import SnapshotSchedule, configure, decrypt_snapshot, snapshot


@unittest.skipUnless(os.name == "nt", "Windows scheduled backup acceptance")
class SnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.root = self.base / "profile"
        self.destination = self.base / "external"
        self.destination.mkdir()
        self.key = self.base / "key" / "recovery.key"
        self.key.parent.mkdir()
        self.project = self.base / "work"
        self.project.mkdir()
        self.db = Database(self.root / "data" / "project.sqlite3")
        self.addAsyncCleanup(self.db.close)
        await self.db.open()
        await Repositories(self.db).register("owner", self.project)

    async def test_verified_snapshot_while_wal_writer_is_open(self) -> None:
        configure(self.root, self.destination, self.key)
        with closing(sqlite3.connect(self.db.path, timeout=2)) as writer, writer:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("UPDATE projects SET owner='uncommitted update'")
            snapshot_id = await asyncio.wait_for(asyncio.to_thread(
                snapshot, self.db, self.root, self.destination, self.key, Event()), timeout=12)
            writer.execute("UPDATE projects SET owner='writer still active'")
        backup = self.destination / snapshot_id
        for kind in ("primary", "ledger"):
            blob = (backup / f"{kind}.aesgcm").read_bytes()
            self.assertNotIn(b"SQLite format", blob)
            raw = decrypt_snapshot(self.key.read_bytes(), blob, kind, snapshot_id)
            wrong_key = bytes(byte ^ 1 for byte in self.key.read_bytes())
            for key, envelope in ((wrong_key, blob), (self.key.read_bytes(), blob[:-1] + bytes([blob[-1] ^ 1]))):
                with self.assertRaises(Failure):
                    decrypt_snapshot(key, envelope, kind, snapshot_id)
            restored = self.base / f"{kind}.sqlite3"
            restored.write_bytes(raw)
            with closing(sqlite3.connect(restored)) as conn:
                self.assertEqual(conn.execute("PRAGMA quick_check").fetchone(), ("ok",))
                if kind == "primary":
                    self.assertEqual(conn.execute("SELECT owner FROM projects").fetchone(), ("owner",))
        self.assertEqual(await self.db.call(lambda c: c.execute("SELECT owner FROM projects").fetchone()[0]),
                         "writer still active")
        self.assertEqual({p.name for p in backup.iterdir()}, {"primary.aesgcm", "ledger.aesgcm"})

    async def test_daily_gate_survives_restart_and_does_not_mark_failed_backup(self) -> None:
        configure(self.root, self.destination, self.key)
        now = datetime(2026, 11, 24, tzinfo=UTC)
        schedule = SnapshotSchedule(self.db, self.root, lambda code: None, now=lambda: now)
        await asyncio.to_thread(schedule.check)
        first, = self.destination.iterdir()
        receipt = self.root / "config" / "snapshot-receipt.json"
        self.assertEqual(json.loads(receipt.read_bytes())["snapshot"], first.name)
        now += timedelta(hours=23)
        schedule = SnapshotSchedule(self.db, self.root, lambda code: None, now=lambda: now)
        await asyncio.to_thread(schedule.check)
        self.assertEqual(list(self.destination.iterdir()), [first])
        now += timedelta(hours=1)
        with patch("stylus_jarvis.storage.snapshots._seal", side_effect=OSError):
            with self.assertRaises(OSError):
                await asyncio.to_thread(schedule.check)
        self.assertEqual(list(self.destination.iterdir()), [first])
        self.assertEqual(json.loads(receipt.read_bytes())["snapshot"], first.name)
        await asyncio.to_thread(schedule.check)
        self.assertEqual(len(list(self.destination.iterdir())), 2)
        self.assertNotEqual(json.loads(receipt.read_bytes())["snapshot"], first.name)

    async def test_key_separation_and_shutdown(self) -> None:
        for key in (self.destination / "recovery.key", self.root / "recovery.key"):
            with self.assertRaises(Failure):
                configure(self.root, self.destination, key)
            self.assertFalse(key.exists())
        configure(self.root, self.destination, self.key)
        self.key.unlink()
        errors: list[Code] = []
        seen = asyncio.Event()
        loop = asyncio.get_running_loop()

        def report(code: Code) -> None:
            errors.append(code)
            loop.call_soon_threadsafe(seen.set)

        schedule = SnapshotSchedule(self.db, self.root, report)
        task = asyncio.create_task(schedule.run())
        try:
            await asyncio.wait_for(seen.wait(), timeout=5)
        finally:
            schedule.shutdown()
            await asyncio.wait_for(task, timeout=2)
        self.assertEqual(errors, [Code.STORE])
        self.assertEqual(list(self.destination.iterdir()), [])

    async def test_recovery_status_reports_age_unavailable_destination_and_scoped_inventory(self) -> None:
        store = Repositories(self.db)
        project_id = await store.register("owner", self.project)
        scope = await store.select("owner", project_id, 1)
        other_project = self.base / "other"
        other_project.mkdir()
        other_id = await store.register("owner", other_project)
        other = await store.select("owner", other_id, 2)
        available = self.project / "retained.txt"
        missing = self.project / "removed.txt"
        foreign = other_project / "foreign.txt"
        for session, path in ((scope, available), (scope, missing), (other, foreign)):
            path.write_text("source", encoding="utf-8")
            await store.approve_source(session, path)
        now = datetime(2026, 11, 24, tzinfo=UTC)
        schedule = SnapshotSchedule(self.db, self.root, lambda code: None, now=lambda: now)
        self.assertIn("Not configured", schedule.status(None).display())
        configure(self.root, self.destination, self.key)
        self.assertIn("No recorded success", schedule.status(scope).display())
        await asyncio.to_thread(schedule.check)
        new = self.project / "added-after-backup.txt"
        new.write_text("new source", encoding="utf-8")
        await store.approve_source(scope, new)
        missing.unlink()
        self.destination.rename(self.base / "disconnected")
        now += timedelta(hours=5, minutes=12)
        # A fresh schedule instance must reconstruct the previous success from disk.
        reopened = SnapshotSchedule(self.db, self.root, lambda code: None, now=lambda: now)
        status = reopened.status(scope)
        self.assertIn("5 h 12 min ago", status.display())
        self.assertIn("Backup destination is unavailable.", status.display())
        self.assertEqual(status.source_count, 2)
        self.assertEqual(status.sources, (("removed.txt", False), ("retained.txt", True)))
        self.assertEqual(reopened.status(other).sources, (("foreign.txt", True),))
        self.assertEqual(reopened.status(None).sources, ())

    async def test_recovery_status_does_not_treat_missing_artifacts_as_available(self) -> None:
        configure(self.root, self.destination, self.key)
        schedule = SnapshotSchedule(self.db, self.root, lambda code: None)
        await asyncio.to_thread(schedule.check)
        backup, = self.destination.iterdir()
        (backup / "ledger.aesgcm").unlink()
        status = schedule.status(None)
        self.assertIsNotNone(status.age)
        self.assertIn("Last verified backup files are unavailable", status.display())
