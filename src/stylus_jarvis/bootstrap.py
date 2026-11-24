"""Application composition root and Qt command bindings for the offline desktop."""
import asyncio
import csv
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID, uuid4

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QComboBox, QFileDialog, QMessageBox
from qasync import QEventLoop

from .contracts.messages import ACTIONS, Code, Failure, RuntimeEvent, Scope, State
from .inference.ollama import Ollama
from .inference.router import Router
from .runtime.coordinator import Coordinator
from .runtime.diagnostics import Diagnostics, Event
from .runtime.scheduler import Scheduler
from .runtime.offline import install_worker_policy, verify_application, whoami
from .settings import load, profile_path
from .storage.database import Database
from .storage.repositories import Repositories
from .ui.main_window import MainWindow


def user_identity() -> str:
    """Use the process token's SID, which survives account renaming."""
    row = next(csv.reader([whoami().decode("ascii", "replace").strip()]))
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
        self.streaming_scope: Scope | None = None
        self.history_version = 0
        self.close_notice_key: str | None = None
        self.closing = False
        self.request: UUID | None = None
        self.view.add_project.clicked.connect(lambda: self.spawn(self.add_project))
        self.view.approve_source.clicked.connect(lambda: self.spawn(self.approve_source))
        self.view.extract_source.clicked.connect(lambda: self.spawn(lambda: self.approve_source(excerpts=True)))
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
                pending = self.core.pending
                if pending is not None and pending.scope == self.core.selection and exc.code in (Code.BUSY, Code.STORE):
                    self.view.status.setText("Reply unsaved. Retry the save in this conversation.")
                else:
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
        self.view.approve_source.setEnabled(bool(self.core.selection and not self.closing))
        self.view.extract_source.setEnabled(self.view.approve_source.isEnabled())
        self.view.send.setEnabled(bool(self.core.selection and self.router.verified
                                      and not self.sending and self.core.pending is None
                                      and not self.core.scheduler.closing))
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

    async def approve_source(self, *, excerpts: bool = False) -> None:
        scope = self.core.selection
        if scope is None:
            return
        title = "Select a file to save revision excerpts locally" if excerpts else "Approve source file"
        path, _ = QFileDialog.getOpenFileName(self.view, title, self.view.projects.currentText())
        if path and self.core.selection == scope:
            receipt = await self.store.approve_source(scope, Path(path))
            if excerpts and self.core.selection == scope:
                records = await self.store.extract_locators(scope, receipt.source_id, receipt.revision_id)
                if self.core.selection == scope:
                    self.view.status.setText(f"Saved locators: {len(records)} · Pages needing OCR: "
                                             f"{sum(r.ocr_needed for r in records)}")
                return
            if self.core.selection == scope:
                self.view.status.setText(f"Approved {receipt.relative_path} · revision {receipt.revision_id}")

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
        if not scope or scope == self.streaming_scope:
            return
        self.history_version += 1
        version = self.history_version
        query = self.view.search.text()

        def current() -> bool:
            return version == self.history_version and scope == self.core.selection and query == self.view.search.text()

        cursor = 0
        lines: list[str] = []
        while True:
            page = await self.store.history(scope, after=cursor, query=query)
            if not current():
                return
            for seq, role, text, state in page:
                lines.append(f"{role} [{state}]\n{text}")
                cursor = seq
            if len(page) < 100:
                break
        await self.store.validate(scope)
        if not current():
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
        if not scope or self.sending or self.core.scheduler.closing:
            return
        self.sending = True
        self.streaming_scope = scope
        self.history_version += 1
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
                    status = ACTIONS[Code.TOKEN_LIMIT] if turn.state == State.TOKEN_LIMIT else turn.state.value
                    self.view.status.setText(f"Offline · {status}")
            finally:
                self.sending = False
                self.streaming_scope = None
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

    async def shutdown(self, grace: float = 5.0) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + grace
        self.closing = True
        self.view.centralWidget().setEnabled(False)
        idle = await self.core.scheduler.shutdown(grace)
        tasks = set(self.tasks)
        if idle and tasks:
            _, tasks = await asyncio.wait(tasks, timeout=max(0., deadline - loop.time()))
        if not idle or tasks:
            self.view.status.setText("Close timed out. Work is still settling. Close again to check.")
            return False
        item = self.core.pending
        if item is not None and (not self.core.recoverable or self.close_notice_key != item.key):
            self.close_notice_key = item.key
            self.closing = False
            self.view.centralWidget().setEnabled(True)
            self.controls()
            message = ("Retry save, or close again to recover the reply on restart." if self.core.recoverable
                       else "Reply exists only in memory. Keep this window open and retry the save.")
            self.view.status.setText(message)
            return False
        return True


async def run_app(view: MainWindow, root: Path, exiting: asyncio.Event, *, shutdown_grace: float = 5.0) -> int:
    log = Diagnostics(root / "logs")
    db = Database(root / "data" / "jarvis.sqlite3", writer_timing=log.writer)
    def refresh_diagnostics() -> None:
        health, recent = log.snapshot()
        view.diagnostic_toggle.setText(health)
        if view.diagnostic_toggle.isChecked():
            content = "\n".join(recent)
            if content != view.diagnostic_view.toPlainText():
                view.diagnostic_view.setPlainText(content)
                view.diagnostic_view.moveCursor(QTextCursor.MoveOperation.End)

    timer = QTimer(view)
    timer.timeout.connect(refresh_diagnostics)
    view.diagnostic_toggle.toggled.connect(refresh_diagnostics)
    refresh_diagnostics()
    timer.start(500)
    model: Ollama | None = None
    desktop: Desktop | None = None
    stopping = False

    async def startup() -> int:
        nonlocal model, desktop
        try:
            settings, manifest = await asyncio.to_thread(load, root)
            log.identify(manifest.build)
            log.emit(Event.START, digest=manifest.digest)
            await db.open()
            store = Repositories(db)
            model = Ollama(settings, manifest)
            router = Router(model, settings, manifest)
            def deliver(event: RuntimeEvent) -> None:
                if desktop:
                    desktop.event(event)
            core = Coordinator(store, router, Scheduler(), log, deliver)
            owner = await asyncio.to_thread(user_identity)
            desktop = Desktop(view, store, router, core, log, owner)
            if not stopping:
                await desktop.projects()
            if not stopping:
                view.centralWidget().setEnabled(True)
                desktop.controls()
                desktop.spawn(desktop.probe)
            return 0
        except Exception as exc:
            failure = exc if isinstance(exc, Failure) else Failure(Code.INTERNAL)
            log.emit(Event.ERROR, code=failure.code, run=failure.reference)
            view.status.setText(f"Startup blocked. {failure} Close and reopen after repair.")
            return 1

    async def close_services() -> None:
        try:
            if model:
                await model.close()
        finally:
            try:
                await db.close()
            finally:
                log.emit(Event.STOP)
                await asyncio.to_thread(log.close)

    startup_task = asyncio.create_task(startup())
    cleanup: asyncio.Task[None] | None = None
    loop = asyncio.get_running_loop()
    while True:
        await exiting.wait()
        exiting.clear()
        stopping = True
        deadline = loop.time() + shutdown_grace
        done, _ = await asyncio.wait({startup_task}, timeout=shutdown_grace)
        if not done:
            view.status.setText("Close timed out during startup. Close again to check.")
            continue
        result = startup_task.result()
        if cleanup is None:
            if desktop and not await desktop.shutdown(max(0., deadline - loop.time())):
                continue
            cleanup = asyncio.create_task(close_services())
        done, _ = await asyncio.wait({cleanup}, timeout=max(0., deadline - loop.time()))
        if done:
            timer.stop()
            cleanup.result()
            return 2 if desktop and desktop.core.pending is not None else result
        view.status.setText("Close timed out while closing services. Close again to check.")


def main() -> int:
    install_worker_policy()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    try:
        verify_application()
    except Failure as exc:
        QMessageBox.critical(None, "STYLUS JARVIS", str(exc))
        return 1
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

