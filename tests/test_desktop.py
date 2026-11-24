"""Headless Windows desktop integration against a real loopback HTTP socket."""
import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from collections.abc import AsyncGenerator, Awaitable, Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog
from qasync import QEventLoop

from stylus_jarvis.bootstrap import run_app
from stylus_jarvis.contracts.messages import ChatMessage, Code, Failure, Scope
from stylus_jarvis.inference.ollama import Ollama
from stylus_jarvis.settings import Settings, load, save
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories
from stylus_jarvis.bootstrap import user_identity
from stylus_jarvis.ui.main_window import MainWindow
from stylus_jarvis.ui.review import FactEditor


@unittest.skipUnless(os.name == "nt", "Windows desktop identity")
class DesktopTest(unittest.TestCase):
    def test_desktop_stream_save_restart(self) -> None:
        self.run_scenario(self.scenario)

    def test_windows_grant_revocation_at_delivery(self) -> None:
        self.run_scenario(self.revocation_scenario)

    def test_degraded_diagnostics_and_desktop_stop(self) -> None:
        self.run_scenario(self.degraded_stop)

    async def degraded_stop(self, root: Path) -> None:
        (root / "logs").write_bytes(b"directory unavailable")
        db = Database(root / "data" / "jarvis.sqlite3")
        await db.open()
        try:
            await Repositories(db).register(user_identity(), root)
        finally:
            await db.close()
        active = asyncio.Event()

        async def generate(model: Ollama, messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
            yield "private prefix"
            active.set()
            await asyncio.Event().wait()

        window = MainWindow()
        window.show()
        stop = asyncio.Event()
        with patch.object(Ollama, "probe", autospec=True), patch.object(Ollama, "generate", generate):
            app = asyncio.create_task(run_app(window, root, stop))
            try:
                async with asyncio.timeout(10):
                    while not window.send.isEnabled() or "degraded" not in window.diagnostic_toggle.text():
                        await asyncio.sleep(.02)
                    window.draft.setPlainText("private prompt")
                    window.send.click()
                    await active.wait()
                    window.stop.click()
                    while "assistant [cancelled]" not in window.history.toPlainText():
                        await asyncio.sleep(.02)
                    window.diagnostic_toggle.click()
                    self.assertIn('"outcome":"cancelled"', window.diagnostic_view.toPlainText())
                    self.assertNotIn("private", window.diagnostic_view.toPlainText())
            finally:
                stop.set()
                await asyncio.wait_for(app, 8)
                window.hide()

    def test_close_with_recovery_record_returns_recovery_disposition(self) -> None:
        self.run_scenario(self.close_with_pending)

    async def close_with_pending(self, root: Path) -> None:
        db = Database(root / "data" / "jarvis.sqlite3")
        await db.open()
        try:
            await Repositories(db).register(user_identity(), root)
        finally:
            await db.close()

        async def generate(model: Ollama, messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
            yield "preserved reply"

        window = MainWindow()
        stop = asyncio.Event()
        window.closing.connect(stop.set)
        window.show()
        with (patch.object(Ollama, "probe", autospec=True), patch.object(Ollama, "generate", generate),
              patch.object(Repositories, "finish", side_effect=Failure(Code.STORE))):
            app = asyncio.create_task(run_app(window, root, stop))
            try:
                async with asyncio.timeout(10):
                    while not window.send.isEnabled() or not window.centralWidget().isEnabled():
                        await asyncio.sleep(.01)
                    window.draft.setPlainText("question")
                    window.send.click()
                    while not window.retry.isEnabled():
                        await asyncio.sleep(.01)
                    window.close()
                    while "close again" not in window.status.text():
                        await asyncio.sleep(.01)
                    self.assertFalse(app.done())
                    self.assertTrue(window.retry.isEnabled())
                    window.close()
                    self.assertEqual(await app, 2)
            finally:
                window.hide()
        reopened = Database(db.path)
        await reopened.open()
        try:
            saved = await reopened.call(lambda c: c.execute(
                "SELECT content FROM messages WHERE role='assistant'").fetchone()[0])
            self.assertEqual(saved, "preserved reply")
        finally:
            await reopened.close()

    def test_close_deadline_covers_startup_and_service_cleanup(self) -> None:
        self.run_scenario(self.close_deadline)

    async def close_deadline(self, root: Path) -> None:
        starting, release_start = asyncio.Event(), asyncio.Event()
        closing, release_close = asyncio.Event(), asyncio.Event()
        original_open, original_close = Database.open, Database.close

        async def delayed_open(db: Database) -> None:
            starting.set()
            await release_start.wait()
            await original_open(db)

        async def delayed_close(db: Database) -> None:
            closing.set()
            await release_close.wait()
            await original_close(db)

        window = MainWindow()
        stop = asyncio.Event()
        with patch.object(Database, "open", delayed_open), patch.object(Database, "close", delayed_close):
            app = asyncio.create_task(run_app(window, root, stop, shutdown_grace=.15))
            try:
                await asyncio.wait_for(starting.wait(), 3)
                stop.set()
                async with asyncio.timeout(1):
                    while "timed out during startup" not in window.status.text():
                        await asyncio.sleep(.01)
                release_start.set()
                async with asyncio.timeout(4):
                    while not closing.is_set():
                        stop.set()
                        await asyncio.sleep(.02)
                async with asyncio.timeout(1):
                    while "timed out while closing services" not in window.status.text():
                        await asyncio.sleep(.01)
                self.assertFalse(app.done())
            finally:
                release_start.set()
                release_close.set()
                async with asyncio.timeout(4):
                    while not app.done():
                        stop.set()
                        await asyncio.sleep(.02)
                self.assertEqual(await app, 0)

    def run_scenario(self, scenario: Callable[[Path], Awaitable[None]]) -> None:
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        loop = QEventLoop(app)
        asyncio.set_event_loop(loop)
        try:
            with tempfile.TemporaryDirectory() as folder:
                loop.run_until_complete(scenario(Path(folder)))
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    async def revocation_scenario(self, root: Path) -> None:
        db = Database(root / "data" / "jarvis.sqlite3")
        await db.open()
        try:
            owner = user_identity()
            project = await Repositories(db).register(owner, root)
        finally:
            await db.close()

        def revoke() -> None:
            with sqlite3.connect(db.path) as connection:
                connection.execute("UPDATE projects SET grant=grant+1 WHERE owner=? AND id=?", (owner, project))
            connection.close()

        async def generate(model: Ollama, messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
            yield "authorized prefix"
            revoke()
            yield "withheld fragment"

        window = MainWindow()
        window.show()
        stop = asyncio.Event()
        with patch.object(Ollama, "probe", autospec=True), patch.object(Ollama, "generate", generate):
            app = asyncio.create_task(run_app(window, root, stop))
            try:
                async with asyncio.timeout(15):
                    while not window.send.isEnabled() or not window.centralWidget().isEnabled():
                        await asyncio.sleep(0.01)
                    window.draft.setPlainText("question")
                    QTest.mouseClick(window.send, Qt.MouseButton.LeftButton)
                    while window.status.text() != str(Failure(Code.SCOPE)):
                        await asyncio.sleep(0.01)
                    self.assertIn("authorized prefix", window.history.toPlainText())
                    self.assertNotIn("withheld fragment", window.history.toPlainText())

                    # Rebind, then revoke between the history read and its on-screen refresh.
                    history = Repositories.history

                    async def read_then_revoke(store: Repositories, scope: Scope, **kwargs: Any) -> list[tuple[int, str, str, str]]:
                        page = await history(store, scope, **kwargs)
                        revoke()
                        return page

                    with patch.object(Repositories, "history", read_then_revoke):
                        window.status.clear()
                        window.projects.currentIndexChanged.emit(window.projects.currentIndex())
                        while not window.history.toPlainText() and window.status.text() != str(Failure(Code.SCOPE)):
                            await asyncio.sleep(0.01)
                        self.assertEqual(window.history.toPlainText(), "")
                        self.assertEqual(window.status.text(), str(Failure(Code.SCOPE)))
            finally:
                stop.set()
                try:
                    await asyncio.wait_for(app, 8)
                finally:
                    window.hide()

    async def scenario(self, root: Path) -> None:
        self.enterContext(patch("stylus_jarvis.inference.ollama.verify_listener"))
        _, manifest = load(root)
        requests: list[str] = []

        async def respond(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                headers = (await reader.readuntil(b"\r\n\r\n")).decode("ascii").split("\r\n")
                path = headers[0].split()[1]
                requests.append(path)
                if path == "/api/status":
                    body = json.dumps({"cloud": {"disabled": True}}).encode()
                elif path == "/api/tags":
                    body = json.dumps({"models": [{"name": manifest.model, "digest": manifest.digest}]}).encode()
                else:
                    length = next(int(h.split(":")[1]) for h in headers if h.lower().startswith("content-length:"))
                    question: dict[str, Any] = json.loads(await reader.readexactly(length))
                    self.assertEqual(question["messages"][-1]["content"], "Explain this project")
                    body = '{"message":{"content":"café"},"done":false}\n{"message":{"content":"!"},"done":true}\n'.encode()
                writer.write(f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode())
                for block in (body[:5], body[5:]):
                    writer.write(block)
                    await writer.drain()
                    await asyncio.sleep(0.01)
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(respond, "127.0.0.1", 0)
        save(root, Settings(port=server.sockets[0].getsockname()[1]))
        db = Database(root/"data"/"jarvis.sqlite3")
        await db.open()
        store = Repositories(db)
        await store.register(user_identity(), root)
        await db.close()
        stop = asyncio.Event()
        window = MainWindow()
        window.show()
        application = asyncio.create_task(run_app(window, root, stop))
        try:
            async with asyncio.timeout(15):
                while not window.send.isEnabled() or not window.centralWidget().isEnabled():
                    await asyncio.sleep(0.02)
                window.draft.setPlainText("Explain this project")
                selected = root / "approved.txt"
                window.capture_fact.click()
                editor = window.findChild(FactEditor)
                self.assertIn(window.projects.currentText(), editor.destination.currentText())
                editor.statement.setPlainText("Discard this draft")
                editor.reject()
                await asyncio.sleep(.02)
                window.capture_fact.click()
                editor = next(d for d in window.findChildren(FactEditor) if d.isVisible())
                editor.destination.setCurrentIndex(1)
                editor.statement.setPlainText("A confirmed personal preference")
                editor.save.click()
                while "saved to personal memory" not in window.status.text():
                    await asyncio.sleep(.02)
                with sqlite3.connect(db.path) as reader:
                    self.assertEqual(reader.execute("SELECT text FROM fact_versions").fetchall(),
                                     [("A confirmed personal preference",)])
                reader.close()
                window.correct_personal.trigger()
                while not any(p.isVisible() for p in window.findChildren(QInputDialog)):
                    await asyncio.sleep(.02)
                picker = next(p for p in window.findChildren(QInputDialog) if p.isVisible())
                picker.accept()
                while not any(e.isVisible() for e in window.findChildren(FactEditor)):
                    await asyncio.sleep(.02)
                editor = next(e for e in window.findChildren(FactEditor) if e.isVisible())
                self.assertEqual(editor.statement.toPlainText(), "A confirmed personal preference")
                self.assertFalse(editor.destination.isEnabled())
                self.assertEqual(editor.save.text(), "Confirm correction")
                editor.statement.setPlainText("A corrected personal preference")
                window.status.clear()
                editor.save.click()
                while "saved to personal memory" not in window.status.text():
                    await asyncio.sleep(.02)
                with sqlite3.connect(db.path) as reader:
                    self.assertEqual(reader.execute("SELECT version,text FROM fact_versions ORDER BY version").fetchall(),
                                     [(1, "A confirmed personal preference"), (2, "A corrected personal preference")])
                reader.close()
                selected.write_bytes(b"owner selected evidence")
                with patch("stylus_jarvis.bootstrap.QFileDialog.getOpenFileName",
                           return_value=(str(selected), "")):
                    window.approve_source.click()
                    while "Approved approved.txt" not in window.status.text():
                        await asyncio.sleep(.02)
                    window.extract_source.click()
                    while "Saved locators: 1" not in window.status.text():
                        await asyncio.sleep(.02)
                QTest.mouseClick(window.send, Qt.MouseButton.LeftButton)
                while "assistant [completed]" not in window.history.toPlainText():
                    await asyncio.sleep(0.02)
                self.assertIn("café!", window.history.toPlainText())
                window.diagnostic_toggle.click()
                diagnostic_text = window.diagnostic_view.toPlainText()
                self.assertIn('"event":"sqlite_writer"', diagnostic_text)
                self.assertIn(manifest.digest, diagnostic_text)
                self.assertIn(manifest.build, diagnostic_text)
                self.assertNotIn("Explain this project", diagnostic_text)
                self.assertNotIn("café", diagnostic_text)
                self.assertEqual(requests.count("/api/chat"), 1)
        finally:
            stop.set()
            await asyncio.wait_for(application, 8)
            window.hide()
            server.close()
            await server.wait_closed()

        # History must be usable on the next launch even with the model server gone.
        second = MainWindow()
        stop = asyncio.Event()
        application = asyncio.create_task(run_app(second, root, stop))
        try:
            async with asyncio.timeout(12):
                while "café!" not in second.history.toPlainText() or "Start local Ollama" not in second.status.text():
                    await asyncio.sleep(0.02)
                self.assertFalse(second.send.isEnabled())
        finally:
            stop.set()
            await asyncio.wait_for(application, 8)

