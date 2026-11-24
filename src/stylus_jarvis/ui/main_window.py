"""Qt view for the foundation release. Runtime work is scheduled by bootstrap."""
from PySide6.QtCore import Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)


class MainWindow(QMainWindow):
    closing = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("STYLUS JARVIS")
        self.resize(840, 620)
        panel = QWidget()
        self.setCentralWidget(panel)
        layout = QVBoxLayout(panel)
        self.status = QLabel("Starting offline…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.projects = QComboBox()
        self.threads = QComboBox()
        self.add_project = QPushButton("Add project…")
        self.new_thread = QPushButton("New conversation")
        for label, picker, button in (("Project", self.projects, self.add_project),
                                      ("Conversation", self.threads, self.new_thread)):
            row = QHBoxLayout()
            picker.setAccessibleName(label)
            row.addWidget(QLabel(label))
            row.addWidget(picker, 1)
            row.addWidget(button)
            layout.addLayout(row)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search this conversation and press Enter")
        layout.addWidget(self.search)
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.setAccessibleName("Conversation history")
        layout.addWidget(self.history, 1)
        self.draft = QPlainTextEdit()
        self.draft.setAccessibleName("Message")
        self.draft.setMaximumHeight(110)
        layout.addWidget(self.draft)
        buttons = QHBoxLayout()
        self.send = QPushButton("Send")
        self.stop = QPushButton("Stop")
        self.probe = QPushButton("Recheck model")
        self.retry = QPushButton("Retry save")
        for button in (self.send, self.stop, self.probe, self.retry):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.diagnostic_toggle = QPushButton("Local diagnostics")
        self.diagnostic_toggle.setAccessibleName("Local diagnostics")
        self.diagnostic_toggle.setCheckable(True)
        self.statusBar().addPermanentWidget(self.diagnostic_toggle)
        self.diagnostic_view = QPlainTextEdit()
        self.diagnostic_view.setAccessibleName("Recent diagnostic events")
        self.diagnostic_view.setReadOnly(True)
        self.diagnostic_view.setMaximumHeight(130)
        self.diagnostic_view.hide()
        layout.addWidget(self.diagnostic_view)
        self.diagnostic_toggle.toggled.connect(self.diagnostic_view.setVisible)
        panel.setEnabled(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.closing.emit()

