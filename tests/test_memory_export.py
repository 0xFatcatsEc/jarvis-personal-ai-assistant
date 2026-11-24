import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from stylus_jarvis.contracts.messages import Code, Failure, Scope, State
from stylus_jarvis.memory.service import Destination, FactDraft
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories


@unittest.skipUnless(os.name == "nt", "Windows project export acceptance")
class MemoryExportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.db = Database(self.root / "profile" / "db.sqlite3")
        self.addAsyncCleanup(self.db.close)
        await self.db.open()
        self.store = Repositories(self.db)
        self.scopes = []
        for name in ("atlas", "birch"):
            folder = self.root / name
            folder.mkdir()
            project = await self.store.register("owner", folder)
            self.scopes.append(await self.store.select("owner", project, 1))
        self.target = self.root / "project.json"

    async def turn(self, scope: Scope, text: str, state: State) -> None:
        turn, _ = await self.store.begin(scope, uuid4(), text, "digest")
        if state != State.ACTIVE:
            await self.store.finish(scope, turn.key, state, "Café", None)

    async def test_readable_project_snapshot_and_original_evidence(self) -> None:
        atlas, birch = self.scopes
        second = await self.store.select(atlas.owner, atlas.project, 2)
        await self.turn(atlas, "first", State.COMPLETED)
        await self.turn(second, "second", State.CANCELLED)
        await self.turn(second, "pending-private", State.ACTIVE)
        await self.turn(birch, "foreign-message", State.COMPLETED)
        path = self.root / "atlas" / "decision.txt"
        path.write_text("original evidence", encoding="utf-8")
        rev = await self.store.approve_source(atlas, path)
        loc, = await self.store.extract_locators(atlas, rev.source_id, rev.revision_id)
        draft = FactDraft(atlas, "superseded-private", locator=loc.id)
        await self.store.confirm_fact(atlas, draft, confirmed=True)
        current = FactDraft(atlas, "Current decision", locator=loc.id, id=draft.id)
        fact = await self.store.correct_fact(atlas, current, expected_version=1, confirmed=True)
        path.write_text("replacement", encoding="utf-8")
        await self.store.approve_source(atlas, path)
        path.unlink()
        await self.store.confirm_fact(atlas, FactDraft(atlas, "personal-private", Destination.PERSONAL),
                                      confirmed=True)
        await self.store.confirm_fact(birch, FactDraft(birch, "foreign-fact"), confirmed=True)
        forgotten = await self.store.confirm_fact(atlas, FactDraft(atlas, "forgotten-private"), confirmed=True)
        with patch("stylus_jarvis.storage.repositories.reconcile", side_effect=Failure(Code.STORE)):
            with self.assertRaises(Failure):
                await self.store.forget_fact(atlas, forgotten.id, expected_version=1, confirmed=True)

        exported = await self.store.export_project(atlas, self.target)
        raw = exported.read_text(encoding="utf-8")
        result = json.loads(raw)
        self.assertEqual((result["version"], result["project_id"]), (1, atlas.project))
        self.assertEqual([c["id"] for c in result["conversations"]], [atlas.conversation, second.conversation])
        for conversation, text, state in zip(result["conversations"], ("first", "second"),
                                             ("completed", "cancelled"), strict=True):
            self.assertEqual([(m["role"], m["content"], m["state"]) for m in conversation["messages"]],
                             [("user", text, state), ("assistant", "Café", state)])
        exported_fact, = result["facts"]
        self.assertEqual((exported_fact["id"], exported_fact["version"], exported_fact["text"]),
                         (fact.id, 2, fact.text))
        self.assertEqual(exported_fact["evidence"], {
            "source_id": rev.source_id, "revision_id": rev.revision_id, "locator_id": loc.id,
            "relative_path": "decision.txt", "sha256": rev.sha256, "page": None, "start": 0, "end": 17,
        })
        for excluded in ("foreign-", "pending-private", "personal-private", "forgotten-private",
                         "superseded-private", "original evidence", str(self.root)):
            self.assertNotIn(excluded, raw)

    async def test_revocation_failure_cleanup_and_no_overwrite(self) -> None:
        atlas, _ = self.scopes
        before = set(self.root.iterdir())
        with patch("stylus_jarvis.memory.export.json.dump", side_effect=OSError):
            with self.assertRaises(Failure):
                await self.store.export_project(atlas, self.target)
        self.assertEqual(set(self.root.iterdir()), before)
        self.target.write_text("existing", encoding="utf-8")
        with self.assertRaises(Failure) as collision:
            await self.store.export_project(atlas, self.target)
        self.assertEqual(collision.exception.code, Code.CONFLICT)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "existing")
        self.target.unlink()
        await self.db.call(lambda c: c.execute("UPDATE projects SET grant=grant+1 WHERE id=?", (atlas.project,)),
                           write=True)
        with self.assertRaises(Failure) as revoked:
            await self.store.export_project(atlas, self.target)
        self.assertEqual(revoked.exception.code, Code.SCOPE)
        self.assertEqual(set(self.root.iterdir()), before)
