"""Owner review of a volatile memory proposal."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QPlainTextEdit, QWidget)

from ..memory.service import Destination, Origin


class FactEditor(QDialog):
    def __init__(self, parent: QWidget, project: str, owner: str, text: str, origin: Origin) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review memory")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QFormLayout(self)
        self.destination = QComboBox()
        self.destination.addItem(f"Project · {project}", Destination.PROJECT.value)
        self.destination.addItem(f"Personal · {owner}", Destination.PERSONAL.value)
        layout.addRow("Save to", self.destination)
        self.statement = QPlainTextEdit()
        self.statement.setPlainText(text)
        layout.addRow("Proposed fact" if origin == Origin.INFERRED else "Fact", self.statement)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.save = buttons.addButton("Confirm and save", QDialogButtonBox.ButtonRole.AcceptRole)
        self.save.setAutoDefault(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        layout.addRow(buttons)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        def validate() -> None:
            value = self.statement.toPlainText()
            self.save.setEnabled(bool(value.strip()) and len(value) <= 8192 and "\x00" not in value)
        self.statement.textChanged.connect(validate)
        validate()
