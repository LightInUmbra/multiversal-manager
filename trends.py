# Imports
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QDialogButtonBox, QGroupBox,
)

import database as db
from charts import HistoryChart
from price_changes import Change, collection_change, compute_changes, format_change, movers, mover_name  # noqa: F401

# (label, days back; None = since the first recorded price)
PERIODS = [("24 hours", 1), ("7 days", 7), ("30 days", 30), ("90 days", 90), ("All time", None)]
DEFAULT_PERIOD = "7 days"

GAIN_COLOR = QColor("#1a8f3c")
LOSS_COLOR = QColor("#c62828")


def change_color(amount):
    if amount > 0.004:
        return GAIN_COLOR
    if amount < -0.004:
        return LOSS_COLOR
    return None


class TrendsDialog(QDialog):
    """Collection value over time, plus the biggest gainers and losers for a period."""

    MOVERS_SHOWN = 15

    def __init__(self, period_label=DEFAULT_PERIOD, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Collection Trends")
        self.resize(1000, 760)

        self.value_chart = HistoryChart("Collection value", min_height=260)
        self.value_note = QLabel(
            "Recorded once a day while the app is open. Value also changes as you add or "
            "remove cards; the gainers and losers below count price movement only."
        )
        self.value_note.setWordWrap(True)
        self.value_note.setStyleSheet("color: gray;")

        self.period_combo = QComboBox()
        for label, _ in PERIODS:
            self.period_combo.addItem(label)
        self.period_combo.setCurrentText(period_label)
        self.period_combo.currentIndexChanged.connect(self.refresh)
        self.summary_label = QLabel()
        self.summary_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        period_row = QHBoxLayout()
        period_row.addWidget(QLabel("Price change over:"))
        period_row.addWidget(self.period_combo)
        period_row.addSpacing(16)
        period_row.addWidget(self.summary_label, stretch=1)

        self.gainers = self._movers_table()
        self.losers = self._movers_table()
        gainers_box, losers_box = QGroupBox("Biggest gainers"), QGroupBox("Biggest losers")
        QVBoxLayout(gainers_box).addWidget(self.gainers)
        QVBoxLayout(losers_box).addWidget(self.losers)
        movers = QHBoxLayout()
        movers.addWidget(gainers_box)
        movers.addWidget(losers_box)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.value_chart)
        layout.addWidget(self.value_note)
        layout.addLayout(period_row)
        layout.addLayout(movers, stretch=1)
        layout.addWidget(buttons)

        history = [(day, value) for day, value, _ in db.get_value_history()]
        self.value_chart.set_points(history, "No value history yet.")
        self.refresh()

    def _movers_table(self):
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Card", "Price", "Change (all copies)"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        return table

    def period_days(self):
        return dict(PERIODS)[self.period_combo.currentText()]

    def refresh(self):
        rows = {row["id"]: row for row in db.get_all_cards()}
        changes = compute_changes(rows.values(), db.get_past_prices(self.period_days()))
        overall = collection_change(changes)
        if overall is None:
            self.summary_label.setText("No price history that far back yet.")
            self.summary_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        else:
            total, percent = overall
            self.summary_label.setText(f"Collection: {format_change(total, percent)}")
            color = change_color(total)
            self.summary_label.setStyleSheet(
                "font-size: 14px; font-weight: bold;" + (f" color: {color.name()};" if color else ""))

        gainers, losers = movers(changes, self.MOVERS_SHOWN)
        self._fill(self.gainers, gainers, rows)
        self._fill(self.losers, losers, rows)

    def _fill(self, table, movers, rows):
        table.setRowCount(len(movers))
        for index, (card_id, change) in enumerate(movers):
            name = mover_name(rows[card_id], change)
            price = QTableWidgetItem(f"${change.past:,.2f} → ${change.now:,.2f}")
            total = QTableWidgetItem(format_change(change.total, change.percent))
            total.setForeground(change_color(change.total))
            for item in (price, total):
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(index, 0, QTableWidgetItem(name))
            table.setItem(index, 1, price)
            table.setItem(index, 2, total)
