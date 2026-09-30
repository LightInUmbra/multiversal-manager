# The desktop's Trends window (trends.TrendsDialog) for the website and the phone: the
# collection's value over the last 90 days and its biggest gainers and losers. A browser keeps
# no price history, so both price the cards as owned today from market.py's daily summary.
import flet as ft

import database as db
import market
import price_changes
import theme
from phone_finance import PERIOD_LABELS, PhoneFinance, _chip
from web_desktop import PAGE_PADDING
from web_finance import chart, high_low

SHOWN = 15  # gainers and losers each, like the desktop
NOTE = ("Your cards as you own them today, priced from the daily market data. The gainers and losers "
        "count price movement only.")


def figures(summary, days):
    # (value history, collection_change or None, gainers, losers, {card id: row}) for a period
    cards = db.get_all_cards()
    changes = price_changes.compute_changes(cards, market.past_prices(summary, cards, days))
    gainers, losers = price_changes.movers(changes, SHOWN)
    return (market.value_history(summary, cards), price_changes.collection_change(changes), gainers, losers,
            {card["id"]: card for card in cards})


def _change_color(amount):
    return theme.GAIN if amount > 0.004 else theme.LOSS if amount < -0.004 else None


def overall_text(overall, size=15):
    if overall is None:
        return ft.Text("No prices that far back for your cards.", size=size - 2, color=theme.MUTED)
    total, percent = overall
    return ft.Text(f"Collection: {price_changes.format_change(total, percent)}", size=size, weight=ft.FontWeight.BOLD,
                   color=_change_color(total))


def _heading(text):
    return ft.Text(text.upper(), size=11.5, weight=ft.FontWeight.W_600, color=theme.GOLD,
                   style=ft.TextStyle(letter_spacing=1.5))


class TrendsPanel:
    """The website's Cards page Trends tab: view and refresh(). busy is main.py's."""

    def __init__(self, page, busy):
        self.page, self.busy = page, busy
        self.summary, self.period = None, market.DEFAULT_PERIOD
        self.chart_area = ft.Column(spacing=8)
        self.controls = ft.Row(spacing=8, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.gainers, self.losers = ft.Column(spacing=0), ft.Column(spacing=0)
        self.view = ft.Column([
            theme.panel(self.chart_area, padding=16),
            self.controls,
            ft.Row([theme.panel(self.gainers, expand=True, padding=16), theme.panel(self.losers, expand=True, padding=16)],
                   spacing=20, vertical_alignment=ft.CrossAxisAlignment.START),
        ], spacing=14, expand=True, scroll=ft.ScrollMode.AUTO)

    def refresh(self):
        if self.summary is None:
            self.summary = self.busy("Loading the market data", market.download)
            if self.summary is None:
                self.chart_area.controls = [ft.Text("Couldn't load the market data. Open Trends again to retry.",
                                                    color=theme.MUTED)]
                self.page.update()
                return
        history, overall, gainers, losers, rows = figures(self.summary, dict(market.PERIODS)[self.period])
        width = (self.page.width or 1400) - 2 * PAGE_PADDING - 40
        self.chart_area.controls = [_heading("Collection value · last 90 days"), chart(history, width, 200),
                                    high_low(history), ft.Text(NOTE, size=11.5, color=theme.MUTED)]
        self.controls.controls = [ft.Text("Price change over", color=theme.MUTED),
                                  *[_chip(label, label == self.period, lambda e, label=label: self.set_period(label))
                                    for label, _ in market.PERIODS],
                                  ft.Container(width=12), overall_text(overall)]
        self.gainers.controls = [_heading("Biggest gainers"), *self.lines(gainers, rows, "No gainers")]
        self.losers.controls = [_heading("Biggest losers"), *self.lines(losers, rows, "No losers")]
        self.page.update()

    def set_period(self, label):
        self.period = label
        self.refresh()

    @staticmethod
    def lines(movers, rows, empty):
        if not movers:
            return [ft.Text(f"{empty} over this period.", italic=True, color=theme.MUTED)]
        return [ft.Container(ft.Row([
            ft.Text(price_changes.mover_name(rows[card_id], change), expand=True, no_wrap=True,
                    overflow=ft.TextOverflow.ELLIPSIS, tooltip=rows[card_id]["name"]),
            ft.Text(f"${change.past:,.2f} → ${change.now:,.2f}", size=12, color=theme.MUTED),
            ft.Text(price_changes.format_change(change.total, change.percent), width=150,
                    text_align=ft.TextAlign.RIGHT, color=_change_color(change.total)),
        ], spacing=12), padding=ft.Padding.symmetric(vertical=7),
            border=ft.Border.only(bottom=ft.BorderSide(1, theme.LINE)))
            for card_id, change in movers]


class PhoneTrends:
    """The phone layout's Trends screen, opened from the Collection's summary line. It takes the
    Collection's place like the import review: screens is main.py's (open, close), and back()
    steps back from a card's page, then closes the screen. cache: the phone app's market file."""

    def __init__(self, page, toast, busy, screens, cache=None):
        self.page, self.busy, self.cache = page, busy, cache
        self.open_screen, self.close_screen = screens
        self.summary, self.period, self.side = None, market.DEFAULT_PERIOD, "Gainers"
        # A tapped card opens Finance's card page, with its back arrow returning here
        self.finance = PhoneFinance(page, toast, busy)
        self.finance.back = self.close_card
        self.body = ft.ListView(expand=True, spacing=10, padding=ft.Padding.only(bottom=20))
        self.trends_view = ft.Column([
            ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, tooltip="Back to your cards", on_click=lambda e: self.back()),
                    ft.Text("Collection Trends", font_family=theme.TITLE_FONT, size=17, weight=ft.FontWeight.W_600,
                            color=theme.GOLD)], spacing=4),
            self.body], expand=True, spacing=4)
        self.view = ft.Container(self.trends_view, expand=True)

    def open(self):
        self.view.content = self.trends_view
        self.open_screen(self)
        if self.summary is None:
            self.body.controls = [ft.Text("Loading today's market data…", color=theme.MUTED)]
            self.page.update()
            self.summary = self.busy("Loading the market data", lambda: market.download(cache=self.cache))
        self.fill()

    def back(self):
        if self.finance.detail is not None:
            self.close_card()
        else:
            self.close_screen()

    def close_card(self):
        self.finance.detail = None
        self.view.content = self.trends_view
        self.page.update()
        return True

    def fill(self):
        if self.summary is None:
            self.body.controls = [ft.Text("Couldn't load the market data. Go back and open Trends again to retry.",
                                          color=theme.MUTED)]
            self.page.update()
            return
        history, overall, gainers, losers, rows = figures(self.summary, dict(market.PERIODS)[self.period])
        width = (self.page.width or 400) - 32

        def segment(labels, chosen, on_pick, short=None):
            return ft.Row([ft.Container(ft.Text((short or {}).get(label, label), size=12.5,
                                                color=None if label == chosen else theme.MUTED),
                                        expand=True, alignment=ft.Alignment.CENTER,
                                        padding=ft.Padding.symmetric(vertical=6),
                                        bgcolor=theme.COLORS["primary_container"] if label == chosen else None,
                                        border=ft.Border.all(1, theme.COLORS["outline"]),
                                        on_click=lambda e, label=label: on_pick(label)) for label in labels], spacing=0)

        movers = gainers if self.side == "Gainers" else losers
        self.body.controls = [
            chart(history, width=width, height=160),
            high_low(history),
            segment([label for label, _ in market.PERIODS], self.period, self.set_period, PERIOD_LABELS),
            ft.Container(ft.Column([ft.Text(f"Collection over {self.period}", size=11.5, color=theme.MUTED),
                                    overall_text(overall, size=16)], spacing=2),
                         bgcolor=theme.COLORS["surface"], border=ft.Border.all(1, theme.LINE), border_radius=10,
                         padding=ft.Padding.symmetric(horizontal=12, vertical=8)),
            segment(["Gainers", "Losers"], self.side, self.set_side),
            *([self.row(rows[card_id], change) for card_id, change in movers]
              or [ft.Text(f"No {self.side.lower()} over this period.", italic=True, color=theme.MUTED)]),
            ft.Text(NOTE, size=11.5, color=theme.MUTED),
        ]
        self.page.update()

    def set_period(self, label):
        self.period = label
        self.fill()

    def set_side(self, side):
        self.side = side
        self.fill()

    def row(self, card, change):
        finish = " ✦" if card["foil"] else ""
        copies = f" · ×{change.quantity}" if change.quantity > 1 else ""
        return ft.Container(ft.Row([
            ft.Column([ft.Text(card["name"] + finish, weight=ft.FontWeight.W_500, no_wrap=True,
                               overflow=ft.TextOverflow.ELLIPSIS),
                       ft.Text(f"{(card['set_code'] or '').upper()}{copies} · ${change.past:,.2f} → ${change.now:,.2f}",
                               size=12, color=theme.MUTED, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)],
                      spacing=1, expand=True),
            ft.Text(price_changes.format_change(change.total), color=_change_color(change.total)),
        ], spacing=10), padding=ft.Padding.symmetric(horizontal=4, vertical=8),
            border=ft.Border.only(bottom=ft.BorderSide(1, theme.LINE)), on_click=lambda e: self.open_card(card))

    def open_card(self, card):
        index = market.index_of(self.summary, card)
        if index is None:
            return
        column = self.summary["offsets"].index(dict(market.PERIODS)[self.period])
        self.finance.summary, self.finance.period = self.summary, self.period
        self.finance.open(market.row(self.summary, index, column))
        self.view.content = self.finance.view
        self.page.update()
