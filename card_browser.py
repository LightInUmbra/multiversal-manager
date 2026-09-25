"""
Cards shown two ways: a grid of card images (standard mode) or a plain table
(lightweight mode, which downloads no images). Used by the deck builder's card
list and by the printing picker.
"""

# Imports
from collections import OrderedDict

from PySide6.QtCore import Qt, QSize, QAbstractListModel, QModelIndex, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QStackedWidget, QListView, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QDialog,
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox, QRadioButton, QButtonGroup, QDialogButtonBox,
    QSplitter, QWidget,
)

import background
import card_image
from card_image import CardImage

THUMB_SIZE = QSize(100, 140)   # grid thumbnails (Scryfall's "small" images, scaled)
THUMB_CACHE_SIZE = 500          # thumbnails kept in memory; the rest reload from the disk cache
OWNED_COLOR = QColor("#1a8f3c")
MUTED_COLOR = QColor("gray")
FINISH_NAMES = {0: "Non-foil", 1: "Foil", 2: "Etched"}


def thumb_url(image_url):
    # Scryfall serves every card image in several sizes at the same path
    return image_url.replace("/normal/", "/small/") if image_url else None


def money(value):
    return f"${value:,.2f}" if value else "—"


class CardGridModel(QAbstractListModel):
    """Cards as a grid of images with a short caption under each. Images load in the
    background as they scroll into view (a view only asks for the items it shows).
    caption(row) returns (text, color or None); tooltip(row) returns text."""

    def __init__(self, caption, tooltip, parent=None):
        super().__init__(parent)
        self.rows = []
        self._caption, self._tooltip = caption, tooltip
        self._thumbs = OrderedDict()   # url -> QPixmap, least recently used first
        self._loading = set()
        self._rows_by_url = {}
        self._placeholder = QPixmap(THUMB_SIZE)
        self._placeholder.fill(QColor("#cccccc"))

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self._rows_by_url = {}
        for index, row in enumerate(rows):
            self._rows_by_url.setdefault(thumb_url(row["image_url"]), []).append(index)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return self._caption(row)[0]
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._caption(row)[1]
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(row)
        if role == Qt.ItemDataRole.DecorationRole:
            return self._thumb(thumb_url(row["image_url"]))
        return None

    def _thumb(self, url):
        if url is None:
            return self._placeholder
        pixmap = self._thumbs.get(url)
        if pixmap is not None:
            self._thumbs.move_to_end(url)
            return pixmap
        if url not in self._loading:
            self._loading.add(url)
            background.run(card_image._fetch, url, on_success=self._loaded)
        return self._placeholder

    def _loaded(self, result):
        url, data = result
        self._loading.discard(url)
        pixmap = QPixmap()
        if data and pixmap.loadFromData(data):
            pixmap = pixmap.scaled(THUMB_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
        else:
            pixmap = self._placeholder  # remembered, so a missing image isn't retried endlessly
        self._thumbs[url] = pixmap
        while len(self._thumbs) > THUMB_CACHE_SIZE:
            self._thumbs.popitem(last=False)
        for row in self._rows_by_url.get(url, []):
            index = self.index(row)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole])


class CardBrowser(QStackedWidget):
    """A list of cards as an image grid or, in lightweight mode, a table.
    columns: [(header, fn(row) -> text or (text, color))] for the table;
    caption / tooltip: as for CardGridModel. Emits the row that was selected,
    double-clicked (activated) or right-clicked (menu_requested)."""

    selected = Signal(object)
    activated = Signal(object)
    menu_requested = Signal(object)

    def __init__(self, columns, caption, tooltip, parent=None):
        super().__init__(parent)
        self.rows = []
        self.lightweight = False
        self._columns, self._tooltip = columns, tooltip

        self.grid_model = CardGridModel(caption, tooltip, self)
        self.grid = QListView()
        self.grid.setModel(self.grid_model)
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setIconSize(THUMB_SIZE)
        self.grid.setGridSize(QSize(THUMB_SIZE.width() + 12, THUMB_SIZE.height() + 26))
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grid.selectionModel().selectionChanged.connect(lambda *_: self._on_selection())
        self.grid.doubleClicked.connect(lambda index: self.activated.emit(self.rows[index.row()]))

        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels([header for header, _ in columns])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.cellDoubleClicked.connect(lambda row, _: self.activated.emit(self.rows[row]))

        for view in (self.grid, self.table):
            view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            view.customContextMenuRequested.connect(lambda position, view=view: self._on_menu(view, position))
            self.addWidget(view)

    def set_lightweight(self, on):
        self.lightweight = on
        self.setCurrentWidget(self.table if on else self.grid)
        self.set_rows(self.rows)

    def set_rows(self, rows):
        self.rows = rows
        if self.lightweight:
            self.grid_model.set_rows([])  # nothing left for the grid to load images for
            self.table.setRowCount(len(rows))
            for index, row in enumerate(rows):
                tooltip = self._tooltip(row)
                for column, (_, value) in enumerate(self._columns):
                    cell = value(row)
                    text, color = cell if isinstance(cell, tuple) else (cell, None)
                    item = QTableWidgetItem(text)
                    if color is not None:
                        item.setForeground(color)
                    item.setToolTip(tooltip)
                    self.table.setItem(index, column, item)
        else:
            self.table.setRowCount(0)
            self.grid_model.set_rows(rows)

    def select(self, index):
        if 0 <= index < len(self.rows):
            if self.lightweight:
                self.table.selectRow(index)
            else:
                self.grid.setCurrentIndex(self.grid_model.index(index))

    def current_index(self):
        if self.lightweight:
            rows = {index.row() for index in self.table.selectionModel().selectedRows()}
            return rows.pop() if rows else None
        indexes = self.grid.selectionModel().selectedIndexes()
        return indexes[0].row() if indexes else None

    def _on_selection(self):
        index = self.current_index()
        if index is not None:
            self.selected.emit(self.rows[index])

    def _on_menu(self, view, position):
        index = view.indexAt(position)
        if index.isValid():
            self.select(index.row())
            self.menu_requested.emit(self.rows[index.row()])


def group_printings(printings):
    # printings_of rows (one per printing + finish) -> one dict per printing, with its
    # finishes as [(foil code, price, copies owned)] and the cheapest price as "price"
    grouped = {}
    for p in printings:
        entry = grouped.setdefault(p["scryfall_id"], {
            **{key: p[key] for key in ("name", "scryfall_id", "set_code", "set_name", "collector_number",
                                       "rarity", "image_url")},
            "finishes": [], "owned": 0, "price": None})
        entry["finishes"].append((p["foil"], p["price"], p["owned"]))
        entry["owned"] += p["owned"]
        if p["price"] and (entry["price"] is None or p["price"] < entry["price"]):
            entry["price"] = p["price"]
    return list(grouped.values())


class PrintingDialog(QDialog):
    """Pick a printing and finish of a card: every printing as images (a table in
    lightweight mode) next to the selected one's large image, set, rarity, and each
    finish's price and how many you own. choice() returns an add_card-style record."""

    def __init__(self, name, printings, lightweight=False, action="Add", current=None, parent=None):
        # current: (scryfall_id, foil) to start on, e.g. when changing a card's printing
        super().__init__(parent)
        self.setWindowTitle(f"Printings of {name}")
        self.resize(1100, 700)
        self._all = group_printings(printings)
        self._start = current
        self._current = None

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter by set name or code…")
        self.filter_input.setClearButtonEnabled(True)
        self.filter_input.textChanged.connect(lambda _: self._apply_filter())
        self.owned_check = QCheckBox("Only printings I own")
        self.owned_check.toggled.connect(lambda _: self._apply_filter())
        filters = QHBoxLayout()
        filters.addWidget(self.filter_input, stretch=1)
        filters.addWidget(self.owned_check)

        self.browser = CardBrowser(
            columns=[("Set", lambda p: f"{p['set_name']} ({p['set_code']})"),
                     ("#", lambda p: p["collector_number"] or ""),
                     ("Rarity", lambda p: (p["rarity"] or "").capitalize()),
                     ("Finishes", lambda p: ", ".join(FINISH_NAMES[f] for f, _, _ in p["finishes"])),
                     ("From", lambda p: money(p["price"])),
                     ("Owned", lambda p: (f"×{p['owned']}", OWNED_COLOR) if p["owned"] else ("—", MUTED_COLOR))],
            caption=lambda p: (f"{p['set_code']} #{p['collector_number']}", OWNED_COLOR if p["owned"] else None),
            tooltip=lambda p: f"{p['set_name']} ({p['set_code']}) #{p['collector_number']}",
        )
        self.browser.set_lightweight(lightweight)
        self.browser.selected.connect(self._show)
        self.browser.activated.connect(lambda _: self.accept())
        self.count_label = QLabel()
        self.count_label.setStyleSheet("color: gray;")
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addLayout(filters)
        left_layout.addWidget(self.browser, stretch=1)
        left_layout.addWidget(self.count_label)

        self.image = CardImage(width=250)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.finish_label = QLabel("Finish:")
        self.finish_box = QVBoxLayout()
        self.finish_group = QButtonGroup(self)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.image, stretch=1)
        right_layout.addWidget(self.details)
        right_layout.addWidget(self.finish_label)
        right_layout.addLayout(self.finish_box)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([740, 360])

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText(action)
        self.ok_button.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter, stretch=1)
        layout.addWidget(buttons)

        self._apply_filter()
        start = next((i for i, p in enumerate(self.browser.rows)
                      if current and p["scryfall_id"] == current[0]), 0)
        self.browser.select(start)

    def _apply_filter(self):
        needle = self.filter_input.text().strip().lower()
        rows = [p for p in self._all
                if (not needle or needle in f"{p['set_name']} {p['set_code']}".lower())
                and (p["owned"] or not self.owned_check.isChecked())]
        self.browser.set_rows(rows)
        self.count_label.setText(f"{len(rows)} of {len(self._all)} printings · double-click to choose")

    def _show(self, printing):
        self._current = printing
        self.ok_button.setEnabled(True)
        self.image.set_image_url(printing["image_url"])
        self.details.setText(
            f"<b>{printing['name']}</b><br>{printing['set_name']} ({printing['set_code']}) "
            f"#{printing['collector_number']}<br>{(printing['rarity'] or '').capitalize()}"
            f"<br>You own {printing['owned']} of this printing")
        for button in self.finish_group.buttons():
            self.finish_group.removeButton(button)
            self.finish_box.removeWidget(button)
            button.deleteLater()
        wanted = self._start[1] if self._start and self._start[0] == printing["scryfall_id"] else None
        for foil, price, owned in printing["finishes"]:
            button = QRadioButton(f"{FINISH_NAMES[foil]} · {money(price)}" + (f" · you own {owned}" if owned else ""))
            button.setProperty("foil", foil)
            self.finish_group.addButton(button)
            self.finish_box.addWidget(button)
            if foil == wanted or len(self.finish_group.buttons()) == 1:
                button.setChecked(True)

    def choice(self):
        # add_card-style record for the chosen printing and finish
        button = self.finish_group.checkedButton()
        foil = button.property("foil") if button else self._current["finishes"][0][0]
        price = next(price for f, price, _ in self._current["finishes"] if f == foil)
        return {**{key: self._current[key] for key in ("name", "scryfall_id", "set_code", "set_name",
                                                      "collector_number", "image_url")},
                "foil": foil, "price": price}
