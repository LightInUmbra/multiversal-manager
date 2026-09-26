"""
Sealed product: booster boxes, bundles, precons and the like, in the main window's
Sealed tab. Products are picked from MTGJSON's catalog of every sealed product (or
typed in by hand), with what you paid and what they're worth now, both entered by
you -- there's no free source of sealed prices to fill them in.
"""

# Imports
from contextlib import contextmanager
from urllib.parse import quote_plus

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QCursor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QPushButton, QDialog, QDialogButtonBox, QSpinBox,
    QDoubleSpinBox, QCheckBox, QPlainTextEdit, QMessageBox, QMenu,
)

import background
import database as db
import mtgjson
import scryfall
import trends

COLUMNS = ["Product", "Set", "Type", "Qty", "Paid (each)", "Value (each)", "Total Value", "Gain / Loss", "Notes"]
(NAME_COL, SET_COL, TYPE_COL, QTY_COL, PAID_COL, VALUE_COL, TOTAL_COL, GAIN_COL, NOTES_COL) = range(len(COLUMNS))
ID_ROLE = Qt.ItemDataRole.UserRole
SORT_ROLE = Qt.ItemDataRole.UserRole + 1


def money(value):
    return f"${value:,.2f}" if value else "—"


def gain(row):
    # What the entry has gained or lost in all, or None without both prices
    if row["paid"] is None or row["value"] is None:
        return None
    return (row["value"] - row["paid"]) * row["quantity"]


def _download_catalog():
    products = mtgjson.sealed_catalog()
    db.replace_sealed_catalog(products)
    return len(products)


class _Item(QTableWidgetItem):
    # Sorts by SORT_ROLE when set (numbers), else by text. (Not super().__lt__: in PySide6
    # that calls straight back into this method, which recurses until the app crashes.)
    def __lt__(self, other):
        mine, theirs = self.data(SORT_ROLE), other.data(SORT_ROLE)
        if mine is not None and theirs is not None:
            return mine < theirs
        return self.text().casefold() < other.text().casefold()


@contextmanager
def _filling(table):
    # A table whose columns fit their contents re-measures every row for each cell added,
    # so filling hundreds of rows took minutes: fit the columns once, after the last cell
    header = table.horizontalHeader()
    modes = [header.sectionResizeMode(column) for column in range(header.count())]
    header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    table.setUpdatesEnabled(False)
    try:
        yield
    finally:
        for column, mode in enumerate(modes):
            header.setSectionResizeMode(column, mode)
        table.setUpdatesEnabled(True)


def _item(text, sort=None, right=False):
    item = _Item(text)
    if sort is not None:
        item.setData(SORT_ROLE, sort)
    if right:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


def _price_input():
    # A dollar amount where $0.00 means "not entered"
    spin = QDoubleSpinBox()
    spin.setPrefix("$")
    spin.setMaximum(1_000_000.00)
    spin.setSpecialValueText("Not entered")
    return spin


class SealedDialog(QDialog):
    """Add a sealed product (pick it from the catalog, or type your own), or edit an
    entry (pass its row as existing). record() returns db.add_sealed fields."""

    def __init__(self, parent=None, existing=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Sealed Product" if existing else "Add Sealed Product")
        self.resize(900, 640)
        self._existing = existing
        self._rows = []

        # Picking from the catalog
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by product or set, e.g. “modern horizons 3 collector”…")
        self.search_input.setClearButtonEnabled(True)
        self.type_combo = QComboBox()
        timer = QTimer(self, singleShot=True, interval=250)
        timer.timeout.connect(self.search)
        self.search_input.textChanged.connect(lambda _: timer.start())
        self.type_combo.currentIndexChanged.connect(lambda _: self.search())
        search_row = QHBoxLayout()
        search_row.addWidget(self.search_input, stretch=1)
        search_row.addWidget(self.type_combo)

        self.results = QTableWidget(0, 4)
        self.results.setHorizontalHeaderLabels(["Product", "Set", "Type", "Released"])
        self.results.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results.verticalHeader().setVisible(False)
        header = self.results.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.results.itemSelectionChanged.connect(self._update_ok)
        self.status = QLabel()
        self.status.setStyleSheet("color: gray;")

        # Or typing it in
        self.custom_check = QCheckBox("It's not in the list: I'll type it in")
        self.custom_check.toggled.connect(self._on_custom)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Secret Lair: Bitterblossom Dreams")
        self.name_input.textChanged.connect(self._update_ok)
        self.set_input = QLineEdit()
        self.set_input.setPlaceholderText("Optional")
        self.type_input = QLineEdit()
        self.type_input.setPlaceholderText("Optional, e.g. Booster Box")
        custom = QFormLayout()
        custom.addRow("Name:", self.name_input)
        custom.addRow("Set:", self.set_input)
        custom.addRow("Type:", self.type_input)
        self.custom_form = QWidget()
        self.custom_form.setLayout(custom)

        # What you have of it
        self.quantity_input = QSpinBox()
        self.quantity_input.setRange(1, 9999)
        self.paid_input = _price_input()
        self.paid_input.setToolTip("What you paid for each one")
        self.value_input = _price_input()
        self.value_input.setToolTip("What each one is worth now. Right-click an entry in the Sealed tab "
                                    "to look it up on TCGplayer.")
        self.notes_input = QPlainTextEdit()
        self.notes_input.setPlaceholderText("Optional, e.g. bought at the prerelease, sealed in the closet")
        self.notes_input.setFixedHeight(60)
        self.notes_input.setTabChangesFocus(True)
        details = QFormLayout()
        details.addRow("Quantity:", self.quantity_input)
        details.addRow("Paid (each):", self.paid_input)
        details.addRow("Value now (each):", self.value_input)
        details.addRow("Notes:", self.notes_input)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText("Save Changes" if existing else "Add to Collection")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        self.catalog = QWidget()
        catalog_layout = QVBoxLayout(self.catalog)
        catalog_layout.setContentsMargins(0, 0, 0, 0)
        catalog_layout.addLayout(search_row)
        catalog_layout.addWidget(self.results, stretch=1)
        catalog_layout.addWidget(self.status)
        layout.addWidget(self.catalog, stretch=1)
        layout.addWidget(self.custom_check)
        layout.addWidget(self.custom_form)
        layout.addLayout(details)
        layout.addWidget(buttons)

        if existing is not None:
            # The product itself stays put when editing; only what you have of it changes
            self.catalog.hide()
            self.custom_check.hide()
            self.custom_form.setEnabled(existing["uuid"] is None)
            self.name_input.setText(existing["name"])
            self.set_input.setText(existing["set_name"] or "")
            self.type_input.setText(existing["product_type"] or "")
            self.quantity_input.setValue(existing["quantity"])
            self.paid_input.setValue(existing["paid"] or 0)
            self.value_input.setValue(existing["value"] or 0)
            self.notes_input.setPlainText(existing["notes"])
        else:
            self.custom_form.hide()
            self._load_catalog()
        self._update_ok()

    # Catalog

    def _load_catalog(self):
        if db.has_sealed_catalog():
            self._fill_types()
            self.search()
        elif scryfall.offline:
            self.status.setText("The sealed product list downloads from MTGJSON, which needs the internet. "
                                "You can still type a product in below.")
        else:
            self.status.setText("Downloading MTGJSON's list of sealed products…")
            background.run(_download_catalog, on_success=self._on_catalog, on_error=self._on_catalog_failed)

    def _on_catalog(self, count):
        self._fill_types()
        self.search()

    def _on_catalog_failed(self, message):
        self.status.setText(f"Couldn't download the sealed product list: {message}. "
                            "You can still type a product in below.")

    def _fill_types(self):
        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        self.type_combo.addItem("Any type", "")
        for category in db.sealed_categories():
            self.type_combo.addItem(category, category)
        self.type_combo.blockSignals(False)

    def search(self):
        rows = db.search_sealed_catalog(self.search_input.text(), self.type_combo.currentData() or "")
        self._rows = rows
        with _filling(self.results):
            self.results.setRowCount(len(rows))
            for index, row in enumerate(rows):
                for column, text in enumerate([row["name"], f"{row['set_name']} ({row['set_code']})",
                                               row["product_type"], row["released"] or ""]):
                    self.results.setItem(index, column, QTableWidgetItem(text))
        more = " (the first 500; search to narrow it down)" if len(rows) == 500 else ""
        self.status.setText(f"{len(rows):,} products{more}. Pick one, or type it in below if it isn't listed.")
        self._update_ok()

    def _selected(self):
        rows = {index.row() for index in self.results.selectionModel().selectedRows()}
        return self._rows[rows.pop()] if rows else None

    def _on_custom(self, on):
        self.catalog.setEnabled(not on)
        self.custom_form.setVisible(on)
        self._update_ok()

    def _update_ok(self):
        typed = self._existing is not None or self.custom_check.isChecked()
        self.ok_button.setEnabled(bool(self.name_input.text().strip()) if typed else self._selected() is not None)

    # Result

    def record(self):
        details = {"quantity": self.quantity_input.value(), "paid": self.paid_input.value() or None,
                   "value": self.value_input.value() or None, "notes": self.notes_input.toPlainText()}
        if self._existing is None and not self.custom_check.isChecked():
            product = self._selected()
            return {"name": product["name"], "set_code": product["set_code"], "set_name": product["set_name"],
                    "product_type": product["product_type"], "uuid": product["uuid"], **details}
        typed = {"name": self.name_input.text().strip(), "set_name": self.set_input.text().strip() or None,
                 "product_type": self.type_input.text().strip() or None}
        if self._existing is not None and self._existing["uuid"] is not None:
            typed = {}  # a catalog product keeps its name, set and type
        return {**typed, **details}


class SealedPanel(QWidget):
    """The Sealed tab: your sealed product, its value, and buttons to add, edit and
    remove. Emits changed when the totals change."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = {}

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter by product, set, type or notes…")
        self.filter_input.setClearButtonEnabled(True)
        self.filter_input.textChanged.connect(self.apply_filter)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(NAME_COL, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(NOTES_COL, QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(NAME_COL, Qt.SortOrder.AscendingOrder)
        self.table.cellDoubleClicked.connect(lambda row, _: self.edit(self.table.item(row, NAME_COL).data(ID_ROLE)))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_menu)
        remove_action = QAction("Remove", self.table, shortcut=QKeySequence.StandardKey.Delete)
        remove_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        remove_action.triggered.connect(self.remove_selected)
        self.table.addAction(remove_action)

        self.summary_label = QLabel()
        self.summary_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.gain_label = QLabel()
        add_button = QPushButton("Add Sealed Product…")
        add_button.clicked.connect(self.add)
        self.edit_button = QPushButton("Edit…")
        self.edit_button.clicked.connect(lambda: self.edit(self.selected_ids()[0]))
        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.clicked.connect(self.remove_selected)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        buttons = QHBoxLayout()
        buttons.addWidget(self.summary_label)
        buttons.addSpacing(12)
        buttons.addWidget(self.gain_label, stretch=1)
        for button in (self.edit_button, self.remove_button, add_button):
            buttons.addWidget(button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.filter_input)
        layout.addWidget(self.table, stretch=1)
        layout.addLayout(buttons)
        self.reload()

    # Table

    def reload(self, select_id=None):
        rows = db.get_sealed()
        self._rows = {row["id"]: row for row in rows}
        self.table.setSortingEnabled(False)
        with _filling(self.table):
            self._fill(rows)
        self.table.setSortingEnabled(True)
        self.apply_filter()
        if select_id is not None:
            self.select(select_id)
        self._update_buttons()
        self.update_summary()

    def _fill(self, rows):
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            change = gain(row)
            items = [
                _item(row["name"]), _item(row["set_name"] or ""), _item(row["product_type"] or ""),
                _item(str(row["quantity"]), row["quantity"], right=True),
                _item(money(row["paid"]), row["paid"] or 0, right=True),
                _item(money(row["value"]), row["value"] or 0, right=True),
                _item(money((row["value"] or 0) * row["quantity"]), (row["value"] or 0) * row["quantity"], right=True),
                _item(trends.format_change(change) if change is not None else "", change or 0, right=True),
                _item(row["notes"].replace("\n", " ")),
            ]
            items[NAME_COL].setData(ID_ROLE, row["id"])
            if change:
                color = trends.change_color(change)
                if color:
                    items[GAIN_COL].setForeground(color)
            if row["value"] is None:
                items[VALUE_COL].setToolTip("No value entered yet. Edit it to add one.")
            for column, item in enumerate(items):
                self.table.setItem(index, column, item)

    def apply_filter(self):
        needle = self.filter_input.text().strip().lower()
        for index in range(self.table.rowCount()):
            row = self._rows[self.table.item(index, NAME_COL).data(ID_ROLE)]
            haystack = " ".join(str(row[k] or "") for k in ("name", "set_name", "set_code", "product_type", "notes"))
            self.table.setRowHidden(index, bool(needle) and needle not in haystack.lower())

    def update_summary(self):
        count, value, paid, value_of_paid = db.sealed_summary()
        self.summary_label.setText(f"Sealed value: ${value:,.2f}    ·    {count:,} item{'s' if count != 1 else ''}")
        if paid:
            change = value_of_paid - paid
            color = trends.change_color(change)
            self.gain_label.setText(f"{trends.format_change(change, change / paid * 100)} "
                                    f"on ${paid:,.2f} paid")
            self.gain_label.setStyleSheet("font-size: 14px;" + (f" color: {color.name()};" if color else ""))
            self.gain_label.setToolTip("Only items with both a paid price and a value count")
        else:
            self.gain_label.setText("")
        self.changed.emit()

    def selected_ids(self):
        return [self.table.item(index.row(), NAME_COL).data(ID_ROLE)
                for index in self.table.selectionModel().selectedRows()]

    def select(self, sealed_id):
        for index in range(self.table.rowCount()):
            if self.table.item(index, NAME_COL).data(ID_ROLE) == sealed_id:
                self.table.selectRow(index)
                self.table.scrollToItem(self.table.item(index, NAME_COL))

    def _update_buttons(self):
        ids = self.selected_ids()
        self.edit_button.setEnabled(len(ids) == 1)
        self.remove_button.setEnabled(bool(ids))

    # Adding, editing and removing

    def add(self):
        dialog = SealedDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.reload(select_id=db.add_sealed(**dialog.record()))

    def edit(self, sealed_id):
        dialog = SealedDialog(self, existing=self._rows[sealed_id])
        if dialog.exec() == QDialog.DialogCode.Accepted:
            db.update_sealed(sealed_id, **dialog.record())
            self.reload(select_id=sealed_id)

    def remove_selected(self):
        ids = self.selected_ids()
        if not ids:
            return
        what = self._rows[ids[0]]["name"] if len(ids) == 1 else f"{len(ids)} sealed products"
        if QMessageBox.question(self, "Remove", f"Remove {what} from your collection?") == \
                QMessageBox.StandardButton.Yes:
            db.remove_sealed(ids)
            self.reload()

    def show_menu(self, position):
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        if not self.table.selectionModel().isRowSelected(index.row()):
            self.table.selectRow(index.row())
        row = self._rows[self.table.item(index.row(), NAME_COL).data(ID_ROLE)]
        menu = QMenu(self)
        menu.addAction("Edit…", lambda: self.edit(row["id"]))
        menu.addAction("Look Up Price on TCGplayer", lambda: QDesktopServices.openUrl(QUrl(
            f"https://www.tcgplayer.com/search/magic/product?q={quote_plus(row['name'])}")))
        menu.addSeparator()
        menu.addAction("Remove", self.remove_selected)
        menu.exec(QCursor.pos())
