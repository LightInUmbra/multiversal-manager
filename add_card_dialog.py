# Imports
from PySide6.QtCore import Qt, QStringListModel, QTimer
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QFormLayout, QLineEdit, QPushButton,
    QSpinBox, QDialogButtonBox, QCompleter, QComboBox, QPlainTextEdit,
)

import background
import copy_details
import scryfall
from printing_picker import PrintingPicker

# Wait this long after the last keystroke before asking Scryfall for suggestions
AUTOCOMPLETE_DELAY_MS = 300


def _autocomplete(text):
    return text, scryfall.autocomplete(text)


class CardDialog(QDialog):
    """Add a card, or edit an existing collection entry (pass its database row as
    `existing`). Type a name (with live Scryfall suggestions), pick the exact
    printing, and the set, price and image fill in automatically."""

    def __init__(self, parent=None, existing=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Card" if existing else "Add Card")
        self._lookup_name = None

        # Name + suggestions
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Start typing a card name…")
        self._suggestions = QStringListModel(self)
        completer = QCompleter(self._suggestions, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        # Scryfall's suggestions can match mid-name, so don't filter them by prefix again
        completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        completer.activated.connect(self._look_up)
        self.name_input.setCompleter(completer)

        self._autocomplete_timer = QTimer(self)
        self._autocomplete_timer.setSingleShot(True)
        self._autocomplete_timer.setInterval(AUTOCOMPLETE_DELAY_MS)
        self._autocomplete_timer.timeout.connect(self._request_suggestions)
        self.name_input.textEdited.connect(lambda _: self._autocomplete_timer.start())
        self.name_input.returnPressed.connect(self._look_up)

        look_up_button = QPushButton("Look Up")
        look_up_button.setAutoDefault(False)
        look_up_button.clicked.connect(self._look_up)
        name_row = QHBoxLayout()
        name_row.addWidget(self.name_input)
        name_row.addWidget(look_up_button)

        self.picker = PrintingPicker()
        self.picker.loaded.connect(self._on_loaded)

        self.quantity_input = QSpinBox()
        self.quantity_input.setMinimum(1)
        self.quantity_input.setMaximum(9999)

        form_layout = QFormLayout()
        form_layout.addRow("Name:", name_row)
        form_layout.addRow(self.picker)
        form_layout.addRow("Quantity:", self.quantity_input)

        # Condition, language and notes describe these copies; a different condition
        # or language of the same printing is kept as its own entry
        self.condition_combo = QComboBox()
        for code, label in copy_details.CONDITIONS.items():
            self.condition_combo.addItem(f"{label} ({code})", code)
        self.language_combo = QComboBox()
        for code, label in copy_details.LANGUAGES.items():
            self.language_combo.addItem(label, code)
        self.language_combo.setToolTip("Prices are for the English printing")
        self.notes_input = QPlainTextEdit()
        self.notes_input.setPlaceholderText("Optional, e.g. signed, altered art, in the red binder…")
        self.notes_input.setFixedHeight(64)
        self.notes_input.setTabChangesFocus(True)
        form_layout.addRow("Condition:", self.condition_combo)
        form_layout.addRow("Language:", self.language_combo)
        form_layout.addRow("Notes:", self.notes_input)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText("Save Changes" if existing else "Add to Collection")
        self.ok_button.setEnabled(False)
        # Enter in the name box means "look up", never "submit"
        for button in self.button_box.buttons():
            button.setAutoDefault(False)
            button.setDefault(False)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        left = QVBoxLayout()
        left.addLayout(form_layout)
        left.addStretch()
        left.addWidget(self.button_box)

        outer_layout = QHBoxLayout(self)
        outer_layout.addLayout(left, stretch=1)
        outer_layout.addWidget(self.picker.image)

        if existing is not None:
            self.name_input.setText(existing["name"])
            self.quantity_input.setValue(existing["quantity"])
            self.condition_combo.setCurrentIndex(self.condition_combo.findData(existing["condition"]))
            self.language_combo.setCurrentIndex(self.language_combo.findData(existing["language"]))
            self.notes_input.setPlainText(existing["notes"])
            # Reselect the entry's current printing, finish and price once printings load
            self._look_up(existing["name"], select_id=existing["scryfall_id"],
                          foil=bool(existing["foil"]), price=existing["price"])

    # Autocomplete

    def _request_suggestions(self):
        text = self.name_input.text().strip()
        if len(text) < 2:
            return
        background.run(_autocomplete, text, on_success=self._on_suggestions)

    def _on_suggestions(self, result):
        text, names = result
        # Ignore suggestions for text the user has since changed
        if text != self.name_input.text().strip():
            return
        self._suggestions.setStringList(names)
        if names and self.name_input.hasFocus():
            self.name_input.completer().complete()

    # Printing lookup

    def _look_up(self, name=None, **restore):
        name = (name or self.name_input.text()).strip()
        if not name or name == self._lookup_name:
            return
        self._autocomplete_timer.stop()
        self._lookup_name = name
        self.ok_button.setEnabled(False)
        self.picker.load(name, **restore)

    def _on_loaded(self, found):
        if not found:
            self._lookup_name = None
            return
        self.name_input.setText(self.picker.selected_printing().name)
        self.ok_button.setEnabled(True)

    # Result

    def card_data(self):
        # Keyword arguments for database.add_card / update_card
        return {
            **self.picker.record(self.quantity_input.value()),
            "condition": self.condition_combo.currentData(),
            "language": self.language_combo.currentData(),
            "notes": self.notes_input.toPlainText(),
        }
