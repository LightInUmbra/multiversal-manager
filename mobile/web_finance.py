# The desktop's Finance window (finance.py) for the website's desktop layout: spikes, drops and
# price history across the whole market, like its "Track Every Card" mode. The website can't
# download the market itself (far too big), so it reads market.py's daily summary.
import flet as ft
import flet.canvas as cv

import market
import theme
from web_desktop import DETAIL_WIDTH, NOTICE, PAGE_PADDING, _money

SHOWN = 300  # rows drawn at once; the desktop's table is virtual, Flet's draws every row
DEFAULT_MIN_PRICE = 1.0  # like the desktop's every-card mode: start past the penny cards
CHART_WIDTH, CHART_HEIGHT = DETAIL_WIDTH - 32, 150
IMAGE_WIDTH = 200  # small enough that the chart fits under it without scrolling
NUMERIC = {market.PRICE_COL, market.CHANGE_COL, market.PERCENT_COL}
FIXED_WIDTHS = {market.NUMBER_COL: 56, market.FINISH_COL: 52, market.RARITY_COL: 86, market.PRICE_COL: 76,
                market.CHANGE_COL: 80, market.PERCENT_COL: 84}
SLACK = 40  # the panel's border and scrollbar
COLUMN_SPACING, MARGIN = 16, 14


def _percent(change):
    return f"{'+' if change[1] >= 0 else '−'}{abs(change[1]):.1f}%" if change else ""


def _each(change):
    return f"{'+' if change[0] >= 0 else '−'}${abs(change[0]):,.2f}" if change else ""


def _color(change):
    if not change or abs(change[0]) <= 0.004:
        return theme.MUTED
    return theme.GAIN if change[0] > 0 else theme.LOSS


class FinancePage:
    """Every printing's price and its change over a period; select one for its history.
    busy(label, fn) is main.py's (a progress bar, and a message if it fails)."""

    def __init__(self, page, busy):
        self.page, self.busy = page, busy
        self.summary = None
        self.entries = []  # (row, market.change_for(row)) for the period
        self.selected = None
        self.sort = {"column": market.PERCENT_COL, "descending": True}
        self.search = ft.TextField(hint_text="Filter by card or set…", prefix_icon=ft.Icons.SEARCH, dense=True,
                                   width=340, filled=True, bgcolor=theme.COLORS["surface_container_low"],
                                   border=ft.OutlineInputBorder(side=ft.BorderSide(1, theme.LINE), border_radius=6),
                                   on_change=lambda e: self.fill())
        self.show = ft.Dropdown(dense=True, width=190, value=market.SHOW_SPIKES, on_select=self.show_changed,
                                options=[ft.DropdownOption(s) for s in (market.SHOW_SPIKES, market.SHOW_DROPS,
                                                                        market.SHOW_ALL)])
        self.period = ft.Dropdown(dense=True, width=140, value=market.DEFAULT_PERIOD, on_select=lambda e: self.load(),
                                  options=[ft.DropdownOption(label) for label, _ in market.PERIODS])
        self.min_price = ft.TextField(value=f"{DEFAULT_MIN_PRICE:.2f}", prefix="$", dense=True, width=100,
                                      tooltip="Hide cheaper cards, so bulk commons going from 5¢ to 10¢ don't "
                                              "swamp the spikes", on_submit=lambda e: self.fill(),
                                      on_blur=lambda e: self.fill())
        self.table = ft.ListView(expand=True)
        self.detail = ft.Column(scroll=ft.ScrollMode.AUTO, spacing=8)
        self.status = ft.Text(size=12, color=theme.MUTED)

        def label(text):
            return ft.Text(text, color=theme.MUTED)

        self.view = ft.Container(ft.Column([
            ft.Row([self.search, ft.Container(expand=True), label("Show:"), self.show, label("Change over:"),
                    self.period, label("Min price:"), self.min_price],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([theme.panel(self.table, expand=True), theme.panel(self.detail, width=DETAIL_WIDTH, padding=16)],
                   expand=True, spacing=20, vertical_alignment=ft.CrossAxisAlignment.START),
            self.status,
            ft.Text(NOTICE, size=11, color=theme.MUTED),
        ], spacing=14, expand=True), padding=ft.Padding.symmetric(horizontal=PAGE_PADDING, vertical=20), expand=True)
        self.show_detail(None)

    # Loading

    def refresh(self):
        # Opening the page: the day's market data, downloaded once per visit
        if self.summary is None:
            self.status.value = "Loading today's market data…"
            self.page.update()
            self.summary = self.busy("Loading the market data", market.download)
            if self.summary is None:
                self.status.value = "Couldn't load the market data. Open Finance again to retry."
                self.page.update()
                return
            self.load()
        else:
            self.fill()

    def days(self):
        return dict(market.PERIODS)[self.period.value]

    def load(self):
        if self.summary is not None:
            self.entries = [(row, market.change_for(row)) for row in market.rows(self.summary, self.days())]
            self.fill()

    def show_changed(self, e):
        # Spikes list the biggest % gain first, drops the biggest % loss, like the desktop
        if self.show.value != market.SHOW_ALL:
            self.sort.update(column=market.PERCENT_COL, descending=self.show.value == market.SHOW_SPIKES)
        self.fill()

    def minimum(self):
        try:
            return max(0.0, float(self.min_price.value or 0))
        except ValueError:
            self.min_price.value = f"{DEFAULT_MIN_PRICE:.2f}"
            return DEFAULT_MIN_PRICE

    # The table

    def fill(self):
        if self.summary is None:
            return
        rows = market.shown(self.entries, (self.search.value or "").strip().lower(), self.minimum(),
                            self.show.value, self.sort["column"], self.sort["descending"])
        self.table.controls = [self.card_table(rows[:SHOWN])]
        self.status.value = (f"Showing {min(len(rows), SHOWN):,} of {len(rows):,} matching printings "
                             f"({len(self.entries):,} in all)"
                             + (". Filter or raise the minimum price to narrow them down" if len(rows) > SHOWN else "")
                             + f". Prices from {self.summary['built']}, updated once a day.")
        self.page.update()

    def card_table(self, rows):
        # Card and Set share what the fixed columns leave (a Flet table doesn't size its columns)
        area = (self.page.width or 1400) - 2 * PAGE_PADDING - DETAIL_WIDTH - 20
        spare = max(280, area - sum(FIXED_WIDTHS.values()) - COLUMN_SPACING * len(market.COLUMNS) - 2 * MARGIN - SLACK)
        widths = {market.NAME_COL: spare * 0.45, market.SET_COL: spare * 0.55, **FIXED_WIDTHS}

        def text(value, column, **style):
            return ft.Text(value, width=widths[column], no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS, **style)

        def cells(row, change):
            return [text(row["name"], market.NAME_COL, weight=ft.FontWeight.W_500, tooltip=row["name"]),
                    text(f"{row['set_name']} ({row['set_code'].upper()})", market.SET_COL, tooltip=row["set_name"]),
                    text(row["collector_number"], market.NUMBER_COL),
                    text(market.FINISH_LABELS[row["foil"]], market.FINISH_COL),
                    text(row["rarity"], market.RARITY_COL),
                    text(_money(row["price"]), market.PRICE_COL, text_align=ft.TextAlign.RIGHT),
                    text(_each(change), market.CHANGE_COL, color=_color(change), text_align=ft.TextAlign.RIGHT,
                         tooltip=f"${row['past']:,.2f} → ${row['price']:,.2f}" if change else
                         "No price recorded that far back"),
                    text(_percent(change), market.PERCENT_COL, color=_color(change), text_align=ft.TextAlign.RIGHT)]

        return ft.DataTable(
            sort_column_index=self.sort["column"], sort_ascending=not self.sort["descending"],
            heading_row_height=40, data_row_min_height=34, data_row_max_height=34,
            column_spacing=COLUMN_SPACING, horizontal_margin=MARGIN, divider_thickness=1,
            horizontal_lines=ft.BorderSide(1, theme.LINE),
            heading_text_style=ft.TextStyle(size=12, weight=ft.FontWeight.W_600, color=theme.GOLD, letter_spacing=1),
            data_row_color={ft.ControlState.SELECTED: theme.COLORS["primary_container"]},
            columns=[ft.DataColumn(ft.Text(label.upper()), numeric=i in NUMERIC, on_sort=self.sorted_by)
                     for i, label in enumerate(market.COLUMNS)],
            rows=[ft.DataRow(selected=self.selected is not None and row["index"] == self.selected["index"],
                             cells=[ft.DataCell(c, on_tap=lambda e, row=row: self.select(row))
                                    for c in cells(row, change)])
                  for row, change in rows])

    def sorted_by(self, e):
        # A number column starts biggest first, a text column A to Z
        column = e.column_index
        if column == self.sort["column"]:
            self.sort["descending"] = not self.sort["descending"]
        else:
            self.sort.update(column=column, descending=column in NUMERIC)
        self.fill()

    # The selected printing

    def select(self, row):
        self.selected = row
        self.show_detail(row)
        self.fill()

    def show_detail(self, row):
        if row is None:
            self.detail.controls = [ft.Text("Select a card to see its price history.", italic=True, color=theme.MUTED)]
            return
        finish = market.FINISH_LABELS[row["foil"]]
        points = market.history(self.summary, row["index"])
        self.detail.controls = [
            ft.Row([ft.Image(src=market.image_url(row["scryfall_id"]), width=IMAGE_WIDTH, border_radius=10)],
                   alignment=ft.MainAxisAlignment.CENTER),
            ft.Text(f"{row['name']}{f'  ✦ {finish}' if finish else ''}", size=16, weight=ft.FontWeight.BOLD,
                    color=theme.GOLD),
            ft.Text(f"{row['set_name']} ({row['set_code'].upper()}) #{row['collector_number']}", color=theme.MUTED),
            ft.Text("Price history", size=12.5, weight=ft.FontWeight.W_600, color=theme.GOLD),
            chart(points),
            high_low(points),
        ]


def chart(points, width=CHART_WIDTH, height=CHART_HEIGHT):
    """A small line chart of [(day, price)], oldest first: the line and the first and last
    day (the high and low go in a line of text under it, see high_low)"""
    if len(points) < 2:
        return ft.Text("No price history for this printing.", italic=True, color=theme.MUTED)
    prices = [p for _, p in points]
    low, high = min(prices), max(prices)
    span = (high - low) or 1
    top, bottom = 6, height - 16

    def x(i):
        return 4 + i * (width - 8) / (len(points) - 1)

    def y(price):
        return bottom - (price - low) / span * (bottom - top)

    color = theme.GAIN if prices[-1] >= prices[0] else theme.LOSS
    line = ft.Paint(color=color, stroke_width=2, style=ft.PaintingStyle.STROKE)
    small = ft.TextStyle(size=10.5, color=theme.MUTED)
    shapes = [cv.Line(x1=0, y1=bottom, x2=width, y2=bottom, paint=ft.Paint(color=theme.LINE, stroke_width=1)),
              cv.Path(elements=[cv.Path.MoveTo(x=x(0), y=y(prices[0])),
                                *[cv.Path.LineTo(x=x(i), y=y(p)) for i, p in enumerate(prices[1:], 1)]], paint=line),
              *[cv.Circle(x=x(i), y=y(p), radius=2.5, paint=ft.Paint(color=color)) for i, p in enumerate(prices)],
              cv.Text(x=0, y=bottom + 2, value=points[0][0], style=small),
              cv.Text(x=width - 62, y=bottom + 2, value=points[-1][0], style=small)]
    return cv.Canvas(shapes=shapes, width=width, height=height)


def high_low(points):
    # The line under a chart: its highest and lowest price
    prices = [p for _, p in points]
    return ft.Text(f"Last 90 days: high {_money(max(prices))} · low {_money(min(prices))}", size=12,
                   color=theme.MUTED) if prices else ft.Text("")
