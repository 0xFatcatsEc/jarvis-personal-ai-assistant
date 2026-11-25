"""A scoped list of confirmed memory and its selected fact."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from ..memory.service import Destination, Fact, Origin


class MemoryView(QWidget):
    def __init__(self, correct: QPushButton, forget: QPushButton) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        label = QLabel("Memory &scope")
        self.scope = QComboBox()
        self.scope.setAccessibleName("Memory scope")
        self.scope.addItem("Project memory", Destination.PROJECT.value)
        self.scope.addItem("Personal memory", Destination.PERSONAL.value)
        label.setBuddy(self.scope)
        self.refresh = QPushButton("Refresh facts")
        row.addWidget(label)
        row.addWidget(self.scope, 1)
        row.addWidget(self.refresh)
        layout.addLayout(row)
        self.feedback = QLabel("Select a project and conversation to browse confirmed facts.")
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.facts = QListWidget()
        self.facts.setWordWrap(True)
        self.facts.setAccessibleName("Confirmed facts")
        layout.addWidget(self.facts, 1)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setAccessibleName("Selected fact and provenance")
        layout.addWidget(self.detail, 2)
        self.provenance = QPushButton("Inspect source citation")
        actions = QHBoxLayout()
        for action in (correct, forget, self.provenance):
            actions.addWidget(action)
            action.setEnabled(False)
        actions.addStretch()
        layout.addLayout(actions)
        self._edit_actions = (correct, forget)
        self.facts.currentItemChanged.connect(self._show_selected)

    @property
    def destination(self) -> Destination:
        return Destination(self.scope.currentData())

    def selected(self) -> Fact | None:
        item = self.facts.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def clear(self, message: str) -> None:
        self.facts.clear()
        self._show_selected()
        self.feedback.setText(message)

    def show_facts(self, facts: list[Fact], selected: str | None) -> None:
        name = self.scope.currentText()
        self.feedback.setText(f"{len(facts)} confirmed facts · {name}" if facts else f"No confirmed facts · {name}")
        row = 0
        for index, fact in enumerate(facts):
            summary = " ".join(fact.text.split())
            if len(summary) > 120:
                summary = summary[:119] + "…"
            item = QListWidgetItem(f"v{fact.version} · {summary}", self.facts)
            item.setData(Qt.ItemDataRole.UserRole, fact)
            if fact.id == selected:
                row = index
        if facts:
            self.facts.setCurrentRow(row)

    def _show_selected(self) -> None:
        fact = self.selected()
        for action in self._edit_actions:
            action.setEnabled(fact is not None)
        self.provenance.setEnabled(bool(fact and fact.locator))
        if fact is None:
            self.detail.clear()
            return
        origin = "Confirmed inference" if fact.origin == Origin.INFERRED else "Owner statement"
        source = f"Source revision  {fact.revision}" if fact.locator else "No source citation attached"
        self.detail.setPlainText(f"{self.scope.currentText()} · Version {fact.version}\n{origin}\n"
                                 f"Fact ID  {fact.id}\n{source}\n\n{fact.text}")
