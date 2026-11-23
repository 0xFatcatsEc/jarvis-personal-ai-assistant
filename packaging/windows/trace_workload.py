"""Drive one real offline desktop turn using a temporary, synthetic user store."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path


def now() -> str:
    return datetime.now(UTC).isoformat()


async def exercise(port: int, root: Path) -> None:
    from stylus_jarvis.bootstrap import run_app, user_identity
    from stylus_jarvis.runtime.offline import verify_application
    from stylus_jarvis.settings import Settings, save
    from stylus_jarvis.storage.database import Database
    from stylus_jarvis.storage.repositories import Repositories
    from stylus_jarvis.ui.main_window import MainWindow

    await asyncio.to_thread(verify_application)
    save(root, Settings(port=port, offline=True, output=96))
    store = Database(root / "data/jarvis.sqlite3")
    await store.open()
    try:
        await Repositories(store).register(user_identity(), root)
    finally:
        await store.close()
    window = MainWindow()
    stop = asyncio.Event()
    window.show()
    desktop = asyncio.create_task(run_app(window, root, stop))
    try:
        async with asyncio.timeout(180):
            while not (window.centralWidget().isEnabled() and window.send.isEnabled()):
                await asyncio.sleep(.1)
            window.draft.setPlainText("Reply with OK.")
            window.send.click()
            while "assistant [completed]" not in window.history.toPlainText():
                await asyncio.sleep(.1)
    finally:
        stop.set()
        if await asyncio.wait_for(desktop, 12) != 0:
            raise RuntimeError("Desktop shutdown failed")
        window.hide()


def workload(directory: Path) -> None:
    from stylus_jarvis.settings import profile_path

    root = profile_path()
    guarded = root / "runtime/python/python.exe"
    repo = Path(__file__).resolve().parents[2]
    system = Path(os.environ["SystemRoot"]) / "System32"
    record = directory / "workload.json"
    with record.open("x", encoding="utf-8") as f:
        json.dump({"completed": False}, f)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    started = now()
    # An observer-only resolution of localhost exercises DNS event collection.
    # Use Windows' DNS API explicitly so Winsock cannot short-circuit numerically.
    with subprocess.Popen([str(system / "WindowsPowerShell/v1.0/powershell.exe"), "-NoProfile",
                           "-NonInteractive", "-Command",
                           "Resolve-DnsName stylus-control.invalid -Type A -DnsOnly -CacheOnly -ErrorAction SilentlyContinue"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as dns:
        dns.wait(timeout=20)
    with tempfile.TemporaryFile() as log:
        launcher = subprocess.Popen([
            str(system / "WindowsPowerShell/v1.0/powershell.exe"), "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "RemoteSigned", "-File", str(repo / "src/stylus_jarvis/runtime/offline-policy.ps1"),
            "-Mode", "Serve", "-PythonImage", str(guarded), "-Port", str(port),
        ], stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 75
            while True:
                if launcher.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Guarded server failed to start")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=.4):
                        break
                except OSError:
                    time.sleep(.25)
            with subprocess.Popen([str(guarded), "-B", "-P", "-s", __file__, "--desktop", str(port)]) as client:
                try:
                    if client.wait(timeout=240):
                        raise RuntimeError("Guarded desktop failed its synthetic turn")
                finally:
                    if client.poll() is None:
                        client.kill()
        finally:
            if launcher.poll() is None:
                subprocess.run([str(system / "taskkill.exe"), "/PID", str(launcher.pid), "/T", "/F"],
                               check=True, capture_output=True, timeout=20)
            launcher.wait(timeout=10)
    record.write_text(json.dumps(dict(completed=True, offline=True, start=started, end=now(), port=port,
                                      launcher=launcher.pid, desktop=client.pid, dnsControl=dns.pid),
                                 indent=2), encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1] == "--desktop":
        from stylus_jarvis.runtime.offline import install_worker_policy
        install_worker_policy()
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtWidgets import QApplication
        from qasync import QEventLoop

        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        with tempfile.TemporaryDirectory() as scratch, QEventLoop(app) as loop:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(exercise(int(sys.argv[2]), Path(scratch)))
    else:
        workload(Path(sys.argv[1]))
