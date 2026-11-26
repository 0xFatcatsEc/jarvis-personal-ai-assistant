"""Windows acceptance for interrupted processes, recovery records and ordered Qt history."""
import asyncio
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from stylus_jarvis.bootstrap import Desktop, user_identity
from stylus_jarvis.contracts.messages import ChatMessage, Code, Failure, Scope, State, Turn
from stylus_jarvis.inference.router import Router
from stylus_jarvis.runtime.coordinator import Coordinator
from stylus_jarvis.runtime.diagnostics import Diagnostics
from stylus_jarvis.runtime.scheduler import Scheduler
from stylus_jarvis.settings import load
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories
from stylus_jarvis.ui.main_window import MainWindow


class LocalModel:
    async def probe(self) -> None:
        pass

    async def generate(self, messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
        yield "reply to " + messages[-1].content


async def crash_worker(root: Path, scenario: str) -> None:
    db = Database(root / "history.sqlite3")
    await db.open()
    store = Repositories(db)
    owner = user_identity()
    project = await store.register(owner, root)
    scope = await store.select(owner, project, 1)
    model = LocalModel()
    router = Router(model, *load(root))
    core = Coordinator(store, router, Scheduler(), Diagnostics(root / "logs"), lambda event: None, clock=lambda: 0.)
    core.select(scope)
    await core.submit(scope, uuid4(), "first")
    if scenario == "locked":
        # Hold a real write lock from the end of the stream through process death.
        writer = sqlite3.connect(db.path)
        async def locked(messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
            yield "final café\nsecond line"
            writer.execute("BEGIN IMMEDIATE")
        with patch.object(model, "generate", locked):
            try:
                await core.submit(scope, UUID(int=2), "second")
            except Failure as exc:
                if exc.code != Code.BUSY or not core.recoverable:
                    raise
            else:
                raise AssertionError("Final commit unexpectedly succeeded")
        os._exit(23)

    async def cancel(messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
        yield "cancelled prefix"
        core.scheduler.stop()
        await asyncio.sleep(0)
    with patch.object(model, "generate", cancel):
        cancelled = await core.submit(scope, uuid4(), "second")
        if cancelled.state != State.CANCELLED:
            raise AssertionError(cancelled)
    await core.submit(scope, uuid4(), "third")

    async def interrupted(messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
        yield "checkpoint before process exit"
        os._exit(23)

    with (patch.object(model, "generate", interrupted),
          patch.object(core, "clock", side_effect=[0., 0., 0., 2.])):
        await core.submit(scope, uuid4(), "fourth")


@unittest.skipUnless(os.name == "nt", "Windows desktop and process-restart acceptance")
class HistoryLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.app = QApplication.instance() or QApplication([])

    async def reopen(self) -> tuple[Desktop, Scope]:
        db = Database(self.root / "history.sqlite3")
        self.addAsyncCleanup(db.close)
        await db.open()
        store = Repositories(db)
        owner = user_identity()
        project = await store.register(owner, self.root)
        threads = await store.conversations(owner, project)
        scope = await store.select(owner, project, 1, threads[0][0] if threads else None)
        log = Diagnostics(self.root / "logs")
        self.addCleanup(log.close)
        router = Router(LocalModel(), *load(self.root))
        core = Coordinator(store, router, Scheduler(), log, lambda event: None)
        core.select(scope)
        return Desktop(MainWindow(), store, router, core, log, owner), scope

    async def crash(self, scenario: str) -> None:
        process = await asyncio.to_thread(subprocess.run, [
            sys.executable, "-B", __file__, str(self.root), scenario,
        ], capture_output=True, timeout=25)
        self.assertEqual(process.returncode, 23, process.stderr.decode(errors="replace"))

    async def test_completed_cancelled_interrupted_render_in_order_after_process_exit(self) -> None:
        await self.crash("stream")
        desktop, _ = await self.reopen()
        await desktop.history()
        self.assertEqual(desktop.view.history.toPlainText(), "\n\n".join([
            "user [completed]\nfirst", "assistant [completed]\nreply to first",
            "user [cancelled]\nsecond", "assistant [cancelled]\ncancelled prefix",
            "user [completed]\nthird", "assistant [completed]\nreply to third",
            "user [interrupted]\nfourth", "assistant [interrupted]\ncheckpoint before process exit",
        ]))
        desktop.view.search.setText("prefix")
        await desktop.history()
        self.assertEqual(desktop.view.history.toPlainText(), "assistant [cancelled]\ncancelled prefix")

    async def test_locked_final_recovers_and_replays_once_after_process_exit(self) -> None:
        await self.crash("locked")
        record, = self.root.glob("*.pending")
        original_record = record.read_bytes()
        desktop, scope = await self.reopen()
        with patch.object(desktop.router, "probe", side_effect=Failure(Code.MODEL)) as probe:
            receipt = await desktop.core.submit(scope, UUID(int=2), "second")
            self.assertEqual((receipt.state, receipt.answer), (State.COMPLETED, "final café\nsecond line"))
            probe.assert_not_awaited()
        self.assertEqual(len(await desktop.store.history(scope)), 4)
        self.assertEqual(list(self.root.glob("*.pending")), [])
        await desktop.store.db.close()
        # Reproduce the disk state after recovery committed but before unlink.
        record.write_bytes(original_record)
        again, scope = await self.reopen()
        rows = await again.store.history(scope)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[-1], (4, "assistant", receipt.answer, "completed"))
        self.assertFalse(record.exists())

    async def test_grant_revoked_before_restart_preserves_only_checkpoint(self) -> None:
        await self.crash("locked")
        with sqlite3.connect(self.root / "history.sqlite3") as writer:
            writer.execute("UPDATE projects SET grant=grant+1")
        writer.close()
        desktop, scope = await self.reopen()
        self.assertEqual((await desktop.store.history(scope))[-1], (4, "assistant", "", "failed"))
        self.assertEqual(list(self.root.glob("*.pending")), [])

    async def test_late_same_scope_refresh_cannot_replace_newer_paged_history(self) -> None:
        desktop, scope = await self.reopen()
        expected: list[str] = []

        async def append(i: int) -> None:
            key = f"q{i}"
            turn, _ = await desktop.store.begin(scope, uuid4(), key, "digest")
            await desktop.store.finish(scope, turn.key, State.COMPLETED, f"a{i}", None)
            expected.extend([f"user [completed]\n{key}", f"assistant [completed]\na{i}"])

        for i in range(51):
            await append(i)
        captured, release = asyncio.Event(), asyncio.Event()
        history = desktop.store.history

        async def delayed(scope: Scope, *, after: int, query: str) -> list[tuple[int, str, str, str]]:
            page = await history(scope, after=after, query=query)
            if after and not captured.is_set():
                captured.set()
                await release.wait()
            return page

        with patch.object(desktop.store, "history", delayed):
            previous = asyncio.create_task(desktop.history())
            try:
                await asyncio.wait_for(captured.wait(), 3)
                await append(51)
                await desktop.history()
            finally:
                release.set()
                await previous
        self.assertEqual(desktop.view.history.toPlainText(), "\n\n".join(expected))

    async def test_close_keeps_memory_only_reply_available_for_retry(self) -> None:
        desktop, scope = await self.reopen()
        with (patch.object(desktop.store, "finish", side_effect=Failure(Code.STORE)),
              patch.object(desktop.store, "preserve", side_effect=Failure(Code.STORE)),
              self.assertRaises(Failure)):
            await desktop.core.submit(scope, uuid4(), "keep me")
        for _ in range(2):
            self.assertFalse(await desktop.shutdown(0.3))
            self.assertTrue(desktop.view.retry.isEnabled())
            self.assertIn("only in memory", desktop.view.status.text())
        await desktop.retry()
        self.assertIn("reply to keep me", desktop.view.history.toPlainText())
        self.assertTrue(await desktop.shutdown(0.3))

    async def test_stalled_terminal_write_and_unfinished_ui_task_have_bounded_close_attempts(self) -> None:
        desktop, scope = await self.reopen()
        committing, release_final, release_ui = asyncio.Event(), asyncio.Event(), asyncio.Event()
        finish = desktop.store.finish

        async def delayed(scope: Scope, key: str, state: State, text: str, error: Code | None) -> Turn:
            committing.set()
            await release_final.wait()
            return await finish(scope, key, state, text, error)

        desktop.spawn(release_ui.wait)
        with patch.object(desktop.store, "finish", delayed):
            generating = asyncio.create_task(desktop.core.submit(scope, uuid4(), "settle"))
            try:
                await asyncio.wait_for(committing.wait(), 3)
                self.assertFalse(await asyncio.wait_for(desktop.shutdown(.05), .5))
                self.assertFalse(generating.done())
                release_final.set()
                result = await asyncio.wait_for(generating, 2)
                self.assertEqual(result.state, State.COMPLETED)
                self.assertFalse(await asyncio.wait_for(desktop.shutdown(.05), .5))
            finally:
                release_final.set()
                release_ui.set()
                await generating
        self.assertTrue(await asyncio.wait_for(desktop.shutdown(.3), .5))


if __name__ == "__main__":
    asyncio.run(crash_worker(Path(sys.argv[1]), sys.argv[2]))
