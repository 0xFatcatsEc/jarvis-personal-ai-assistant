"""Headless Windows desktop integration against a real loopback HTTP socket."""
import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from collections.abc import AsyncGenerator, Awaitable, Callable
from pathlib import Path
from threading import Event
from typing import Any
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtMultimedia import QAudioFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QLineEdit, QListView, QPlainTextEdit
from qasync import QEventLoop

from stylus_jarvis.bootstrap import run_app
from stylus_jarvis.contracts.messages import ChatMessage, Code, Failure, SavedCode, Scope
from stylus_jarvis.editor.named_pipe import LocalPipe
from stylus_jarvis.editor.protocol import encode_frame
from stylus_jarvis.inference.ollama import Ollama
from stylus_jarvis.memory.service import Destination, FactDraft
from stylus_jarvis.security.broker import EditorLaunchBroker, SavedCodeBroker
from stylus_jarvis.settings import Settings, load, save
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories
from stylus_jarvis.bootstrap import user_identity
from stylus_jarvis.ui.main_window import MainWindow
from stylus_jarvis.ui.dashboard import CoreState
from stylus_jarvis.ui.review import FactEditor
from stylus_jarvis.voice.capture import AudioClip
from stylus_jarvis.voice.piper import ReplySpeech


@unittest.skipUnless(os.name == "nt", "Windows desktop identity")
class DesktopTest(unittest.TestCase):
    def test_memory_browse_scope_and_retained_citation(self) -> None:
        self.run_scenario(self.memory_browser_scenario)

    async def memory_browser_scenario(self, root: Path) -> None:
        db = Database(root / "data/jarvis.sqlite3")
        await db.open()
        store = Repositories(db)
        owner = user_identity()
        atlas, birch = root / "Atlas", root / "Birch"
        try:
            atlas.mkdir()
            birch.mkdir()
            first = await store.select(owner, await store.register(owner, atlas), 1)
            second = await store.select(owner, await store.register(owner, birch), 1)
            source = atlas / "notes.txt"
            source.write_text("Retained source wording.", encoding="utf-8")
            revision = await store.approve_source(first, source)
            locator, = await store.extract_locators(first, revision.source_id, revision.revision_id)
            await store.confirm_fact(first, FactDraft(first, "Atlas decision", locator=locator.id), confirmed=True)
            await store.confirm_fact(second, FactDraft(second, "Birch decision"), confirmed=True)
            personal = FactDraft(first, "Personal preference", Destination.PERSONAL)
            await store.confirm_fact(first, personal, confirmed=True)
        finally:
            await db.close()

        window = MainWindow()
        window.show()
        memory = window.memory
        stop = asyncio.Event()

        async def wait_for_fact(text: str) -> None:
            while text not in memory.detail.toPlainText():
                await asyncio.sleep(.02)
            self.assertEqual(memory.facts.count(), 1)

        with patch.object(Ollama, "probe", side_effect=Failure(Code.MODEL)):
            app = asyncio.create_task(run_app(window, root, stop))
            try:
                async with asyncio.timeout(15):
                    while not window.capture_fact.isEnabled():
                        await asyncio.sleep(.02)
                    window.projects.setCurrentIndex(window.projects.findData(first.project))
                    window.navigate("Memory")
                    await wait_for_fact("Atlas decision")
                    memory.provenance.click()
                    while not (dialog := next((d for d in window.findChildren(QDialog)
                                              if d.isVisible() and d.windowTitle() == "Fact source citation"), None)):
                        await asyncio.sleep(.02)
                    detail = dialog.findChild(QPlainTextEdit).toPlainText()
                    self.assertIn(revision.revision_id, detail)
                    self.assertIn(locator.id, detail)
                    self.assertIn("Retained source wording.", detail)
                    dialog.reject()

                    memory.scope.setCurrentIndex(1)
                    self.assertEqual(memory.detail.toPlainText(), "")
                    await wait_for_fact("Personal preference")
                    self.assertFalse(memory.provenance.isEnabled())
                    window.projects.setCurrentIndex(window.projects.findData(second.project))
                    self.assertEqual(memory.facts.count(), 0)
                    self.assertEqual(memory.destination, Destination.PROJECT)
                    await wait_for_fact("Birch decision")
                    memory.scope.setCurrentIndex(1)
                    await wait_for_fact("Personal preference")
            finally:
                stop.set()
                self.assertEqual(await asyncio.wait_for(app, 8), 0)
                window.hide()
                window.deleteLater()

    def test_evidence_search_exact_locators_and_scope_changes(self) -> None:
        self.run_scenario(self.evidence_scenario)

    async def evidence_scenario(self, root: Path) -> None:
        db = Database(root / "data/jarvis.sqlite3")
        await db.open()
        store = Repositories(db)
        owner = user_identity()
        project, other = root / "Atlas", root / "Birch"
        try:
            project.mkdir()
            other.mkdir()
            atlas = await store.select(owner, await store.register(owner, project), 1)
            birch = await store.select(owner, await store.register(owner, other), 1)

            async def publish(path: Path, replaces: tuple[str, str] | None = None) -> tuple[str, str]:
                record = await store.approve_source(atlas, path)
                ids = record.source_id, record.revision_id
                await store.extract_locators(atlas, *ids)
                await store.publish_revision(atlas, *ids, replaces=replaces)
                return ids

            pdf = project / "handbook.pdf"
            shutil.copyfile(Path(__file__).parent / "fixtures/m0-v1/atlas/handbook.pdf", pdf)
            await publish(pdf)
            text = project / "notes.txt"
            text.write_text("archival marker", encoding="utf-8")
            old = await publish(text)
            text.write_text("current marker", encoding="utf-8")
            await publish(text, replaces=old)
        finally:
            await db.close()

        window = MainWindow()
        window.show()
        evidence = window.evidence
        stop = asyncio.Event()
        received, release, returned = (asyncio.Event() for _ in range(3))
        search = Repositories.cited_context

        async def delayed(repository, scope, question, **kwargs):
            result = await search(repository, scope, question, **kwargs)
            if question == "current marker":
                received.set()
                await release.wait()
                returned.set()
            return result

        async def wait_for(predicate: Callable[[], bool]) -> None:
            while not predicate():
                await asyncio.sleep(.02)

        with (patch.object(Ollama, "probe", side_effect=Failure(Code.MODEL)),
              patch.object(Repositories, "cited_context", delayed)):
            app = asyncio.create_task(run_app(window, root, stop))
            try:
                async with asyncio.timeout(20):
                    await wait_for(window.approve_source.isEnabled)
                    window.projects.setCurrentIndex(window.projects.findData(atlas.project))
                    await wait_for(window.approve_source.isEnabled)
                    window.navigate("Evidence")
                    evidence.query.setText("Which database holds checkout records?")
                    QTest.keyClick(evidence.query, Qt.Key.Key_Return)
                    await wait_for(lambda: evidence.matches.count() > 0)
                    evidence.matches.setFocus()
                    QTest.keyClick(evidence.matches, Qt.Key.Key_Return)
                    await wait_for(lambda: "SQLite" in evidence.detail.toPlainText())
                    self.assertIn("Page 1", evidence.detail.toPlainText())

                    evidence.query.setText("archival marker")
                    evidence.revision.setText(old[1])
                    evidence.search.click()
                    await wait_for(lambda: evidence.matches.count() > 0)
                    evidence.inspect.click()
                    await wait_for(lambda: "archival marker" in evidence.detail.toPlainText())
                    self.assertIn(f"Revision ID  {old[1]}", evidence.detail.toPlainText())
                    self.assertIn("Text range [0, 15)", evidence.detail.toPlainText())

                    evidence.revision.clear()
                    evidence.query.setText("current marker")
                    evidence.search.click()
                    await received.wait()
                    foreign = window.projects.findData(birch.project)
                    self.assertGreaterEqual(foreign, 0)
                    window.projects.setCurrentIndex(foreign)
                    self.assertEqual(evidence.query.text(), "")
                    self.assertEqual(evidence.detail.toPlainText(), "")
                    release.set()
                    await returned.wait()
                    await wait_for(window.approve_source.isEnabled)
                    self.assertEqual(evidence.matches.count(), 0)
                    evidence.query.setText("archival marker")
                    evidence.revision.setText(old[1])
                    evidence.search.click()
                    await wait_for(lambda: "Insufficient evidence" in evidence.feedback.text())
                    self.assertEqual(evidence.matches.count(), 0)

                    window.projects.setCurrentIndex(window.projects.findData(atlas.project))
                    await wait_for(window.approve_source.isEnabled)
                    evidence.query.setText("archival marker")
                    evidence.revision.setText(old[1])
                    evidence.search.click()
                    await wait_for(lambda: evidence.matches.count() > 0)
                    with sqlite3.connect(db.path) as conn:
                        conn.execute("UPDATE projects SET grant=grant+1 WHERE id=?", (atlas.project,))
                    conn.close()
                    evidence.inspect.click()
                    await wait_for(lambda: "unavailable" in evidence.feedback.text())
                    self.assertEqual(evidence.matches.count(), 0)
                    self.assertEqual(evidence.detail.toPlainText(), "")
            finally:
                release.set()
                stop.set()
                self.assertEqual(await asyncio.wait_for(app, 8), 0)
                window.hide()
                window.deleteLater()

    def test_saved_code_uses_the_selected_historical_revision(self) -> None:
        self.run_scenario(self.saved_code_scenario)

    async def saved_code_scenario(self, root: Path) -> None:
        project_root = root / "approved"
        project_root.mkdir()
        foreign_root = root / "unrelated"
        foreign_root.mkdir()
        file = project_root / "example.py"
        file.write_text("def old_revision_only():\n    return 42\n", encoding="utf-8")
        database = Database(root / "data/jarvis.sqlite3")
        await database.open()
        try:
            store = Repositories(database)
            owner = user_identity()
            project = await store.register(owner, project_root)
            foreign_project = await store.register(owner, foreign_root)
            scope = await store.select(owner, project, 1)
            foreign = await store.select(owner, foreign_project, 1)
            original = await store.approve_source(scope, file)
            await store.extract_locators(scope, original.source_id, original.revision_id)
            file.write_text("def replacement_only():\n    return 84\n", encoding="utf-8")
            replacement = await store.approve_source(scope, file)
            await store.extract_locators(scope, replacement.source_id, replacement.revision_id)
            reference = SavedCode(original.source_id, original.revision_id)
            broker = SavedCodeBroker(store)
            self.assertEqual(await broker.choices(foreign), [])
            with self.assertRaises(Failure) as denied:
                await broker.identify(foreign, reference)
            self.assertEqual(denied.exception.code, Code.SCOPE)
            await database.call(lambda conn: conn.execute("UPDATE projects SET grant=grant+1 WHERE id=?", (project,)),
                                write=True)
            with self.assertRaises(Failure) as revoked:
                await broker.read(scope, reference, 4096)
            self.assertEqual(revoked.exception.code, Code.SCOPE)
        finally:
            await database.close()

        before = hashlib.sha256(file.read_bytes()).hexdigest()
        received: list[ChatMessage] = []

        async def generate(_model: Ollama, messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
            received.extend(messages)
            yield "The saved function returns 42."

        stop = asyncio.Event()
        window = MainWindow()
        window.show()
        with patch.object(Ollama, "probe", autospec=True), patch.object(Ollama, "generate", generate):
            app = asyncio.create_task(run_app(window, root, stop))
            try:
                async with asyncio.timeout(15):
                    while not window.send.isEnabled():
                        await asyncio.sleep(.02)
                    window.projects.setCurrentIndex(window.projects.findData(project))
                    while not window.choose_code.isEnabled():
                        await asyncio.sleep(.02)
                    window.pair_editor.trigger()
                    while not (pairing := window.findChild(QDialog)) or pairing.windowTitle() != "Pair VS Code":
                        await asyncio.sleep(.02)
                    invitation_field = pairing.findChild(QLineEdit)
                    self.assertTrue(invitation_field.isReadOnly())
                    ticket = json.loads(invitation_field.text())
                    await self.share_editor_fixture(window, ticket, project_root, file)
                    window.disconnect_editor.trigger()
                    while window.editor_status.text() != "VS Code disconnected":
                        await asyncio.sleep(.02)
                    self.assertEqual(window.editor_snapshot_summary.text(), "No editor context shared")
                    self.assertFalse(window.disconnect_editor.isEnabled())
                    with patch.object(EditorLaunchBroker, "open_project", autospec=True) as launch:
                        QTest.keyClick(window.open_editor, Qt.Key.Key_Space)
                        while not launch.await_count:
                            await asyncio.sleep(.02)
                        _, launched_scope, _ = launch.await_args.args
                        self.assertEqual(launched_scope.project, project)
                        self.assertIn("VS Code launch requested", window.status.text())
                    window.choose_code.click()
                    while not (picker := window.findChild(QInputDialog)) or not picker.isVisible():
                        await asyncio.sleep(.02)
                    listing = picker.findChild(QListView)
                    self.assertIsNotNone(listing)
                    QTest.keyClick(listing, Qt.Key.Key_End)
                    self.assertIn(original.revision_id, picker.textValue())
                    picker.accept()
                    self.assertIn(original.revision_id, window.code_label.text())
                    window.draft.setPlainText("Explain this saved code.")
                    window.send.click()
                    while "assistant [completed]" not in window.history.toPlainText():
                        await asyncio.sleep(.02)
                    self.assertIn("Saved code: example.py", window.history.toPlainText())
                    self.assertIn(original.revision_id, window.history.toPlainText())
                    self.assertEqual(window.code_label.text(), "")
                    self.assertEqual(len(received), 1)
                    self.assertIn("old_revision_only", received[0].content)
                    self.assertIn(original.revision_id, received[0].content)
                    self.assertNotIn("replacement_only", received[0].content)
                    self.assertNotIn(replacement.revision_id, received[0].content)
                    self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(), before)
            finally:
                stop.set()
                self.assertEqual(await asyncio.wait_for(app, 8), 0)
                window.hide()

    async def share_editor_fixture(self, window: MainWindow, ticket: dict, root: Path, file: Path) -> None:
        from _winapi import CreateFile

        client = object.__new__(LocalPipe)
        client.handle = CreateFile(ticket["pipe"], 0xC0000000, 0, 0, 3, 0x40000000, 0)
        try:
            await client.send(encode_frame({"operation": "pair", "request_id": 1,
                                            "deadline_ms": time.time_ns() // 1_000_000 + 4000,
                                            "invitation": ticket["invitation"], "versions": [1], "window": "a" * 32}))
            hello = json.loads(await client.receive())
            point = {"line": 0, "character": 0}
            await client.send(encode_frame({"operation": "snapshot", "request_id": 2,
                                            "deadline_ms": time.time_ns() // 1_000_000 + 4000,
                                            **{key: hello[key] for key in ("session", "version", "binding", "window")},
                                            "snapshot": {"workspace_uri": root.as_uri(), "document_uri": file.as_uri(),
                                                         "document_id": "b" * 32, "document_version": 1,
                                                         "dirty": True, "sha256": "a" * 64,
                                                         "selection": {"anchor": point, "active": point},
                                                         "diagnostics": []}}))
            self.assertTrue(json.loads(await client.receive())["ok"])
            summary = window.editor_snapshot_summary.text()
            self.assertIn("Last shared workspace", summary)
            self.assertIn(f"Buffer: {file.name}", summary)
            self.assertIn("Version 1 · Unsaved changes", summary)
            window.view_editor_context.trigger()
            while not (dialog := next((item for item in window.findChildren(QDialog) if item.isVisible()
                                       and item.windowTitle() == "Last shared VS Code context"), None)):
                await asyncio.sleep(.02)
            shown = dialog.findChild(QPlainTextEdit).toPlainText()
            self.assertIn(f"File: {file.name}", shown)
            self.assertIn("Unsaved changes", shown)
            dialog.close()
        finally:
            client.close()

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
        spoken: list[str] = []
        speech_started = asyncio.Event()
        playback_stopped = asyncio.Event()
        first = "Visit the café! "
        last = "Open `script.py` and see [the guide](https://example.com)."

        async def play(pcm, _cancel):
            spoken.append(pcm.decode("utf-8"))
            speech_started.set()
            if len(spoken) == 2:
                while not _cancel.is_set():
                    await asyncio.sleep(.01)
                playback_stopped.set()

        self.enterContext(patch("stylus_jarvis.voice.piper.Piper.synthesize",
                                new=lambda _self, sentence, _cancel: sentence.encode("utf-8")))
        self.enterContext(patch("stylus_jarvis.bootstrap.ReplySpeech",
                                side_effect=lambda engine, validate, status: ReplySpeech(engine, validate, status, play)))

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
                    self.assertEqual(question["messages"][-1]["content"], "Explain this project\nCorrected dictation")
                    frames = [(json.dumps({"message": {"content": text}, "done": done}) + "\n").encode()
                              for text, done in ((first, False), (last, True))]
                    body = b"".join(frames)
                writer.write(f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode())
                if path == "/api/chat":
                    writer.write(frames[0])
                    await writer.drain()
                    await asyncio.wait_for(speech_started.wait(), 5)
                    writer.write(frames[1])
                    await writer.drain()
                    return
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
                window.navigate("Memory")
                window.memory.scope.setCurrentIndex(1)
                while not window.correct_fact.isEnabled():
                    await asyncio.sleep(.02)
                window.correct_fact.click()
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
                window.navigate("Conversation")
                selected.write_bytes(b"owner selected evidence")
                with patch("stylus_jarvis.bootstrap.QFileDialog.getOpenFileName",
                           return_value=(str(selected), "")):
                    window.approve_source.click()
                    while "Approved approved.txt" not in window.status.text():
                        await asyncio.sleep(.02)
                    window.extract_source.click()
                    while "Saved locators: 1" not in window.status.text():
                        await asyncio.sleep(.02)
                window.activateWindow()
                while not window.isActiveWindow():
                    await asyncio.sleep(.02)
                original_conversation = window.threads.currentData()
                voice = window.voice
                microphone = Mock()
                microphone.id.return_value = b"desktop-rehearsal"
                microphone.description.return_value = "Desktop rehearsal microphone"
                with (patch.object(voice._capture, "inputs", side_effect=[[microphone], [], []]),
                      patch.object(voice._capture, "start", return_value=True),
                      patch.object(voice._capture, "stop", return_value=None) as discard):
                    voice.refresh()
                    window.draft.setPlainText("Explain this")
                    QTest.mousePress(voice.talk, Qt.MouseButton.LeftButton)
                    self.assertIn("Recording", voice.recording.text())
                    voice._capture.inputs_changed.emit()
                    discard.assert_called_once_with(discard=True)
                    self.assertIn("Continue by typing", voice.recording.text())
                    self.assertTrue(window.draft.hasFocus())
                    window.draft.moveCursor(QTextCursor.MoveOperation.End)
                    QTest.keyClicks(window.draft, " project")
                    self.assertEqual(window.draft.toPlainText(), "Explain this project")
                    self.assertEqual(window.threads.currentData(), original_conversation)
                clip = AudioClip(b"\0\0", 16000, 1, QAudioFormat.SampleFormat.Int16)
                worker_started = Event()
                worker_cancelled = Event()

                def late_result(_worker, _clip, cancel):
                    worker_started.set()
                    if not cancel.wait(3):
                        raise RuntimeError("Voice cancellation was not signalled")
                    worker_cancelled.set()
                    return "Late result"

                with patch("stylus_jarvis.voice.whisper.Whisper.transcribe", late_result):
                    window.voice.capture_ready.emit(clip)
                    while not worker_started.is_set():
                        await asyncio.sleep(.02)
                    window.discard_transcript.click()
                    while not window.voice.isEnabled():
                        await asyncio.sleep(.02)
                    self.assertTrue(worker_cancelled.is_set())
                    self.assertTrue(window.voice_review.isHidden())
                    self.assertEqual(window.voice_transcript.toPlainText(), "")
                with patch("stylus_jarvis.voice.whisper.Whisper.transcribe", return_value="Sample dictated message"):
                    window.voice.capture_ready.emit(clip)
                    while window.voice_transcript.toPlainText() != "Sample dictated message":
                        await asyncio.sleep(.02)
                    window.discard_transcript.click()
                    self.assertTrue(window.voice_review.isHidden())
                    self.assertEqual(window.draft.toPlainText(), "Explain this project")

                    window.voice.capture_ready.emit(clip)
                    while window.voice_transcript.toPlainText() != "Sample dictated message":
                        await asyncio.sleep(.02)
                    self.assertFalse(window.voice_transcript.isReadOnly())
                    window.voice_transcript.selectAll()
                    QTest.keyClicks(window.voice_transcript, "Corrected dictation")
                    self.assertEqual(window.draft.toPlainText(), "Explain this project")
                    self.assertNotIn("/api/chat", requests)
                    window.use_transcript.click()
                    self.assertEqual(window.draft.toPlainText(), "Explain this project\nCorrected dictation")
                    self.assertTrue(window.voice_review.isHidden())
                    self.assertEqual(window.voice_transcript.toPlainText(), "")
                    self.assertFalse(window.voice_transcript.document().isUndoAvailable())
                    self.assertNotIn("/api/chat", requests)
                self.assertFalse(window.speak_replies.isChecked())
                window.speak_replies.click()
                QTest.mouseClick(window.send, Qt.MouseButton.LeftButton)
                while "assistant [completed]" not in window.history.toPlainText():
                    await asyncio.sleep(0.02)
                self.assertIn("café!", window.history.toPlainText())
                self.assertIn("`script.py`", window.history.toPlainText())
                self.assertIn("[the guide](https://example.com)", window.history.toPlainText())
                while len(spoken) < 2:
                    await asyncio.sleep(.02)
                self.assertEqual(spoken, ["Visit the café!", "Open and see."])
                self.assertTrue(window.voice.playing)
                self.assertTrue(window.stop.isEnabled())
                self.assertEqual(window.core_display.state, CoreState.SPEAKING)
                window.stop.click()
                self.assertEqual(window.speech_status.text(), "Speech stopped.")
                await asyncio.wait_for(playback_stopped.wait(), 1)
                self.assertFalse(window.voice.playing)
                window.recovery_toggle.click()
                while "No recorded success" not in window.recovery_view.toPlainText():
                    await asyncio.sleep(.02)
                self.assertIn("Not configured", window.recovery_view.toPlainText())
                window.navigate("Memory")
                async def open_forget_editor() -> FactEditor:
                    while not window.forget_fact.isEnabled():
                        await asyncio.sleep(.02)
                    window.forget_fact.click()
                    while not any(e.isVisible() for e in window.findChildren(FactEditor)):
                        await asyncio.sleep(.02)
                    return next(e for e in window.findChildren(FactEditor) if e.isVisible())

                forget_editor = await open_forget_editor()
                self.assertEqual(forget_editor.statement.toPlainText(), "A corrected personal preference")
                self.assertTrue(forget_editor.statement.isReadOnly())
                self.assertEqual(forget_editor.save.text(), "Confirm forget")
                forget_editor.reject()
                forget_editor = await open_forget_editor()
                forget_editor.save.click()
                while "forgotten from personal memory" not in window.status.text():
                    await asyncio.sleep(.02)
                with sqlite3.connect(db.path) as reader:
                    self.assertEqual(reader.execute("SELECT count(*) FROM fact_versions").fetchone()[0], 0)
                reader.close()
                export = root / "desktop-export.json"
                with patch("stylus_jarvis.bootstrap.QFileDialog.getSaveFileName",
                           return_value=(str(export), "")) as choose:
                    window.export_project.click()
                    while "Project exported" not in window.status.text():
                        await asyncio.sleep(.02)
                    self.assertIn(window.projects.currentText(), choose.call_args.args[1])
                manifest_data = json.loads(export.read_bytes())
                self.assertEqual(manifest_data["conversations"][0]["messages"][1]["content"], first + last)
                self.assertEqual(manifest_data["facts"], [])
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

