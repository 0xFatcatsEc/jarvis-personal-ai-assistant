"""Acceptance coverage for backlog 1.2.1.1 against the real store and Qt picker."""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from stylus_jarvis.bootstrap import run_app, user_identity
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories
from stylus_jarvis.ui.main_window import MainWindow


class RootIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / "Parent A" / "Shared Project"
        self.root.mkdir(parents=True)
        self.db = await self.open_database()
        self.store = Repositories(self.db)

    async def open_database(self) -> Database:
        db = Database(self.base / "profile" / "jarvis.sqlite3")
        self.addAsyncCleanup(db.close)
        await db.open()
        return db

    async def test_same_name_ids_survive_database_reopen(self) -> None:
        other = self.base / "Parent B" / self.root.name
        other.mkdir(parents=True)
        first = await self.store.register("owner", self.root)
        second = await self.store.register("owner", other)
        self.assertNotEqual(first, second)
        await self.db.close()

        reopened = Repositories(await self.open_database())
        self.assertEqual(await reopened.register("owner", other), second)
        self.assertEqual(await reopened.register("owner", self.root), first)
        self.assertCountEqual(await reopened.projects("owner"), [
            (first, str(self.root.resolve())), (second, str(other.resolve())),
        ])

    async def assert_alias_identity(self, alias: Path) -> None:
        # Register the alias first so the stored label must still be the real root.
        project = await self.store.register("owner", alias)
        self.assertEqual(await self.store.register("owner", self.root), project)
        self.assertEqual(await self.store.projects("owner"), [(project, str(self.root.resolve()))])

    @unittest.skipUnless(os.name == "nt", "Windows case-insensitive root")
    async def test_case_variant(self) -> None:
        await self.assert_alias_identity(self.root.with_name(self.root.name.swapcase()))

    @unittest.skipUnless(os.name == "nt", "Windows directory junction")
    async def test_junction_in_parent_path(self) -> None:
        from _winapi import CreateJunction

        alias = self.base / "Parent Junction"
        CreateJunction(str(self.root.parent), str(alias))
        self.assertTrue(alias.is_junction())
        await self.assert_alias_identity(alias / self.root.name)

    async def test_directory_symlink(self) -> None:
        alias = self.base / "Project Link"
        try:
            alias.symlink_to(self.root, target_is_directory=True)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                self.skipTest("Windows did not grant directory symlink creation")
            raise
        await self.assert_alias_identity(alias)


@unittest.skipUnless(os.name == "nt", "Windows desktop identity")
class ProjectPickerDesktopTest(unittest.TestCase):
    def test_keyboard_switches_between_identically_named_roots(self) -> None:
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        with tempfile.TemporaryDirectory() as folder, QEventLoop(app) as loop:
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.keyboard_scenario(Path(folder)))
            finally:
                asyncio.set_event_loop(None)

    async def keyboard_scenario(self, base: Path) -> None:
        profile = base / "profile"
        db = Database(profile / "data" / "jarvis.sqlite3")
        await db.open()
        try:
            store = Repositories(db)
            owner = user_identity()
            projects: list[tuple[str, str, str]] = []
            for parent in ("Parent A", "Parent B"):
                root = base / parent / "Shared Project"
                root.mkdir(parents=True)
                key = await store.register(owner, root)
                scope = await store.select(owner, key, 1)
                projects.append((str(root.resolve()), key, scope.conversation))
        finally:
            await db.close()

        window = MainWindow()
        window.show()
        exiting = asyncio.Event()

        async def assert_selection(expected: tuple[str, str, str]) -> None:
            label, project, conversation = expected
            async with asyncio.timeout(5):
                while window.threads.currentData() != conversation:
                    await asyncio.sleep(0.01)
            self.assertEqual(window.projects.currentText(), label)
            self.assertEqual(window.projects.currentData(), project)

        with patch("stylus_jarvis.inference.ollama.Ollama.probe", autospec=True):
            application = asyncio.create_task(run_app(window, profile, exiting))
            try:
                await assert_selection(projects[0])
                self.assertEqual(window.projects.count(), 2)
                # Shift+Tab from the adjacent Add project button reaches the picker.
                window.add_project.setFocus()
                self.assertTrue(window.add_project.hasFocus())
                QTest.keyClick(window.add_project, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
                self.assertTrue(window.projects.hasFocus(), "Shift+Tab must reach the project picker")
                QTest.keyClick(window.projects, Qt.Key.Key_Down)
                await assert_selection(projects[1])
                QTest.keyClick(window.projects, Qt.Key.Key_Up)
                await assert_selection(projects[0])
            finally:
                exiting.set()
                try:
                    await asyncio.wait_for(application, 8)
                finally:
                    window.hide()
