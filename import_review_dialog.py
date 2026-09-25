# Imports
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QTableWidget, QTableWidgetItem, QLabel,
    QCheckBox, QDialogButtonBox, QHeaderView, QAbstractItemView, QSplitter, QWidget,
    QMessageBox, QPushButton,
)

import scryfall
from printing_picker import PrintingPicker

COLUMNS = ["Import", "Qty", "Name", "Printing", "Finish", "Status"]
INCLUDE_COL, QTY_COL, NAME_COL, PRINTING_COL, FINISH_COL, STATUS_COL = range(len(COLUMNS))

# Entry states
EXACT = "exact"           # the file named this exact printing
UNSPECIFIED = "unspecified"  # the file only gave a name (or name + set)
FELL_BACK = "fell_back"   # the file's printing wasn't found; matched by name instead
CHOSEN = "chosen"         # the user picked the printing here
NOT_FOUND = "not_found"

_STATUS_TEXT = {
    EXACT: "✓ Printing from file",
    UNSPECIFIED: "⚠ Choose printing (file didn't say which)",
    FELL_BACK: "⚠ Choose printing (file's printing not found)",
    CHOSEN: "✓ Chosen",
    NOT_FOUND: "✗ Not found on Scryfall",
}
_NEEDS_REVIEW = {UNSPECIFIED, FELL_BACK}


@dataclass
class ReviewEntry:
    row: object
    card: object = None
    state: str = NOT_FOUND
    foil: bool = False
    price: float = None  # None = Scryfall's price for the printing + finish
    quantity: int = 1
    include: bool = True

    def record(self):
        return {**scryfall.card_record(self.card, foil=self.foil, quantity=self.quantity, price=self.price),
                **self.row.details()}


def build_entries(result):
    # One ReviewEntry per file row, entries that need a decision first
    fell_back = {id(row) for row, _ in result.approximate}
    entries = []
    for row, card in result.matched:
        if id(row) in fell_back:
            state = FELL_BACK
        elif row.scryfall_id or (row.set_code and row.collector_number):
            state = EXACT
        else:
            state = UNSPECIFIED
        entries.append(ReviewEntry(row, card, state, row.foil, None, row.quantity))
    entries += [ReviewEntry(row, None, NOT_FOUND, row.foil, None, row.quantity, include=False)
                for row in result.unmatched]
    order = {FELL_BACK: 0, UNSPECIFIED: 1, NOT_FOUND: 2, EXACT: 3}
    entries.sort(key=lambda e: (order[e.state], e.row.line))
    return entries


class ImportReviewDialog(QDialog):
    """Shows every imported entry before anything is saved. Entries whose printing
    isn't certain are listed first; select one to pick the printing you own."""

    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review Import")
        self.resize(1200, 700)
        self.entries = build_entries(result)
        self._current = None

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.review_only = QCheckBox("Show only entries that need a printing chosen")
        self.review_only.toggled.connect(self._apply_filter)

        self.table = QTableWidget(len(self.entries), len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(NAME_COL, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(PRINTING_COL, QHeaderView.ResizeMode.Stretch)
        for index in range(len(self.entries)):
            self._fill_row(index)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        # Printing picker for the selected entry
        self.picker = PrintingPicker(image_width=250)
        self.picker.clear("Select an entry to choose its printing")
        self.picker.changed.connect(self._on_picker_changed)
        self.picker_title = QLabel()
        self.picker_title.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.picker_title.setWordWrap(True)
        self.picker_hint = QLabel()
        self.picker_hint.setWordWrap(True)
        self.picker_hint.setStyleSheet("color: gray;")

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.addWidget(self.picker.image, stretch=1)
        side_layout.addWidget(self.picker_title)
        side_layout.addWidget(self.picker_hint)
        side_layout.addWidget(self.picker)
        self.next_button = QPushButton("Next Entry to Review ›")
        self.next_button.setAutoDefault(False)
        self.next_button.clicked.connect(self._select_next_to_review)
        side_layout.addWidget(self.next_button)

        splitter = QSplitter()
        splitter.addWidget(self.table)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([820, 380])

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        self.button_box.accepted.connect(self._confirm)
        self.button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.review_only)
        layout.addWidget(splitter, stretch=1)
        layout.addWidget(self.button_box)

        needs_review = sum(e.state in _NEEDS_REVIEW for e in self.entries)
        self.review_only.setChecked(needs_review > 0)
        self._update_summary()
        if self.entries:
            first_visible = next((i for i in range(len(self.entries)) if not self.table.isRowHidden(i)), 0)
            self.table.selectRow(first_visible)

    # Table

    def _fill_row(self, index):
        entry = self.entries[index]
        found = entry.card is not None
        self.table.blockSignals(True)

        include = QTableWidgetItem()
        flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        if found:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        include.setFlags(flags)
        include.setCheckState(Qt.CheckState.Checked if entry.include else Qt.CheckState.Unchecked)

        quantity = QTableWidgetItem()
        quantity.setData(Qt.ItemDataRole.EditRole, entry.quantity)
        if not found:
            quantity.setFlags(quantity.flags() & ~Qt.ItemFlag.ItemIsEditable)

        def text_item(text):
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            return item

        if found:
            card = entry.card
            name, printing = card.name, f"{card.set_name} ({card.set}) #{card.collector_number}"
        else:
            name, printing = entry.row.name, entry.row.describe()
        status = text_item(_STATUS_TEXT[entry.state])
        if entry.state in _NEEDS_REVIEW:
            status.setForeground(Qt.GlobalColor.darkYellow)
        elif entry.state == NOT_FOUND:
            status.setForeground(Qt.GlobalColor.red)

        self.table.setItem(index, INCLUDE_COL, include)
        self.table.setItem(index, QTY_COL, quantity)
        self.table.setItem(index, NAME_COL, text_item(name))
        self.table.setItem(index, PRINTING_COL, text_item(printing))
        self.table.setItem(index, FINISH_COL, text_item("Foil" if entry.foil else ""))
        self.table.setItem(index, STATUS_COL, status)
        self.table.blockSignals(False)

    def _on_item_changed(self, item):
        entry = self.entries[item.row()]
        if item.column() == INCLUDE_COL:
            entry.include = item.checkState() == Qt.CheckState.Checked
        elif item.column() == QTY_COL:
            quantity = item.data(Qt.ItemDataRole.EditRole)
            if isinstance(quantity, int) and quantity > 0:
                entry.quantity = quantity
            else:
                self._fill_row(item.row())
        self._update_summary()

    def _apply_filter(self):
        only_review = self.review_only.isChecked()
        for index, entry in enumerate(self.entries):
            self.table.setRowHidden(index, only_review and entry.state not in _NEEDS_REVIEW
                                    and entry is not self._current)

    def _update_summary(self):
        included = [e for e in self.entries if e.include and e.card is not None]
        needs_review = sum(e.state in _NEEDS_REVIEW for e in self.entries)
        not_found = sum(e.state == NOT_FOUND for e in self.entries)
        text = f"{len(self.entries):,} entries in the file."
        if needs_review:
            text += (f" <b>{needs_review:,} need a printing chosen</b>: the file didn't say which "
                     "printing you own (or named one Scryfall doesn't have), so a suggestion "
                     "is filled in. Select each one to pick the right printing.")
        else:
            text += " Every printing is accounted for."
        if not_found:
            text += f" {not_found:,} couldn't be found on Scryfall and will be skipped."
        self.summary_label.setText(text)
        self.next_button.setEnabled(needs_review > 0)
        cards = sum(e.quantity for e in included)
        self.ok_button.setText(f"Import {cards:,} Card{'s' if cards != 1 else ''}")
        self.ok_button.setEnabled(bool(included))

    # Picking a printing

    def _on_selection_changed(self):
        rows = self.table.selectionModel().selectedRows()
        entry = self.entries[rows[0].row()] if rows else None
        self._current = entry
        if entry is None or entry.card is None:
            self.picker.clear("Not found on Scryfall" if entry else "Select an entry to choose its printing")
            self.picker.setEnabled(False)
            self.picker_title.setText(entry.row.name if entry else "")
            self.picker_hint.setText(f"From your file: {entry.row.describe()}" if entry else "")
            return
        self.picker.setEnabled(True)
        self.picker_title.setText(entry.card.name)
        self.picker_hint.setText(f"From your file: {entry.row.describe()}")
        self.picker.load(entry.card.name, select_id=entry.card.id, foil=entry.foil, price=entry.price)

    def _on_picker_changed(self):
        entry = self._current
        card = self.picker.selected_printing()
        if entry is None or card is None:
            return
        foil = self.picker.is_foil()
        auto_price = scryfall.price_for(card, foil)
        # An exact match stays "from file" unless the user switches to another printing
        if entry.state != EXACT or card.id != entry.card.id:
            entry.state = CHOSEN
        entry.card, entry.foil = card, foil
        entry.price = None if abs(self.picker.price() - auto_price) < 0.005 else self.picker.price()
        self._fill_row(self.entries.index(entry))
        self._update_summary()

    def _select_next_to_review(self):
        # The next entry (after the selected one, wrapping around) still needing a decision
        start = self.entries.index(self._current) + 1 if self._current in self.entries else 0
        count = len(self.entries)
        for offset in range(count):
            index = (start + offset) % count
            if self.entries[index].state in _NEEDS_REVIEW:
                self._apply_filter()
                self.table.selectRow(index)
                self.table.scrollToItem(self.table.item(index, NAME_COL))
                return
        self._apply_filter()
        QMessageBox.information(self, "Review Import", "Every entry has a printing chosen.")

    # Finishing

    def _confirm(self):
        unreviewed = sum(e.state in _NEEDS_REVIEW and e.include for e in self.entries)
        if unreviewed:
            answer = QMessageBox.question(
                self, "Review Import",
                f"{unreviewed:,} included entr{'y' if unreviewed == 1 else 'ies'} still use a suggested "
                "printing that may not be the one you own. Import anyway?\n\n"
                "(You can fix any entry later: right-click it in your collection and choose Edit.)",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.accept()

    def records(self):
        # add_card keyword dicts for every entry being imported
        return [e.record() for e in self.entries if e.include and e.card is not None]
