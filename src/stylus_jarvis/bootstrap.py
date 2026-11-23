"""Application composition root and Qt command bindings for the offline desktop."""
import asyncio
import csv
import os
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID, uuid4

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QComboBox, QFileDialog, QMessageBox
from qasync import QEventLoop

from .contracts.messages import Code, Failure, RuntimeEvent, Scope
from .inference.ollama import Ollama
from .inference.router import Router
from .runtime.coordinator import Coordinator
from .runtime.diagnostics import Diagnostics, Event
from .runtime.scheduler import Scheduler
from .settings import load, profile_path
from .storage.database import Database
from .storage.repositories import Repositories
from .ui.main_window import MainWindow


def user_identity() -> str:
    """Use the process token's SID, which survives account renaming."""
    executable = Path(os.environ["SystemRoot"]) / "System32" / "whoami.exe"
    result = subprocess.run([str(executable), "/user", "/fo", "csv", "/nh"], check=True,
                            capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
    row = next(csv.reader([result.stdout.decode("ascii", "replace").strip()]))
    if len(row) != 2 or not row[1].startswith("S-1-"):
        raise Failure(Code.SCOPE)
    return row[1]


class Desktop:
    def __init__(self, view: MainWindow, store: Repositories, router: Router,
                 coordinator: Coordinator, log: Diagnostics, owner: str) -> None:
        self.view = view
        self.store = store
        self.router = router
        self.core = coordinator
        self.log = log
        self.owner = owner
        self.generation = 0
        self.tasks: set[asyncio.Task[None]] = set()
        self.sending = False
        self.closing = False
        self.request: UUID | None = None
        self.view.add_project.clicked.connect(lambda: self.spawn(self.add_project))
        self.view.projects.currentIndexChanged.connect(lambda: self.change(True))
        self.view.threads.currentIndexChanged.connect(lambda: self.change(False))
        self.view.new_thread.clicked.connect(lambda: self.change(False, new=True))
        self.view.probe.clicked.connect(lambda: self.spawn(self.probe))
        self.view.search.returnPressed.connect(lambda: self.spawn(self.history))
        self.view.retry.clicked.connect(lambda: self.spawn(self.retry))
        self.view.send.clicked.connect(self.send)
        self.view.stop.clicked.connect(self.stop)

    def spawn(self, action: Callable[[], Awaitable[None]]) -> None:
        if self.closing:
            return
        async def guarded() -> None:
            try:
                await action()
            except Failure as exc:
                self.log.emit(Event.ERROR, code=exc.code, run=exc.reference)
                self.view.status.setText(str(exc))
            except Exception:
                self.log.emit(Event.ERROR, code=Code.INTERNAL)
                self.view.status.setText(str(Failure(Code.INTERNAL)))
            finally:
                self.controls()
        task = asyncio.create_task(guarded())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def controls(self) -> None:
        self.view.send.setEnabled(bool(self.core.selection and self.router.verified
                                      and not self.sending and self.core.pending is None))
        self.view.stop.setEnabled(self.sending)
        self.view.retry.setEnabled(self.core.pending is not None)
        self.view.probe.setEnabled(not self.sending)

    @staticmethod
    def populate(combo: QComboBox, items: list[tuple[str, str]], selected: str | None = None) -> None:
        blocked = combo.blockSignals(True)
        try:
            combo.clear()
            for key, label in items:
                combo.addItem(label, key)
            if selected is not None:
                combo.setCurrentIndex(combo.findData(selected))
        finally:
            combo.blockSignals(blocked)

    async def projects(self, selected: str | None = None) -> None:
        items = await self.store.projects(self.owner)
        self.populate(self.view.projects, items, selected)
        self.change(True)

    async def add_project(self) -> None:
        path = QFileDialog.getExistingDirectory(self.view, "Select a local project")
        if path:
            key = await self.store.register(self.owner, Path(path))
            await self.projects(key)

    def change(self, project_changed: bool, *, new: bool = False) -> None:
        self.generation += 1
        generation = self.generation
        project = self.view.projects.currentData()
        self.core.select(None)
        self.view.history.clear()
        self.view.search.clear()
        self.view.draft.clear()
        self.request = None
        if project_changed:
            self.populate(self.view.threads, [])
        self.controls()
        if not project:
            return

        async def activate() -> None:
            threads = await self.store.conversations(self.owner, project)
            if self.generation != generation:
                return
            key = self.view.threads.currentData() if not project_changed else None
            if not new and not key and threads:
                key = threads[0][0]
            scope = await self.store.select(self.owner, project, generation, None if new else key)
            threads = await self.store.conversations(self.owner, project)
            await self.store.validate(scope)
            if self.generation == generation:
                self.populate(self.view.threads, threads, scope.conversation)
                self.core.select(scope)
                await self.history()
        self.spawn(activate)

    async def history(self) -> None:
        scope = self.core.selection
        if not scope:
            return
        query = self.view.search.text()
        cursor = 0
        lines: list[str] = []
        while True:
            page = await self.store.history(scope, after=cursor, query=query)
            if scope != self.core.selection or query != self.view.search.text():
                return
            for seq, role, text, state in page:
                lines.append(f"{role} [{state}]\n{text}")
                cursor = seq
            if len(page) < 100:
                break
        await self.store.validate(scope)
        if scope != self.core.selection or query != self.view.search.text():
            return
        self.view.history.setPlainText("\n\n".join(lines))
        self.view.history.moveCursor(QTextCursor.MoveOperation.End)

    async def probe(self) -> None:
        started = time.monotonic()
        try:
            await self.router.probe()
            self.view.status.setText("Offline · Local model verified")
        finally:
            self.log.emit(Event.PROBE, elapsed_ms=(time.monotonic()-started)*1000,
                          digest=self.router.digest)

    def event(self, event: RuntimeEvent) -> None:
        if self.closing or event.scope != self.core.selection or event.request != self.request:
            return
        if event.kind == "fragment":
            self.view.history.moveCursor(QTextCursor.MoveOperation.End)
            self.view.history.insertPlainText(event.text)
        else:
            self.view.status.setText(event.text)

    def stop(self) -> None:
        self.core.scheduler.stop()
        self.view.status.setText("Stopping local reply…")

    def send(self) -> None:
        scope = self.core.selection
        if not scope or self.sending:
            return
        self.sending = True
        request = uuid4()
        self.request = request
        text = self.view.draft.toPlainText()
        self.controls()
        self.view.history.appendPlainText(f"\nuser\n{text}\n\nassistant [provisional]")
        self.view.status.setText("Generating locally…")

        async def run() -> None:
            try:
                turn = await self.core.submit(scope, request, text)
                if scope == self.core.selection and text == self.view.draft.toPlainText():
                    self.view.draft.clear()
                    self.view.status.setText(f"Offline · {turn.state.value}")
            finally:
                self.sending = False
                if scope == self.core.selection and self.core.pending is None:
                    await self.history()
                    threads = await self.store.conversations(self.owner, scope.project)
                    await self.store.validate(scope)
                    if scope == self.core.selection:
                        self.populate(self.view.threads, threads, scope.conversation)
        self.spawn(run)

    async def retry(self) -> None:
        await self.core.retry_save()
        await self.history()
        self.view.status.setText("Reply saved")

    async def shutdown(self) -> None:
        self.closing = True
        self.view.centralWidget().setEnabled(False)
        if not await self.core.scheduler.shutdown():
            self.view.status.setText("Finishing the accepted database operation before closing…")
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)


async def run_app(view: MainWindow, root: Path, exiting: asyncio.Event) -> int:
    log = Diagnostics(root / "logs")
    db = Database(root / "data" / "jarvis.sqlite3")
    model: Ollama | None = None
    desktop: Desktop | None = None
    try:
        log.emit(Event.START)
        settings, manifest = await asyncio.to_thread(load, root)
        await db.open()
        store = Repositories(db)
        model = Ollama(settings, manifest)
        router = Router(model, settings, manifest)
        scheduler = Scheduler()
        def deliver(event: RuntimeEvent) -> None:
            if desktop:
                desktop.event(event)
        core = Coordinator(store, router, scheduler, log, deliver)
        owner = await asyncio.to_thread(user_identity)
        desktop = Desktop(view, store, router, core, log, owner)
        if not exiting.is_set():
            await desktop.projects()
            view.centralWidget().setEnabled(True)
            desktop.controls()
            desktop.spawn(desktop.probe)
            await exiting.wait()
        return 0
    except (Failure, OSError, subprocess.SubprocessError) as exc:
        failure = exc if isinstance(exc, Failure) else Failure(Code.INTERNAL)
        log.emit(Event.ERROR, code=failure.code, run=failure.reference)
        view.centralWidget().setEnabled(True)
        view.status.setText(f"Startup blocked. {failure} Close and reopen after repair.")
        if not exiting.is_set():
            await exiting.wait()
        return 1
    finally:
        if desktop:
            await desktop.shutdown()
        if model:
            await model.close()
        await db.close()
        log.emit(Event.STOP)
        await asyncio.to_thread(log.close)


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    try:
        root = profile_path()
        root.mkdir(parents=True, exist_ok=True)
    except (Failure, OSError):
        QMessageBox.critical(None, "STYLUS JARVIS", "Cannot open the local user profile.")
        return 1
    lock = QLockFile(str(root / "instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.warning(None, "STYLUS JARVIS", "Another instance is running or the profile lock is unavailable.")
        return 1
    try:
        view = MainWindow()
        loop = QEventLoop(app)
        asyncio.set_event_loop(loop)
        exiting = asyncio.Event()
        view.closing.connect(exiting.set)
        view.show()
        with loop:
            return loop.run_until_complete(run_app(view, root, exiting))
    finally:
        lock.unlock()

