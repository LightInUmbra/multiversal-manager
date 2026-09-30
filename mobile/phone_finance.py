# The phone layout's Finance tab (the website's desktop layout has web_finance.FinancePage): the
# day's spikes and drops as a list, and a page for each printing with the enlarged card, its
# price over every period, its history and its Scryfall details. Both read market.py's summary.
import flet as ft

import database as db
import market
import scryfall
import theme
from web_finance import _color, _each, _money, _percent, chart, high_low

SHOWN = 200  # rows drawn at once; filtering narrows the rest down
DEFAULT_MIN_PRICE = 1.0
SHOW_LABELS = [(market.SHOW_SPIKES, "Spikes"), (market.SHOW_DROPS, "Drops"), (market.SHOW_ALL, "All")]
PERIOD_LABELS = {"24 hours": "24h", "7 days": "7d", "30 days": "30d", "90 days": "90d"}
MAX_IMAGE = 420  # the enlarged card on a tablet or wide window


def _chip(text, on, on_click):
    return ft.Container(ft.Text(text, size=12.5, color=None if on else theme.MUTED), on_click=on_click,
                        bgcolor=theme.COLORS["primary_container"] if on else None,
                        border=ft.Border.all(1, theme.COLORS["primary_container"] if on else theme.COLORS["outline"]),
                        border_radius=8, padding=ft.Padding.symmetric(horizontal=11, vertical=5))


class PhoneFinance:
    """A phone tab: view, refresh() and back(). cache: where the phone app keeps the day's
    market file (None on the website, which downloads it per visit)."""

    def __init__(self, page, toast, busy, cache=None):
        self.page, self.toast, self.busy, self.cache = page, toast, busy, cache
        self.summary = None
        self.entries = []
        self.show, self.period, self.min_price = market.SHOW_SPIKES, market.DEFAULT_PERIOD, DEFAULT_MIN_PRICE
        self.detail = None  # the printing whose page is open
        self.card_details = ft.Column(spacing=6)
        self.search = ft.TextField(hint_text="Filter by card or set", prefix_icon=ft.Icons.SEARCH, dense=True,
                                   on_change=lambda e: self.fill())
        self.controls_row = ft.Row(spacing=6, wrap=True)
        self.periods = ft.Row(spacing=0)
        self.status = ft.Text(size=11.5, color=theme.MUTED)
        self.rows = ft.ListView(expand=True, spacing=0)
        self.list_view = ft.Column([self.search, self.controls_row, self.periods, self.status, self.rows],
                                   expand=True, spacing=8)
        self.view = ft.Container(self.list_view, expand=True)

    # The tab

    def refresh(self):
        if self.summary is None:
            self.status.value = "Loading today's market data…"
            self.draw_controls()
            self.page.update()
            self.summary = self.busy("Loading the market data", lambda: market.download(cache=self.cache))
            if self.summary is None:
                self.status.value = "Couldn't load the market data. Open Finance again to retry."
                self.page.update()
                return
            self.load()
        elif self.detail is None:
            self.fill()

    def back(self):
        # Back from a card's page to the list; from the list, the tab has nowhere to go back to
        if self.detail is None:
            return False
        self.detail = None
        self.view.content = self.list_view
        self.page.update()
        return True

    # The list

    def load(self):
        days = dict(market.PERIODS)[self.period]
        self.entries = [(row, market.change_for(row)) for row in market.rows(self.summary, days)]
        self.fill()

    def draw_controls(self):
        def set_show(show):
            self.show = show
            self.fill()

        def set_period(label):
            self.period = label
            self.load()

        self.controls_row.controls = [
            *[_chip(label, show == self.show, lambda e, show=show: set_show(show)) for show, label in SHOW_LABELS],
            _chip(f"≥ ${self.min_price:,.2f}", self.min_price > 0, lambda e: self.ask_min_price())]
        self.periods.controls = [
            ft.Container(ft.Text(PERIOD_LABELS[label], size=12.5, color=None if label == self.period else theme.MUTED),
                         expand=True, alignment=ft.Alignment.CENTER, padding=ft.Padding.symmetric(vertical=6),
                         bgcolor=theme.COLORS["primary_container"] if label == self.period else None,
                         border=ft.Border.all(1, theme.COLORS["outline"]),
                         on_click=lambda e, label=label: set_period(label))
            for label, _ in market.PERIODS]

    def ask_min_price(self):
        field = ft.TextField(value=f"{self.min_price:.2f}", prefix="$", keyboard_type=ft.KeyboardType.NUMBER,
                             autofocus=True, helper="Hides cheaper cards, so bulk commons going from 5¢ to 10¢ "
                                                    "don't swamp the spikes")

        def done(e):
            try:
                self.min_price = max(0.0, float(field.value or 0))
            except ValueError:
                return
            self.page.pop_dialog()
            self.fill()

        field.on_submit = done
        self.page.show_dialog(ft.AlertDialog(title=ft.Text("Minimum price"), content=field, actions=[
            ft.TextButton("Cancel", on_click=lambda e: self.page.pop_dialog()), ft.TextButton("OK", on_click=done)]))

    def fill(self):
        self.draw_controls()
        if self.summary is None:
            self.page.update()
            return
        # Spikes list the biggest % gain first, drops the biggest % loss, everything by price
        column, descending = ((market.PERCENT_COL, self.show != market.SHOW_DROPS) if self.show != market.SHOW_ALL
                              else (market.PRICE_COL, True))
        rows = market.shown(self.entries, (self.search.value or "").strip().lower(), self.min_price, self.show,
                            column, descending)
        self.rows.controls = [self.row(row, change) for row, change in rows[:SHOWN]]
        self.status.value = (f"{len(rows):,} printings" + (f", the first {SHOWN} shown" if len(rows) > SHOWN else "")
                             + f". Prices from {self.summary['built']}, updated once a day.")
        self.page.update()

    def row(self, row, change):
        finish = " ✦" if row["foil"] else ""
        return ft.Container(ft.Row([
            ft.Column([ft.Text(row["name"] + finish, weight=ft.FontWeight.W_500, no_wrap=True,
                               overflow=ft.TextOverflow.ELLIPSIS),
                       ft.Text(f"{row['set_name']} · {row['rarity']}", size=12, color=theme.MUTED, no_wrap=True,
                               overflow=ft.TextOverflow.ELLIPSIS)], spacing=1, expand=True),
            ft.Column([ft.Text(_money(row["price"])), ft.Text(_percent(change), size=12, color=_color(change))],
                      spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END),
        ], spacing=10), padding=ft.Padding.symmetric(horizontal=4, vertical=8),
            border=ft.Border.only(bottom=ft.BorderSide(1, theme.LINE)), on_click=lambda e: self.open(row))

    # A printing's page

    def open(self, row):
        self.detail = row
        width = min(MAX_IMAGE, (self.page.width or 400) - 40)
        finish = market.FINISH_LABELS[row["foil"]]
        periods = market.period_changes(self.summary, row["index"])
        history = market.history(self.summary, row["index"])
        chosen = next((c for label, _, c in periods if label == self.period), None)
        owned = sum(r["quantity"] for r in db.get_all_cards()
                    if r["scryfall_id"] == row["scryfall_id"] and r["foil"] == row["foil"])
        self.card_details.controls = [ft.Text("Looking up the card on Scryfall…", size=12, color=theme.MUTED)]

        def period(label, then, change):
            return ft.Container(ft.Column([
                ft.Text(PERIOD_LABELS[label], size=11.5, color=theme.MUTED),
                ft.Text(_percent(change) or "—", weight=ft.FontWeight.W_600, color=_color(change)),
                ft.Text(_each(change) or "no price then", size=11, color=_color(change) if change else theme.MUTED),
            ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.CENTER), expand=True,
                tooltip=f"{_money(then)} then" if then else None,
                bgcolor=theme.COLORS["primary_container"] if label == self.period else None, border_radius=8,
                padding=ft.Padding.symmetric(vertical=6))

        page_controls = [
            ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, tooltip="Back to the list", on_click=lambda e: self.back()),
                    ft.Text(row["name"], font_family=theme.TITLE_FONT, size=17, weight=ft.FontWeight.W_600,
                            color=theme.GOLD, expand=True, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)], spacing=4),
            ft.Row([ft.Image(src=market.image_url(row["scryfall_id"]), width=width, border_radius=14)],
                   alignment=ft.MainAxisAlignment.CENTER),
            ft.Column([
                ft.Text(f"{row['name']}{f'  ✦ {finish}' if finish else ''}", size=18, weight=ft.FontWeight.BOLD,
                        text_align=ft.TextAlign.CENTER),
                ft.Text(f"{row['set_name']} ({row['set_code'].upper()}) #{row['collector_number']} · {row['rarity']}",
                        color=theme.MUTED, text_align=ft.TextAlign.CENTER),
            ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([ft.Text(_money(row["price"]), size=26, weight=ft.FontWeight.BOLD),
                    ft.Text(f"{_each(chosen)} · {_percent(chosen)} in {self.period}" if chosen
                            else f"No price {self.period} ago", color=_color(chosen), expand=True,
                            text_align=ft.TextAlign.RIGHT)], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([period(*p) for p in periods], spacing=4),
            ft.Text("Price history", size=13, weight=ft.FontWeight.W_600, color=theme.GOLD),
            chart(history, width=width, height=160),
            high_low(history),
            ft.Text(f"In your collection: {owned} {'copy' if owned == 1 else 'copies'}" if owned
                    else "Not in your collection", color=theme.GOLD if owned else theme.MUTED),
            ft.Divider(color=theme.LINE),
            self.card_details,
            ft.OutlinedButton("Open on Scryfall ↗", url=scryfall.scryfall_page(row["set_code"], row["collector_number"])),
        ]
        self.view.content = ft.ListView(page_controls, expand=True, spacing=12, padding=ft.Padding.only(bottom=20))
        self.page.update()
        self.page.run_thread(self.look_up, row)

    def look_up(self, row):
        # The card's rules, artist and other finishes' prices, from Scryfall, once the page is up
        try:
            card = scryfall.get_cards_by_id([row["scryfall_id"]]).get(row["scryfall_id"])
        except Exception:
            card = None
        if self.detail is not row:
            return  # moved on while this loaded
        if card is None:
            self.card_details.controls = [ft.Text("Couldn't reach Scryfall for the card's details.", size=12,
                                                  color=theme.MUTED)]
            self.page.update()
            return
        data = card.data
        faces = data.get("card_faces") or [data]
        lines = []
        for face in faces:
            heading = " ".join(filter(None, [face.get("name") if len(faces) > 1 else None, face.get("mana_cost")]))
            if heading:
                lines.append(ft.Text(heading, weight=ft.FontWeight.W_600))
            if face.get("type_line"):
                lines.append(ft.Text(face["type_line"], color=theme.MUTED, size=12.5))
            if face.get("oracle_text"):
                lines.append(ft.Text(face["oracle_text"], size=13, selectable=True))
            if face.get("power") is not None:
                lines.append(ft.Text(f"{face['power']}/{face['toughness']}", size=12.5))
        others = [f"{scryfall.FINISHES[code][1]} {_money(scryfall.price_for(card, code))}"
                  for code in scryfall.finish_codes(card) if code != row["foil"]]
        facts = [f"Illustrated by {card.artist}" if card.artist else "",
                 f"Released {card.released_at}" if card.released_at else "",
                 "Other finishes: " + ", ".join(others) if others else ""]
        self.card_details.controls = [*lines, *[ft.Text(f, size=12, color=theme.MUTED) for f in facts if f]]
        self.page.update()
