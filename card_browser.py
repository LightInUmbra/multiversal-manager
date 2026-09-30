"""
Cards shown two ways: a grid of card images (standard mode) or a plain table
(lightweight mode, which downloads no images). Used by the deck builder's card
list and by the printing picker.
"""

# Imports
from collections import OrderedDict

from PySide6.QtCore import Qt, QSize, QAbstractListModel, QModelIndex, QRect, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QStackedWidget, QListView, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QDialog,
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox, QRadioButton, QButtonGroup, QDialogButtonBox,
    QSplitter, QWidget,
)

import background
import card_image
from card_image import CardImage

THUMB_SIZE = QSize(146, 204)   # grid thumbnails: Scryfall's "small" images, at their own size
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

    def __init__(self, caption, tooltip, parent=None, size=THUMB_SIZE):
        super().__init__(parent)
        self.rows = []
        self._caption, self._tooltip = caption, tooltip
        self._size = size
        self._thumbs = OrderedDict()   # url -> QPixmap, least recently used first
        self._loading = set()
        self._rows_by_url = {}
        self._placeholder = QPixmap(size)
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
            pixmap = pixmap.scaled(self._size, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
        else:
            pixmap = self._placeholder  # remembered, so a missing image isn't retried endlessly
        self._thumbs[url] = pixmap
        while len(self._thumbs) > THUMB_CACHE_SIZE:
            self._thumbs.popitem(last=False)
        for row in self._rows_by_url.get(url, []):
            index = self.index(row)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole])


class _StretchGrid(QListView):
    """An icon grid whose columns share the spare width, so there's no empty strip on
    the right when the view is a little narrower than one more column."""

    def __init__(self, cell):
        super().__init__()
        self._cell = cell  # the smallest a grid cell can be

    def resizeEvent(self, event):
        # Also runs when the viewport resizes (a scrollbar showing or hiding)
        width = self.viewport().width() - 4
        columns = max(1, width // self._cell.width())
        size = QSize(max(self._cell.width(), width // columns), self._cell.height())
        if size != self.gridSize():
            self.setGridSize(size)
        super().resizeEvent(event)


class CardBrowser(QStackedWidget):
    """A list of cards as an image grid or, in lightweight mode, a table.
    columns: [(header, fn(row) -> text or (text, color))] for the table;
    caption / tooltip: as for CardGridModel (caption_lines tall under thumbnails of
    thumb_size). Emits the row that was selected, double-clicked (activated) or
    right-clicked (menu_requested)."""

    selected = Signal(object)
    activated = Signal(object)
    menu_requested = Signal(object)

    def __init__(self, columns, caption, tooltip, parent=None, thumb_size=THUMB_SIZE, caption_lines=1):
        super().__init__(parent)
        self.rows = []
        self.lightweight = False
        self._columns, self._tooltip = columns, tooltip

        self.grid_model = CardGridModel(caption, tooltip, self, thumb_size)
        cell = QSize(thumb_size.width() + 12, thumb_size.height() + 12 + 14 * caption_lines)
        self.grid = _StretchGrid(cell)
        self.grid.setModel(self.grid_model)
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setIconSize(thumb_size)
        self.grid.setGridSize(cell)
        self.grid.setWordWrap(caption_lines > 1)
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


class DeckCanvas(QWidget):
    """A deck's groups drawn as card images: "Grid" (rows under each heading) or "Stacks" (a
    column of overlapping cards per group, the hovered one lifted). Lightweight mode draws
    name placeholders and downloads nothing. Emits the entry id clicked or right-clicked;
    selected (a set of ids) gets a highlight. Goes in a QScrollArea."""

    clicked = Signal(int)
    menu_requested = Signal(int)

    GAP, HEADING, STEP = 10, 26, 30  # STEP: how much of each card a stack leaves showing

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.groups, self.mode, self.lightweight, self.selected = [], "Grid", False, set()
        self._cards, self._headings, self._hover = [], [], None  # [(QRect, entry)], [(QRect, text)], index
        self._thumbs, self._loading = {}, set()

    def show_groups(self, groups, mode, lightweight):
        self.groups, self.mode, self.lightweight, self._hover = groups, mode, lightweight, None
        self._place()

    def _place(self):
        size, gap = THUMB_SIZE, self.GAP
        width = max(size.width() + 2 * gap, self.width())
        self._cards, self._headings = [], []
        x = y = bottom = gap
        for title, entries in self.groups:
            heading = f"{title} ({sum(e['quantity'] for e in entries)})"
            if self.mode == "Stacks":
                if x + size.width() > width and x > gap:  # the next column wraps below
                    x, y = gap, bottom + gap
                self._headings.append((QRect(x, y, size.width(), self.HEADING), heading))
                top = y + self.HEADING
                for i, entry in enumerate(entries):
                    self._cards.append((QRect(x, top + i * self.STEP, size.width(), size.height()), entry))
                bottom = max(bottom, top + max(len(entries) - 1, 0) * self.STEP + size.height())
                x += size.width() + gap
            else:
                self._headings.append((QRect(gap, y, width - 2 * gap, self.HEADING), heading))
                y += self.HEADING
                per_row = max(1, (width - gap) // (size.width() + gap))
                for i, entry in enumerate(entries):
                    row, column = divmod(i, per_row)
                    self._cards.append((QRect(gap + column * (size.width() + gap),
                                              y + row * (size.height() + gap), size.width(), size.height()), entry))
                y += -(-len(entries) // per_row) * (size.height() + gap) + gap
                bottom = y
        self.setMinimumHeight(bottom + gap)
        self.update()

    def resizeEvent(self, event):
        if event.size().width() != event.oldSize().width():
            self._place()
        super().resizeEvent(event)

    def _thumb(self, url):
        if self.lightweight or not url:
            return None
        if url not in self._thumbs and url not in self._loading:
            self._loading.add(url)
            background.run(card_image._fetch, url, on_success=self._loaded)
        return self._thumbs.get(url)

    def _loaded(self, result):
        url, data = result
        self._loading.discard(url)
        pixmap = QPixmap()
        # A missing image is remembered as None, so it isn't retried
        self._thumbs[url] = pixmap.scaled(THUMB_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation) \
            if data and pixmap.loadFromData(data) else None
        self.update()

    def _rect(self, index):
        rect = self._cards[index][0]
        return rect.translated(0, -12) if index == self._hover and self.mode == "Stacks" else rect

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self.palette().text().color())
        for rect, text in self._headings:
            text = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
            painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        # The hovered card is drawn last, so it's on top of its stack
        order = [i for i in range(len(self._cards)) if i != self._hover] + (
            [self._hover] if self._hover is not None else [])
        visible = event.rect().adjusted(0, -40, 0, 40)
        for i in order:
            rect, entry = self._rect(i), self._cards[i][1]
            if not rect.intersects(visible):
                continue
            pixmap = self._thumb(thumb_url(entry["image_url"]))
            if pixmap is not None:
                painter.drawPixmap(rect.topLeft(), pixmap)
            else:
                painter.setPen(QPen(MUTED_COLOR))
                painter.setBrush(self.palette().base())
                painter.drawRoundedRect(rect, 8, 8)
                painter.setPen(self.palette().text().color())
                painter.drawText(rect.adjusted(8, 6, -8, -6), Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                                 entry["name"])
            if entry["quantity"] > 1:
                badge = QRect(rect.right() - 38, rect.top() + 6, 32, 18)  # on the name bar, which a stack shows
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 0, 0, 190))
                painter.drawRoundedRect(badge, 9, 9)
                painter.setPen(QColor("white"))
                painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, f"×{entry['quantity']}")
            if entry["id"] in self.selected:
                painter.setPen(QPen(self.palette().highlight().color(), 3))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 8, 8)

    def _at(self, pos):
        # The card on top at pos (the hovered one first, as it's drawn last)
        if self._hover is not None and self._rect(self._hover).contains(pos):
            return self._hover
        return next((i for i in reversed(range(len(self._cards))) if self._rect(i).contains(pos)), None)

    def mouseMoveEvent(self, event):
        index = self._at(event.position().toPoint())
        if index != self._hover:
            self._hover = index
            self.setToolTip(self._cards[index][1]["name"] if index is not None else "")
            self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()

    def mousePressEvent(self, event):
        index = self._at(event.position().toPoint())
        if index is not None and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._cards[index][1]["id"])

    def contextMenuEvent(self, event):
        index = self._at(event.pos())
        if index is not None:
            self.menu_requested.emit(self._cards[index][1]["id"])
