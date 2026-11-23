"""Grant acceptance tests using the runtime coordinator and the real SQLite actor."""
import sqlite3
import tempfile
import unittest
from collections.abc import AsyncGenerator
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from stylus_jarvis.contracts.messages import ChatMessage, Code, Failure, RuntimeEvent, Scope, State, Turn
from stylus_jarvis.inference.router import Router
from stylus_jarvis.runtime.coordinator import Coordinator
from stylus_jarvis.runtime.diagnostics import Diagnostics
from stylus_jarvis.runtime.scheduler import Scheduler
from stylus_jarvis.settings import load
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories


class LocalModel:
    async def probe(self) -> None:
        pass

    async def generate(self, messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
        yield "visible prefix"


class RequestGrantTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.db = Database(root / "db.sqlite3")
        self.addAsyncCleanup(self.db.close)
        await self.db.open()
        self.store = Repositories(self.db)
        self.owner = "S-1-5-21-12345-67890-54321-1001"
        self.project = await self.store.register(self.owner, root)
        await self.revoke()  # Exercise a revision other than the schema default.
        self.scope = await self.store.select(self.owner, self.project, 7)
        self.request = uuid4()
        self.model = LocalModel()
        self.router = Router(self.model, *load(root))
        self.events: list[RuntimeEvent] = []
        log = Diagnostics(root / "logs")
        self.addCleanup(log.close)
        self.core = Coordinator(self.store, self.router, Scheduler(), log, self.events.append, clock=lambda: 0.)
        self.core.select(self.scope)

    async def revoke(self) -> None:
        await self.db.call(lambda c: c.execute(
            "UPDATE projects SET grant=grant+1 WHERE id=? AND owner=?", (self.project, self.owner)
        ).rowcount, write=True)

    async def submit(self) -> Turn:
        return await self.core.submit(self.scope, self.request, "question")

    async def assert_revoked_turn(self, expected_checkpoint: str) -> None:
        row = await self.db.call(lambda c: tuple(c.execute(
            "SELECT t.state,t.error,t.ended_at,m.content FROM turns t JOIN messages m ON m.turn=t.id "
            "WHERE t.submission=? AND m.role='assistant'", (self.request.hex,)
        ).fetchone()))
        self.assertEqual(row[:2], (State.FAILED, Code.SCOPE))
        self.assertIsNotNone(row[2])
        self.assertEqual(row[3], expected_checkpoint)
        self.assertFalse(any(e.kind == "saved" for e in self.events))
        self.assertIsNone(self.core.scheduler.current)
        self.assertIsNone(self.core.pending)
        with self.assertRaises(Failure) as denied:
            await self.store.history(self.scope)
        self.assertEqual(denied.exception.code, Code.SCOPE)

    async def test_dispatch_keeps_scope_and_request_at_each_boundary(self) -> None:
        expected = Scope(self.owner, self.project, self.scope.conversation, 2, 7, offline=True)
        with (patch.object(self.store, "context", wraps=self.store.context) as context,
              patch.object(self.store, "begin", wraps=self.store.begin) as begin,
              patch.object(self.store, "finish", wraps=self.store.finish) as finish):
            result = await self.submit()
        self.assertEqual(context.await_args.args[0], expected)
        self.assertEqual(begin.await_args.args[:2], (expected, self.request))
        self.assertEqual(finish.await_args.args[:2], (expected, result.key))
        self.assertEqual(self.events, [
            RuntimeEvent(expected, self.request, "fragment", "visible prefix"),
            RuntimeEvent(expected, self.request, "saved", State.COMPLETED.value),
        ])

    async def test_invalid_dispatch_fields_rejected_before_model(self) -> None:
        for field, value in (("owner", "other"), ("project", uuid4().hex),
                             ("conversation", uuid4().hex), ("offline", False), ("grant", 1)):
            with self.subTest(field=field), patch.object(self.model, "probe") as probe:
                scope = replace(self.scope, **{field: value})
                self.core.select(scope)
                with self.assertRaises(Failure) as denied:
                    await self.core.submit(scope, self.request, "question")
                self.assertEqual(denied.exception.code, Code.SCOPE)
                probe.assert_not_awaited()
        self.assertEqual(self.events, [])
        self.assertEqual(await self.store.history(self.scope), [])

    async def test_revoked_between_fragments(self) -> None:
        async def stream(messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
            yield "allowed"
            await self.revoke()
            yield "withheld"
            self.fail("The revoked stream was consumed again")

        # Force the first authorized fragment to be checkpointed.
        with (patch.object(self.model, "generate", stream),
              patch.object(self.core, "clock", side_effect=[0., 0., 1., 2., 3.])):
            with self.assertRaises(Failure) as denied:
                await self.submit()
        self.assertEqual(denied.exception.code, Code.SCOPE)
        self.assertEqual([e.text for e in self.events], ["allowed"])
        await self.assert_revoked_turn("allowed")

    async def test_revoke_during_final_root_check_blocks_model_dispatch(self) -> None:
        is_dir = Path.is_dir
        root_checks = 0

        def check_root(path: Path) -> bool:
            nonlocal root_checks
            root_checks += 1
            if root_checks == 2:  # Accepted turn, immediately before dispatch.
                with sqlite3.connect(self.db.path) as connection:
                    connection.execute("UPDATE projects SET grant=grant+1 WHERE id=?", (self.project,))
                connection.close()
            return is_dir(path)

        with (patch.object(Path, "is_dir", check_root),
              patch.object(self.model, "generate", wraps=self.model.generate) as generate,
              self.assertRaises(Failure) as denied):
            await self.submit()
        self.assertEqual(denied.exception.code, Code.SCOPE)
        generate.assert_not_called()
        self.assertEqual(self.events, [])
        await self.assert_revoked_turn("")

    async def test_revoked_before_any_content(self) -> None:
        async def stream(messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
            await self.revoke()
            yield "withheld"

        with patch.object(self.model, "generate", stream), self.assertRaises(Failure) as denied:
            await self.submit()
        self.assertEqual(denied.exception.code, Code.SCOPE)
        self.assertEqual(self.events, [])
        await self.assert_revoked_turn("")

    async def test_revoked_after_last_fragment_before_final_write(self) -> None:
        async def stream(messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
            yield "visible prefix"
            await self.revoke()

        with (patch.object(self.model, "generate", stream), patch.object(self.core, "clock", return_value=0.),
              self.assertRaises(Failure) as denied):
            await self.submit()
        self.assertEqual(denied.exception.code, Code.SCOPE)
        self.assertEqual([e.text for e in self.events], ["visible prefix"])
        await self.assert_revoked_turn("")

    async def test_revoked_after_commit_before_receipt(self) -> None:
        finish = self.store.finish

        async def commit_then_revoke(scope: Scope, key: str, state: State, text: str, error: Code | None) -> Turn:
            result = await finish(scope, key, state, text, error)
            await self.revoke()
            return result

        with patch.object(self.store, "finish", commit_then_revoke), self.assertRaises(Failure) as denied:
            await self.submit()
        self.assertEqual(denied.exception.code, Code.SCOPE)
        self.assertEqual([e.kind for e in self.events], ["fragment"])
        fresh = await self.store.select(self.owner, self.project, 8, self.scope.conversation)
        self.assertEqual((await self.store.history(fresh))[-1][2:], ("visible prefix", "completed"))

    async def test_revoke_before_duplicate_receipt_delivery(self) -> None:
        await self.submit()
        self.events.clear()
        lookup = self.store.lookup

        async def lookup_then_revoke(scope: Scope, request: UUID, text: str) -> Turn | None:
            result = await lookup(scope, request, text)
            self.assertIsNotNone(result)
            await self.revoke()
            return result

        with patch.object(self.store, "lookup", lookup_then_revoke), self.assertRaises(Failure) as denied:
            await self.submit()
        self.assertEqual(denied.exception.code, Code.SCOPE)
        self.assertEqual(self.events, [])

    async def test_revoked_pending_save_settles_under_original_revision(self) -> None:
        with patch.object(self.store, "finish", side_effect=Failure(Code.BUSY)), self.assertRaises(Failure):
            await self.submit()
        self.assertIsNotNone(self.core.pending)
        await self.revoke()
        self.core.select(await self.store.select(self.owner, self.project, 8, self.scope.conversation))
        with self.assertRaises(Failure) as denied:
            await self.core.retry_save()
        self.assertEqual(denied.exception.code, Code.SCOPE)
        await self.assert_revoked_turn("")

    async def test_settlement_is_confined_to_original_turn_and_revision(self) -> None:
        original, _ = await self.store.begin(self.scope, self.request, "old", self.router.digest)
        await self.revoke()
        fresh = await self.store.select(self.owner, self.project, 8, self.scope.conversation)
        newer, _ = await self.store.begin(fresh, uuid4(), "new", self.router.digest)
        await self.store.checkpoint(fresh, original.key, 1, "wrong revision")
        with self.assertRaises(Failure) as denied:
            await self.store.checkpoint(self.scope, newer.key, 1, "revoked writer")
        self.assertEqual(denied.exception.code, Code.SCOPE)
        for scope, key in ((replace(self.scope, owner="other"), original.key),
                           (replace(self.scope, project=uuid4().hex), original.key),
                           (replace(self.scope, conversation=uuid4().hex), original.key),
                           (replace(self.scope, offline=False), original.key),
                           (self.scope, newer.key), (fresh, original.key)):
            with self.subTest(scope=scope, key=key):
                with self.assertRaises(Failure) as denied:
                    await self.store.finish(scope, key, State.COMPLETED, "wrong revision", None)
                self.assertEqual(denied.exception.code, Code.SCOPE)
        self.assertTrue(all(row[3] == "active" for row in await self.store.history(fresh)))
        for _ in range(2):
            with self.assertRaises(Failure) as denied:
                await self.store.finish(self.scope, original.key, State.COMPLETED, "withheld", None)
            self.assertEqual(denied.exception.code, Code.SCOPE)
        await self.assert_revoked_turn("")
        self.assertEqual((await self.store.history(fresh))[-1][2:], ("", "active"))
