"""Headless Windows desktop integration against a real loopback HTTP socket."""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from stylus_jarvis.bootstrap import run_app
from stylus_jarvis.settings import Settings, load, save
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories
from stylus_jarvis.bootstrap import user_identity
from stylus_jarvis.ui.main_window import MainWindow


@unittest.skipUnless(os.name == "nt", "Windows desktop identity")
class DesktopTest(unittest.TestCase):
    def test_desktop_stream_save_restart(self) -> None:
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        loop = QEventLoop(app)
        asyncio.set_event_loop(loop)
        try:
            with tempfile.TemporaryDirectory() as folder:
                loop.run_until_complete(self.scenario(Path(folder)))
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    async def scenario(self, root: Path) -> None:
        _, manifest = load(root)
        requests: list[str] = []

        async def respond(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                headers = (await reader.readuntil(b"\r\n\r\n")).decode("ascii").split("\r\n")
                path = headers[0].split()[1]
                requests.append(path)
                if path == "/api/tags":
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
                QTest.mouseClick(window.send, Qt.MouseButton.LeftButton)
                while "assistant [completed]" not in window.history.toPlainText():
                    await asyncio.sleep(0.02)
                self.assertIn("café!", window.history.toPlainText())
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

