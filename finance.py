"""
Finance window: follow card prices like a stock ticker (think MTGStocks) --
biggest spikes and drops over a period, across every card or just the ones you pick.

Both modes keep the full list of paper printings (from Scryfall's daily bulk data)
and 90 days of back history (from MTGJSON); the mode only decides what's listed.
"""

# Imports
from datetime import date, timedelta

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSettings, QTimer
from PySide6.QtGui import QAction, QCursor, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, QDoubleSpinBox, QTableView,
    QHeaderView, QAbstractItemView, QPushButton, QSplitter, QMessageBox, QDialog, QDialogButtonBox,
    QProgressBar, QMenu,
)

import background
import database as db
import mtgjson
import scryfall
import trends
from card_image import CardImage
from charts import HistoryChart

BAREBONES, POPULATED = "barebones", "populated"

COLUMNS = ["Card", "Set", "#", "Finish", "Rarity", "Price", "Change", "Change %"]
(NAME_COL, SET_COL, NUMBER_COL, FINISH_COL, RARITY_COL, PRICE_COL, CHANGE_COL,
 PERCENT_COL) = range(len(COLUMNS))

SHOW_SPIKES, SHOW_DROPS, SHOW_ALL = "Biggest spikes", "Biggest drops", "Everything"

# Scryfall finish -> (foil code stored with prices, Scryfall price key)
FINISHES = {"nonfoil": (0, "usd"), "foil": (1, "usd_foil"), "etched": (2, "usd_etched")}
FINISH_LABELS = {0: "", 1: "Foil", 2: "Etched"}

# MTGJSON's history is re-read this often, filling in days the app wasn't opened
BACKFILL_EVERY = timedelta(days=7)


def _settings():
    return QSettings("Multiversal Manager", "Multiversal Manager")


def _printings(n):
    return f"{n:,} printing{'s' if n != 1 else ''}"


def watch_records(data):
    # Watchlist records for a raw Scryfall card dict, one per finish it's printed in
    prices = data.get("prices") or {}
    card = scryfall.Card(data)
    return [{
        "scryfall_id": card.id,
        "foil": code,
        "name": card.name,
        "set_code": card.set,
        "set_name": card.set_name,
        "collector_number": card.collector_number,
        "rarity": card.rarity,
        "image_url": scryfall.image_url_for(card),
        "price": float(prices[key]) if prices.get(key) else None,
    } for finish, (code, key) in FINISHES.items() if finish in card.finishes]


def change_for(row):
    # (each, percent) since the period's start, or None without a price then and now
    if not row["past"] or not row["price"]:
        return None
    each = row["price"] - row["past"]
    return each, each / row["past"] * 100


def backfill_due(last_backfill, today=None):
    today = today or date.today()
    return not last_backfill or date.fromisoformat(last_backfill) + BACKFILL_EVERY <= today


# Background work (runs on a worker thread)

def update_market(last_bulk, last_backfill, track_new=False, progress=None):
    """Brings the card list and prices up to date: Scryfall's bulk file when it has a
    newer one, and MTGJSON's 90 days of history when a backfill is due. New printings
    are tracked if track_new. Returns {"bulk": updated_at, "backfill": day} for the
    steps that ran."""
    done = {}

    def step(label):
        return (lambda value: progress((label, *value))) if progress else None

    info = scryfall.bulk_info()
    if info is not None and info["updated_at"] != last_bulk:
        records = []
        for data in scryfall.iter_bulk_data(info, step("Downloading every card's price from Scryfall…")):
            if not data.get("digital"):
                records.extend(watch_records(data))
        db.watch_cards(records, track_new)
        done["bulk"] = info["updated_at"]
    if backfill_due(last_backfill):
        db.add_price_history(mtgjson.price_history(step("Downloading 90 days of price history from MTGJSON…")))
        done["backfill"] = date.today().isoformat()
    return done


def ask_mode(parent):
    # Asks how the Finance window should start out. Returns BAREBONES, POPULATED or None.
    box = QMessageBox(QMessageBox.Icon.Question, "Finance", "What should the Finance window track?",
                      parent=parent)
    box.setInformativeText(
        "<b>Track every card</b>: every paper printing and finish in Magic (about 160,000) is "
        "listed and tracked, so you can watch the whole market. New printings are added as "
        "they come out.<br><br>"
        "<b>Start empty</b>: the same card database is loaded, but nothing is listed until you "
        "pick the cards, printings, sets or finishes you want to follow.<br><br>"
        "Either way you can add or remove cards whenever you like.<br><br>"
        "Either way, the first open downloads Scryfall's card data (about 80 MB) and 90 days of "
        "price history from MTGJSON (about 60 MB). That takes a few minutes and adds a few "
        "hundred MB to the database. After that, prices update once a day, as often as Scryfall "
        "publishes them. You can switch modes later with Tracking Mode…"
    )
    everything = box.addButton("Track Every Card", QMessageBox.ButtonRole.AcceptRole)
    empty = box.addButton("Start Empty", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    return {empty: BAREBONES, everything: POPULATED}.get(box.clickedButton())


class WatchlistModel(QAbstractTableModel):
    """Printings, filtered and sorted in plain Python. Every card means ~160k rows,
    and Qt's proxy models call back into Python millions of times to sort that
    many (half a minute); sorted() with a key takes a fraction of a second."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.all_rows = []  # (sqlite3.Row from db.get_watchlist, change_for(row))
        self.rows = []      # the filtered, sorted subset on screen
        self.text, self.min_price, self.show = "", 0.0, SHOW_ALL
        self.sort_column, self.sort_order = NAME_COL, Qt.SortOrder.AscendingOrder

    def set_rows(self, rows):
        self.all_rows = [(row, change_for(row)) for row in rows]
        self._update()

    def set_filter(self, text, min_price, show):
        self.text, self.min_price, self.show = text.strip().lower(), min_price, show
        self._update()

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        # Called by the view when a header is clicked
        self.sort_column, self.sort_order = column, order
        self._update()

    def _accepts(self, entry):
        row, change = entry
        if (row["price"] or 0.0) < self.min_price:
            return False
        if self.show == SHOW_SPIKES and (change is None or change[0] <= 0.004):
            return False
        if self.show == SHOW_DROPS and (change is None or change[0] >= -0.004):
            return False
        return not self.text or self.text in f"{row['name']} {row['set_name']} {row['set_code']}".lower()

    def _sort_key(self, entry):
        row, change = entry
        column = self.sort_column
        if column >= CHANGE_COL:
            return change[column - CHANGE_COL] if change else 0.0
        if column == PRICE_COL:
            return row["price"] or 0.0
        if column == NUMBER_COL:
            number = row["collector_number"] or ""
            return (int(number) if number.isdigit() else 0, number)
        if column == FINISH_COL:
            return row["foil"]
        return (row[["name", "set_name", "", "", "rarity"][column]] or "").casefold()

    def _update(self):
        self.beginResetModel()
        self.rows = sorted(filter(self._accepts, self.all_rows), key=self._sort_key,
                           reverse=self.sort_order == Qt.SortOrder.DescendingOrder)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        row, change = self.rows[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == PRICE_COL:
                return f"${row['price']:,.2f}" if row["price"] else "—"
            if column == CHANGE_COL:
                return trends.format_change(change[0]) if change else ""
            if column == PERCENT_COL:
                return f"{'+' if change[1] >= 0 else '−'}{abs(change[1]):.1f}%" if change else ""
            return [row["name"], f"{row['set_name']} ({row['set_code']})", row["collector_number"],
                    FINISH_LABELS[row["foil"]], (row["rarity"] or "").capitalize()][column]
        if role == Qt.ItemDataRole.ForegroundRole and column >= CHANGE_COL and change:
            return trends.change_color(change[0])
        if role == Qt.ItemDataRole.TextAlignmentRole and column >= PRICE_COL:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.ToolTipRole and column >= CHANGE_COL:
            return f"${row['past']:,.2f} → ${row['price']:,.2f}" if change else "No price recorded that far back"
        if role == Qt.ItemDataRole.ToolTipRole and column in (NAME_COL, SET_COL):
            return self.data(index)
        return None


def _table(model):
    table = QTableView()
    table.setModel(model)
    table.setSortingEnabled(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    # The small columns get fixed widths so the card name gets the rest of the room.
    # (Resize-to-contents would measure all ~160k rows.) Full names are in the tooltip.
    header = table.horizontalHeader()
    for column, width in ((SET_COL, 200), (NUMBER_COL, 50), (FINISH_COL, 60), (RARITY_COL, 75),
                          (PRICE_COL, 80), (CHANGE_COL, 95), (PERCENT_COL, 80)):
        header.resizeSection(column, width)
    header.setSectionResizeMode(NAME_COL, QHeaderView.ResizeMode.Stretch)
    return table


class TrackDialog(QDialog):
    """Pick printings to track from the local card list: filter by card or set, then
    track the selected rows or everything shown (every printing of a card, a whole set…)."""

    def __init__(self, rows, text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Track Cards")
        self.resize(1100, 640)
        self.model = WatchlistModel(self)
        self.model.set_rows(rows)
        self.model.set_filter(text, 0.0, SHOW_ALL)

        self.filter_input = QLineEdit(text)
        self.filter_input.setPlaceholderText("Card name, set name or set code…")
        self.filter_input.setClearButtonEnabled(True)
        timer = QTimer(self, singleShot=True, interval=250)
        timer.timeout.connect(lambda: self.model.set_filter(self.filter_input.text(), 0.0, SHOW_ALL))
        self.filter_input.textChanged.connect(lambda _: timer.start())
        self.table = _table(self.model)
        self.table.doubleClicked.connect(self.accept)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Track Selected", QDialogButtonBox.ButtonRole.AcceptRole)
        track_all = buttons.addButton("Track All Shown", QDialogButtonBox.ButtonRole.ActionRole)
        track_all.clicked.connect(self.track_all_shown)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.filter_input)
        layout.addWidget(self.table)
        layout.addWidget(buttons)

    def track_all_shown(self):
        self.table.selectAll()
        self.accept()

    def keys(self):
        # (scryfall_id, foil) of the chosen printings
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        return [(self.model.rows[r][0]["scryfall_id"], self.model.rows[r][0]["foil"]) for r in rows]


class FinanceWindow(QWidget):
    """Spikes, drops and price history for tracked printings. mode is POPULATED (starts
    with every printing tracked, and tracks new ones as they come out) or BAREBONES
    (starts empty). Either way the user can track or remove printings at any time."""

    def __init__(self, mode, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Finance")
        self.resize(1280, 760)
        self.settings = _settings()
        self._busy = False

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter by card or set…")
        self.filter_input.setClearButtonEnabled(True)
        # Filtering ~160k rows takes a moment, so wait for a pause in typing
        self._filter_timer = QTimer(self, singleShot=True, interval=250)
        self._filter_timer.timeout.connect(self.apply_filter)
        self.filter_input.textChanged.connect(lambda _: self._filter_timer.start())

        self.show_combo = QComboBox()
        self.show_combo.addItems([SHOW_SPIKES, SHOW_DROPS, SHOW_ALL])
        self.show_combo.currentTextChanged.connect(self.on_show_changed)
        self.period_combo = QComboBox()
        for label, _ in trends.PERIODS:
            self.period_combo.addItem(label)
        self.period_combo.setCurrentText(self.settings.value("finance_period", trends.DEFAULT_PERIOD))
        self.period_combo.currentTextChanged.connect(self.on_period_changed)
        self.min_price = QDoubleSpinBox()
        self.min_price.setPrefix("$")
        self.min_price.setMaximum(100000.00)
        self.min_price.setToolTip("Hide cheaper cards, so bulk commons going from 5¢ to 10¢ don't swamp the spikes")
        self.min_price.valueChanged.connect(lambda _: self._filter_timer.start())

        top = QHBoxLayout()
        top.addWidget(self.filter_input, stretch=1)
        top.addWidget(QLabel("Show:"))
        top.addWidget(self.show_combo)
        top.addWidget(QLabel("Change over:"))
        top.addWidget(self.period_combo)
        top.addWidget(QLabel("Min price:"))
        top.addWidget(self.min_price)

        self.model = WatchlistModel(self)
        self.table = _table(self.model)
        self.table.selectionModel().selectionChanged.connect(self.show_selected)
        # Delete key and right-click work like the collection table
        remove_action = QAction("Remove", self.table, shortcut=QKeySequence.StandardKey.Delete)
        remove_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        remove_action.triggered.connect(self.remove_selected)
        self.table.addAction(remove_action)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        self.card_image = CardImage()
        self.detail_name = QLabel()
        self.detail_name.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.detail_name.setWordWrap(True)
        self.price_chart = HistoryChart(min_height=180)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.addWidget(self.card_image, stretch=1)
        detail_layout.addWidget(self.detail_name)
        detail_layout.addWidget(self.price_chart)

        splitter = QSplitter()
        splitter.addWidget(self.table)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([960, 320])

        self.status_label = QLabel()
        self.status_label.setStyleSheet("color: gray;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(240)
        self.progress_bar.hide()
        self.track_button = QPushButton("Track Cards…")
        self.track_button.setToolTip("Add cards, printings, finishes or whole sets")
        self.track_button.clicked.connect(lambda: self.track_cards())
        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.setToolTip("Stop tracking the selected printings (or press Delete, or right-click)")
        self.remove_button.clicked.connect(self.remove_selected)
        self.refresh_button = QPushButton("Refresh Prices")
        self.refresh_button.clicked.connect(self.refresh)
        mode_button = QPushButton("Tracking Mode…")
        mode_button.clicked.connect(self.change_mode)
        buttons = QHBoxLayout()
        buttons.addWidget(self.status_label, stretch=1)
        buttons.addWidget(self.progress_bar)
        for button in (mode_button, self.refresh_button, self.remove_button, self.track_button):
            buttons.addWidget(button)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(splitter, stretch=1)
        layout.addLayout(buttons)

        self.set_mode(mode)
        self.refresh()

    # Mode

    def set_mode(self, mode):
        self.mode = mode
        self.settings.setValue("finance_mode", mode)
        # Track Every Card starts with everything tracked; after that, removals stick
        if mode == POPULATED and not self.settings.value("finance_all_tracked"):
            db.track_all()
            self.settings.setValue("finance_all_tracked", True)
        # Every card includes thousands of penny cards; start past them
        self.min_price.setValue(0.0 if mode == BAREBONES else 1.0)
        self.load()

    def change_mode(self):
        mode = ask_mode(self)
        if mode is None or mode == self.mode:
            return
        if mode == BAREBONES:
            answer = QMessageBox.question(
                self, "Finance", "Start with an empty list? Cards you track from now on are listed "
                "here; the card database and price history are kept.")
            if answer != QMessageBox.StandardButton.Yes:
                return
            db.untrack_all()
            self.settings.remove("finance_all_tracked")
        self.set_mode(mode)

    # Table

    def period_days(self):
        return dict(trends.PERIODS)[self.period_combo.currentText()]

    def load(self):
        self.model.set_rows(db.get_watchlist(self.period_days(), tracked_only=True))
        self.on_show_changed(self.show_combo.currentText())

    def apply_filter(self):
        self.model.set_filter(self.filter_input.text(), self.min_price.value(), self.show_combo.currentText())
        self.update_status()

    def on_show_changed(self, show):
        # Spikes list the biggest % gain first, drops the biggest % loss
        if show == SHOW_SPIKES:
            self.table.sortByColumn(PERCENT_COL, Qt.SortOrder.DescendingOrder)
        elif show == SHOW_DROPS:
            self.table.sortByColumn(PERCENT_COL, Qt.SortOrder.AscendingOrder)
        self.apply_filter()

    def on_period_changed(self, label):
        self.settings.setValue("finance_period", label)
        self.load()

    def update_status(self, message=None):
        # While prices are downloading the status line shows progress instead
        if message is None and self._busy:
            return
        if message is None:
            total, shown = len(self.model.all_rows), self.model.rowCount()
            message = (f"Showing {shown:,} of {total:,} tracked printings. Prices update once a day."
                       if total else "Nothing tracked yet. Use Track Cards… to pick cards, printings or sets.")
        self.status_label.setText(message)

    def selected_rows(self):
        return [self.model.rows[index.row()][0] for index in self.table.selectionModel().selectedRows()]

    def show_selected(self):
        rows = self.selected_rows()
        if len(rows) != 1:
            self.card_image.clear_image(f"{len(rows)} cards selected" if rows else "No card selected")
            self.detail_name.setText("")
            self.price_chart.show_message("")
            return
        row = rows[0]
        finish = FINISH_LABELS[row["foil"]]
        self.card_image.set_image_url(row["image_url"])
        self.detail_name.setText(f"{row['name']}{f'  ✦ {finish}' if finish else ''}\n"
                                 f"{row['set_name']} ({row['set_code']}) #{row['collector_number']}")
        history = db.get_price_history(row["scryfall_id"], row["foil"])
        # History only stores price changes, so carry the current price up to today
        today = date.today().isoformat()
        if row["price"] and (not history or history[-1][0] != today):
            history.append((today, row["price"]))
        self.price_chart.set_points(history, "No price for this printing.")
        self.price_chart.chart.setTitle("Price history")

    # Tracking

    def track_cards(self, text=""):
        untracked = [row for row in db.get_watchlist(self.period_days()) if not row["tracked"]]
        dialog = TrackDialog(untracked, text, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        keys = dialog.keys()
        db.track(keys)
        self.load()
        self.update_status(f"Now tracking {_printings(len(keys))} more.")

    def show_context_menu(self, position):
        # Right-clicking a row that isn't part of the selection selects just that row
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        if not self.table.selectionModel().isRowSelected(index.row()):
            self.table.selectRow(index.row())
        count = len(self.selected_rows())
        row = self.model.rows[index.row()][0]
        menu = QMenu(self)
        menu.addAction("Remove" if count == 1 else f"Remove {_printings(count)}", self.remove_selected)
        menu.addAction(f"Remove every card from {row['set_name']}", lambda: self.remove_set(row["set_code"]))
        menu.addSeparator()
        menu.addAction(f"Track other printings or finishes of {row['name']}…",
                       lambda: self.track_cards(row["name"]))
        menu.exec(QCursor.pos())

    def remove_selected(self):
        rows = self.selected_rows()
        if len(rows) == 1:
            finish = FINISH_LABELS[rows[0]["foil"]]
            what = f"{rows[0]['name']} ({rows[0]['set_code']}{f', {finish.lower()}' if finish else ''})"
        else:
            what = _printings(len(rows))
        self._untrack(rows, what)

    def remove_set(self, set_code):
        rows = [row for row, _ in self.model.all_rows if row["set_code"] == set_code]
        self._untrack(rows, f"all {_printings(len(rows))} from {rows[0]['set_name']}" if rows else "")

    def _untrack(self, rows, what):
        if not rows:
            return
        answer = QMessageBox.question(
            self, "Remove", f"Stop tracking {what}?\n\n"
            "Price history is kept, and you can add them back with Track Cards…")
        if answer != QMessageBox.StandardButton.Yes:
            return
        db.untrack((row["scryfall_id"], row["foil"]) for row in rows)
        self.load()
        self.update_status(f"Stopped tracking {_printings(len(rows))}.")

    # Updating prices

    def refresh(self):
        if self._busy:
            return
        self._busy = True
        for button in (self.refresh_button, self.track_button):
            button.setEnabled(False)
        self.status_label.setText("Checking for new prices…")
        background.run(update_market, self.settings.value("finance_bulk_updated"),
                       self.settings.value("finance_backfilled"), self.mode == POPULATED,
                       on_success=self._on_updated, on_error=self._on_failed, on_progress=self._on_progress)

    def _on_progress(self, value):
        label, done, total = value
        self.status_label.setText(label)
        self.progress_bar.show()
        self.progress_bar.setValue(min(99, done * 100 // max(total, 1)))

    def _finish(self):
        self._busy = False
        self.progress_bar.hide()
        for button in (self.refresh_button, self.track_button):
            button.setEnabled(True)

    def _on_updated(self, done):
        self._finish()
        if "bulk" in done:
            self.settings.setValue("finance_bulk_updated", done["bulk"])
        if "backfill" in done:
            self.settings.setValue("finance_backfilled", done["backfill"])
        if done:
            self.load()
        else:
            self.update_status("Prices are up to date. Scryfall publishes new ones once a day.")

    def _on_failed(self, message):
        self._finish()
        self.update_status(f"Couldn't update prices: {message}")
