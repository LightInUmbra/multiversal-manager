# Imports
from PySide6.QtCore import Qt, QStringListModel, QTimer
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QFormLayout, QLineEdit, QPushButton,
    QComboBox, QCheckBox, QDoubleSpinBox, QSpinBox, QDialogButtonBox, QLabel,
    QCompleter,
)

import background
import scryfall
from card_image import CardImage

# Wait this long after the last keystroke before asking Scryfall for suggestions
AUTOCOMPLETE_DELAY_MS = 300


def _autocomplete(text):
    return text, scryfall.autocomplete(text)


def _printings(name):
    return name, scryfall.get_printings(name)


class AddCardDialog(QDialog):
    """Type a card name (with live Scryfall suggestions), pick the exact printing,
    and the set, price and image fill in automatically."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Card")
        self._printings = []
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

        # Printing details
        self.printing_combo = QComboBox()
        self.printing_combo.setMinimumContentsLength(32)
        self.printing_combo.currentIndexChanged.connect(self._on_printing_changed)

        self.foil_check = QCheckBox("Foil")
        self.foil_check.toggled.connect(self._update_price)

        self.price_input = QDoubleSpinBox()
        self.price_input.setPrefix("$")
        self.price_input.setMaximum(100000.00)  # a reasonable ceiling for a card price
        self.price_input.setDecimals(2)
        self.price_input.setToolTip("Filled in from Scryfall's USD price; you can override it")

        self.quantity_input = QSpinBox()
        self.quantity_input.setMinimum(1)
        self.quantity_input.setMaximum(999)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: gray;")

        form_layout = QFormLayout()
        form_layout.addRow("Name:", name_row)
        form_layout.addRow("Printing:", self.printing_combo)
        form_layout.addRow("Finish:", self.foil_check)
        form_layout.addRow("Price (each):", self.price_input)
        form_layout.addRow("Quantity:", self.quantity_input)
        form_layout.addRow(self.status_label)

        self.image = CardImage(width=220)
        self.image.clear_image("Look up a card to see it here")

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText("Add to Collection")
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
        outer_layout.addWidget(self.image)

        self._set_printings([])

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

    def _look_up(self, name=None):
        name = (name or self.name_input.text()).strip()
        if not name or name == self._lookup_name:
            return
        self._autocomplete_timer.stop()
        self._lookup_name = name
        self._set_printings([])
        self.status_label.setText(f"Searching Scryfall for “{name}”…")
        background.run(_printings, name, on_success=self._on_printings, on_error=self._on_lookup_failed)

    def _on_printings(self, result):
        name, printings = result
        if name != self._lookup_name:
            return
        if not printings:
            self._lookup_name = None
            self.status_label.setText(f"No card found matching “{name}”.")
            return
        self.name_input.setText(printings[0].name)
        self._set_printings(printings)
        count = len(printings)
        self.status_label.setText(f"{count} printing{'s' if count != 1 else ''} found. Pick the one you own.")

    def _on_lookup_failed(self, message):
        self._lookup_name = None
        self.status_label.setText(f"Couldn't reach Scryfall: {message}")

    def _set_printings(self, printings):
        self._printings = printings
        self.printing_combo.blockSignals(True)
        self.printing_combo.clear()
        for card in printings:
            self.printing_combo.addItem(scryfall.printing_label(card))
        self.printing_combo.blockSignals(False)

        has_printings = bool(printings)
        self.printing_combo.setEnabled(has_printings)
        self.ok_button.setEnabled(has_printings)
        if has_printings:
            self.printing_combo.setCurrentIndex(0)
            self._on_printing_changed(0)
        else:
            self.foil_check.setEnabled(False)
            self.price_input.setValue(0)
            self.image.clear_image("Look up a card to see it here")

    def _on_printing_changed(self, index):
        card = self.selected_printing()
        if card is None:
            return
        finishes = set(card.finishes)
        # Only let the user choose when this printing exists in both finishes
        self.foil_check.blockSignals(True)
        self.foil_check.setChecked("nonfoil" not in finishes and "foil" in finishes)
        self.foil_check.setEnabled({"foil", "nonfoil"} <= finishes)
        self.foil_check.blockSignals(False)
        self._update_price()
        self.image.set_image_url(scryfall.image_url_for(card))

    def _update_price(self):
        card = self.selected_printing()
        if card is not None:
            self.price_input.setValue(scryfall.price_for(card, self.foil_check.isChecked()))

    # Result

    def selected_printing(self):
        index = self.printing_combo.currentIndex()
        return self._printings[index] if 0 <= index < len(self._printings) else None

    def card_data(self):
        # Keyword arguments for database.add_card
        card = self.selected_printing()
        return {
            "name": card.name,
            "set_name": card.set_name,
            "price": self.price_input.value(),
            "quantity": self.quantity_input.value(),
            "scryfall_id": card.id,
            "set_code": card.set,
            "collector_number": card.collector_number,
            "foil": self.foil_check.isChecked(),
            "rarity": card.rarity,
            "artist": card.artist,
            "image_url": scryfall.image_url_for(card),
        }
