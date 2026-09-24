"""
Finance window: follow card prices like a stock ticker (think MTGStocks) --
biggest spikes and drops over a period, for cards you pick or for every card.
"""

# Imports
from datetime import date

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSettings, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, QDoubleSpinBox, QTableView,
    QHeaderView, QAbstractItemView, QPushButton, QSplitter, QMessageBox, QDialog, QProgressDialog,
    QInputDialog,
)

import background
import database as db
import scryfall
import trends
from add_card_dialog import CardDialog
from card_image import CardImage
from charts import HistoryChart
from Functions import ScryFunctions as sf  # importable once scryfall has set up sys.path

BAREBONES, POPULATED = "barebones", "populated"

COLUMNS = ["Card", "Set", "#", "Finish", "Rarity", "Price", "Change", "Change %"]
(NAME_COL, SET_COL, NUMBER_COL, FINISH_COL, RARITY_COL, PRICE_COL, CHANGE_COL,
 PERCENT_COL) = range(len(COLUMNS))

SHOW_SPIKES, SHOW_DROPS, SHOW_ALL = "Biggest spikes", "Biggest drops", "Everything tracked"


def _settings():
    return QSettings("Multiversal Manager", "Multiversal Manager")


def watch_records(card, foil=None):
    # Watchlist records for a Scryfall printing: just `foil`'s finish, or every
    # finish it exists in when foil is None. ponytail: etched finishes are skipped,
    # the shared Card class has no usd_etched price yet.
    finishes = [f for f in (False, True) if ("foil" if f else "nonfoil") in card.finishes]
    return [{
        "scryfall_id": card.id,
        "foil": f,
        "name": card.name,
        "set_code": card.set,
        "set_name": card.set_name,
        "collector_number": card.collector_number,
        "rarity": card.rarity,
        "image_url": scryfall.image_url_for(card),
        "price": scryfall.price_for(card, f) or None,
    } for f in (finishes if foil is None else [foil])]


def change_for(row):
    # (each, percent) since the period's start, or None without a price then and now
    if not row["past"] or not row["price"]:
        return None
    each = row["price"] - row["past"]
    return each, each / row["past"] * 100


# Background work (runs on worker threads)

def _track_everything(last_updated, progress=None):
    # Downloads Scryfall's daily bulk file and tracks every paper printing. Returns
    # (bulk updated_at, printings written), or None when there's nothing newer.
    info = scryfall.bulk_info()
    if info is None or info["updated_at"] == last_updated:
        return None
    records = []
    for card in scryfall.iter_bulk_cards(info, progress):
        if not card.digital:
            records.extend(watch_records(card))
    return info["updated_at"], db.watch_cards(records)


def _refresh_watched(keys):
    # Refreshes the given (scryfall_id, foil) printings from Scryfall
    cards = scryfall.get_cards_by_id([sid for sid, _ in keys])
    return db.watch_cards([r for sid, foil in keys if sid in cards
                           for r in watch_records(cards[sid], bool(foil))])


def _track_set(code):
    cards = sf.search_cards_by_set(code)
    if not cards:
        raise LookupError(f"Scryfall has no set with the code {code.upper()}.")
    return db.watch_cards([r for card in cards if not card.digital for r in watch_records(card)])


def ask_mode(parent):
    # Asks how the Finance window should start out. Returns BAREBONES, POPULATED or None.
    box = QMessageBox(QMessageBox.Icon.Question, "Finance", "What should the Finance window track?",
                      parent=parent)
    box.setInformativeText(
        "<b>Start empty</b>: nothing is tracked until you add the cards, printings or sets you "
        "care about.<br><br>"
        "<b>Every card</b>: tracks every paper printing in Magic (about 100,000, foil and non-foil) "
        "so you can watch the whole market. Downloads Scryfall's card data (about 80 MB) once a day "
        "while the window is open, and the database grows as price history builds up.<br><br>"
        "Scryfall updates prices once a day. You can change this later with Tracking Mode."
    )
    empty = box.addButton("Start Empty", QMessageBox.ButtonRole.AcceptRole)
    everything = box.addButton("Track Every Card", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    return {empty: BAREBONES, everything: POPULATED}.get(box.clickedButton())


class WatchlistModel(QAbstractTableModel):
    """Every tracked printing, filtered and sorted in plain Python. Tracking every card
    means ~160k rows, and Qt's proxy models call back into Python millions of times
    to sort that many (half a minute); sorted() with a key takes a fraction of a second."""

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
                    "Foil" if row["foil"] else "", (row["rarity"] or "").capitalize()][column]
        if role == Qt.ItemDataRole.ForegroundRole and column >= CHANGE_COL and change:
            return trends.change_color(change[0])
        if role == Qt.ItemDataRole.TextAlignmentRole and column >= PRICE_COL:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.ToolTipRole and column >= CHANGE_COL:
            return f"${row['past']:,.2f} → ${row['price']:,.2f}" if change else "No price recorded that far back yet"
        return None


class FinanceWindow(QWidget):
    """Spikes, drops and price history for tracked printings. mode is BAREBONES
    (the user picks what to track) or POPULATED (every card, from Scryfall's bulk data)."""

    def __init__(self, mode, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Finance")
        self.resize(1280, 760)
        self.settings = _settings()
        self._busy = False
        self._progress = None

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter by card or set…")
        self.filter_input.setClearButtonEnabled(True)
        # Filtering ~150k rows takes a moment, so wait for a pause in typing
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
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(NAME_COL, QHeaderView.ResizeMode.Stretch)
        header.resizeSection(SET_COL, 260)
        self.table.selectionModel().selectionChanged.connect(self.show_selected)

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
        splitter.setSizes([900, 380])

        self.status_label = QLabel()
        self.status_label.setStyleSheet("color: gray;")
        self.track_button = QPushButton("Track Card…")
        self.track_button.clicked.connect(self.track_card)
        self.track_set_button = QPushButton("Track Set…")
        self.track_set_button.clicked.connect(self.track_set)
        self.remove_button = QPushButton("Stop Tracking")
        self.remove_button.clicked.connect(self.remove_selected)
        self.refresh_button = QPushButton("Refresh Prices")
        self.refresh_button.clicked.connect(lambda: self.refresh(force=True))
        mode_button = QPushButton("Tracking Mode…")
        mode_button.clicked.connect(self.change_mode)
        buttons = QHBoxLayout()
        buttons.addWidget(self.status_label, stretch=1)
        for button in (mode_button, self.refresh_button, self.remove_button, self.track_set_button,
                       self.track_button):
            buttons.addWidget(button)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(splitter, stretch=1)
        layout.addLayout(buttons)

        self.set_mode(mode)

    # Mode

    def set_mode(self, mode):
        self.mode = mode
        self.settings.setValue("finance_mode", mode)
        barebones = mode == BAREBONES
        for button in (self.track_button, self.track_set_button, self.remove_button):
            button.setVisible(barebones)
        # Every card includes thousands of penny cards; start past them
        self.min_price.setValue(0.0 if barebones else 1.0)
        self.load()
        if barebones and not self.model.all_rows:
            self.show_combo.setCurrentText(SHOW_ALL)
        self.refresh()

    def change_mode(self):
        mode = ask_mode(self)
        if mode is None or mode == self.mode:
            return
        if mode == BAREBONES:
            answer = QMessageBox.question(
                self, "Finance", "Stop tracking every card and start with an empty list?\n\n"
                "Price history already recorded is kept.")
            if answer != QMessageBox.StandardButton.Yes:
                return
            db.clear_watchlist()
        self.settings.remove("finance_bulk_updated")
        self.set_mode(mode)

    # Table

    def period_days(self):
        return dict(trends.PERIODS)[self.period_combo.currentText()]

    def load(self):
        self.model.set_rows(db.get_watchlist(self.period_days()))
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
        total, shown = len(self.model.all_rows), self.model.rowCount()
        if message is None:
            message = (f"Showing {shown:,} of {total:,} tracked printings. Scryfall updates prices once a day."
                       if total or self.mode == POPULATED
                       else "Nothing tracked yet. Use Track Card… or Track Set… to add some.")
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
        self.card_image.set_image_url(row["image_url"])
        self.detail_name.setText(f"{row['name']}{'  ✦ Foil' if row['foil'] else ''}\n"
                                 f"{row['set_name']} ({row['set_code']}) #{row['collector_number']}")
        history = db.get_price_history(row["scryfall_id"], row["foil"])
        # History only stores price changes, so carry the current price up to today
        today = date.today().isoformat()
        if row["price"] and (not history or history[-1][0] != today):
            history.append((today, row["price"]))
        self.price_chart.set_points(history, "Scryfall has no price for this printing.")
        self.price_chart.chart.setTitle("Price history")

    # Tracking

    def track_card(self):
        dialog = CardDialog(self, watch=True)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        picker = dialog.picker
        if dialog.all_printings_check.isChecked():
            records = [r for card in picker.printings() for r in watch_records(card)]
        else:
            records = watch_records(picker.selected_printing(), picker.is_foil())
        db.watch_cards(records)
        self.load()
        self.update_status(f"Now tracking {len(records):,} more printing{'s' if len(records) != 1 else ''}.")

    def track_set(self):
        code, ok = QInputDialog.getText(self, "Track Set", "Set code (e.g. BLB, MH3, LEA):")
        if ok and code.strip():
            self._start(f"Looking up set {code.strip().upper()}…", _track_set, code.strip())

    def remove_selected(self):
        rows = self.selected_rows()
        if rows:
            db.unwatch((row["scryfall_id"], row["foil"]) for row in rows)
            self.load()

    # Refreshing prices

    def refresh(self, force=False):
        if self._busy:
            return
        if self.mode == POPULATED:
            last = None if force else self.settings.value("finance_bulk_updated")
            self._progress = QProgressDialog("Downloading every card's price from Scryfall…", None, 0, 100, self)
            self._progress.setWindowTitle("Finance")
            self._progress.setMinimumDuration(1500)
            self._start("Checking Scryfall for new prices…", _track_everything, last, progress=True)
            return
        # Scryfall only updates once a day, so only prices from before today are refreshed
        today = date.today().isoformat()
        stale = [(row["scryfall_id"], row["foil"]) for row, _ in self.model.all_rows
                 if force or not row["price_updated"] or row["price_updated"][:10] < today]
        if stale:
            self._start(f"Refreshing {len(stale):,} prices…", _refresh_watched, stale)

    def _start(self, message, fn, *args, progress=False):
        if self._busy:
            return
        self._busy = True
        self.refresh_button.setEnabled(False)
        self.update_status(message)
        background.run(fn, *args, on_success=self._on_done, on_error=self._on_failed,
                       on_progress=self._on_progress if progress else None)

    def _on_progress(self, value):
        done, total = value
        if self._progress is not None:
            self._progress.setValue(min(99, done * 100 // max(total, 1)))

    def _finish(self):
        self._busy = False
        self.refresh_button.setEnabled(True)
        if self._progress is not None:
            self._progress.close()
            self._progress = None

    def _on_done(self, result):
        self._finish()
        if isinstance(result, tuple):  # bulk download: (updated_at, printings written)
            self.settings.setValue("finance_bulk_updated", result[0])
        self.load()
        if result is None:
            self.update_status("Prices are already up to date. Scryfall updates them once a day.")

    def _on_failed(self, message):
        self._finish()
        self.update_status(f"Couldn't update from Scryfall: {message}")
