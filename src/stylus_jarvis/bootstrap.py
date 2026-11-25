"""Application composition root and Qt command bindings for the offline desktop."""
import asyncio
import csv
import os
import re
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from threading import Event as CancelEvent
from typing import Literal
from uuid import UUID, uuid4

from PySide6.QtCore import QLockFile, Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QInputDialog,
                               QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QVBoxLayout)
from qasync import QEventLoop

from .contracts.messages import ACTIONS, Code, Failure, RuntimeEvent, SavedCode, Scope, State
from .editor.launch import VSCodeLauncher
from .editor.bridge import EditorBridge
from .inference.ollama import Ollama
from .inference.router import Router
from .knowledge.context import Citation
from .runtime.coordinator import Coordinator
from .runtime.diagnostics import Diagnostics, Event
from .runtime.index_queue import IndexQueue
from .runtime.scheduler import Scheduler
from .runtime.offline import install_worker_policy, verify_application, whoami
from .security.broker import EditorLaunchBroker, LocalReadBroker, SavedCodeBroker
from .settings import load, profile_path
from .storage.database import Database
from .storage.editor_journal import EditorJournal
from .storage.tool_journal import ToolJournal
from .storage.repositories import Repositories
from .ui.dashboard import CoreState
from .ui.evidence import citation_text
from .storage.snapshots import SnapshotSchedule
from .ui.main_window import MainWindow
from .ui.review import FactEditor
from .voice.capture import AudioClip
from .voice.piper import Piper, ReplySpeech
from .voice.whisper import Whisper
from .memory.service import Destination, Fact, FactDraft, Origin


def user_identity() -> str:
    """Use the process token's SID, which survives account renaming."""
    row = next(csv.reader([whoami().decode("ascii", "replace").strip()]))
    if len(row) != 2 or not row[1].startswith("S-1-"):
        raise Failure(Code.SCOPE)
    return row[1]


class Desktop:
    def __init__(self, view: MainWindow, store: Repositories, router: Router,
                 coordinator: Coordinator, log: Diagnostics, owner: str, whisper: Whisper | None = None,
                 piper: Piper | None = None, *, journal: ToolJournal | None = None) -> None:
        self.view = view
        self.store = store
        self.router = router
        self.core = coordinator
        self.log = log
        self.owner = owner
        self.whisper = whisper
        self.speech = ReplySpeech(piper, store.validate, view.speech_status.setText) if piper else None
        if self.speech is not None:
            self.speech.microphone_active = lambda: view.voice.capturing
            self.speech.playback_changed = self.playback_changed
        self.view.speak_replies.setEnabled(self.speech is not None)
        self.view.speak_replies.toggled.connect(self.speech_toggled)
        self.voice_cancel: CancelEvent | None = None
        self.view.voice.capture_ready.connect(self.transcribe)
        self.view.use_transcript.clicked.connect(self.add_transcript_to_draft)
        self.view.discard_transcript.clicked.connect(self.discard_transcript)
        self.generation = 0
        self.tasks: set[asyncio.Task[None]] = set()
        self.sending = False
        self.stop_requested = False
        self.model_checking = False
        self.streaming_scope: Scope | None = None
        self.history_version = 0
        self.evidence_version = 0
        self.memory_version = 0
        self.memory_dialog: QDialog | None = None
        self.close_notice_key: str | None = None
        self.closing = False
        self.request: UUID | None = None
        self.code: SavedCode | None = None
        self.code_picker: QInputDialog | None = None
        self.editor_launch = EditorLaunchBroker(store, VSCodeLauncher(), journal)
        self.local_reads = LocalReadBroker(store, journal)
        self.editor_launching = False
        self.editor_invitation: QDialog | None = None
        self.editor_context_dialog: QDialog | None = None
        self.editor_bridge = EditorBridge(owner, self.editor_bridge_status, store=store, journal=EditorJournal(store.db),
                                          current_scope=lambda: None if self.closing else self.core.selection)
        self.view.pair_editor.setEnabled(False)
        self.view.view_editor_context.setEnabled(False)
        self.view.disconnect_editor.setEnabled(False)
        self.view.pair_editor.triggered.connect(lambda: self.spawn(self.pair_editor))
        self.view.view_editor_context.triggered.connect(lambda: self.spawn(self.show_editor_context))
        self.view.disconnect_editor.triggered.connect(lambda: self.spawn(self.editor_bridge.stop))
        self.index = IndexQueue(store, self.index_status)
        self.view.voice.capture_state_changed.connect(self.controls)
        self.view.add_project.clicked.connect(lambda: self.spawn(self.add_project))
        self.view.open_editor.clicked.connect(lambda: self.spawn(self.open_project_in_editor))
        self.view.capture_fact.clicked.connect(lambda: self.review_fact())
        self.view.export_project.clicked.connect(lambda: self.spawn(self.export_project))
        memory = self.view.memory
        self.view.memory_opened.connect(self.request_memory_refresh)
        memory.refresh.clicked.connect(self.request_memory_refresh)
        memory.scope.currentIndexChanged.connect(self.change_memory_destination)
        self.view.correct_fact.clicked.connect(lambda: self.spawn(lambda: self.open_memory_fact("correct")))
        self.view.forget_fact.clicked.connect(lambda: self.spawn(lambda: self.open_memory_fact("forget")))
        memory.provenance.clicked.connect(lambda: self.spawn(lambda: self.open_memory_fact("citation")))
        self.view.approve_source.clicked.connect(lambda: self.spawn(self.approve_source))
        self.view.extract_source.clicked.connect(lambda: self.spawn(lambda: self.approve_source(excerpts=True)))
        evidence = self.view.evidence
        evidence.query.textChanged.connect(self.clear_evidence)
        evidence.revision.textChanged.connect(self.clear_evidence)
        evidence.matches.currentItemChanged.connect(self.clear_evidence_detail)
        evidence.search.clicked.connect(lambda: self.spawn(self.search_evidence))
        evidence.query.returnPressed.connect(evidence.search.click)
        evidence.revision.returnPressed.connect(evidence.search.click)
        evidence.inspect.clicked.connect(lambda: self.spawn(self.inspect_evidence))
        evidence.matches.itemActivated.connect(lambda _: evidence.inspect.click())
        self.view.projects.currentIndexChanged.connect(lambda: self.change(True))
        self.view.threads.currentIndexChanged.connect(lambda: self.change(False))
        self.view.new_thread.clicked.connect(lambda: self.change(False, new=True))
        self.view.probe.clicked.connect(lambda: self.spawn(self.probe))
        self.view.choose_code.clicked.connect(lambda: self.spawn(self.choose_saved_code))
        self.view.remove_code.clicked.connect(self.clear_saved_code)
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
        self.index.set_foreground(self.closing or self.sending or self.view.voice.capturing
                                  or self.voice_cancel is not None or bool(self.speech and self.speech.busy))
        self.view.approve_source.setEnabled(bool(self.core.selection and not self.closing))
        self.view.open_editor.setEnabled(bool(self.core.selection and not self.closing and not self.editor_launching))
        self.view.pair_editor.setEnabled(bool(os.name == "nt" and self.core.selection and not self.closing))
        self.view.extract_source.setEnabled(self.view.approve_source.isEnabled())
        self.view.evidence.setEnabled(self.view.approve_source.isEnabled())
        self.view.capture_fact.setEnabled(self.view.approve_source.isEnabled())
        self.view.memory.setEnabled(self.view.capture_fact.isEnabled())
        self.view.export_project.setEnabled(self.view.capture_fact.isEnabled())
        self.view.send.setEnabled(bool(self.core.selection and self.router.verified
                                      and not self.sending and self.core.pending is None
                                      and not self.core.scheduler.closing))
        self.view.stop.setEnabled(self.sending or bool(self.speech and self.speech.busy))
        self.view.retry.setEnabled(self.core.pending is not None)
        self.view.probe.setEnabled(not self.sending and not self.model_checking and not self.closing)
        self.view.choose_code.setEnabled(bool(self.core.selection and self.core.code_broker
                                             and not self.closing and not self.sending))
        self.view.coding_choose.setEnabled(self.view.choose_code.isEnabled())
        self.view.remove_code.setEnabled(not self.closing and not self.sending)
        self.view.show_task_actions()
        self.update_core()

    def playback_changed(self, playing: bool) -> None:
        self.view.voice.set_playback(playing)
        self.update_core()

    def update_core(self) -> None:
        if self.core.pending is not None:
            state = CoreState.SAVE
        elif self.sending and self.stop_requested:
            state = CoreState.STOPPING
        elif self.view.voice.capturing:
            state = CoreState.RECORDING
        elif self.voice_cancel is not None and not self.voice_cancel.is_set():
            state = CoreState.TRANSCRIBING
        elif self.sending:
            state = CoreState.GENERATING
        elif self.view.voice.playing:
            state = CoreState.SPEAKING
        elif self.model_checking:
            state = CoreState.CHECKING
        else:
            state = CoreState.READY if self.router.verified else CoreState.UNAVAILABLE
        self.view.core_display.set_state(state)
        health = ("Checking…" if self.model_checking else
                  "Verified · local only" if self.router.verified else "Local model unavailable")
        if self.view.model_health.text() != health:
            self.view.model_health.setText(health)

    async def choose_saved_code(self) -> None:
        scope = self.core.selection
        broker = self.core.code_broker
        if scope is None or broker is None or self.code_picker is not None or self.sending:
            return
        revisions = await broker.choices(scope)
        if self.closing or self.sending or self.core.selection != scope or self.code_picker is not None:
            return
        if not revisions:
            self.view.status.setText("Save source excerpts for a local text file before selecting code.")
            return
        choices = {f"{r.relative_path} · {r.revision_id}": SavedCode(r.source_id, r.revision_id)
                   for r in revisions}
        picker = QInputDialog(self.view)
        picker.setWindowTitle("Select saved code")
        picker.setLabelText("Approved file and revision")
        picker.setComboBoxItems(list(choices))
        picker.setComboBoxEditable(False)
        picker.setOption(QInputDialog.InputDialogOption.UseListViewForComboBoxItems)
        self.code_picker = picker

        def attach(label: str) -> None:
            if scope == self.core.selection and not self.closing and not self.sending and label in choices:
                self.code = choices[label]
                self.view.show_saved_code(label)
                self.view.navigate("Conversation")

        def close_picker() -> None:
            self.code_picker = None
            picker.deleteLater()

        picker.textValueSelected.connect(attach)
        picker.finished.connect(close_picker)
        picker.open()

    async def open_project_in_editor(self) -> None:
        scope = self.core.selection
        if scope is None or self.closing or self.editor_launching:
            return
        self.editor_launching = True
        self.controls()

        def current() -> bool:
            return self.core.selection == scope and not self.closing

        try:
            await self.editor_launch.open_project(scope, current)
        except Failure:
            if current():
                raise
        else:
            if current():
                self.view.status.setText("VS Code launch requested for the selected project.")
        finally:
            self.editor_launching = False

    def editor_bridge_status(self, status: str) -> None:
        self.view.editor_status.setText(status)
        waiting = status == "Waiting for VS Code pairing"
        record = self.editor_bridge.snapshot
        current = record is not None and record.scope == self.core.selection and not self.closing
        if current and record is not None:
            snapshot = record.metadata
            dirty = "Unsaved changes" if snapshot.dirty else "Saved"
            self.view.editor_snapshot_summary.setText(
                f"Last shared workspace\n{record.workspace}\n"
                f"Buffer: {record.relative_path}\nVersion {snapshot.document_version} · {dirty}"
            )
        else:
            self.view.editor_snapshot_summary.setText("No editor context shared")
        self.view.disconnect_editor.setEnabled(not self.closing and status != "VS Code disconnected")
        if not waiting and self.editor_invitation is not None:
            self.editor_invitation.close()
        self.view.view_editor_context.setEnabled(current)
        if self.editor_context_dialog is not None:
            self.editor_context_dialog.close()

    async def pair_editor(self) -> None:
        scope = self.core.selection
        if self.closing or scope is None:
            return
        try:
            invitation = await self.editor_bridge.issue(scope)
        except OSError as error:
            raise Failure(Code.EDITOR) from error
        if self.closing:
            await self.editor_bridge.stop()
            return
        if self.core.selection != scope:
            return
        dialog = QDialog(self.view)
        dialog.setWindowTitle("Pair VS Code")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Paste this one-time invitation into STYLUS JARVIS: Pair in VS Code."))
        text = QLineEdit(invitation)
        text.setAccessibleName("One-time VS Code invitation")
        text.setReadOnly(True)
        layout.addWidget(text)
        self.editor_invitation = dialog

        def closed() -> None:
            text.clear()
            self.editor_invitation = None
            dialog.deleteLater()

        dialog.finished.connect(closed)
        dialog.open()
        text.selectAll()
        text.setFocus()

    async def show_editor_context(self) -> None:
        record = self.editor_bridge.snapshot
        if record is None or self.editor_context_dialog is not None:
            return
        try:
            await self.store.validate(record.scope)
        except Failure:
            if self.editor_bridge.snapshot is not record or self.core.selection != record.scope:
                return
            await self.editor_bridge.stop()
            raise
        if self.editor_context_dialog is not None or self.editor_bridge.snapshot is not record or (
                self.closing or self.core.selection != record.scope):
            return
        snapshot = record.metadata
        anchor, active = snapshot.selection.anchor, snapshot.selection.active
        lines = [f"Workspace: {record.workspace}", f"File: {record.relative_path}",
                 f"Window: {record.window}", f"Open document: {snapshot.document_id}",
                 f"Version: {snapshot.document_version} · {'Unsaved changes' if snapshot.dirty else 'Saved'}",
                 f"Selection (UTF-16): {anchor.line}:{anchor.character} → {active.line}:{active.character}",
                 "", "Shared diagnostics"]
        lines.extend(f"{item.start.line}:{item.start.character} · "
                     f"{('Error', 'Warning', 'Information', 'Hint')[item.severity]} · {item.message}"
                     for item in snapshot.diagnostics)
        if not snapshot.diagnostics:
            lines.append("None")
        dialog = QDialog(self.view)
        dialog.setWindowTitle("Last shared VS Code context")
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit("\n".join(lines))
        text.setAccessibleName("Last shared VS Code context")
        text.setReadOnly(True)
        layout.addWidget(text)
        self.editor_context_dialog = dialog

        def closed() -> None:
            self.editor_context_dialog = None
            dialog.deleteLater()

        dialog.finished.connect(closed)
        dialog.resize(600, 320)
        dialog.open()

    def clear_saved_code(self) -> None:
        if self.code_picker is not None:
            self.code_picker.reject()
        self.code = None
        self.view.show_saved_code("")

    def transcribe(self, clip: AudioClip) -> None:
        worker = self.whisper
        if worker is None or self.closing or self.voice_cancel is not None:
            return
        cancel = CancelEvent()
        self.voice_cancel = cancel
        self.controls()
        generation = self.generation
        scope = self.core.selection
        self.view.voice.setEnabled(False)
        self.view.show_voice_review("Transcribing locally…")

        async def run() -> None:
            nonlocal clip
            try:
                # Hand ownership to the executor. The review retains only text.
                work = asyncio.get_running_loop().run_in_executor(None, worker.transcribe, clip, cancel)
                del clip
                text = await work
                if scope is not None and not cancel.is_set():
                    await self.store.validate(scope)
                if not self.closing and not cancel.is_set() and generation == self.generation:
                    message = "Review transcript" if text else "No speech recognized."
                    self.view.show_voice_review(message, text)
            except (OSError, ValueError, RuntimeError):
                if not self.closing and not cancel.is_set() and generation == self.generation:
                    self.view.show_voice_review("Local transcription failed. Continue by typing.")
            except Failure:
                self.view.clear_voice_review()
            finally:
                self.voice_cancel = None
                self.view.voice.setEnabled(not self.closing and self.view.voice_transcript.isHidden())

        self.spawn(run)

    def add_transcript_to_draft(self) -> None:
        text = self.view.voice_transcript.toPlainText()
        if self.closing or self.view.voice_review.isHidden() or not text.strip():
            return
        draft = self.view.draft
        draft.moveCursor(QTextCursor.MoveOperation.End)
        separator = "\n" if draft.toPlainText() and not draft.toPlainText().endswith("\n") else ""
        draft.insertPlainText(separator + text)
        self.discard_transcript()
        draft.setFocus()

    def discard_transcript(self) -> None:
        if self.voice_cancel is not None:
            self.voice_cancel.set()
        self.view.clear_voice_review()
        self.view.voice.setEnabled(not self.closing and self.voice_cancel is None)
        self.update_core()

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
        if path and not self.closing and self.core.selection == scope:
            if excerpts:
                if self.index.put(scope, Path(path)):
                    self.spawn(self.index.drain)
                if not self.sending:
                    self.view.status.setText("Source indexing queued.")
                return
            receipt = await self.store.approve_source(scope, Path(path))
            if self.core.selection == scope:
                self.view.status.setText(f"Approved {receipt.relative_path} · revision {receipt.revision_id}")

    def index_status(self, scope: Scope, message: str) -> None:
        if scope == self.core.selection and not self.closing and not self.sending:
            self.view.status.setText(message)

    def clear_evidence(self) -> None:
        self.evidence_version += 1
        self.view.evidence.clear_results()

    def clear_evidence_detail(self) -> None:
        self.evidence_version += 1
        self.view.evidence.detail.clear()

    def evidence_is_current(self, scope: Scope, version: int) -> bool:
        return not self.closing and self.core.selection == scope and self.evidence_version == version

    async def search_evidence(self) -> None:
        scope = self.core.selection
        if scope is None:
            return
        evidence = self.view.evidence
        query = evidence.query.text().strip()
        revision = evidence.revision.text().strip().lower()
        self.clear_evidence()
        if not query:
            evidence.feedback.setText("Enter terms to search the published excerpts.")
            return
        if revision and not re.fullmatch(r"[0-9a-f]{32}", revision):
            evidence.feedback.setText("Enter the full 32-character revision ID, or leave it blank for current revisions.")
            return
        version = self.evidence_version
        evidence.feedback.setText("Searching published excerpts…")
        try:
            bundle = await self.local_reads.search(scope, query, revision or None,
                                                   lambda: self.evidence_is_current(scope, version))
        except Failure as exc:
            if self.evidence_is_current(scope, version):
                evidence.feedback.setText("Evidence access is no longer available for this selection."
                                          if exc.code == Code.SCOPE else
                                          "Could not search evidence. Try a shorter query or retry.")
            self.log.emit(Event.ERROR, code=exc.code, run=exc.reference)
            return
        if self.evidence_is_current(scope, version):
            evidence.show_results(bundle)

    async def inspect_evidence(self) -> None:
        scope = self.core.selection
        evidence = self.view.evidence
        item = evidence.matches.currentItem()
        citation = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if scope is None or not isinstance(citation, Citation):
            return
        self.clear_evidence_detail()
        version = self.evidence_version
        try:
            locator = await self.local_reads.inspect(scope, citation.source, citation.revision, citation.locator,
                                                     lambda: self.evidence_is_current(scope, version))
        except Failure as exc:
            if self.evidence_is_current(scope, version):
                evidence.clear_results("The retained citation is unavailable. Search again with the current project.")
            self.log.emit(Event.ERROR, code=exc.code, run=exc.reference)
            return
        if self.evidence_is_current(scope, version):
            evidence.show_locator(citation, locator)
            evidence.feedback.setText("Showing the retained excerpt for this exact citation.")
            if item is not None and evidence.matches.hasFocus():
                evidence.detail.setFocus()

    async def export_project(self) -> None:
        scope = self.core.selection
        if scope is None:
            return
        title = f"Export project history and facts as readable JSON · {self.view.projects.currentText()}"
        path, _ = QFileDialog.getSaveFileName(self.view, title, "stylus-project.json", "JSON (*.json)",
                                             options=QFileDialog.Option.DontConfirmOverwrite)
        if not path or self.closing or self.core.selection != scope:
            return
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".json")
        try:
            saved = await self.store.export_project(scope, target)
        except Failure as exc:
            if exc.code != Code.CONFLICT:
                raise
            self.view.status.setText("This export name already exists. Choose a new filename.")
            return
        if self.core.selection == scope:
            self.view.status.setText(f"Project exported · {saved.name}")

    def clear_memory(self, message: str) -> None:
        self.memory_version += 1
        self.view.memory.clear(message)

    def change_memory_destination(self) -> None:
        if self.memory_dialog is not None:
            self.memory_dialog.reject()
        self.request_memory_refresh()

    def request_memory_refresh(self) -> None:
        scope = self.core.selection
        memory = self.view.memory
        previous = memory.selected()
        destination = memory.destination
        self.clear_memory("Loading confirmed facts…" if scope else
                          "Select a project and conversation to browse facts.")
        version = self.memory_version
        if scope is not None:
            self.spawn(lambda: self.refresh_memory(scope, version, destination, previous.id if previous else None))

    async def refresh_memory(self, scope: Scope, version: int, destination: Destination, selected: str | None) -> None:
        if not self.memory_is_current(scope, version):
            return
        memory = self.view.memory
        try:
            facts = await self.local_reads.recall(scope, destination, lambda: self.memory_is_current(scope, version))
        except Failure as exc:
            if self.memory_is_current(scope, version):
                memory.feedback.setText("Memory is unavailable for this selection. Refresh or select the project again.")
            self.log.emit(Event.ERROR, code=exc.code, run=exc.reference)
            return
        if self.memory_is_current(scope, version):
            memory.show_facts(facts, selected)

    def memory_is_current(self, scope: Scope, version: int) -> bool:
        return not self.closing and self.core.selection == scope and self.memory_version == version

    async def open_memory_fact(self, action: Literal["correct", "forget", "citation"]) -> None:
        scope = self.core.selection
        memory = self.view.memory
        selected = memory.selected()
        if scope is None or selected is None or self.memory_dialog is not None:
            return
        destination = memory.destination
        version = self.memory_version
        source_text = ""
        try:
            fact = await self.store.get_fact(scope, selected.id, destination=destination, version=selected.version)
            if action == "citation" and fact.source and fact.revision and fact.locator:
                source = await self.store.source_revision(scope, fact.source, fact.revision)
                locator = await self.local_reads.inspect(scope, fact.source, fact.revision, fact.locator,
                                                         lambda: self.memory_is_current(scope, version))
                # A fact can be forgotten while the independent source is being resolved.
                await self.store.get_fact(scope, fact.id, destination=destination, version=fact.version)
                source_text = citation_text(source.relative_path, fact.source, locator)
        except Failure as exc:
            if self.memory_is_current(scope, version):
                self.clear_memory("The selected fact or citation is unavailable. Refresh facts to continue.")
            self.log.emit(Event.ERROR, code=exc.code, run=exc.reference)
            return
        if (not self.memory_is_current(scope, version) or memory.selected() != selected
                or self.memory_dialog is not None or not memory.isVisible()):
            return
        if action == "correct":
            self.review_fact(fact.text, previous=fact)
        elif action == "forget":
            self.review_forget(scope, fact, destination)
        elif source_text:
            dialog = QDialog(self.view)
            dialog.setWindowTitle("Fact source citation")
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            layout = QVBoxLayout(dialog)
            excerpt = QPlainTextEdit()
            excerpt.setAccessibleName("Exact citation and retained excerpt")
            excerpt.setReadOnly(True)
            excerpt.setPlainText(source_text)
            layout.addWidget(excerpt)
            close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            close.rejected.connect(dialog.reject)
            layout.addWidget(close)
            dialog.resize(600, 320)
            self.open_memory_dialog(dialog)

    def open_memory_dialog(self, dialog: QDialog) -> None:
        self.memory_dialog = dialog
        dialog.finished.connect(lambda: setattr(self, "memory_dialog", None))
        dialog.open()

    def review_forget(self, scope: Scope, fact: Fact, destination: Destination) -> None:
        editor = FactEditor(self.view, self.view.projects.currentText(), scope.owner, fact.text, Origin.USER)
        editor.setWindowTitle(f"Forget fact · remove all versions (current version {fact.version})")
        editor.destination.setCurrentIndex(0 if destination == Destination.PROJECT else 1)
        editor.destination.setEnabled(False)
        editor.statement.setReadOnly(True)
        editor.save.setText("Confirm forget")

        async def persist() -> None:
            if self.core.selection == scope:
                try:
                    await self.store.forget_fact(scope, fact.id, expected_version=fact.version,
                                                 confirmed=True, destination=destination)
                    if self.core.selection == scope:
                        self.view.status.setText(f"Fact forgotten from {destination.value} memory")
                finally:
                    if self.core.selection == scope:
                        self.request_memory_refresh()

        editor.accepted.connect(lambda: self.spawn(persist))
        self.open_memory_dialog(editor)

    def review_fact(self, text: str = "", origin: Origin = Origin.USER, *, previous: Fact | None = None) -> None:
        scope = self.core.selection
        if scope is None or self.closing or self.memory_dialog is not None:
            return
        editor = FactEditor(self.view, self.view.projects.currentText(), scope.owner, text, origin)
        editor.destination.setCurrentIndex(self.view.memory.scope.currentIndex())
        if previous is not None:
            editor.setWindowTitle(f"Correct fact · version {previous.version}")
            editor.destination.setCurrentIndex(0 if previous.project is not None else 1)
            editor.destination.setEnabled(False)
            editor.save.setText("Confirm correction")
            if previous.locator:
                editor.setWindowTitle(f"Correct version {previous.version} · save as an owner statement without evidence")

        def confirm() -> None:
            if self.core.selection != scope or self.closing:
                return
            destination = Destination(editor.destination.currentData())
            value = editor.statement.toPlainText()
            draft = (FactDraft(scope, value, destination, origin, id=UUID(previous.id))
                     if previous else FactDraft(scope, value, destination, origin))

            async def persist() -> None:
                if self.core.selection == scope:
                    try:
                        if previous:
                            await self.store.correct_fact(scope, draft, expected_version=previous.version, confirmed=True)
                        else:
                            await self.store.confirm_fact(scope, draft, confirmed=True)
                        if self.core.selection == scope:
                            self.view.status.setText(f"Fact saved to {draft.destination.value} memory")
                    except Failure as exc:
                        if not previous or exc.code != Code.CONFLICT:
                            raise
                        if self.core.selection == scope:
                            self.view.status.setText("This fact changed. Reopen its latest version and review your correction.")
                    finally:
                        if self.core.selection == scope:
                            self.request_memory_refresh()
            self.spawn(persist)

        editor.accepted.connect(confirm)
        self.open_memory_dialog(editor)

    async def add_project(self) -> None:
        path = QFileDialog.getExistingDirectory(self.view, "Select a local project")
        if path:
            key = await self.store.register(self.owner, Path(path))
            await self.projects(key)

    def change(self, project_changed: bool, *, new: bool = False) -> None:
        self.generation += 1
        self.index.clear()
        self.speech_toggled(False)
        self.view.voice.cancel()
        self.discard_transcript()
        generation = self.generation
        project = self.view.projects.currentData()
        self.core.select(None)
        if self.memory_dialog is not None:
            self.memory_dialog.reject()
        self.view.memory.scope.setCurrentIndex(0)
        self.clear_memory("Select a project and conversation to browse facts.")
        self.editor_bridge.snapshot = None
        self.view.editor_snapshot_summary.setText("No editor context shared")
        if self.editor_invitation is not None:
            self.editor_invitation.close()
        self.view.view_editor_context.setEnabled(False)
        if self.editor_context_dialog is not None:
            self.editor_context_dialog.close()
        self.clear_saved_code()
        self.view.recovery_view.clear()
        self.view.history.clear()
        self.view.search.clear()
        self.view.evidence.query.clear()
        self.view.evidence.revision.clear()
        self.clear_evidence()
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
                if self.view.memory.isVisible():
                    self.request_memory_refresh()
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
        if self.model_checking or self.sending:
            return
        self.model_checking = True
        self.controls()
        started = time.monotonic()
        try:
            await self.router.probe()
            self.view.status.setText("Offline · Local model verified")
        finally:
            self.model_checking = False
            self.controls()
            self.log.emit(Event.PROBE, elapsed_ms=(time.monotonic()-started)*1000,
                          digest=self.router.digest)

    def event(self, event: RuntimeEvent) -> None:
        if self.closing or event.scope != self.core.selection or event.request != self.request:
            return
        if event.kind == "fragment":
            self.view.history.moveCursor(QTextCursor.MoveOperation.End)
            self.view.history.insertPlainText(event.text)
            self.speak(event.text)
        else:
            self.view.status.setText(event.text)

    def speech_toggled(self, enabled: bool) -> None:
        if not enabled and self.speech is not None and self.speech.scope is not None:
            self.speech.clear()
            self.controls()

    def speak(self, text: str, *, final: bool = False) -> None:
        speech = self.speech
        if speech is not None and speech.feed(text, final=final):
            self.spawn(speech.drain)
            self.controls()

    def stop(self) -> None:
        self.stop_requested = self.sending
        speech_active = bool(self.speech and self.speech.busy)
        self.speech_toggled(False)
        self.core.scheduler.stop()
        if speech_active:
            self.view.speech_status.setText("Speech stopped.")
        if self.sending:
            self.view.status.setText("Stopping local reply…")
        self.controls()

    def send(self) -> None:
        scope = self.core.selection
        if not scope or self.closing or self.sending or self.core.scheduler.closing:
            return
        self.sending = True
        self.stop_requested = False
        self.streaming_scope = scope
        self.history_version += 1
        request = uuid4()
        self.request = request
        if self.speech is not None and self.view.speak_replies.isChecked():
            self.speech.begin(scope)
        text = self.view.draft.toPlainText()
        code = self.code
        self.controls()
        attachment = f"\n\nSaved code: {self.view.code_label.text()}" if code is not None else ""
        self.view.history.appendPlainText(f"\nuser\n{text}{attachment}\n\nassistant [provisional]")
        self.view.status.setText("Generating locally…")

        async def run() -> None:
            speak_final = False
            try:
                turn = await self.core.submit(scope, request, text, code=code)
                if code is not None and scope == self.core.selection:
                    self.clear_saved_code()
                speak_final = turn.state in (State.COMPLETED, State.TOKEN_LIMIT)
                if scope == self.core.selection and text == self.view.draft.toPlainText():
                    self.view.draft.clear()
                    status = ACTIONS[Code.TOKEN_LIMIT] if turn.state == State.TOKEN_LIMIT else turn.state.value
                    self.view.status.setText(f"Offline · {status}")
            finally:
                if self.request == request and not self.closing:
                    if speak_final:
                        self.speak("", final=True)
                    else:
                        self.speech_toggled(False)
                self.sending = False
                self.stop_requested = False
                self.update_core()
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
        await self.editor_bridge.stop()
        self.clear_saved_code()
        self.index.clear()
        self.speech_toggled(False)
        self.discard_transcript()
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
            self.view.voice.setEnabled(True)
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
        heading, _, counters = health.partition(" · ")
        view.diagnostic_toggle.setText(heading)
        view.diagnostic_summary.setText(counters.replace(" · ", "\n"))
        view.system_diagnostic_summary.setText(health)
        if view.diagnostic_toggle.isChecked():
            view.refresh_status_text(view.diagnostic_view, "\n".join(recent), follow_tail=True)

    timer = QTimer(view)
    timer.timeout.connect(refresh_diagnostics)
    view.diagnostic_toggle.toggled.connect(refresh_diagnostics)
    refresh_diagnostics()
    timer.start(500)
    model: Ollama | None = None
    desktop: Desktop | None = None
    stopping = False
    snapshots = SnapshotSchedule(db, root, lambda code: log.emit(Event.ERROR, code=code))
    snapshot_task: asyncio.Task[None] | None = None
    recovery_refreshing = False
    recovery_detail_requested = False
    recovery_timer = QTimer(view)

    def refresh_recovery() -> None:
        nonlocal recovery_refreshing, recovery_detail_requested
        if desktop is None or desktop.closing:
            return
        detailed = view.recovery_toggle.isChecked()
        if recovery_refreshing:
            recovery_detail_requested |= detailed
            return
        scope = desktop.core.selection
        recovery_refreshing = True

        async def refresh() -> None:
            nonlocal recovery_refreshing, recovery_detail_requested
            try:
                if detailed and scope is not None:
                    await desktop.store.validate(scope)
                status = await asyncio.to_thread(snapshots.status, scope if detailed else None)
                if detailed and scope is not None:
                    await desktop.store.validate(scope)
                if desktop.closing:
                    return
                if status.age is not None:
                    minutes = int(status.age.total_seconds()) // 60
                    age = f"{minutes // 60} h {minutes % 60} min ago" if minutes >= 60 else f"{minutes} min ago"
                    summary = f"Last verified backup: {age}"
                    if status.previous_configuration:
                        summary += " (previous configuration)"
                else:
                    summary = "No verified backup" if status.destination else "Backup destination not configured"
                if status.problem:
                    summary += f"\n{status.problem}"
                view.recovery_summary.setText(summary)
                view.system_recovery_summary.setText(summary)
                if detailed and scope == desktop.core.selection and view.recovery_toggle.isChecked():
                    view.refresh_status_text(view.recovery_view, status.display())
            except Failure:
                if scope == desktop.core.selection:
                    view.recovery_view.setPlainText("Recovery status for this project is unavailable.")
            finally:
                recovery_refreshing = False
                if recovery_detail_requested:
                    recovery_detail_requested = False
                    if view.recovery_toggle.isChecked():
                        QTimer.singleShot(0, refresh_recovery)

        desktop.spawn(refresh)

    recovery_timer.timeout.connect(refresh_recovery)
    view.recovery_toggle.toggled.connect(refresh_recovery)

    async def startup() -> int:
        nonlocal model, desktop, snapshot_task
        try:
            settings, manifest = await asyncio.to_thread(load, root)
            view.model.setText(manifest.model)
            log.identify(manifest.build)
            log.emit(Event.START, digest=manifest.digest)
            await db.open()
            store = Repositories(db)
            model = Ollama(settings, manifest)
            router = Router(model, settings, manifest)
            def deliver(event: RuntimeEvent) -> None:
                if desktop:
                    desktop.event(event)
            journal = ToolJournal(db)
            core = Coordinator(store, router, Scheduler(), log, deliver, code_broker=SavedCodeBroker(store, journal))
            owner = await asyncio.to_thread(user_identity)
            desktop = Desktop(view, store, router, core, log, owner, Whisper(root), Piper(root), journal=journal)
            if not stopping:
                await desktop.projects()
            if not stopping:
                view.centralWidget().setEnabled(True)
                desktop.controls()
                desktop.spawn(desktop.probe)
                snapshot_task = asyncio.create_task(snapshots.run())
                recovery_timer.start(5000)
                refresh_recovery()
            return 0
        except Exception as exc:
            failure = exc if isinstance(exc, Failure) else Failure(Code.INTERNAL)
            log.emit(Event.ERROR, code=failure.code, run=failure.reference)
            view.status.setText(f"Startup blocked. {failure} Close and reopen after repair.")
            return 1

    async def close_services() -> None:
        recovery_timer.stop()
        snapshots.shutdown()
        try:
            if snapshot_task:
                await snapshot_task
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

