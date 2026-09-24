# Imports
import csv
import sys
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt, QItemSelectionModel, QTimer, QUrl
from PySide6.QtGui import QAction, QCursor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QDialog, QLineEdit, QLabel,
    QSplitter, QHeaderView, QStyledItemDelegate, QMessageBox, QFileDialog, QAbstractItemView,
    QProgressDialog, QMenu,
)

import background
import database as db
import importer
import scryfall
from add_card_dialog import CardDialog
from import_review_dialog import ImportReviewDialog
from card_image import CardImage

# Constants
APP_NAME = "Multiversal Manager"

FAN_CONTENT_NOTICE = (
    "Multiversal Manager is unofficial Fan Content permitted under the Fan Content Policy. "
    "Not approved/endorsed by Wizards. Portions of the materials used are property of "
    "Wizards of the Coast. ©Wizards of the Coast LLC."
)
SCRYFALL_NOTICE = "Card data, prices and images provided by Scryfall (scryfall.com)."

# Scryfall updates prices about once a day, so anything older is refreshed on startup
PRICE_MAX_AGE = timedelta(hours=24)

COLUMNS = ["Name", "Set", "#", "Finish", "Qty", "Price", "Total"]
NAME_COL, SET_COL, NUMBER_COL, FINISH_COL, QTY_COL, PRICE_COL, TOTAL_COL = range(len(COLUMNS))

ID_ROLE = Qt.ItemDataRole.UserRole          # database id, stored on the Name cell


def _item(value, align_right=False):
    # Cells hold raw values (numbers stay numbers) so Qt's built-in sorting orders
    # them correctly; MoneyDelegate handles the "$" formatting for display.
    # (Overriding __lt__ in a Python QTableWidgetItem subclass crashes PySide
    # when the table re-sorts after items are replaced.)
    item = QTableWidgetItem()
    item.setData(Qt.ItemDataRole.DisplayRole, value)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if align_right:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


def _count(n, word):
    # "1 entry", "3 entries", "1,204 cards"
    plural = word[:-1] + "ies" if word.endswith("y") else word + "s"
    return f"{n:,} {word if n == 1 else plural}"


def _money(value):
    # Scryfall has no price for some printings; show that as a dash rather than $0.00
    return f"${value:,.2f}" if value else "—"


class MoneyDelegate(QStyledItemDelegate):
    def displayText(self, value, locale):
        return _money(value)


def _price_is_stale(row):
    if not row["scryfall_id"]:
        return False
    if not row["price_updated"]:
        return True
    updated = datetime.fromisoformat(row["price_updated"])
    return datetime.now(timezone.utc) - updated > PRICE_MAX_AGE


def _fetch_prices(rows):
    # rows: list of (card_id, scryfall_id, foil). Returns (updates, missing_count).
    cards = scryfall.get_cards_by_id([scryfall_id for _, scryfall_id, _ in rows])
    updates, missing = [], 0
    for card_id, scryfall_id, foil in rows:
        card = cards.get(scryfall_id)
        if card is None:
            missing += 1
            continue
        updates.append((card_id, scryfall.price_for(card, foil)))
    return updates, missing


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 720)
        self._rows_by_id = {}
        self._refreshing = False
        self._quiet_refresh = False

        self._build_menu()

        # Filter box
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter by name, set, or artist…")
        self.filter_input.setClearButtonEnabled(True)
        self.filter_input.textChanged.connect(self.apply_filter)

        # Collection table
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(NAME_COL, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(SET_COL, QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(True)
        money_delegate = MoneyDelegate(self.table)
        self.table.setItemDelegateForColumn(PRICE_COL, money_delegate)
        self.table.setItemDelegateForColumn(TOTAL_COL, money_delegate)
        self.table.sortByColumn(NAME_COL, Qt.SortOrder.AscendingOrder)
        self.table.itemSelectionChanged.connect(self.show_selected_card)
        self.table.itemChanged.connect(self.on_item_changed)
        # Delete key removes the selected rows, but only while the table has focus
        remove_action = QAction("Remove Selected", self.table, shortcut=QKeySequence.StandardKey.Delete)
        remove_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        remove_action.triggered.connect(self.on_remove_selected_clicked)
        self.table.addAction(remove_action)
        # Right-click menu, and double-click anywhere but Qty (edited in place) opens Edit
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.cellDoubleClicked.connect(
            lambda row, column: self.edit_card(self.table.item(row, NAME_COL).data(ID_ROLE))
            if column != QTY_COL else None
        )

        # Detail panel
        self.card_image = CardImage()
        self.detail_name = QLabel()
        self.detail_name.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.detail_name.setWordWrap(True)
        self.detail_fields = {label: QLabel() for label in
                              ("Set", "Rarity", "Artist", "Price", "Owned", "Subtotal", "Price as of")}
        detail_form = QFormLayout()
        for label, widget in self.detail_fields.items():
            widget.setWordWrap(True)
            detail_form.addRow(f"{label}:", widget)
        self.scryfall_button = QPushButton("View on Scryfall")
        self.scryfall_button.clicked.connect(self.open_on_scryfall)

        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.addWidget(self.card_image, stretch=1)
        detail_layout.addWidget(self.detail_name)
        detail_layout.addLayout(detail_form)
        detail_layout.addWidget(self.scryfall_button)

        splitter = QSplitter()
        splitter.addWidget(self.table)
        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([900, 380])

        # Summary + buttons
        self.summary_label = QLabel()
        self.summary_label.setStyleSheet("font-size: 15px; font-weight: bold;")

        add_button = QPushButton("Add Card")
        add_button.clicked.connect(self.on_add_card_clicked)
        self.edit_button = QPushButton("Edit…")
        self.edit_button.setToolTip("Change printing, finish, quantity or price (or double-click / right-click a card)")
        self.edit_button.clicked.connect(lambda: self.edit_card(self.selected_ids()[0]))
        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.clicked.connect(self.on_remove_selected_clicked)
        self.refresh_button = QPushButton("Refresh Prices")
        self.refresh_button.clicked.connect(lambda: self.refresh_prices())

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.summary_label, stretch=1)
        button_layout.addWidget(self.refresh_button)
        button_layout.addWidget(self.edit_button)
        button_layout.addWidget(self.remove_button)
        button_layout.addWidget(add_button)

        notice = QLabel(f"{FAN_CONTENT_NOTICE} {SCRYFALL_NOTICE}")
        notice.setWordWrap(True)
        notice.setStyleSheet("color: gray; font-size: 10px;")

        central = QWidget()
        outer_layout = QVBoxLayout(central)
        outer_layout.addWidget(self.filter_input)
        outer_layout.addWidget(splitter, stretch=1)
        outer_layout.addLayout(button_layout)
        outer_layout.addWidget(notice)
        self.setCentralWidget(central)

        self.populate_table()
        self.show_selected_card()

        stale = [row for row in self._rows_by_id.values() if _price_is_stale(row)]
        if stale:
            self.refresh_prices(stale, quiet=True)

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("&File")
        add_action = QAction("&Add Card…", self, shortcut=QKeySequence.StandardKey.New)
        add_action.triggered.connect(self.on_add_card_clicked)
        import_action = QAction("&Import…", self, shortcut=QKeySequence.StandardKey.Open)
        import_action.triggered.connect(self.import_file)
        export_action = QAction("&Export to CSV…", self)
        export_action.triggered.connect(self.export_csv)
        quit_action = QAction("&Quit", self, shortcut=QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(add_action)
        file_menu.addAction(import_action)
        file_menu.addAction(export_action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)


        help_menu = self.menuBar().addMenu("&Help")
        about_action = QAction(f"&About {APP_NAME}", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    # Table

    def populate_table(self):
        rows = db.get_all_cards()
        self._rows_by_id = {row["id"]: row for row in rows}
        selected_ids = set(self.selected_ids())

        # Sorting and itemChanged are paused while filling, otherwise rows
        # jump around mid-fill and every setItem looks like a user edit
        self.table.setSortingEnabled(False)
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))

        for row_index, row in enumerate(rows):
            name_item = _item(row["name"])
            name_item.setData(ID_ROLE, row["id"])

            set_label = f"{row['set_name']} ({row['set_code']})" if row["set_code"] else row["set_name"]
            number = row["collector_number"] or ""

            # Quantity is the one editable cell; storing an int makes Qt edit it with a spin box
            quantity_item = QTableWidgetItem()
            quantity_item.setData(Qt.ItemDataRole.EditRole, row["quantity"])
            quantity_item.setToolTip("Double-click to change quantity")

            total = row["price"] * row["quantity"]
            self.table.setItem(row_index, NAME_COL, name_item)
            self.table.setItem(row_index, SET_COL, _item(set_label))
            self.table.setItem(row_index, NUMBER_COL, _item(int(number) if number.isdigit() else number))
            self.table.setItem(row_index, FINISH_COL, _item("Foil" if row["foil"] else ""))
            self.table.setItem(row_index, QTY_COL, quantity_item)
            self.table.setItem(row_index, PRICE_COL, _item(row["price"], True))
            self.table.setItem(row_index, TOTAL_COL, _item(total, True))

        self.table.blockSignals(False)
        self.table.setSortingEnabled(True)

        # Keep the previous selection where possible
        self.select_ids(selected_ids)
        self.apply_filter()
        self.update_summary()

    def select_ids(self, ids):
        # Signals are blocked so the detail panel updates once at the end rather
        # than flashing empty when the old selection is cleared
        self.table.blockSignals(True)
        selection = self.table.selectionModel()
        selection.clearSelection()
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        for row_index in range(self.table.rowCount()):
            item = self.table.item(row_index, NAME_COL)
            if item.data(ID_ROLE) in ids:
                selection.select(self.table.model().index(row_index, NAME_COL), flags)
                self.table.scrollToItem(item)
        self.table.blockSignals(False)
        self.show_selected_card()

    def apply_filter(self):
        needle = self.filter_input.text().strip().lower()
        for row_index in range(self.table.rowCount()):
            row = self._rows_by_id[self.table.item(row_index, NAME_COL).data(ID_ROLE)]
            haystack = " ".join(str(row[key] or "") for key in ("name", "set_name", "set_code", "artist")).lower()
            self.table.setRowHidden(row_index, bool(needle) and needle not in haystack)

    def update_summary(self):
        unique, count, value = db.get_summary()
        self.summary_label.setText(
            f"Total value: ${value:,.2f}    ·    {count:,} card{'s' if count != 1 else ''}"
            f" ({unique:,} unique)"
        )

    def selected_ids(self):
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        return [self.table.item(r, NAME_COL).data(ID_ROLE) for r in sorted(rows)]

    def on_item_changed(self, item):
        if item.column() != QTY_COL:
            return
        card_id = self.table.item(item.row(), NAME_COL).data(ID_ROLE)
        row = self._rows_by_id[card_id]
        quantity = item.data(Qt.ItemDataRole.EditRole)

        if isinstance(quantity, int) and quantity > 0 and quantity != row["quantity"]:
            db.update_quantity(card_id, quantity)
        elif quantity == 0 and self.confirm_remove([card_id]):
            db.remove_card(card_id)
        # Rebuild after the edit has fully finished (this runs mid-commit); it also
        # puts back the old value if the edit was invalid or the removal was cancelled
        QTimer.singleShot(0, self.populate_table)

    # Detail panel

    def show_selected_card(self):
        ids = self.selected_ids()
        row = self._rows_by_id.get(ids[0]) if len(ids) == 1 else None
        self.remove_button.setEnabled(bool(ids))
        self.edit_button.setEnabled(len(ids) == 1)

        if row is None:
            self.card_image.clear_image(f"{len(ids)} cards selected" if ids else "No card selected")
            self.detail_name.setText("")
            for widget in self.detail_fields.values():
                widget.setText("")
            self.scryfall_button.setEnabled(False)
            return

        self.card_image.set_image_url(row["image_url"])
        self.detail_name.setText(row["name"] + ("  ✦ Foil" if row["foil"] else ""))
        fields = self.detail_fields
        set_text = row["set_name"]
        if row["set_code"]:
            set_text += f" ({row['set_code']}) #{row['collector_number']}"
        fields["Set"].setText(set_text)
        fields["Rarity"].setText((row["rarity"] or "—").capitalize())
        fields["Artist"].setText(row["artist"] or "—")
        fields["Price"].setText(_money(row["price"]))
        fields["Owned"].setText(str(row["quantity"]))
        fields["Subtotal"].setText(_money(row["price"] * row["quantity"]))
        if row["price_updated"]:
            updated = datetime.fromisoformat(row["price_updated"]).astimezone()
            fields["Price as of"].setText(updated.strftime("%Y-%m-%d %H:%M"))
        else:
            fields["Price as of"].setText("Entered manually")
        self.scryfall_button.setEnabled(bool(row["set_code"] and row["collector_number"]))

    def open_on_scryfall(self):
        ids = self.selected_ids()
        if len(ids) == 1:
            row = self._rows_by_id[ids[0]]
            QDesktopServices.openUrl(QUrl(scryfall.scryfall_page(row["set_code"], row["collector_number"])))

    # Action functions

    def on_add_card_clicked(self):
        dialog = CardDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        card_id = db.add_card(**dialog.card_data())
        self.filter_input.clear()
        self.populate_table()
        # Select the card that was just added so it shows in the detail panel
        self.select_ids({card_id})

    def edit_card(self, card_id):
        row = self._rows_by_id.get(card_id)
        if row is None:
            return
        dialog = CardDialog(self, existing=row)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        surviving_id = db.update_card(card_id, **dialog.card_data())
        if surviving_id != card_id:
            self.statusBar().showMessage(
                "You already had that printing, so the two entries were combined.", 8000)
        self.populate_table()
        self.select_ids({surviving_id})

    def show_context_menu(self, position):
        # Right-clicking a row that isn't part of the selection selects just that row
        index = self.table.indexAt(position)
        if index.isValid() and not self.table.selectionModel().isRowSelected(index.row()):
            self.select_ids({self.table.item(index.row(), NAME_COL).data(ID_ROLE)})
        menu = self.build_context_menu(self.selected_ids())
        if menu is not None:
            menu.exec(QCursor.pos())

    def build_context_menu(self, ids):
        if not ids:
            return None
        menu = QMenu(self)
        if len(ids) == 1:
            row = self._rows_by_id[ids[0]]
            menu.addAction("Edit…", lambda: self.edit_card(ids[0]))
            view = menu.addAction("View on Scryfall", self.open_on_scryfall)
            view.setEnabled(bool(row["set_code"] and row["collector_number"]))
            menu.addSeparator()
        label = "Remove" if len(ids) == 1 else f"Remove {_count(len(ids), 'entry')}"
        menu.addAction(label, self.on_remove_selected_clicked)
        return menu

    def confirm_remove(self, ids):
        if len(ids) == 1:
            question = f"Remove {self._rows_by_id[ids[0]]['name']} from your collection?"
        else:
            question = f"Remove {_count(len(ids), 'entry')} from your collection?"
        answer = QMessageBox.question(self, "Remove Cards", question)
        return answer == QMessageBox.StandardButton.Yes

    def on_remove_selected_clicked(self):
        ids = self.selected_ids()
        if not ids or not self.confirm_remove(ids):
            return
        for card_id in ids:
            db.remove_card(card_id)
        self.populate_table()

    def refresh_prices(self, rows=None, quiet=False):
        if self._refreshing:
            return
        rows = [r for r in (rows or self._rows_by_id.values()) if r["scryfall_id"]]
        if not rows:
            if not quiet:
                self.statusBar().showMessage("No Scryfall-linked cards to refresh.", 5000)
            return
        self._refreshing = True
        self._quiet_refresh = quiet
        self.refresh_button.setEnabled(False)
        self.statusBar().showMessage(f"Refreshing prices for {_count(len(rows), 'entry')}…")
        work = [(r["id"], r["scryfall_id"], bool(r["foil"])) for r in rows]
        background.run(_fetch_prices, work, on_success=self._on_prices, on_error=self._on_prices_failed)

    def _on_prices(self, result):
        updates, missing = result
        self._refreshing = False
        self.refresh_button.setEnabled(True)
        # Rows removed while the refresh was running just don't match anything
        db.update_prices(updates)
        self.populate_table()
        message = f"Updated prices for {_count(len(updates), 'entry')}."
        if missing:
            message += f" {missing} couldn't be found on Scryfall."
        self.statusBar().showMessage(message, 8000)

    def _on_prices_failed(self, message):
        self._refreshing = False
        self.refresh_button.setEnabled(True)
        if self._quiet_refresh:
            self.statusBar().showMessage("Couldn't refresh prices (offline?). Showing saved prices.", 8000)
        else:
            QMessageBox.warning(self, "Refresh Prices", f"Couldn't reach Scryfall:\n{message}")
            self.statusBar().clearMessage()

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Cards", "",
            "Card lists (*.csv *.txt *.dec *.dek);;All files (*)",
        )
        if not path:
            return
        try:
            rows, errors = importer.parse_file(path)
        except (OSError, UnicodeDecodeError) as error:
            QMessageBox.warning(self, "Import", f"Couldn't read that file:\n{error}")
            return
        if not rows:
            QMessageBox.warning(self, "Import", "\n".join(errors) or "No cards found in the file.")
            return

        total = sum(row.quantity for row in rows)
        question = QMessageBox(
            QMessageBox.Icon.Question, "Import",
            f"Found {_count(total, 'card')} in {_count(len(rows), 'entry')}.\n\n"
            "Look them up on Scryfall? You'll be able to review them and choose "
            "printings before anything is added to your collection.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self,
        )
        if errors:
            question.setInformativeText(f"{_count(len(errors), 'line')} couldn't be read and will be skipped.")
            question.setDetailedText("\n".join(errors))
        if question.exec() != QMessageBox.StandardButton.Yes:
            return

        self._import_progress = QProgressDialog("Looking up cards on Scryfall…", None, 0, 0, self)
        self._import_progress.setWindowTitle("Import")
        self._import_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._import_progress.setMinimumDuration(0)
        self._import_progress.show()
        background.run(importer.resolve, rows, on_success=self._on_import_resolved,
                       on_error=self._on_import_failed)

    def _on_import_resolved(self, result):
        self._import_progress.close()
        review = ImportReviewDialog(result, self)
        if review.exec() != QDialog.DialogCode.Accepted:
            self.statusBar().showMessage("Import cancelled, nothing was added.", 8000)
            return
        records = review.records()
        card_ids = db.add_cards(records)
        self.filter_input.clear()
        self.populate_table()
        self.select_ids(set(card_ids))
        imported = sum(record["quantity"] for record in records)
        self.statusBar().showMessage(
            f"Imported {_count(imported, 'card')} ({_count(len(records), 'entry')}).", 10000)

    def _on_import_failed(self, message):
        self._import_progress.close()
        QMessageBox.warning(self, "Import", f"Couldn't reach Scryfall, nothing was imported:\n{message}")

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Collection", "collection.csv", "CSV files (*.csv)")
        if not path:
            return
        fields = ["name", "set_code", "set_name", "collector_number", "foil", "quantity",
                  "price", "rarity", "artist", "scryfall_id"]
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(fields)
                for row in db.get_all_cards():
                    writer.writerow([row[field] for field in fields])
        except OSError as error:
            QMessageBox.warning(self, "Export Failed", str(error))
            return
        self.statusBar().showMessage(f"Exported collection to {path}", 8000)

    def show_about(self):
        QMessageBox.about(self, f"About {APP_NAME}", (
            f"<h3>{APP_NAME}</h3>"
            "<p>A desktop tracker for your Magic: The Gathering collection.</p>"
            f"<p>{SCRYFALL_NOTICE}</p>"
            f"<p>{FAN_CONTENT_NOTICE}</p>"
        ))


# App setup

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    db.create_table()
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
