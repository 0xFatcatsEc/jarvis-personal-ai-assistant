"""Search controls and exact retained-locator inspection."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from ..knowledge.context import Citation, EvidenceBundle
from ..knowledge.locators import Locator


def location(page: int | None, start: int | None, end: int | None) -> str:
    if page is not None:
        return f"Page {page}"
    return f"Text range [{start}, {end})"


def citation_text(path: str, source: str, locator: Locator) -> str:
    return (f"{path}\n{location(locator.page, locator.start, locator.end)}\n"
            f"Source ID  {source}\nRevision ID  {locator.revision}\nLocator ID  {locator.id}"
            f"\n\n{locator.excerpt}")


class EvidenceView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        filters = QFormLayout()
        self.query = QLineEdit()
        self.query.setMaxLength(512)
        self.query.setPlaceholderText("Search approved excerpts")
        self.revision = QLineEdit()
        self.revision.setMaxLength(32)
        self.revision.setPlaceholderText("Optional exact revision ID")
        for name, field in (("Search &terms", self.query), ("&Revision", self.revision)):
            label = QLabel(name)
            label.setBuddy(field)
            field.setAccessibleName(name.replace("&", ""))
            filters.addRow(label, field)
        layout.addLayout(filters)
        buttons = QHBoxLayout()
        self.search = QPushButton("Search evidence")
        self.inspect = QPushButton("Inspect selected citation")
        self.inspect.setEnabled(False)
        buttons.addWidget(self.search)
        buttons.addWidget(self.inspect)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.feedback = QLabel("Search the current project’s published excerpts.")
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.matches = QListWidget()
        self.matches.setAccessibleName("Evidence search results")
        self.matches.setWordWrap(True)
        layout.addWidget(self.matches, 1)
        self.detail = QPlainTextEdit()
        self.detail.setAccessibleName("Exact citation and retained excerpt")
        self.detail.setReadOnly(True)
        layout.addWidget(self.detail, 2)
        self.matches.currentItemChanged.connect(lambda current, _: self.inspect.setEnabled(current is not None))

    def clear_results(self, message: str = "Search the current project’s published excerpts.") -> None:
        self.matches.clear()
        self.detail.clear()
        self.feedback.setText(message)

    def show_results(self, bundle: EvidenceBundle) -> None:
        if not bundle.passages:
            self.feedback.setText("Insufficient evidence in the selected revisions. Check your search terms or save "
                                  "source excerpts. Scanned PDF pages need a text layer to appear in search.")
            return
        for number, passage in enumerate(bundle.passages, 1):
            for citation in passage.citations:
                label = (f"Passage {number} · {citation.relative_path} · "
                         f"{location(citation.page, citation.start, citation.end)} · {citation.revision[:12]}")
                item = QListWidgetItem(label, self.matches)
                item.setData(Qt.ItemDataRole.UserRole, citation)
        self.feedback.setText("Select a citation and press Enter to inspect the retained excerpt.")
        self.matches.setCurrentRow(0)

    def show_locator(self, citation: Citation, locator: Locator) -> None:
        self.detail.setPlainText(citation_text(citation.relative_path, citation.source, locator))
