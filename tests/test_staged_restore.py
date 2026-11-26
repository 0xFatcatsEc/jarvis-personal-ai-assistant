import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from threading import Event

from stylus_jarvis.contracts.messages import Failure
from stylus_jarvis.memory.service import FactDraft, Origin
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories
from stylus_jarvis.storage.snapshots import configure, snapshot
from stylus_jarvis.storage.staged_restore import stage_restore


@unittest.skipUnless(os.name == "nt", "Windows staged restore acceptance")
class StagedRestoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.root = self.base / "profile"
        self.backups = self.base / "backups"
        self.backups.mkdir()
        self.key = self.base / "recovery.key"
        self.project = self.base / "work"
        self.project.mkdir()
        self.db = Database(self.root / "data" / "jarvis.sqlite3")
        self.addAsyncCleanup(self.db.close)
        await self.db.open()
        self.store = Repositories(self.db)
        self.scope = await self.store.select("owner", await self.store.register("owner", self.project), 1)
        configure(self.root, self.backups, self.key)
        self.forgotten = await self.store.confirm_fact(self.scope, FactDraft(self.scope, "Forgotten"), confirmed=True)
        self.retained = await self.store.confirm_fact(self.scope, FactDraft(self.scope, "Retained"), confirmed=True)
        self.older = await self.capture()
        await self.store.forget_fact(self.scope, self.forgotten.id, expected_version=1, confirmed=True)
        self.latest = await self.capture()

    async def capture(self) -> Path:
        identity = await asyncio.to_thread(snapshot, self.db, self.root, self.backups, self.key, Event())
        return self.backups / identity

    async def test_later_deletions_replay_before_database_is_reviewable(self) -> None:
        stage = self.base / "review"
        report = stage_restore(self.older, self.key, stage, latest_ledger_set=self.latest,
                               expected_sequence=1, protected_profile=self.root)
        self.assertEqual((report.status, report.primary_sequence, report.ledger_sequence, report.removed_facts),
                         ("ready_for_review", 0, 1, 1))
        self.assertEqual(json.loads((stage / "restore-report.json").read_bytes())["status"], report.status)
        restored = Database(stage / "data" / "jarvis.sqlite3")
        self.addAsyncCleanup(restored.close)
        await restored.open()
        repo = Repositories(restored)
        self.assertEqual(await repo.recall_facts(self.scope), [self.retained])
        with self.assertRaises(Failure):
            await repo.get_fact(self.scope, self.forgotten.id)
        with self.assertRaises(Failure):
            await repo.confirm_fact(self.scope, FactDraft(self.scope, "Forgotten", origin=Origin.INFERRED),
                                    confirmed=True)
        self.assertEqual(await self.store.recall_facts(self.scope), [self.retained])

    async def test_missing_stale_and_tampered_coverage_publish_report_only(self) -> None:
        def quarantine(name: str, **options) -> None:
            target = self.base / name
            report = stage_restore(self.older, self.key, target, **options)
            self.assertEqual(report.status, "quarantined")
            self.assertEqual([p.name for p in target.iterdir()], ["restore-report.json"])

        quarantine("absent")
        quarantine("no-coverage", latest_ledger_set=self.latest)
        quarantine("same-set", latest_ledger_set=self.older, expected_sequence=1)
        quarantine("behind", latest_ledger_set=self.latest, expected_sequence=2)
        quarantine("disallowed", latest_ledger_set=Path(r"\\unavailable.invalid\backup"), expected_sequence=1)
        quarantine("missing-artifact", latest_ledger_set=self.backups / "f0d1be71b0674a80b1b0c8dd00aab431",
                   expected_sequence=1)
        ledger = self.latest / "ledger.aesgcm"
        intact = ledger.read_bytes()
        ledger.write_bytes(intact[:-1] + bytes([intact[-1] ^ 1]))
        quarantine("tampered", latest_ledger_set=self.latest, expected_sequence=1)

    async def test_never_overwrites_and_invalid_primary_publishes_nothing(self) -> None:
        with self.assertRaises(Failure):
            stage_restore(self.older, self.key, self.root, protected_profile=self.root)
        with self.assertRaises(Failure):
            stage_restore(self.older, self.key, self.root / "fresh", protected_profile=self.root)
        wrong = self.base / "wrong.key"
        wrong.write_bytes(bytes(b ^ 1 for b in self.key.read_bytes()))
        target = self.base / "invalid"
        with self.assertRaises(Failure):
            stage_restore(self.older, wrong, target)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.base.glob(".stylus-restore-*")), [])
