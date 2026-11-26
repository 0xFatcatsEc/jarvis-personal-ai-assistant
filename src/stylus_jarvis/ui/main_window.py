"""Dashboard shell around the existing desktop command bindings."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QKeySequence, QPalette, QResizeEvent, QShortcut, QTextCursor
from PySide6.QtWidgets import (QApplication, QBoxLayout, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QPushButton,
                               QScrollArea, QSizePolicy, QStackedWidget, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from ..voice.controller import VoiceControls
from .dashboard import CoreDisplay, DASHBOARD_STYLE
from .evidence import EvidenceView
from .memory import MemoryView


class MainWindow(QMainWindow):
    closing = Signal()
    memory_opened = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("STYLUS JARVIS")
        editor_menu = self.menuBar().addMenu("&Editor")
        self.pair_editor = editor_menu.addAction("Pair VS Code…")
        self.view_editor_context = editor_menu.addAction("View VS Code context…")
        self.disconnect_editor = editor_menu.addAction("Disconnect VS Code")
        self.editor_status = QLabel("VS Code disconnected")
        self.editor_status.setTextFormat(Qt.TextFormat.PlainText)
        panel = QWidget()
        panel.setObjectName("dashboard")
        self.setCentralWidget(panel)
        shell = QVBoxLayout(panel)
        shell.setContentsMargins(14, 6, 14, 8)
        shell.setSpacing(6)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#0B1118"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#111C27"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#E4EDF6"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#E4EDF6"))
        self.setPalette(palette)
        self.setStyleSheet(DASHBOARD_STYLE)

        self.status = QLabel("Starting offline…")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setAccessibleName("Desktop feedback")
        self.projects = QComboBox()
        self.threads = QComboBox()
        self.add_project = QPushButton("Add project…")
        self.open_editor = QPushButton("Open in VS Code")
        self.new_thread = QPushButton("New conversation")
        self.model = QLabel("Starting…")
        self.model.setTextFormat(Qt.TextFormat.PlainText)
        self.model.setAccessibleName("Configured local model")
        self.scope_strip = QGridLayout()
        offline = QLabel("Offline")
        offline.setObjectName("offlineMode")
        identity = self._row(self._heading("STYLUS JARVIS"), offline, self.model, stretch=True)
        project = self._scope_control("Project", self.projects, self.add_project)
        thread = self._scope_control("Conversation", self.threads, self.new_thread)
        for group in (identity, project, thread):
            group.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.scope_strip.addWidget(identity, 0, 0)
        self.scope_strip.addWidget(project, 0, 1)
        self.scope_strip.addWidget(thread, 0, 2)
        for index, weight in enumerate((3, 3, 4)):
            self.scope_strip.setColumnStretch(index, weight)
        self._scope_groups = (identity, project, thread)
        self._scope_width: int | None = None
        shell.addLayout(self.scope_strip)
        shell.addWidget(self.status)

        workspace = QWidget()
        workspace.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        body = QHBoxLayout(workspace)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        shell.addWidget(workspace, 1)
        self._left = QWidget()
        self._left.setFixedWidth(244)
        self._left_layout = self._rail_host(self._left)
        body.addWidget(self._left)
        center = QVBoxLayout()
        center.setSpacing(6)
        body.addLayout(center, 1)
        self._right = QWidget()
        self._right.setFixedWidth(292)
        self._right_layout = self._rail_host(self._right)
        body.addWidget(self._right)

        self.core_display = CoreDisplay()
        self.stop = QPushButton("Stop")
        self.retry = QPushButton("Retry save")
        for action in (self.stop, self.retry):
            action.setMinimumHeight(36)
            action.setEnabled(False)
        self._task_buttons = self._row(self.stop, self.retry)
        self._task_buttons.setFixedHeight(36)
        self._core_band = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        self._core_band.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._core_band.addWidget(self.core_display, alignment=Qt.AlignmentFlag.AlignCenter)
        self._core_band.addWidget(self._task_buttons, alignment=Qt.AlignmentFlag.AlignCenter)
        center.addLayout(self._core_band)
        self.show_task_actions()

        self.pages = QStackedWidget()
        # The active page determines the usable size. Hidden rails and dialogs can be wider.
        self.pages.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        center.addWidget(self.pages, 1)
        conversation, layout = self._card()
        self.pages.addWidget(conversation)
        self._work_page = conversation
        self.search = QLineEdit()
        self.search.setAccessibleName("Search conversation")
        self.search.setPlaceholderText("Search this conversation and press Enter")
        conversation_header = self._row(self._heading("Conversation"), self.search)
        conversation_header.layout().setStretch(1, 1)
        layout.addWidget(conversation_header)
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.setAccessibleName("Conversation history")
        self.history.setMinimumHeight(88)
        layout.addWidget(self.history, 1)
        self.draft = QPlainTextEdit()
        self.draft.setAccessibleName("Message")
        self.draft.setPlaceholderText("Write a message")
        self.draft.setFixedHeight(60)
        layout.addWidget(self.draft)
        self.choose_code = QPushButton("Select saved code…")
        self.remove_code = QPushButton("Remove code context")
        self.code_label = QLabel()
        self.code_label.setTextFormat(Qt.TextFormat.PlainText)
        self.code_label.setWordWrap(True)
        self.code_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.remove_code.hide()
        code_row = self._row(self.choose_code, self.code_label, self.remove_code)
        code_row.layout().setStretch(1, 1)
        layout.addWidget(code_row)
        self.voice = VoiceControls(panel)
        self.voice.capture_interrupted.connect(self.draft.setFocus)
        layout.addWidget(self.voice)
        self.speak_replies = QCheckBox("Speak replies")
        self.speech_status = QLabel()
        self.speech_status.setWordWrap(True)
        self.send = QPushButton("Send")
        self.send.setObjectName("sendMessage")
        self.send.setEnabled(False)
        speech_row = self._row(self.speak_replies, self.speech_status, self.send)
        speech_row.layout().setStretch(1, 1)
        self.voice_review = QWidget()
        review_layout = QVBoxLayout(self.voice_review)
        review_layout.setContentsMargins(0, 0, 0, 0)
        self.voice_review_status = QLabel()
        self.voice_review_status.setWordWrap(True)
        review_layout.addWidget(self.voice_review_status)
        self.voice_transcript = QPlainTextEdit()
        self.voice_transcript.setAccessibleName("Whisper transcript")
        self.voice_transcript.setTabChangesFocus(True)
        self.voice_transcript.setMaximumHeight(100)
        review_layout.addWidget(self.voice_transcript)
        review_actions = QHBoxLayout()
        self.use_transcript = QPushButton("Add transcript to message")
        self.discard_transcript = QPushButton("Discard")
        review_actions.addWidget(self.use_transcript)
        review_actions.addWidget(self.discard_transcript)
        review_actions.addStretch()
        review_layout.addLayout(review_actions)
        self.voice_transcript.textChanged.connect(
            lambda: self.use_transcript.setEnabled(bool(self.voice_transcript.toPlainText().strip())))
        self.voice_review.hide()
        layout.addWidget(self.voice_review)
        layout.addWidget(speech_row)
        QWidget.setTabOrder(self.voice.talk, self.voice_transcript)
        QWidget.setTabOrder(self.voice_transcript, self.use_transcript)
        QWidget.setTabOrder(self.use_transcript, self.discard_transcript)
        QWidget.setTabOrder(self.discard_transcript, self.speak_replies)
        QWidget.setTabOrder(self.speak_replies, self.send)
        self.probe = QPushButton("Recheck model")
        self.approve_source = QPushButton("Approve source file…")
        self.extract_source = QPushButton("Save source excerpts…")
        evidence, evidence_layout = self._card()
        evidence_layout.addWidget(self._heading("Evidence"))
        evidence_layout.addWidget(self._row(self.approve_source, self.extract_source, stretch=True))
        self.evidence = EvidenceView()
        evidence_layout.addWidget(self.evidence, 1)
        self.pages.addWidget(evidence)
        self.capture_fact = QPushButton("Remember a fact…")
        self.correct_fact = QPushButton("Correct selected fact…")
        self.forget_fact = QPushButton("Forget selected fact…")
        self.export_project = QPushButton("Export project…")
        memory, memory_layout = self._card()
        memory_layout.addWidget(self._heading("Memory"))
        memory_layout.addWidget(self._row(self.capture_fact, self.export_project, stretch=True))
        self.memory = MemoryView(self.correct_fact, self.forget_fact)
        memory_layout.addWidget(self.memory, 1)
        self.pages.addWidget(memory)

        self.recovery_toggle = QPushButton("Recovery status")
        self.recovery_toggle.setCheckable(True)
        self.recovery_summary = QLabel("Checking backup status…")
        self.recovery_summary.setWordWrap(True)
        self.recovery_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.recovery_view = QPlainTextEdit()
        self.recovery_view.setAccessibleName("Recovery status")
        self.recovery_view.setReadOnly(True)
        self.recovery_view.hide()
        self.diagnostic_toggle = QPushButton("Local diagnostics")
        self.diagnostic_toggle.setAccessibleName("Local diagnostics")
        self.diagnostic_toggle.setCheckable(True)
        self.diagnostic_summary = QLabel()
        self.diagnostic_summary.setWordWrap(True)
        self.diagnostic_view = QPlainTextEdit()
        self.diagnostic_view.setAccessibleName("Recent diagnostic events")
        self.diagnostic_view.setReadOnly(True)
        self.diagnostic_view.hide()
        self.model_health = QLabel("Waiting for local model check")
        self.model_health.setWordWrap(True)
        self._operations = self._rail(
            "Operations", ("Local model", self.model_health, self.probe),
            ("Data protection", self.recovery_summary, self.recovery_toggle),
            ("Diagnostics", self.diagnostic_summary, self.diagnostic_toggle))
        self._left_layout.addWidget(self._operations)

        self._system = QWidget()
        self._system_layout = QVBoxLayout(self._system)
        self._system_layout.addWidget(self._heading("System"))
        self.system_tabs = QTabWidget()
        self.system_tabs.setAccessibleName("System details")
        self._system_layout.addWidget(self.system_tabs, 2)
        self.system_diagnostic_summary = QLabel()
        self.system_recovery_summary = QLabel()
        for label, summary, detail in (
            ("Diagnostics", self.system_diagnostic_summary, self.diagnostic_view),
            ("Recovery", self.system_recovery_summary, self.recovery_view),
        ):
            card, column = self._card()
            summary.setWordWrap(True)
            summary.setTextFormat(Qt.TextFormat.PlainText)
            column.addWidget(summary)
            detail.show()
            column.addWidget(detail, 1)
            self.system_tabs.addTab(card, label)
        self.pages.addWidget(self._system)
        self.recovery_toggle.clicked.connect(lambda: self._open_system(1))
        self.diagnostic_toggle.clicked.connect(lambda: self._open_system(0))
        self.system_tabs.currentChanged.connect(self._sync_system_toggles)

        editor_actions = QToolButton()
        editor_actions.setText("VS Code connection")
        editor_actions.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        editor_actions.setMenu(editor_menu)
        patch_hint = QLabel("In the VS Code Command Palette:\n"
                            "STYLUS JARVIS: Review Patch from Clipboard\n"
                            "STYLUS JARVIS: View and Reconcile Patch Outcome")
        patch_hint.setWordWrap(True)
        self.editor_snapshot_summary = QLabel("No editor context shared")
        self.editor_snapshot_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.editor_snapshot_summary.setWordWrap(True)
        self.editor_snapshot_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        editor_details = QPushButton()
        editor_details.setText("View shared context…")
        editor_details.clicked.connect(self.view_editor_context.trigger)
        self.view_editor_context.changed.connect(
            lambda: editor_details.setEnabled(self.view_editor_context.isEnabled()))
        self.coding_choose = QPushButton("Select saved code…")
        self.coding_choose.clicked.connect(self.choose_code.click)
        self.coding_revision = QLabel("No saved revision attached")
        self.coding_revision.setTextFormat(Qt.TextFormat.PlainText)
        self.coding_revision.setWordWrap(True)
        self._coding = self._rail("Coding Assistant", ("Saved revision", self.coding_revision, self.coding_choose),
                                 ("VS Code session", self.editor_status, self.editor_snapshot_summary, editor_details,
                                  self.open_editor, editor_actions),
                                 ("Patch review", patch_hint))
        self._right_layout.addWidget(self._coding)
        self._coding_page = QWidget()
        self._coding_page_layout = self._rail_host(self._coding_page)
        self.pages.addWidget(self._coding_page)

        view_menu = self.menuBar().addMenu("&View")
        dock_host = QWidget()
        dock_host.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._dock_host = dock_host
        dock = QHBoxLayout(dock_host)
        dock.setContentsMargins(0, 0, 0, 0)
        self._dock: dict[str, QToolButton] = {}
        self._destinations = {"Conversation": conversation, "Evidence": evidence, "Memory": memory,
                              "Coding": self._coding_page, "System": self._system}
        self._destination = "Conversation"
        for number, name in enumerate(self._destinations, 1):
            action = view_menu.addAction(name)
            action.setShortcut(QKeySequence(f"Ctrl+{number}"))
            action.triggered.connect(lambda checked=False, target=name: self.navigate(target))
            button = QToolButton()
            button.setText(name)
            button.setToolTip(f"{name} ({action.shortcut().toString()})")
            button.clicked.connect(action.trigger)
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setMinimumHeight(36)
            dock.addWidget(button, 1)
            self._dock[name] = button
        self._dock["Conversation"].setChecked(True)
        shell.addWidget(dock_host, alignment=Qt.AlignmentFlag.AlignHCenter)
        QShortcut(QKeySequence.StandardKey.Find, conversation, self.search.setFocus,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence.StandardKey.Find, evidence, self.evidence.query.setFocus,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        for key in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(key), self.draft, self.send.click, context=Qt.ShortcutContext.WidgetShortcut)
        QShortcut(QKeySequence("F6"), panel, lambda: self._focus_region(1))
        QShortcut(QKeySequence("Shift+F6"), panel, lambda: self._focus_region(-1))
        self._wide: bool | None = None
        self._coding_on_rail: bool | None = None
        panel.setEnabled(False)
        self.setMinimumWidth(580)
        self.resize(1440, 830)
        self._arrange()

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("heading", True)
        return label

    @staticmethod
    def _row(*widgets: QWidget, stretch: bool = False) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        for widget in widgets:
            layout.addWidget(widget)
        if stretch:
            layout.addStretch()
        return row

    def _scope_control(self, name: str, picker: QComboBox, action: QPushButton) -> QWidget:
        picker.setAccessibleName(name)
        picker.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        picker.setMinimumContentsLength(5)
        picker.currentTextChanged.connect(picker.setToolTip)
        label = QLabel(f"&{name}")
        label.setBuddy(picker)
        group = self._row(label, picker, action)
        group.layout().setStretch(1, 1)
        return group

    @staticmethod
    def _card() -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setProperty("dashCard", True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(9, 8, 9, 8)
        layout.setSpacing(6)
        return card, layout

    @staticmethod
    def _rail_host(widget: QWidget) -> QVBoxLayout:
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        return layout

    def _rail(self, title: str, *sections: tuple[str, QWidget, ...]) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setAccessibleName(title)
        content = QWidget()
        content.setObjectName("railContent")
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = self._rail_host(content)
        layout.addWidget(self._heading(title))
        for heading, *widgets in sections:
            card, column = self._card()
            column.addWidget(self._heading(heading))
            for widget in widgets:
                column.addWidget(widget)
            layout.addWidget(card)
        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    def navigate(self, destination: str) -> None:
        self._destination = destination
        if destination != "Coding":
            self._work_page = self._destinations[destination]
        self._arrange_coding()
        self._select_page()
        if destination == "Memory":
            self.memory_opened.emit()
        focus = {"Conversation": self.draft, "Evidence": self.evidence.query, "Memory": self.capture_fact,
                 "Coding": self.coding_choose, "System": self.system_tabs.tabBar()}
        widget = focus[destination]
        (widget if widget and widget.isEnabled() else self._dock[destination]).setFocus()

    def _select_page(self) -> None:
        if self._work_page != self._destinations["Conversation"]:
            self.voice.cancel()
        self.pages.setCurrentWidget(self._work_page)
        self._sync_system_toggles()
        for name, button in self._dock.items():
            button.setChecked(name == self._destination)
        self._size_core()

    def _open_system(self, index: int) -> None:
        self.system_tabs.setCurrentIndex(index)
        self.navigate("System")

    def _sync_system_toggles(self) -> None:
        active = self.pages.currentWidget() is self._system
        self.diagnostic_toggle.setChecked(active and self.system_tabs.currentIndex() == 0)
        self.recovery_toggle.setChecked(active and self.system_tabs.currentIndex() == 1)

    def show_task_actions(self) -> None:
        self.stop.setVisible(self.stop.isEnabled())
        self.retry.setVisible(self.retry.isEnabled())

    def show_saved_code(self, label: str) -> None:
        self.code_label.setText(label)
        self.coding_revision.setText(label or "No saved revision attached")
        self.remove_code.setVisible(bool(label))

    @staticmethod
    def refresh_status_text(view: QPlainTextEdit, text: str, *, follow_tail: bool = False) -> None:
        if text == view.toPlainText():
            return
        vertical = view.verticalScrollBar()
        position, horizontal = vertical.value(), view.horizontalScrollBar().value()
        cursor = view.textCursor()
        anchor, point = cursor.anchor(), cursor.position()
        at_tail = position == vertical.maximum() and not cursor.hasSelection()
        view.setPlainText(text)
        if follow_tail and at_tail:
            view.moveCursor(QTextCursor.MoveOperation.End)
        else:
            end = view.document().characterCount() - 1
            cursor = view.textCursor()
            cursor.setPosition(min(anchor, end))
            cursor.setPosition(min(point, end), QTextCursor.MoveMode.KeepAnchor)
            view.setTextCursor(cursor)
            vertical.setValue(position)
            view.horizontalScrollBar().setValue(horizontal)

    def _arrange_coding(self) -> None:
        right = bool(self._wide or (self._destination == "Coding" and self.width() >= 1000))
        if right != self._coding_on_rail:
            self._coding_on_rail = right
            self._right.setVisible(right)
            host = self._right_layout if right else self._coding_page_layout
            host.addWidget(self._coding)
            self._coding.show()
        if self._destination == "Coding":
            if not right:
                self._work_page = self._coding_page
            elif not self._wide or self._work_page == self._coding_page:
                self._work_page = self._destinations["Conversation"]

    def _arrange(self) -> None:
        self._dock_host.setFixedWidth(min(680, self.width() - 28))
        wide = self.width() >= 1320
        if wide != self._wide:
            self._wide = wide
            self._left.setVisible(wide)
            if wide:
                self._left_layout.addWidget(self._operations)
            else:
                self._system_layout.insertWidget(0, self._operations, 1)
            self._operations.show()
        self._arrange_coding()
        self._select_page()
        columns = 3 if wide else 2 if self.width() >= 1000 else 1
        if self._scope_width != columns:
            self._scope_width = columns
            positions = {
                3: ((0, 0, 1, 1), (0, 1, 1, 1), (0, 2, 1, 1)),
                2: ((0, 0, 1, 3), (1, 0, 1, 1), (1, 1, 1, 2)),
                1: ((0, 0, 1, 3), (1, 0, 1, 3), (2, 0, 1, 3)),
            }
            for widget, position in zip(self._scope_groups, positions[columns], strict=True):
                self.scope_strip.addWidget(widget, *position)

    def _size_core(self) -> None:
        available = self.height() - (124 if not self.voice_review.isHidden() else 0)
        diameter = 24
        if self.pages.currentWidget() == self._destinations["Conversation"]:
            if self._wide and available >= 820:
                diameter = 256
            elif self._wide and available >= 760:
                diameter = 224
            elif available >= 705:
                diameter = 144
        self.core_display.set_diameter(diameter)
        direction = QBoxLayout.Direction.TopToBottom if diameter >= 144 else QBoxLayout.Direction.LeftToRight
        if self._core_band.direction() != direction:
            self._core_band.setDirection(direction)

    def _focus_region(self, step: int) -> None:
        candidates = (self.projects, self.probe, self.stop, self.draft, self.evidence.query,
                      self.capture_fact, self.coding_choose, self.system_tabs.tabBar(), self._dock[self._destination])
        controls = [widget for widget in candidates if widget.isVisible() and widget.isEnabled()]
        if not controls:
            return
        focus = QApplication.focusWidget()
        index = next((idx for idx, widget in enumerate(controls) if widget == focus or
                      (focus is not None and widget.isAncestorOf(focus))), -1 if step > 0 else 0)
        controls[(index + step) % len(controls)].setFocus()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._arrange()

    def show_voice_review(self, message: str, transcript: str = "") -> None:
        self.voice_review_status.setText(message)
        self.voice_transcript.setPlainText(transcript)
        self.voice_transcript.setVisible(bool(transcript))
        self.use_transcript.setVisible(bool(transcript))
        self.voice_review.show()
        self._size_core()
        if transcript and self.voice_review.isVisible():
            self.voice_transcript.setFocus()

    def clear_voice_review(self) -> None:
        self.voice_review.hide()
        self.voice_transcript.clear()
        self.voice_review_status.clear()
        self._size_core()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.voice.cancel()
        event.ignore()
        self.closing.emit()

