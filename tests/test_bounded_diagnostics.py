"""Windows acceptance for the local diagnostic view's event feed and disk bounds."""
import asyncio
import json
import logging
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx

from stylus_jarvis.contracts.messages import Code, Failure, State
from stylus_jarvis.inference.ollama import Ollama
from stylus_jarvis.inference.router import Router
from stylus_jarvis.runtime import diagnostics
from stylus_jarvis.runtime.coordinator import Coordinator
from stylus_jarvis.runtime.diagnostics import Diagnostics, Event, Sink
from stylus_jarvis.runtime.scheduler import Scheduler
from stylus_jarvis.settings import Settings, load
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories


@unittest.skipUnless(os.name == "nt", "Windows diagnostic acceptance")
class WindowsDiagnostics(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())) / "private-path-marker"
        self.root.mkdir()

    async def test_terminal_frames_replay_and_private_rotated_logs(self) -> None:
        settings = Settings(output=96)
        _, manifest = load(self.root)
        prompt = "private-prompt-marker"
        answer = "private-answer-marker"
        error = "private-provider-error"
        final: dict = {}

        def respond(request: httpx.Request) -> httpx.Response:
            first = {"message": {"content": answer, "thinking": "private-thinking-marker"}, "done": False}
            return httpx.Response(200, content=json.dumps(first) + "\n" + json.dumps(final))

        adapter = Ollama(settings, manifest, transport=httpx.MockTransport(respond))
        self.addAsyncCleanup(adapter.close)
        self.enterContext(patch.object(adapter, "probe", autospec=True))
        self.enterContext(patch.object(diagnostics, "FILE_BYTES", 1400))
        log = Diagnostics(self.root / "logs")
        self.addCleanup(log.close)
        log.identify(manifest.build)
        db = Database(self.root / "test.db", writer_timing=log.writer)
        self.addAsyncCleanup(db.close)
        await db.open()
        store = Repositories(db)
        scope = await store.select("owner", await store.register("owner", self.root), 1)
        core = Coordinator(store, Router(adapter, settings, manifest), Scheduler(), log, lambda event: None)
        core.select(scope)
        for metadata, state in [
            ({"done_reason": "length", "eval_count": 96}, State.TOKEN_LIMIT),
            ({"eval_count": 96}, State.TOKEN_LIMIT),
            ({"done_reason": "stop", "eval_count": 96}, State.COMPLETED),
            ({"error": error}, State.FAILED),
        ]:
            request = uuid4()
            final = {"done": True, "message": {"content": ""}, **metadata}
            if state == State.FAILED:
                with self.assertRaises(Failure) as caught:
                    await core.submit(scope, request, prompt)
                self.assertEqual(caught.exception.code, Code.STREAM)
            else:
                self.assertEqual((await core.submit(scope, request, prompt)).state, state)
            with patch.object(adapter, "probe", side_effect=AssertionError("model used for replay")):
                receipt = await core.submit(scope, request, prompt)
            self.assertEqual((receipt.state, receipt.answer), (state, answer))
            self.assertEqual((await store.history(scope))[-1][-1], state.value)
            finish = next(json.loads(s) for s in reversed(log.snapshot()[1])
                          if json.loads(s)["event"] == "turn_finish")
            self.assertEqual((finish["outcome"], finish["model_digest"], finish["build"]),
                             (state.value, manifest.digest, manifest.build))
            self.assertGreaterEqual(finish["elapsed_ms"], 0)
            if state == State.TOKEN_LIMIT:
                self.assertEqual(await store.context(scope, 4096), [])
        log.close()
        files = sorted((self.root / "logs").iterdir())
        self.assertEqual([p.name for p in files], ["runtime.jsonl", "runtime.jsonl.1", "runtime.jsonl.2"])
        records = []
        for path in files:
            self.assertLessEqual(path.stat().st_size, 1400)
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("private-", raw)
            records.extend(json.loads(line) for line in raw.splitlines())
        writer = next(row for row in records if row["event"] == "sqlite_writer")
        self.assertGreaterEqual(min(writer["wait_ms"], writer["elapsed_ms"]), 0)
        self.assertEqual(log.dropped, 0)

    async def test_saturation_cancel_and_sink_failure(self) -> None:
        started, release = threading.Event(), threading.Event()

        def stalled(sink: Sink, record: logging.LogRecord) -> None:
            started.set()
            release.wait(10)
            raise OSError("private-sink-error")

        self.enterContext(patch.object(Sink, "emit", stalled))
        log = Diagnostics(self.root / "logs")
        self.addCleanup(log.close)
        self.addCleanup(release.set)
        log.emit(Event.START)
        self.assertTrue(await asyncio.to_thread(started.wait, 3))
        for _ in range(266):
            log.emit(Event.PROBE)
        health, rows = log.snapshot()
        self.assertIn("queued 256/256 · dropped 10", health)
        self.assertEqual(len(rows), 32)
        settings, manifest = load(self.root)
        adapter = Ollama(settings, manifest)
        self.addAsyncCleanup(adapter.close)
        self.enterContext(patch.object(adapter, "probe", autospec=True))
        active = asyncio.Event()

        async def generate(messages):
            yield "private-prefix"
            active.set()
            await asyncio.Event().wait()

        self.enterContext(patch.object(adapter, "generate", generate))
        db = Database(self.root / "test.db")
        self.addAsyncCleanup(db.close)
        await db.open()
        store = Repositories(db)
        scope = await store.select("owner", await store.register("owner", self.root), 1)
        core = Coordinator(store, Router(adapter, settings, manifest), Scheduler(), log, lambda event: None)
        core.select(scope)
        task = asyncio.create_task(core.submit(scope, uuid4(), "private-prompt"))
        await asyncio.wait_for(active.wait(), 2)
        core.scheduler.stop()
        self.assertEqual((await asyncio.wait_for(task, 2)).state, State.CANCELLED)
        self.assertEqual(json.loads(log.snapshot()[1][-1])["outcome"], "cancelled")
        release.set()
        log.close()
        log.emit(Event.ERROR, code=Code.STORE)
        health, rows = log.snapshot()
        self.assertIn("degraded", health)
        self.assertIn("queued 0/256 · dropped 270", health)
        self.assertNotIn("private-", "".join(rows))
        self.assertEqual((await store.history(scope))[-1][2:], ("private-prefix", "cancelled"))
