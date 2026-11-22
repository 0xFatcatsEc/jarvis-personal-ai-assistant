import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import httpx
from pydantic import ValidationError

from stylus_jarvis.contracts.messages import ChatMessage, Code, Failure, RuntimeEvent, State
from stylus_jarvis.inference.ollama import Ollama
from stylus_jarvis.inference.router import Router
from stylus_jarvis.runtime.coordinator import Coordinator
from stylus_jarvis.runtime.diagnostics import Diagnostics
from stylus_jarvis.runtime.scheduler import Scheduler
from stylus_jarvis.settings import Settings, load, save
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories


class ScriptedModel:
    def __init__(self) -> None:
        self.hold = False
        self.fail = False
        self.started = asyncio.Event()
        self.closed = False
        self.calls: list[list[ChatMessage]] = []

    async def probe(self) -> None:
        return None

    async def generate(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        self.calls.append(messages)
        try:
            yield "Answer"
            self.started.set()
            if self.hold:
                await asyncio.Event().wait()
            if self.fail:
                raise Failure(Code.STREAM)
        finally:
            self.closed = True


class FoundationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = Database(self.root / "data" / "db.sqlite3")
        await self.db.open()
        self.store = Repositories(self.db)
        self.project = await self.store.register("owner", self.root)
        self.scope = await self.store.select("owner", self.project, 1)
        self.settings, self.manifest = load(self.root)
        self.model = ScriptedModel()
        self.router = Router(self.model, self.settings, self.manifest)
        self.log = Diagnostics(self.root / "logs")
        self.events: list[RuntimeEvent] = []
        self.core = Coordinator(self.store, self.router, Scheduler(), self.log, self.events.append)
        self.core.select(self.scope)

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.log.close()
        self.temp.cleanup()

    async def test_wal_and_constraints(self) -> None:
        self.assertEqual(await self.db.call(lambda c: c.execute("PRAGMA journal_mode").fetchone()[0]), "wal")
        self.assertEqual(await self.db.call(lambda c: c.execute("PRAGMA foreign_keys").fetchone()[0]), 1)
        with self.assertRaises(Failure):
            await self.store.select("someone else", self.project, 2, self.scope.conversation)

    async def test_duplicate_and_completed_context(self) -> None:
        request = uuid4()
        first = await self.core.submit(self.scope, request, "private marker")
        self.assertEqual(first.state, State.COMPLETED)
        self.assertEqual(first, await self.core.submit(self.scope, request, "private marker"))
        self.assertEqual(len(self.model.calls), 1)
        with self.assertRaises(Failure) as error:
            await self.core.submit(self.scope, request, "changed")
        self.assertEqual(error.exception.code, Code.CONFLICT)
        await self.core.submit(self.scope, uuid4(), "second")
        self.assertEqual([m.content for m in self.model.calls[-1]], ["private marker", "Answer", "second"])
        self.assertEqual(len(await self.store.history(self.scope, query="marker")), 1)
        self.log.close()
        self.assertNotIn("private marker", (self.root/"logs"/"runtime.jsonl").read_text())

    async def test_switch_cancels_stream(self) -> None:
        self.model.hold = True
        running = asyncio.create_task(self.core.submit(self.scope, uuid4(), "private"))
        await asyncio.wait_for(self.model.started.wait(), 2)
        with self.assertRaises(Failure) as busy:
            await self.core.submit(self.scope, uuid4(), "double click")
        self.assertEqual(busy.exception.code, Code.BUSY)
        other = await self.store.select("owner", self.project, 2)
        self.core.select(other)
        result = await asyncio.wait_for(running, 1)
        self.assertTrue(self.model.closed)
        self.assertEqual(result.state, State.CANCELLED)
        self.assertEqual(await self.store.history(other), [])
        self.assertFalse(any(e.kind == "saved" for e in self.events))
        self.assertEqual(await self.store.context(self.scope, 1000), [])

    async def test_stream_failure_retains_partial(self) -> None:
        self.model.fail = True
        with self.assertRaises(Failure):
            await self.core.submit(self.scope, uuid4(), "question")
        self.assertEqual((await self.store.history(self.scope))[-1][2:], ("Answer", "failed"))

    async def test_interrupted_restart_and_checkpoint_order(self) -> None:
        turn, _ = await self.store.begin(self.scope, uuid4(), "question", self.manifest.digest)
        await self.store.checkpoint(self.scope, turn.key, 3, "new")
        await self.store.checkpoint(self.scope, turn.key, 2, "old")
        await self.db.close()
        self.db = Database(self.db.path)
        await self.db.open()
        self.store = Repositories(self.db)
        self.assertEqual((await self.store.history(self.scope))[-1][2:], ("new", "interrupted"))
        await self.store.checkpoint(self.scope, turn.key, 4, "late")
        self.assertEqual((await self.store.history(self.scope))[-1][2], "new")

    async def test_newer_schema_fails_closed(self) -> None:
        await self.db.close()
        with sqlite3.connect(self.db.path) as conn:
            conn.execute("INSERT INTO migrations VALUES(2,'new-release')")
        conn.close()
        self.db = Database(self.db.path)
        with self.assertRaises(Failure) as caught:
            await self.db.open()
        self.assertEqual(caught.exception.code, Code.SCHEMA)

    async def test_settings_validation_and_round_trip(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(host="example.com")
        prefs = Settings(port=12345)
        save(self.root, prefs)
        self.assertEqual(load(self.root)[0], prefs)
        (self.root/"config"/"settings.toml").write_text("version = 99")
        with self.assertRaises(Failure):
            load(self.root)

    async def test_prompt_budget_does_not_persist_rejected_input(self) -> None:
        with self.assertRaises(Failure):
            await self.core.submit(self.scope, uuid4(), "x"*4096)
        self.assertEqual(await self.store.history(self.scope), [])

    async def test_ollama_protocol_and_digest(self) -> None:
        digest = self.manifest.digest
        body = b'{"message":{"content":"hello","thinking":"secret"},"done":false}\n{"message":{"content":""},"done":true}'
        def reply(req: httpx.Request) -> httpx.Response:
            self.assertEqual(req.url.host, "127.0.0.1")
            if req.url.path == "/api/tags":
                return httpx.Response(200, json={"models":[{"name":self.manifest.model,"digest":digest}]})
            return httpx.Response(200, content=body)
        adapter = Ollama(self.settings, self.manifest, transport=httpx.MockTransport(reply))
        try:
            await adapter.probe()
            self.assertEqual([p async for p in adapter.generate([])], ["hello"])
            digest = "a"*64
            with self.assertRaises(Failure) as caught:
                await adapter.probe()
            self.assertEqual(caught.exception.code, Code.DIGEST)
            body = b'{"done":false,"message":{"content":"unfinished"}}\n'
            with self.assertRaises(Failure):
                _ = [p async for p in adapter.generate([])]
        finally:
            await adapter.close()

    async def test_redirect_does_not_leave_loopback(self) -> None:
        requests: list[str] = []
        def redirect(req: httpx.Request) -> httpx.Response:
            requests.append(str(req.url))
            return httpx.Response(307, headers={"Location": "https://example.com/"})
        adapter = Ollama(self.settings, self.manifest, transport=httpx.MockTransport(redirect))
        try:
            with self.assertRaises(Failure):
                await adapter.probe()
            self.assertEqual(len(requests), 1)
        finally:
            await adapter.close()

