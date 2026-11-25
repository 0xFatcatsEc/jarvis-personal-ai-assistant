import os
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from stylus_jarvis.contracts.messages import Code, Failure
from stylus_jarvis.editor.launch import VSCodeLauncher, pin_path
from stylus_jarvis.runtime.offline import _audit
from stylus_jarvis.security.broker import EditorLaunchBroker
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.repositories import Repositories
from stylus_jarvis.storage.tool_journal import ToolJournal


@unittest.skipUnless(os.name == "nt", "Windows desktop launch")
class EditorLaunchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.scratch = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.root = self.scratch / "Approved project with spaces"
        self.root.mkdir()
        self.foreign = self.scratch / "Unrelated project"
        self.foreign.mkdir()
        self.image = self.scratch / "Installed application with spaces" / "Code.exe"
        self.image.parent.mkdir()
        self.image.write_bytes(b"unsigned fixture")
        self.db = Database(self.scratch / "data/jarvis.sqlite3")
        await self.db.open()
        self.addAsyncCleanup(self.db.close)
        self.store = Repositories(self.db)
        project = await self.store.register("owner", self.root)
        self.scope = await self.store.select("owner", project, 1)
        self.launcher = VSCodeLauncher()
        self.broker = EditorLaunchBroker(self.store, self.launcher, ToolJournal(self.db))

    async def test_passes_exact_absolute_command_through_audit(self) -> None:
        def spawn(args, **kwargs):
            line = subprocess.list2cmdline(args)
            _audit("subprocess.Popen", (kwargs["executable"], line, kwargs["cwd"], kwargs["env"]))
            return Mock()

        with (patch.object(self.launcher, "resolve", return_value=self.image),
              patch.object(self.launcher, "verify") as verify,
              patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-secret"}),
              patch("stylus_jarvis.runtime.offline.subprocess.Popen", side_effect=spawn) as launch):
            await self.broker.open_project(self.scope, lambda: True)
        verify.assert_called_once()
        args, = launch.call_args.args
        self.assertEqual(args, [str(self.image), "--new-window", "--disable-extensions",
                                "--disable-telemetry", "--disable-updates", str(self.root)])
        self.assertEqual(launch.call_args.kwargs["executable"], str(self.image))
        self.assertEqual(launch.call_args.kwargs["cwd"], self.image.parent)
        self.assertNotIn("OPENAI_API_KEY", launch.call_args.kwargs["env"])
        receipt = await self.db.call(lambda c: dict(c.execute("SELECT * FROM local_tool_runs").fetchone()))
        self.assertEqual((receipt["tool"], receipt["state"]), ("system.open_approved_project", "succeeded"))
        self.assertIsNotNone(receipt["dispatch_at"])
        self.assertNotIn(str(self.root), str(receipt))
        with self.assertRaises(Failure):
            _audit("subprocess.Popen", (str(self.image), subprocess.list2cmdline(args), None, None))

    async def test_unrelated_and_redirected_roots_never_reach_launch(self) -> None:
        with patch.object(self.launcher, "resolve") as resolve:
            with self.assertRaises(Failure) as denied:
                await self.broker.open_project(self.scope, lambda: True, target=self.foreign)
            self.assertEqual(denied.exception.code, Code.SCOPE)
            from _winapi import CreateJunction

            hidden_root = self.scratch / "Renamed original"
            self.root.rename(hidden_root)
            CreateJunction(str(self.foreign), str(self.root))
            with self.assertRaises(Failure) as redirected:
                await self.broker.open_project(self.scope, lambda: True)
            self.assertEqual(redirected.exception.code, Code.SCOPE)
            resolve.assert_not_called()

    async def test_stale_selection_and_revocation_during_signature_check(self) -> None:
        still_selected = True

        def change_selection(_image, _handle):
            nonlocal still_selected
            still_selected = False

        def revoke(_image, _handle):
            with closing(sqlite3.connect(self.db.path)) as connection, connection:
                connection.execute("UPDATE projects SET grant=grant+1 WHERE id=?", (self.scope.project,))

        with (patch.object(self.launcher, "resolve", return_value=self.image),
              patch.object(self.launcher, "launch") as launch):
            with patch.object(self.launcher, "verify", side_effect=change_selection):
                with self.assertRaises(Failure) as stale:
                    await self.broker.open_project(self.scope, lambda: still_selected)
                self.assertEqual(stale.exception.code, Code.SCOPE)
            with patch.object(self.launcher, "verify", side_effect=revoke):
                with self.assertRaises(Failure) as revoked:
                    await self.broker.open_project(self.scope, lambda: True)
                self.assertEqual(revoked.exception.code, Code.SCOPE)
            launch.assert_not_called()

    async def test_unsigned_image_rejected_without_dispatch(self) -> None:
        with (patch.object(self.launcher, "resolve", return_value=self.image),
              patch.object(self.launcher, "launch") as launch):
            with self.assertRaises(Failure) as denied:
                await self.broker.open_project(self.scope, lambda: True)
            self.assertEqual(denied.exception.code, Code.EDITOR)
            launch.assert_not_called()

    async def test_root_redirected_during_signature_verification_never_dispatches(self) -> None:
        from _winapi import CreateJunction

        def redirect(_image, _handle):
            self.root.rename(self.scratch / "Previous root")
            CreateJunction(str(self.foreign), str(self.root))

        with (patch.object(self.launcher, "resolve", return_value=self.image),
              patch.object(self.launcher, "verify", side_effect=redirect),
              patch.object(self.launcher, "launch") as launch):
            with self.assertRaises(Failure) as denied:
                await self.broker.open_project(self.scope, lambda: True)
        self.assertEqual(denied.exception.code, Code.SCOPE)
        launch.assert_not_called()

    def test_native_installed_image(self) -> None:
        if os.environ.get("STYLUS_VSCODE_NATIVE") != "1":
            self.skipTest("requires the installed Microsoft VS Code build")
        image = self.launcher.resolve()
        with pin_path(image) as handle:
            self.launcher.verify(image, handle)
