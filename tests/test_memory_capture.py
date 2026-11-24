import asyncio
import os
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from stylus_jarvis.contracts.messages import Code, Failure
from stylus_jarvis.memory.service import Destination, FactDraft, Origin
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories


@unittest.skipUnless(os.name == "nt", "Windows memory acceptance")
class MemoryCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_ledger_survives_primary_rollback_and_missing_copy_fails_closed(self):
        atlas, _, _ = self.scopes
        draft = FactDraft(atlas, "Forget after crash")
        fact = await self.store.confirm_fact(atlas, draft, confirmed=True)
        with patch("stylus_jarvis.storage.repositories.reconcile", side_effect=Failure(Code.STORE)):
            with self.assertRaises(Failure):
                await self.store.forget_fact(atlas, fact.id, expected_version=1, confirmed=True)
        self.assertEqual(await self.db.call(lambda c: c.execute("SELECT count(*) FROM facts").fetchone()[0]), 1)
        self.assertEqual(await self.store.recall_facts(atlas), [])
        with self.assertRaises(Failure):
            await self.store.get_fact(atlas, fact.id)
        await self.db.close()
        unpaired = Database(self.root / "unpaired.sqlite3")
        shutil.copyfile(self.db.path, unpaired.path)
        self.addAsyncCleanup(unpaired.close)
        with self.assertRaises(Failure):
            await unpaired.open()
        await self.open_store()
        self.assertEqual(await self.db.call(lambda c: c.execute("SELECT count(*) FROM facts").fetchone()[0]), 0)
        self.assertTrue(await self.store.forget_fact(atlas, fact.id, expected_version=1, confirmed=True))

    async def test_older_primary_replays_newer_ledger_and_rejects_stale_ledger(self):
        atlas, _, _ = self.scopes
        fact = await self.store.confirm_fact(atlas, FactDraft(atlas, "Restore fixture"), confirmed=True)
        await self.db.close()
        older_primary = self.root / "older.sqlite3"
        stale_ledger = self.root / "stale-ledger.sqlite3"
        shutil.copyfile(self.db.path, older_primary)
        shutil.copyfile(self.db.deletion_path(), stale_ledger)
        await self.open_store()
        await self.store.forget_fact(atlas, fact.id, expected_version=1, confirmed=True)
        await self.db.close()
        restored = Database(older_primary.resolve(strict=True))
        self.addAsyncCleanup(restored.close)
        shutil.copyfile(self.db.deletion_path(), restored.deletion_path())
        await restored.open()
        self.assertEqual(await Repositories(restored).recall_facts(atlas), [])
        newer_primary = self.root / "newer.sqlite3"
        shutil.copyfile(self.db.path, newer_primary)
        untrusted = Database(newer_primary.resolve(strict=True))
        self.addAsyncCleanup(untrusted.close)
        shutil.copyfile(stale_ledger, untrusted.deletion_path())
        with self.assertRaises(Failure):
            await untrusted.open()

    async def test_forget_confirmation_predecessor_grant_and_personal_scope(self):
        atlas, birch, other = self.scopes
        draft = FactDraft(atlas, "First preference", Destination.PERSONAL)
        fact = await self.store.confirm_fact(atlas, draft, confirmed=True)
        await self.store.correct_fact(atlas, replace(draft, text="Current preference"),
                                      expected_version=1, confirmed=True)
        other_fact = await self.store.confirm_fact(other, FactDraft(other, draft.text, Destination.PERSONAL),
                                                   confirmed=True)
        self.assertFalse(await self.store.forget_fact(atlas, fact.id, expected_version=2, confirmed=False,
                                                      destination=Destination.PERSONAL))
        for scope, version, destination, code in (
            (other, 2, Destination.PERSONAL, Code.SCOPE),
            (atlas, 2, Destination.PROJECT, Code.SCOPE),
            (atlas, 1, Destination.PERSONAL, Code.CONFLICT),
        ):
            with self.assertRaises(Failure) as denied:
                await self.store.forget_fact(scope, fact.id, expected_version=version, confirmed=True,
                                             destination=destination)
            self.assertEqual(denied.exception.code, code)
        await self.db.call(lambda c: c.execute("UPDATE projects SET grant=grant+1 WHERE id=?", (atlas.project,)),
                           write=True)
        with self.assertRaises(Failure):
            await self.store.forget_fact(atlas, fact.id, expected_version=2, confirmed=True,
                                         destination=Destination.PERSONAL)
        self.assertEqual((await self.store.recall_facts(birch, destination=Destination.PERSONAL))[0].version, 2)
        await self.store.forget_fact(birch, fact.id, expected_version=2, confirmed=True,
                                     destination=Destination.PERSONAL)
        self.assertEqual(await self.store.recall_facts(birch, destination=Destination.PERSONAL), [])
        self.assertEqual(await self.store.recall_facts(other, destination=Destination.PERSONAL), [other_fact])
        with self.assertRaises(Failure):
            await self.store.confirm_fact(birch, FactDraft(birch, draft.text, Destination.PERSONAL, Origin.INFERRED),
                                          confirmed=True)

    async def test_forget_reindex_restart_suppresses_fresh_inference_only_in_destination(self):
        atlas, birch, _ = self.scopes
        path = self.root / "atlas" / "decision.txt"
        path.write_text("Use local storage.", encoding="utf-8")
        rev = await self.store.approve_source(atlas, path)
        pair = rev.source_id, rev.revision_id
        loc, = await self.store.extract_locators(atlas, *pair)
        await self.store.publish_revision(atlas, *pair)
        draft = FactDraft(atlas, loc.excerpt, origin=Origin.INFERRED, locator=loc.id)
        fact = await self.store.confirm_fact(atlas, draft, confirmed=True)
        sibling = await self.store.confirm_fact(birch, FactDraft(birch, draft.text), confirmed=True)
        await self.store.forget_fact(atlas, fact.id, expected_version=1, confirmed=True)
        path.write_text("Use local storage. Updated heading.", encoding="utf-8")
        replacement = await self.store.approve_source(atlas, path)
        new_pair = replacement.source_id, replacement.revision_id
        new_loc, = await self.store.extract_locators(atlas, *new_pair)
        await self.store.publish_revision(atlas, *new_pair, replaces=pair)
        await self.db.close()
        await self.open_store()
        self.assertEqual(await self.store.recall_facts(atlas), [])
        self.assertEqual(await self.store.recall_facts(birch), [sibling])
        with self.assertRaises(Failure):
            await self.store.get_fact(atlas, fact.id)
        with self.assertRaises(Failure):
            await self.store.correct_fact(atlas, draft, expected_version=1, confirmed=True)
        for text in ("  USE LOCAL STORAGE. ", "Store all data locally."):
            proposal = FactDraft(atlas, text, origin=Origin.INFERRED, locator=new_loc.id)
            with self.assertRaises(Failure):
                await self.store.confirm_fact(atlas, proposal, confirmed=True)
        self.assertEqual(await self.store.resolve_locator(atlas, *pair, loc.id), loc)
        self.assertTrue(await self.store.search_evidence(atlas, "local storage"))

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
