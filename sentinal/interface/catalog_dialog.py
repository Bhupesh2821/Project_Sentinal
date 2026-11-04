"""Search the selected local model's exact permitted category catalog."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QTableWidget, QTableWidgetItem, QDialogButtonBox, QHeaderView
from sentinal.vision.object_catalog import catalog_rows, profile_for_model


class CatalogDialog(QDialog):
    def __init__(self, model_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SENTINAL · Supported object categories")
        self.resize(620, 600)
        self.rows = catalog_rows(model_path)
        profile = profile_for_model(model_path)
        layout = QVBoxLayout(self)
        title = QLabel(profile.title if profile else Path(model_path).name)
        layout.addWidget(title)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search helmet, hammer, ladder, wrench…")
        self.search.textChanged.connect(self._refresh)
        layout.addWidget(self.search)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Object category", "Model ID", "Category group"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table, 1)
        note = QLabel("These are pretrained object categories, not a list of people. Generic helmet, glove and boot labels do not establish protective rating, correct use or safety compliance. Unsupported classes such as high-visibility vest and fire extinguisher are not claimed. Detection can miss objects or produce false positives.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    def _refresh(self, *_):
        query = self.search.text().strip().casefold()
        selected = [r for r in self.rows if query in r["label"].casefold()]
        self.table.setRowCount(len(selected))
        for row, entry in enumerate(selected):
            for column, value in enumerate([entry["label"], str(entry["id"]), "Safety / tools" if entry["safety_tool"] else "Everyday objects"]):
                self.table.setItem(row, column, QTableWidgetItem(value))
        safety = sum(r["safety_tool"] for r in self.rows)
        self.summary.setText(f"{len(selected)} shown / {len(self.rows)} permitted categories · {safety} safety / tool categories")
