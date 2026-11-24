import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from stylus_jarvis.contracts.messages import Code, Failure
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories


@unittest.skipUnless(os.name == "nt", "Windows scoped FTS5 acceptance")
class ScopedIndexTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.root = self.base / "atlas"
        self.root.mkdir()
        self.file = self.root / "guide.txt"
        await self.open_store()
        self.scope = await self.store.select("owner", await self.store.register("owner", self.root), 1)

    async def open_store(self):
        self.db = Database(self.base / "profile" / "db.sqlite3")
        self.addAsyncCleanup(self.db.close)
        await self.db.open()
        self.store = Repositories(self.db)

    async def prepare(self, text):
        self.file.write_text(text, encoding="utf-8")
        revision = await self.store.approve_source(self.scope, self.file)
        pair = revision.source_id, revision.revision_id
        return pair, await self.store.extract_locators(self.scope, *pair)

    async def test_publication_reopen_replacement_and_rename(self):
        pair, records = await self.prepare("green alpha ".ljust(1024) + "green beta")
        self.assertFalse(await self.store.search_evidence(self.scope, "green"))
        await self.store.publish_revision(self.scope, *pair)
        await self.store.publish_revision(self.scope, *pair)
        await self.db.close()
        await self.open_store()
        hits = await self.store.search_evidence(self.scope, "green")
        self.assertEqual([h.locator for h in hits], [r.id for r in records])
        for hit in hits:
            resolved = await self.store.resolve_locator(self.scope, hit.source, hit.revision, hit.locator)
            self.assertIn("green", resolved.excerpt)
        newer, _ = await self.prepare("gold gamma")
        await self.store.publish_revision(self.scope, *newer, replaces=pair)
        self.assertFalse(await self.store.search_evidence(self.scope, "green"))
        self.assertEqual(await self.store.search_evidence(self.scope, "green", revision=pair[1]), hits)
        renamed = self.file.with_name("renamed.txt")
        self.file.rename(renamed)
        self.file = renamed
        moved, _ = await self.prepare("gold gamma")
        await self.store.publish_revision(self.scope, *moved, replaces=newer)
        self.assertEqual([h.relative_path for h in await self.store.search_evidence(self.scope, "gold")],
                         ["renamed.txt"])
        self.assertEqual((await self.store.search_evidence(self.scope, "gold", revision=newer[1]))[0].source, newer[0])
        with self.assertRaises(Failure):
            await self.store.publish_revision(self.scope, *newer)

    async def test_failure_after_first_posting_preserves_previous_view(self):
        old, _ = await self.prepare("original")
        await self.store.publish_revision(self.scope, *old)
        new, records = await self.prepare("candidate ".ljust(1024) + "candidate")
        observed = []

        def interrupt(conn):
            def inspect():
                with closing(sqlite3.connect(self.db.path)) as reader:
                    rows = reader.execute("SELECT count(*) FROM evidence_fts WHERE evidence_fts MATCH 'candidate'")
                    observed.append((rows.fetchone()[0], reader.execute("SELECT revision FROM active_evidence").fetchone()[0]))
                return 1
            conn.create_function("inspect_reader", 0, inspect)
            conn.execute("CREATE TEMP TRIGGER stop_publication BEFORE INSERT ON indexed_locators "
                         "WHEN (SELECT count(*) FROM indexed_locators) = 2 BEGIN "
                         "SELECT inspect_reader(); SELECT RAISE(ABORT,'fixture'); END")
        await self.db.call(interrupt)
        with self.assertRaises(Failure):
            await self.store.publish_revision(self.scope, *new, replaces=old)
        self.assertEqual(observed, [(0, old[1])])
        self.assertTrue(await self.store.search_evidence(self.scope, "original"))
        self.assertFalse(await self.store.search_evidence(self.scope, "candidate", revision=new[1]))
        await self.db.call(lambda c: c.execute("DROP TRIGGER stop_publication"))
        await self.store.publish_revision(self.scope, *new, replaces=old)
        self.assertEqual(len(await self.store.search_evidence(self.scope, "candidate")), len(records))

    async def test_scope_revocation_and_unextracted_revision(self):
        pair, _ = await self.prepare("private coursework")
        other = self.base / "birch"
        other.mkdir()
        scope = await self.store.select("owner", await self.store.register("owner", other), 2)
        with self.assertRaises(Failure):
            await self.store.publish_revision(scope, *pair)
        await self.store.publish_revision(self.scope, *pair)
        for revision in (None, pair[1]):
            self.assertEqual(await self.store.search_evidence(scope, "private", revision=revision), [])
        other_file = other / self.file.name
        other_file.write_text("private separate coursework", encoding="utf-8")
        foreign = await self.store.approve_source(scope, other_file)
        other_pair = foreign.source_id, foreign.revision_id
        await self.store.extract_locators(scope, *other_pair)
        with self.assertRaises(Failure):
            await self.store.publish_revision(scope, *other_pair, replaces=pair)
        await self.store.publish_revision(scope, *other_pair)
        self.assertEqual([h.source for h in await self.store.search_evidence(scope, "private")], [other_pair[0]])
        self.assertEqual([h.source for h in await self.store.search_evidence(self.scope, "private")], [pair[0]])
        self.file.write_text("unpublished", encoding="utf-8")
        pending = await self.store.approve_source(self.scope, self.file)
        with self.assertRaises(Failure) as missing:
            await self.store.publish_revision(self.scope, pair[0], pending.revision_id, replaces=pair)
        self.assertEqual(missing.exception.code, Code.CONFLICT)
        await self.store.extract_locators(self.scope, pair[0], pending.revision_id)
        await self.db.call(lambda c: c.execute("UPDATE projects SET grant=grant+1 WHERE id=?",
                                               (self.scope.project,)), write=True)
        with self.assertRaises(Failure) as revoked:
            await self.store.publish_revision(self.scope, pair[0], pending.revision_id, replaces=pair)
        self.assertEqual(revoked.exception.code, Code.SCOPE)
        with self.assertRaises(Failure):
            await self.store.search_evidence(self.scope, "private")
        self.assertEqual(await self.db.call(lambda c: c.execute(
            "SELECT revision FROM active_evidence WHERE source=?", (pair[0],)).fetchone()[0]), pair[1])
