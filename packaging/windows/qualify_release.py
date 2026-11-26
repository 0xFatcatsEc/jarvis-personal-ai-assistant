"""Exercise the installed rehearsal profile with real Qt, SQLite and the guarded Qwen model."""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryFile
from unittest.mock import patch
from urllib.request import ProxyHandler, build_opener

from stylus_jarvis.settings import Settings, profile_path, save


def desktop(root: Path, reopen: bool) -> None:
    from PySide6.QtCore import QTimer
    from stylus_jarvis import bootstrap

    project = root / "sample-project"
    project.mkdir(exist_ok=True)
    sent = False
    completed = False

    class RehearsalWindow(bootstrap.MainWindow):
        def __init__(self):
            super().__init__()
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.drive)
            self.timer.start(200)
            self.selected = False
            self.report_at = time.monotonic() + 30

        def drive(self):
            nonlocal sent, completed
            if time.monotonic() >= self.report_at:
                print("Window status:", self.status.text(), "projects:", self.projects.count(),
                      "threads:", self.threads.count(), "send enabled:", self.send.isEnabled(),
                      flush=True)
                self.report_at = time.monotonic() + 30
            if completed:
                if "Close again" in self.status.text():
                    self.close()
                return
            if not self.centralWidget().isEnabled():
                return
            if not self.selected and not self.projects.count() and not reopen:
                self.selected = True
                self.add_project.click()
            elif not sent and not reopen and self.send.isEnabled():
                self.draft.setPlainText("Reply with OK.")
                sent = True
                self.send.click()
            elif self.send.isEnabled() and "assistant [completed]" in self.history.toPlainText():
                completed = True
                self.close()

    with patch.object(bootstrap, "MainWindow", RehearsalWindow), patch.object(
        bootstrap.QFileDialog, "getExistingDirectory", return_value=str(project)
    ):
        if bootstrap.main() or not completed:
            raise RuntimeError("Desktop did not reopen a completed local turn")


def qualify(root: Path) -> None:
    receipt = json.loads((root / "bundle.json").read_bytes())
    if (root / "data/jarvis.sqlite3").exists():
        raise FileExistsError("Qualify an installation with a fresh sample store")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    save(root, Settings(port=port, output=96))
    system = Path(os.environ["SystemRoot"]) / "System32"
    environment = {key: os.environ[key] for key in (
        "SystemRoot", "WINDIR", "TEMP", "TMP", "LOCALAPPDATA", "APPDATA", "USERPROFILE",
        "PROGRAMDATA", "PATH", "PATHEXT", "ComSpec", "ProgramFiles", "ProgramFiles(x86)",
        "PROCESSOR_ARCHITECTURE", "SystemDrive", "COMPUTERNAME"
    )}
    environment["QT_QPA_PLATFORM"] = "offscreen"
    with TemporaryFile() as log:
        server = subprocess.Popen([str(system / "WindowsPowerShell/v1.0/powershell.exe"),
                                   "-NoProfile", "-NonInteractive", "-File", str(root / "launch-release.ps1"),
                                   "-Component", "Model"], stdout=log, stderr=log, env=environment)
        try:
            client = build_opener(ProxyHandler({}))
            deadline = time.monotonic() + 90
            while True:
                try:
                    with client.open(f"http://127.0.0.1:{port}/api/version", timeout=2) as response:
                        version = json.load(response)["version"]
                    break
                except OSError:
                    if server.poll() is not None or time.monotonic() >= deadline:
                        log.seek(0)
                        details = log.read().decode(errors="replace")[-3000:]
                        raise RuntimeError(f"Installed model server did not start. {details}")
                    time.sleep(.25)
            if version != receipt["ollama"]:
                raise RuntimeError("Installed Ollama version differs from the release")
            for action in ("turn", "reopen"):
                print("Testing installed desktop:", action, flush=True)
                subprocess.run([sys.executable, "-I", "-B", __file__, action], timeout=240,
                               check=True, env=environment)
        finally:
            if server.poll() is None:
                subprocess.run([str(system / "taskkill.exe"), "/PID", str(server.pid), "/T", "/F"],
                               check=True, capture_output=True, timeout=30)
            server.wait(timeout=15)
    with closing(sqlite3.connect(root / "data/jarvis.sqlite3")) as db:
        db.execute("CREATE VIRTUAL TABLE temp.search USING fts5(body)")
        migrations = dict(db.execute("SELECT version,checksum FROM migrations"))
        expected = {int(n.split("_")[0]): h for n, h in receipt["migrations"].items()}
        if migrations != expected or sqlite3.sqlite_version != receipt["sqlite"]:
            raise RuntimeError("Installed database differs from the release")
        if db.execute("SELECT count(*) FROM turns WHERE state='completed'").fetchone() != (1,):
            raise RuntimeError("Expected one durable completed turn")
    print("PASS: installed desktop generated with Qwen, reopened history, verified SQLite migrations and FTS5.")


if __name__ == "__main__":
    target = profile_path()
    if target != Path(os.environ["LOCALAPPDATA"]) / "StylusJarvis-Rehearsal" or not sys.flags.isolated:
        raise SystemExit("Use the rehearsal interpreter with -I.")
    if len(sys.argv) == 1:
        qualify(target)
    else:
        desktop(target, sys.argv[1] == "reopen")
