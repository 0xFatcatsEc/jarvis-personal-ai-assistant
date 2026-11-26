"""Offline role discovery and typed, scope-bound proposals."""
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from stylus_jarvis.contracts.messages import Code, Failure, Scope
from stylus_jarvis.contracts.tools import InspectCitation, OpenApprovedProject, ReadSavedCode, RecallFacts, SearchEvidence
from stylus_jarvis.runtime.roles import Role, offline_tools, prepare_proposal
from stylus_jarvis.memory.service import Destination, FactDraft
from stylus_jarvis.security.broker import LocalReadBroker
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories


class LocalRoleTests(unittest.TestCase):
    scope = Scope("owner", "project", "conversation", 7, 2)
    source = "a" * 32
    revision = "b" * 32
    locator = "c" * 32

    def test_local_inventory_and_scope_binding(self) -> None:
        for role, model, body in (
            (Role.CODING, ReadSavedCode,
             {"tool": "coding.read_saved_code", "source": self.source, "revision": self.revision}),
            (Role.SYSTEM, OpenApprovedProject, {"tool": "system.open_approved_project"}),
            (Role.FILES, SearchEvidence, {"tool": "files.search_evidence", "query": "queue", "revision": self.revision}),
            (Role.FILES, InspectCitation, {"tool": "files.inspect_citation", "source": self.source,
                                           "revision": self.revision, "locator": self.locator}),
            (Role.MEMORY, RecallFacts, {"tool": "memory.recall_facts", "destination": "personal"}),
        ):
            with self.subTest(role=role, tool=body["tool"]):
                self.assertIs(offline_tools(role)[body["tool"]], model)
                call = prepare_proposal(self.scope, role, body)
                self.assertIs(call.scope, self.scope)
                self.assertIs(call.role, role)
                self.assertIsInstance(call.tool, model)

    def test_inactive_roles_and_nonoffline_scope_are_denied(self) -> None:
        request = {"tool": "system.open_approved_project"}
        for role, scope in (
            (Role.EMAIL, self.scope), (Role.RESEARCH, self.scope), (Role.SYSTEM, replace(self.scope, offline=False)),
        ):
            with self.subTest(role=role, scope=scope), self.assertRaises(Failure) as denied:
                prepare_proposal(scope, role, request)
            self.assertEqual(denied.exception.code, Code.OFFLINE)
        self.assertFalse(offline_tools(Role.EMAIL))
        self.assertFalse(offline_tools(Role.RESEARCH))

    def test_rejects_extra_authority_wrong_roles_and_invalid_shapes(self) -> None:
        code = {"tool": "coding.read_saved_code", "source": self.source, "revision": self.revision}
        launch = {"tool": "system.open_approved_project"}
        files = {"tool": "files.search_evidence", "query": "sqlite"}
        for role, body in (
            (Role.FILES, code), (Role.SYSTEM, launch | {"target": r"C:\Other"}),
            (Role.SYSTEM, launch | {"executable": "other.exe"}),
            (Role.SYSTEM, launch | {"grant": 7}), (Role.SYSTEM, launch | {"project": "other"}),
            (Role.SYSTEM, launch | {"approved": True}), (Role.SYSTEM, launch | {"version": 2}),
            (Role.CODING, code | {"source": "a" * 33}), (Role.CODING, code | {"revision": "a" * 32 + "\n"}),
            (Role.CODING, code | {"max_bytes": True}), (Role.CODING, code | {"max_bytes": "8192"}),
            (Role.CODING, code | {"max_bytes": 65537}), (Role.CODING, code | {"max_bytes": 1}),
            (Role.FILES, files | {"query": " "}), (Role.FILES, files | {"query": "a" * 513}),
            (Role.FILES, files | {"query": "sqlite\x00private marker"}),
            (Role.FILES, files | {"revision": r"C:\Other"}),
            (Role.MEMORY, {"tool": "memory.recall_facts"}),
            (Role.MEMORY, {"tool": "memory.recall_facts", "destination": "foreign"}),
            (Role.MEMORY, {"tool": "memory.forget_fact"}), (Role.SYSTEM, {"tool": ["unhashable"]}),
        ):
            with self.subTest(role=role, body=body):
                with self.assertRaises(Failure) as rejected:
                    prepare_proposal(self.scope, role, body)
                self.assertEqual(rejected.exception.code, Code.INPUT)
                self.assertNotIn("private marker", str(rejected.exception))


@unittest.skipUnless(os.name == "nt", "Windows scoped broker acceptance")
class LocalReadPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_scoped_reads_deny_foreign_ids_and_revoked_grants(self) -> None:
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        with_project, without_project = root / "First project", root / "Second project"
        with_project.mkdir()
        without_project.mkdir()
        database = Database(root / "data/jarvis.sqlite3")
        await database.open()
        self.addAsyncCleanup(database.close)
        store = Repositories(database)
        first = await store.select("owner", await store.register("owner", with_project), 1)
        second = await store.select("owner", await store.register("owner", without_project), 2)
        source = with_project / "notes.txt"
        source.write_text("Scoped evidence marker", encoding="utf-8")
        revision = await store.approve_source(first, source)
        ids = revision.source_id, revision.revision_id
        locator, = await store.extract_locators(first, *ids)
        await store.publish_revision(first, *ids)
        fact = await store.confirm_fact(first, FactDraft(first, "Scoped fact"), confirmed=True)
        broker = LocalReadBroker(store)

        self.assertEqual((await broker.inspect(first, *ids, locator.id, lambda: True)).id, locator.id)
        self.assertTrue((await broker.search(first, "evidence marker", None, lambda: True)).passages)
        self.assertEqual(await broker.recall(first, Destination.PROJECT, lambda: True), [fact])
        self.assertFalse((await broker.search(second, "evidence marker", ids[1], lambda: True)).passages)
        self.assertEqual(await broker.recall(second, Destination.PROJECT, lambda: True), [])
        with self.assertRaises(Failure) as foreign:
            await broker.inspect(second, *ids, locator.id, lambda: True)
        self.assertEqual(foreign.exception.code, Code.SCOPE)

        await database.call(lambda conn: conn.execute("UPDATE projects SET grant=grant+1 WHERE id=?", (first.project,)),
                            write=True)
        with (patch.object(store, "recall_facts", new_callable=AsyncMock) as dispatched,
              self.assertRaises(Failure) as revoked):
            await broker.recall(first, Destination.PROJECT, lambda: True)
        self.assertEqual(revoked.exception.code, Code.SCOPE)
        dispatched.assert_not_awaited()

    async def test_invalid_tool_and_changed_selection_do_not_dispatch(self) -> None:
        scope = LocalRoleTests.scope
        store = AsyncMock(spec=Repositories)
        broker = LocalReadBroker(store)
        with self.assertRaises(Failure) as invalid:
            await broker.search(scope, "queue", r"C:\other", lambda: True)
        self.assertEqual(invalid.exception.code, Code.INPUT)
        store.validate.assert_not_awaited()
        with self.assertRaises(Failure) as stale:
            checks = iter((True, False))
            await broker.search(scope, "queue", None, lambda: next(checks))
        self.assertEqual(stale.exception.code, Code.SCOPE)
        store.cited_context.assert_not_awaited()

        with self.assertRaises(Failure) as late:
            checks = iter((True, True, False))
            await broker.search(scope, "queue", None, lambda: next(checks))
        self.assertEqual(late.exception.code, Code.SCOPE)
        store.cited_context.assert_awaited_once()
