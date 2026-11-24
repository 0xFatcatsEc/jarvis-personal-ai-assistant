import asyncio
import hashlib
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from stylus_jarvis.contracts.messages import Code, Failure
from stylus_jarvis.knowledge.ingestion import fingerprint
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories


@unittest.skipUnless(os.name == "nt", "Windows source registry acceptance")
class SourceRevisionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.root = self.base / "coursework"
        self.root.mkdir()
        self.file = self.root / "Brief.txt"
        self.file.write_bytes(b"version one")
        self.db = Database(self.base / "profile" / "db.sqlite3")
        self.addAsyncCleanup(self.db.close)
        await self.db.open()
        self.repo = Repositories(self.db)
        project = await self.repo.register("owner", self.root)
        self.scope = await self.repo.select("owner", project, 1)

    async def test_01_replacement_and_historical_address_after_restart(self) -> None:
        first = await self.repo.approve_source(self.scope, self.file)
        replacement = self.root / "temporary"
        replacement.write_bytes(b"version two")
        replacement.replace(self.file)
        second = await self.repo.approve_source(self.scope, self.file)
        self.assertEqual(first.source_id, second.source_id)
        self.assertNotEqual(first.revision_id, second.revision_id)
        self.assertEqual([r.sha256 for r in (first, second)],
                         [hashlib.sha256(b).hexdigest() for b in (b"version one", b"version two")])
        self.file.unlink()
        await self.db.close()
        reopened = Database(self.db.path)
        self.addAsyncCleanup(reopened.close)
        await reopened.open()
        for receipt in (first, second):
            self.assertEqual(await Repositories(reopened).source_revision(
                self.scope, receipt.source_id, receipt.revision_id), receipt)
        with self.assertRaises(Failure):
            await reopened.call(lambda c: c.execute("UPDATE source_revisions SET byte_count=0"), write=True)

    async def test_concurrent_approval_and_scope_checks(self) -> None:
        a, b = await asyncio.gather(self.repo.approve_source(self.scope, self.file),
                                    self.repo.approve_source(self.scope, self.file))
        self.assertEqual(a, b)
        other = self.base / "other"
        other.mkdir()
        other_file = other / self.file.name
        other_file.write_bytes(self.file.read_bytes())
        scope = await self.repo.select("owner", await self.repo.register("owner", other), 2)
        self.assertNotEqual((await self.repo.approve_source(scope, other_file)).source_id, a.source_id)
        for invalid in (scope, replace(self.scope, owner="other"), replace(self.scope, offline=False)):
            with self.assertRaises(Failure):
                await self.repo.source_revision(invalid, a.source_id, a.revision_id)
        with self.assertRaises(Failure):
            await self.repo.approve_source(self.scope, other_file)
        linked = self.root / "linked"
        os.link(other_file, linked)
        with self.assertRaises(Failure):
            await self.repo.approve_source(self.scope, linked)

    async def test_revocation_during_hash_rolls_back_admission(self) -> None:
        import sqlite3
        from contextlib import closing

        def revoke(root: Path, path: Path) -> tuple[str, str, int]:
            result = fingerprint(root, path)
            with closing(sqlite3.connect(self.db.path)) as conn, conn:
                conn.execute("UPDATE projects SET grant=grant+1")
            return result

        with patch("stylus_jarvis.storage.repositories.fingerprint", revoke), self.assertRaises(Failure) as denied:
            await self.repo.approve_source(self.scope, self.file)
        self.assertEqual(denied.exception.code, Code.SCOPE)
        self.assertEqual(await self.db.call(lambda c: c.execute("SELECT count(*) FROM sources").fetchone()[0]), 0)
