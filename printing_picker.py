# Imports
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QComboBox, QCheckBox, QDoubleSpinBox, QLabel,
)

import background
import scryfall
from card_image import CardImage

# name -> printings, so revisiting a card (e.g. while reviewing an import) is instant
_printings_cache = {}


def _printings(name):
    key = name.lower()
    if key not in _printings_cache:
        _printings_cache[key] = scryfall.get_printings(name)
    return name, _printings_cache[key]


class PrintingPicker(QWidget):
    """Printing / finish / price fields for one card, plus a card image preview
    (exposed as .image so the parent can place it). Call load(name) to fill it."""

    # The user changed the printing, finish or price
    changed = Signal()
    # A load() finished: True if any printings were found
    loaded = Signal(bool)

    def __init__(self, image_width=220, parent=None):
        super().__init__(parent)
        self._printings = []
        self._lookup_name = None
        self._pending = None
        self._applying = False

        self.printing_combo = QComboBox()
        self.printing_combo.setMinimumContentsLength(32)
        self.printing_combo.currentIndexChanged.connect(self._on_printing_changed)

        self.foil_check = QCheckBox("Foil")
        self.foil_check.toggled.connect(self._on_foil_toggled)

        self.price_input = QDoubleSpinBox()
        self.price_input.setPrefix("$")
        self.price_input.setMaximum(100000.00)  # a reasonable ceiling for a card price
        self.price_input.setDecimals(2)
        self.price_input.setToolTip("Filled in from Scryfall's USD price; you can override it")
        self.price_input.valueChanged.connect(self._emit_changed)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: gray;")

        self.image = CardImage(width=image_width)

        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addRow("Printing:", self.printing_combo)
        layout.addRow("Finish:", self.foil_check)
        layout.addRow("Price (each):", self.price_input)
        layout.addRow(self.status_label)

        self.clear()

    # Loading

    def clear(self, message="Look up a card to see it here"):
        self._lookup_name = None
        self._set_printings([])
        self.status_label.setText("")
        self.image.clear_image(message)

    def load(self, name, select_id=None, foil=None, price=None):
        # Fetches every printing of name. select_id / foil / price restore a
        # previous choice once the printings arrive.
        name = name.strip()
        self._lookup_name = name
        self._pending = (select_id, foil, price)
        self._set_printings([])
        self.status_label.setText(f"Searching Scryfall for “{name}”…")
        background.run(_printings, name, on_success=self._on_printings, on_error=self._on_failed)

    def _on_printings(self, result):
        name, printings = result
        if name != self._lookup_name:
            return
        if not printings:
            self.status_label.setText(f"No card found matching “{name}”.")
            self.image.clear_image("No card found")
            self.loaded.emit(False)
            return
        self._set_printings(printings)
        count = len(printings)
        self.status_label.setText(f"{count} printing{'s' if count != 1 else ''} found. Pick the one you own.")
        self.loaded.emit(True)

    def _on_failed(self, message):
        self.status_label.setText(f"Couldn't reach Scryfall: {message}")
        self.loaded.emit(False)

    def _set_printings(self, printings):
        select_id, foil, price = self._pending or (None, None, None)
        self._pending = None
        self._printings = printings

        self._applying = True
        self.printing_combo.clear()
        for card in printings:
            self.printing_combo.addItem(scryfall.printing_label(card))
        self.printing_combo.setEnabled(bool(printings))
        if printings:
            ids = [card.id for card in printings]
            self.printing_combo.setCurrentIndex(ids.index(select_id) if select_id in ids else 0)
            self._on_printing_changed()
            if foil is not None and self.foil_check.isEnabled():
                self.foil_check.setChecked(foil)
            if price is not None:
                self.price_input.setValue(price)
        else:
            self.foil_check.setEnabled(False)
            self.price_input.setValue(0)
        self._applying = False

    # Reacting to changes

    def _on_printing_changed(self, *_):
        card = self.selected_printing()
        if card is None:
            return
        finishes = set(card.finishes)
        # Only let the user choose when this printing exists in both finishes
        applying, self._applying = self._applying, True
        self.foil_check.setChecked("nonfoil" not in finishes and "foil" in finishes)
        self.foil_check.setEnabled({"foil", "nonfoil"} <= finishes)
        self._update_price()
        self._applying = applying
        self.image.set_image_url(scryfall.image_url_for(card))
        self._emit_changed()

    def _on_foil_toggled(self):
        applying, self._applying = self._applying, True
        self._update_price()
        self._applying = applying
        self._emit_changed()

    def _update_price(self):
        card = self.selected_printing()
        if card is not None:
            self.price_input.setValue(scryfall.price_for(card, self.foil_check.isChecked()))

    def _emit_changed(self, *_):
        if not self._applying:
            self.changed.emit()

    # Result

    def selected_printing(self):
        index = self.printing_combo.currentIndex()
        return self._printings[index] if 0 <= index < len(self._printings) else None

    def is_foil(self):
        return self.foil_check.isChecked()

    def price(self):
        return self.price_input.value()

    def record(self, quantity):
        # Keyword arguments for database.add_card
        return scryfall.card_record(self.selected_printing(), foil=self.is_foil(),
                                    quantity=quantity, price=self.price())
