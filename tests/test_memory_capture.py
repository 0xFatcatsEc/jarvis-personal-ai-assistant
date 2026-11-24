import asyncio
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from stylus_jarvis.contracts.messages import Code, Failure
from stylus_jarvis.memory.service import Destination, FactDraft, Origin
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories


@unittest.skipUnless(os.name == "nt", "Windows memory acceptance")
class MemoryCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        await self.open_store()
        self.scopes = []
        for owner, name in (("owner", "atlas"), ("owner", "birch"), ("other", "atlas")):
            path = self.root / name
            path.mkdir(exist_ok=True)
            project = await self.store.register(owner, path)
            self.scopes.append(await self.store.select(owner, project, 1))

    async def open_store(self):
        self.db = Database(self.root / "profile" / "db.sqlite3")
        self.addAsyncCleanup(self.db.close)
        await self.db.open()
        self.store = Repositories(self.db)

    async def test_confirm_only_and_reopen_exact_version(self):
        atlas, birch, other = self.scopes
        path = self.root / "atlas" / "policy.txt"
        path.write_text("Use local storage.", encoding="utf-8")
        rev = await self.store.approve_source(atlas, path)
        loc, = await self.store.extract_locators(atlas, rev.source_id, rev.revision_id)
        draft = FactDraft(atlas, "Use local storage.", origin=Origin.INFERRED, locator=loc.id)
        self.assertIsNone(await self.store.confirm_fact(atlas, draft, confirmed=False))
        self.assertEqual(await self.db.call(lambda c: c.execute("SELECT count(*) FROM facts").fetchone()[0]), 0)
        fact = await self.store.confirm_fact(atlas, draft, confirmed=True)
        self.assertEqual((fact.id, fact.version, fact.text, fact.locator, fact.origin),
                         (draft.id.hex, 1, draft.text, loc.id, Origin.INFERRED))
        self.assertEqual(await self.store.confirm_fact(atlas, draft, confirmed=True), fact)
        with self.assertRaises(Failure) as changed:
            await self.store.confirm_fact(atlas, replace(draft, text="changed"), confirmed=True)
        self.assertEqual(changed.exception.code, Code.CONFLICT)
        await self.db.close()
        await self.open_store()
        self.assertEqual(await self.store.get_fact(atlas, fact.id, version=1), fact)
        self.assertEqual(await self.store.resolve_locator(atlas, fact.source, fact.revision, fact.locator), loc)
        for scope in (birch, other):
            with self.assertRaises(Failure):
                await self.store.get_fact(scope, fact.id)
            with self.assertRaises(Failure):
                await self.store.confirm_fact(scope, FactDraft(scope, "foreign citation", locator=loc.id),
                                              confirmed=True)

    async def test_personal_requires_explicit_destination_and_owner(self):
        atlas, birch, other = self.scopes
        draft = FactDraft(atlas, "I prefer offline tools.", Destination.PERSONAL)
        fact = await self.store.confirm_fact(atlas, draft, confirmed=True)
        self.assertIsNone(fact.project)
        self.assertEqual(await self.store.get_fact(birch, fact.id, destination=Destination.PERSONAL), fact)
        with self.assertRaises(Failure):
            await self.store.get_fact(atlas, fact.id)
        with self.assertRaises(Failure):
            await self.store.get_fact(other, fact.id, destination=Destination.PERSONAL)

    async def test_revoked_or_rebound_draft_creates_no_version(self):
        atlas, birch, _ = self.scopes
        draft = FactDraft(atlas, "pending")
        with self.assertRaises(Failure):
            await self.store.confirm_fact(birch, draft, confirmed=True)
        await self.db.call(lambda c: c.execute("UPDATE projects SET grant=grant+1 WHERE id=?", (atlas.project,)),
                           write=True)
        with self.assertRaises(Failure) as revoked:
            await self.store.confirm_fact(atlas, draft, confirmed=True)
        self.assertEqual(revoked.exception.code, Code.SCOPE)
        self.assertEqual(await self.db.call(lambda c: c.execute("SELECT count(*) FROM fact_versions").fetchone()[0]), 0)

    async def test_correction_preserves_old_evidence_after_source_replacement_and_restart(self):
        atlas, birch, _ = self.scopes
        path = self.root / "atlas" / "decision.txt"
        async def evidence(text):
            path.write_text(text, encoding="utf-8")
            rev = await self.store.approve_source(atlas, path)
            loc, = await self.store.extract_locators(atlas, rev.source_id, rev.revision_id)
            return loc.id
        draft = FactDraft(atlas, "Blue", locator=await evidence("Blue"))
        old = await self.store.confirm_fact(atlas, draft, confirmed=True)
        update = replace(draft, text="Green", locator=await evidence("Green"))
        self.assertIsNone(await self.store.correct_fact(atlas, update, expected_version=1, confirmed=False))
        self.assertEqual(await self.store.recall_facts(atlas), [old])
        new = await self.store.correct_fact(atlas, update, expected_version=1, confirmed=True)
        self.assertEqual((new.id, new.version, new.text), (old.id, 2, "Green"))
        path.unlink()
        await self.db.close()
        await self.open_store()
        self.assertEqual(await self.store.recall_facts(atlas), [new])
        for expected in (old, new):
            fact = await self.store.get_fact(atlas, old.id, version=expected.version)
            self.assertEqual(fact, expected)
            loc = await self.store.resolve_locator(atlas, fact.source, fact.revision, fact.locator)
            self.assertEqual(loc.excerpt, fact.text)
        self.assertEqual(await self.store.recall_facts(birch), [])
        with self.assertRaises(Failure):
            await self.store.correct_fact(birch, replace(update, scope=birch, locator=None), expected_version=2, confirmed=True)

    async def test_concurrent_predecessors_and_revoked_correction(self):
        scope = self.scopes[0]
        draft = FactDraft(scope, "first")
        await self.store.confirm_fact(scope, draft, confirmed=True)
        second_db = Database(self.db.path)
        self.addAsyncCleanup(second_db.close)
        await second_db.open()
        results = await asyncio.gather(
            self.store.correct_fact(scope, replace(draft, text="left"), expected_version=1, confirmed=True),
            Repositories(second_db).correct_fact(scope, replace(draft, text="right"), expected_version=1, confirmed=True),
            return_exceptions=True)
        self.assertEqual([v.code for v in results if isinstance(v, Failure)], [Code.CONFLICT])
        winner, = [v for v in results if not isinstance(v, Exception)]
        self.assertEqual(await self.store.recall_facts(scope), [winner])
        await self.db.call(lambda c: c.execute("UPDATE projects SET grant=grant+1 WHERE id=?", (scope.project,)), write=True)
        with self.assertRaises(Failure) as denied:
            await self.store.correct_fact(scope, replace(draft, text="revoked"), expected_version=2, confirmed=True)
        self.assertEqual(denied.exception.code, Code.SCOPE)
        self.assertEqual(await self.db.call(lambda c: c.execute("SELECT count(*) FROM fact_versions").fetchone()[0]), 2)

    async def test_personal_correction_requires_owner_and_explicit_destination(self):
        atlas, birch, other = self.scopes
        draft = FactDraft(atlas, "old", Destination.PERSONAL)
        await self.store.confirm_fact(atlas, draft, confirmed=True)
        for invalid in (replace(draft, scope=other), replace(draft, destination=Destination.PROJECT)):
            with self.assertRaises(Failure) as denied:
                await self.store.correct_fact(invalid.scope, invalid, expected_version=1, confirmed=True)
            self.assertEqual(denied.exception.code, Code.SCOPE)
        latest = await self.store.correct_fact(birch, replace(draft, scope=birch, text="new"),
                                               expected_version=1, confirmed=True)
        self.assertEqual(await self.store.recall_facts(atlas, destination=Destination.PERSONAL), [latest])
        self.assertEqual(await self.store.recall_facts(other, destination=Destination.PERSONAL), [])
        self.assertEqual(await self.store.recall_facts(birch), [])
