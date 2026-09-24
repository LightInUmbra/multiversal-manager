# Imports
from datetime import date, datetime, time

from PySide6.QtCharts import QChart, QChartView, QDateTimeAxis, QLineSeries, QScatterSeries, QValueAxis
from PySide6.QtCore import Qt, QDateTime, QMargins
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtWidgets import QStackedWidget, QLabel

LINE_COLOR = QColor("#2f7ed8")


def _msecs(day):
    # "YYYY-MM-DD" -> msecs since epoch at local midnight, as QtCharts expects
    return QDateTime(datetime.combine(date.fromisoformat(day), time())).toMSecsSinceEpoch()


class HistoryChart(QStackedWidget):
    """A date / dollar line chart, or a short message when there's nothing to plot yet."""

    def __init__(self, title="", min_height=160, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(min_height)

        self.chart = QChart()
        self.chart.setTitle(title)
        self.chart.legend().hide()
        self.chart.setMargins(QMargins(0, 0, 0, 0))
        self.chart.setBackgroundRoundness(0)
        self.view = QChartView(self.chart)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)

        self.message = QLabel()
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: gray;")

        self.addWidget(self.view)
        self.addWidget(self.message)
        self.show_message("")

    def show_message(self, text):
        self.message.setText(text)
        self.setCurrentWidget(self.message)

    def set_points(self, points, empty_message="Not enough price history yet."):
        # points: [(day, value)] oldest first. A single point is drawn as a dot, since
        # history only starts building from the first time a card's price is fetched.
        if not points:
            self.show_message(empty_message)
            return

        self.chart.removeAllSeries()
        for axis in self.chart.axes():
            self.chart.removeAxis(axis)

        line = QLineSeries()
        line.setPen(QPen(LINE_COLOR, 2))
        dots = QScatterSeries()
        dots.setColor(LINE_COLOR)
        dots.setBorderColor(LINE_COLOR)
        dots.setMarkerSize(7)
        for day, value in points:
            line.append(_msecs(day), value)
            dots.append(_msecs(day), value)
        self.chart.addSeries(line)
        self.chart.addSeries(dots)

        first, last = _msecs(points[0][0]), _msecs(points[-1][0])
        one_day = 24 * 60 * 60 * 1000
        if first == last:
            first, last = first - one_day, last + one_day
        x_axis = QDateTimeAxis()
        x_axis.setFormat("MMM d")
        x_axis.setRange(QDateTime.fromMSecsSinceEpoch(first), QDateTime.fromMSecsSinceEpoch(last))
        x_axis.setTickCount(min(6, max(2, len(points))))

        values = [value for _, value in points]
        low, high = min(values), max(values)
        padding = (high - low) * 0.1 or max(high * 0.1, 0.5)
        y_axis = QValueAxis()
        y_axis.setRange(max(0.0, low - padding), high + padding)
        y_axis.setLabelFormat("$%.2f")
        y_axis.setTickCount(4)

        self.chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)
        self.chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)
        for series in (line, dots):
            series.attachAxis(x_axis)
            series.attachAxis(y_axis)
        self.setCurrentWidget(self.view)
