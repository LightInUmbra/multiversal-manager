# The website's Deck Builder, in the desktop layout (the user's pick: the desktop's three
# panels, "layout A", plus a Stats tab). A home page of every deck, binder and wishlist, then
# per list: its summary tiles, the selected card | the list grouped by section | cards to add
# (My Cards, Explore, Recommended) and the deck's Stats. Every format's rules apply
# (formats.py), and Commander decks get brackets (brackets.py) and the same recommendations as
# the desktop (synergy.py); like the desktop, other formats get none.
#
# The website has no downloaded card database, so it asks Scryfall only for what it needs:
# the list's cards once, Explore a page at a time, and Recommended the most played cards in
# the commander's colors and themes (kept for the visit).
import time

import flet as ft

import brackets
import card_form
import database as db
import deck_stats
import formats
import importer
import scryfall
import synergy
import theme
from importer import SECTIONS
from web_desktop import PAGE_PADDING, tile

KINDS ={"deck": "Deck", "binder": "Binder", "wishlist": "Wishlist"}
SECTION_TITLES = {"Commander": "Commander", "Companion": "Companion", "Main": "Main Deck",
                  "Sideboard": "Sideboard", "Maybeboard": "Maybeboard", "": "Cards"}
TABS = ["My Cards", "Explore", "Recommended", "Stats"]
MY_CARDS, EXPLORE, RECOMMENDED, STATS = range(len(TABS))
DETAIL_WIDTH = 250
BROWSER_WIDTH = 420
GRID_CARD = 120           # a card's width in the browsing grids: three across the right panel
# A Commander deck's pool: the most played cards in its colors, then per theme its rules-text
# matches and each of its Scryfall tags (175 cards a page, most played first)
GENERAL_PAGES, THEME_PAGES, TAG_PAGES = 2, 1, 1
SHOWN = 12                # cards per recommendation section before Show More
SHOW_MORE = 24
MY_CARDS_SHOWN = 300
THEMES_OFFERED = 6  # suggested themes shown as chips; the rest are under More themes (the desktop's MAX_CHIPS)
PRICES = {"Any price": None, "Under $1": 1, "Under $5": 5, "Under $20": 20, "Under $50": 50}
SORTS = {"Name": lambda l: l["name"].lower(), "Value": lambda l: -l["value"], "Newest": lambda l: l["created"] or ""}
MANA = {"W": ("#F3E3A6", "#1A1300"), "U": ("#1F7BC8", "#FFFFFF"), "B": ("#8E7A99", "#FFFFFF"),
        "R": ("#D9453B", "#FFFFFF"), "G": ("#2E9E5B", "#FFFFFF")}
GENERIC = ("#CFC7B0", "#1A1300")
COLOR_NAMES = {"W": "White", "U": "Blue", "B": "Black", "R": "Red", "G": "Green", "C": "Colorless"}


def popularity_order(format_key):
    """(Scryfall order, direction, how to say it) for the most played cards first. Scryfall's
    only play counts are EDHREC's (Commander) and Penny Dreadful's; MTGO ticket prices were
    tried for constructed and ranked poorly (Goblin Guide about 300th in Modern red)."""
    if format_key == "penny":
        return "penny", "asc", "most played in Penny Dreadful first"
    return "edhrec", "auto", "most played in Commander first (Scryfall's play count)"


# The deck table's columns: (heading, width or a share of what's left, right-aligned)
GRID_HEADERS = [("Qty", 36, True), ("Card", 3, False), ("Type", 2, False), ("Mana", 84, False),
                ("Price", 64, True), ("Owned", 54, True), ("", 20, False)]
FLEX = 10  # widths up to this are shares of the leftover space, not pixels


def _money(value):
    return f"${value:,.2f}" if value else "—"


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _small(url):
    # Scryfall's small image (about a seventh of the size) for grids of cards
    return url.replace("/normal/", "/small/") if url else None


def _art(url):
    return url.replace("/normal/", "/art_crop/") if url else None


def _symbol(symbol, size=16):
    colors = [c for c in symbol.split("/") if c in MANA]
    bg, fg = MANA[colors[0]] if colors else GENERIC
    return ft.Container(ft.Text(symbol.replace("/", ""), size=size * 0.55, weight=ft.FontWeight.BOLD, color=fg),
                        width=size, height=size, border_radius=size / 2, bgcolor=bg, alignment=ft.Alignment.CENTER)


def mana(cost, size=16):
    # A mana cost like {2}{U}{U} as colored circles
    symbols = deck_stats._SYMBOL.findall(cost or "")
    return ft.Row([_symbol(s, size) for s in symbols], spacing=2, tight=True)


def _dot(color, size=10):
    return ft.Container(width=size, height=size, border_radius=size / 2, bgcolor=MANA.get(color, GENERIC)[0])


def _colors(entries):
    # A list's colors: its commanders' color identity, or the colors of the cards in it
    commanders = [e for e in entries if e["section"] == "Commander"]
    source = commanders or deck_stats.counted(entries) or entries
    found = "".join((e["color_identity"] if commanders else e["colors"]) or "" for e in source)
    return "".join(c for c in "WUBRG" if c in found)


def _heading(text, size=14):
    return ft.Text(text, font_family=theme.TITLE_FONT, size=size, weight=ft.FontWeight.W_700)


def _bar(fraction, height=6, color=theme.GOLD):
    # A thin progress bar, fraction 0-1 of it filled
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * 1000)
    return ft.Container(ft.Row([
        ft.Container(bgcolor=color, border_radius=height / 2, height=height, expand=filled, visible=filled > 0),
        ft.Container(height=height, expand=1000 - filled, visible=filled < 1000)], spacing=0),
        bgcolor=theme.COLORS["surface_container_highest"], border_radius=height / 2, height=height)


def _check(ok, text):
    return ft.Row([ft.Text("✓" if ok else "✗", color=theme.GAIN if ok else theme.LOSS, weight=ft.FontWeight.BOLD),
                   ft.Text(text, size=12.5, expand=True)], vertical_alignment=ft.CrossAxisAlignment.START, spacing=6)


def _warn(lines):
    return ft.Container(ft.Column([ft.Text(f"⚠ {line}", size=12.5, color="#F0A7A0") for line in lines], spacing=3),
                        bgcolor="#2A1726", border=ft.Border.all(1, "#5A2A3A"), border_radius=8,
                        padding=ft.Padding.symmetric(horizontal=10, vertical=7))


def _dropdown(value, options, on_select, width=None):
    return ft.Dropdown(value=value, options=[ft.DropdownOption(key=k, text=t) for k, t in options], dense=True,
                       width=width, text_size=13, on_select=on_select, filled=True,
                       content_padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                       bgcolor=theme.COLORS["surface_container_low"],
                       border=ft.OutlineInputBorder(side=ft.BorderSide(1, theme.LINE), border_radius=6))


def _field(hint, on_submit=None, on_change=None, value="", width=None, expand=None, multiline=False):
    return ft.TextField(value=value, hint_text=hint, dense=True, width=width, expand=expand, multiline=multiline,
                        min_lines=8 if multiline else None, max_lines=14 if multiline else None, text_size=13,
                        filled=True, bgcolor=theme.COLORS["surface_container_low"],
                        border=ft.OutlineInputBorder(side=ft.BorderSide(1, theme.LINE), border_radius=6),
                        on_submit=on_submit, on_change=on_change)


def _oracle(card):
    # The card database row out of a Scryfall row, to remember a card added from Explore or Recommended
    return {k: card[k] for k in db._ORACLE_COLUMNS if k in card}


def _type_title(card_type):
    return {"Sorcery": "Sorceries", "Other": "Other"}.get(card_type, card_type + "s")


class DecksPage:
    def __init__(self, page, toast, busy):
        self.page, self.toast, self.busy = page, toast, busy
        self.view = ft.Container(expand=True)
        self.list_id = None
        self.home = {"kind": "all", "search": "", "sort": "Name"}
        self.tab = MY_CARDS  # instant; Recommended loads from Scryfall only when opened
        self.group = "Section"
        self.add_to = "Main"
        self.selected = None          # ("entry", id) or ("card", Scryfall/collection row)
        self.spellbook = {}           # list id -> Commander Spellbook's reading, until the list changes
        self.searches = {}            # (Scryfall query, pages) -> its cards, for the visit
        self.prepared = {}            # card name -> the card ready for scoring
        self.scored = {}              # (query, themes) -> synergy.score() result
        self.explore = {"query": "", "type": "", "rows": [], "page": 0, "more": False, "total": 0, "for": None,
                        "format": "casual", "colors": True}
        self.mine = {"search": "", "type": "", "legal": True}
        self.rec = {"list": None, "themes": [], "offered": [], "owned": False, "staples": True, "price": "Any price",
                    "shown": {}}
        self.collection_looked_up = False
        self.clicked_at = (None, 0)

    # Moving around

    def refresh(self):
        if self.list_id is not None and self._info() is None:
            self.list_id = None
        self.show_deck() if self.list_id is not None else self.show_home()

    def _info(self):
        return next((l for l in db.get_lists() if l["id"] == self.list_id), None)

    def open(self, list_id):
        self.list_id, self.selected = list_id, None
        self.show_deck()
        self.fill_card_data()

    def close(self, e=None):
        self.list_id = None
        self.show_home()

    def changed(self):
        # After an edit: Spellbook's reading is out of date
        self.spellbook.pop(self.list_id, None)
        self.update_deck()

    # Home: every list

    def show_home(self):
        owned = db.owned_by_name()
        everything = db.get_lists()
        lists = [l for l in everything
                 if (self.home["kind"] == "all" or l["kind"] == self.home["kind"])
                 and self.home["search"].lower() in l["name"].lower()]
        lists.sort(key=SORTS[self.home["sort"]])

        def chip(key, label):
            on = self.home["kind"] == key
            return ft.Container(ft.Text(label, size=12, color=theme.COLORS["on_surface"] if on else theme.MUTED),
                                bgcolor=theme.COLORS["primary_container"] if on else None, border_radius=14,
                                border=ft.Border.all(1, theme.COLORS["primary_container"] if on else theme.COLORS["outline"]),
                                padding=ft.Padding.symmetric(horizontal=12, vertical=5),
                                on_click=lambda e: self._set_home(kind=key))

        search = _field("Search decks…", width=240, value=self.home["search"],
                        on_submit=lambda e: self._set_home(search=e.control.value))
        toolbar = ft.Row([
            _heading("Decks", 24),
            ft.Text(f"{_plural(len(everything), 'list')} · {_money(sum(l['value'] for l in everything))} together",
                    color=theme.MUTED),
            ft.Container(expand=True), search, chip("all", "All"), chip("deck", "Decks"), chip("binder", "Binders"),
            chip("wishlist", "Wishlists"),
            _dropdown(self.home["sort"], [(k, f"Sort: {k}") for k in SORTS], lambda e: self._set_home(sort=e.control.value), 150),
            theme.button("Import deck…", lambda e: self.new_list(paste=True)),
            theme.button("+ New Deck", lambda e: self.new_list(), primary=True)], spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER)
        tiles = [self._list_tile(l, owned) for l in lists]
        tiles.append(ft.Container(
            ft.Column([ft.Text("+", size=30, color=theme.MUTED), ft.Text("New deck, binder or wishlist", color=theme.MUTED),
                       ft.Text("or paste a list from Arena, Moxfield…", size=11.5, color=theme.MUTED)],
                      horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=4),
            border=ft.Border.all(1, theme.COLORS["outline"]), border_radius=10, on_click=lambda e: self.new_list()))
        grid = ft.GridView(tiles, max_extent=330, child_aspect_ratio=1.25, spacing=16, run_spacing=16, expand=True)
        self.view.content = ft.Container(ft.Column([toolbar, grid], spacing=18, expand=True),
                                         padding=ft.Padding.symmetric(horizontal=PAGE_PADDING, vertical=18), expand=True)
        self.page.update()

    def _set_home(self, **changes):
        self.home.update(changes)
        self.show_home()

    def _list_tile(self, info, owned):
        entries = db.get_list_entries(info["id"])
        have = deck_stats.completion(entries, owned)
        cards, value, got, missing, _ = deck_stats.summary(entries, have)
        is_deck = info["kind"] == "deck"
        fmt = formats.FORMATS.get(info["format"], formats.FORMATS["casual"])
        size = sum(e["quantity"] for e in deck_stats.counted(entries))
        problems = formats.validate(entries, info["format"])[0] if is_deck else []
        commander = next((e for e in entries if e["section"] == "Commander" and e["image_url"]), None)
        showcase = commander or next(iter(deck_stats.priciest([e for e in entries if e["image_url"]], 1)), None)
        labels = [theme.pill(fmt.label if is_deck else KINDS[info["kind"]])]
        if is_deck and info["bracket"]:
            labels.append(ft.Container(ft.Text(f"Bracket {info['bracket']}", size=11, color=theme.GOLD), bgcolor="#3A3020",
                                       border_radius=10, padding=ft.Padding.symmetric(horizontal=8, vertical=2)))
        badge = ft.Container(ft.Text(f"⚠ {_plural(len(problems), 'problem')}", size=11, color=theme.LOSS),
                             bgcolor="#3B1F2A", border_radius=10, padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                             right=8, top=8, visible=bool(problems))
        banner = ft.Stack([
            ft.Container(height=120, bgcolor=theme.COLORS["surface_container_high"],
                         image=ft.DecorationImage(src=_art(showcase["image_url"]), fit=ft.BoxFit.COVER) if showcase else None),
            ft.Container(height=120, gradient=theme.gradient(["#00151229", theme.COLORS["surface"]], vertical=True)),
            badge], height=120)
        share = got / cards if cards else 0
        body = ft.Container(ft.Column([
            ft.Text(info["name"], font_family=theme.TITLE_FONT, size=16, weight=ft.FontWeight.W_700,
                    no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Row([*[_dot(c) for c in _colors(entries)], *labels], spacing=5),
            ft.Row([ft.Text(f"{size}/{fmt.deck_size}" if is_deck and fmt.deck_size else _plural(cards, "card")),
                    ft.Text(_money(value), color=theme.GOLD)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Text(f"You own {round(100 * share)}%" + (f" · {missing} missing" if missing else ""), size=11.5,
                    color=theme.MUTED),
            _bar(share)], spacing=6, tight=True), padding=ft.Padding.only(left=14, right=14, bottom=12))
        return ft.Container(ft.Column([banner, body], spacing=4), bgcolor=theme.COLORS["surface"],
                            border=ft.Border.all(1, theme.LINE), border_radius=10, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                            on_click=lambda e: self.open(info["id"]), ink=True)

    def new_list(self, paste=False):
        name = _field("e.g. Mono-Red Aggro, Trade Binder, Birthday Wishlist", width=400)
        kind = _dropdown("deck", KINDS.items(), None, 200)
        fmt = _dropdown("commander", [(k, f.label) for k, f in formats.FORMATS.items()], None, 260)
        kind.on_select = lambda e: (setattr(fmt, "visible", kind.value == "deck"), self.page.update())
        text = _field("Paste a deck list (optional): Arena, Moxfield, MTGO or \"4 Lightning Bolt\" lines",
                      multiline=True, width=536)
        text.visible = paste
        reveal = ft.TextButton("Paste a deck list…", visible=not paste)
        reveal.on_click = lambda e: (setattr(text, "visible", True), setattr(reveal, "visible", False), self.page.update())

        def create(e):
            pasted = (text.value or "").strip()
            if not name.value.strip():
                name.error_text = "Give it a name"
                self.page.update()
                return
            self.page.pop_dialog()
            self.list_id = db.create_list(name.value.strip(), kind.value, fmt.value if kind.value == "deck" else "casual")
            if pasted:
                self.import_text(pasted, is_deck=kind.value == "deck")
            self.open(self.list_id)

        rows = [("Name", name), ("Kind", kind), ("Format", fmt)]
        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("Import Deck" if paste else "New Deck"),
            content=ft.Column([*[ft.Row([ft.Text(f"{label}:", width=70), control]) for label, control in rows],
                               text, reveal], tight=True, width=560, spacing=12),
            actions=[theme.button("Cancel", lambda e: self.page.pop_dialog()), theme.button("Create", create, primary=True)]))

    # One list

    def fill_card_data(self):
        # Types, colors and legality of the list's cards this browser hasn't looked up yet
        missing = [e["name"] for e in db.get_list_entries(self.list_id) if e["legalities"] is None]
        if missing:
            rows = self.busy("Looking up cards", lambda: scryfall.fetch_card_data(missing))
            if rows:
                db.add_oracle_cards(rows)
                self.update_deck(browser=True)

    def _state(self):
        # Everything the deck's panels show, read once per change (None: the list is gone)
        info = self._info()
        if info is None:
            return None
        entries = db.get_list_entries(self.list_id)
        owned = db.owned_by_name()
        is_deck = info["kind"] == "deck"
        fmt = formats.FORMATS.get(info["format"], formats.FORMATS["casual"])
        problems, statuses = formats.validate(entries, info["format"]) if is_deck else ([], {})
        report = brackets.check(entries, self.spellbook.get(self.list_id)) if is_deck and fmt.commander else None
        if not is_deck:
            self.add_to = ""
        elif self.add_to not in SECTIONS:
            self.add_to = "Main"
        if self.tab == RECOMMENDED and not is_deck:
            self.tab = MY_CARDS
        self.s = dict(info=info, entries=entries, owned=owned, have=deck_stats.completion(entries, owned),
                      is_deck=is_deck, fmt=fmt, problems=problems, statuses=statuses, report=report)
        return self.s

    def show_deck(self):
        """Builds the deck page. Its panels stay in place afterwards and are updated one by
        one (update_deck, the tabs), so nothing scrolls back to the top on a click or an edit."""
        s = self._state()
        if s is None:
            return self.show_home()
        self.bar_box = ft.Container(self._deck_bar(s))
        self.tiles_box = ft.Container(self._tiles(s))
        self.detail_box = ft.Container(self._detail(s), expand=True)
        self.deck_rows = ft.ListView(expand=True)
        self.warn_box = ft.Container()
        self.tab_row = ft.Row(spacing=0)
        self.bodies = [ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO, expand=True) for _ in TABS]
        self.stale = set(range(len(TABS)))  # tabs to rebuild when next shown
        self.badges = {}                    # card name -> the grids' +/✓ marks for it
        self.body_box = ft.Container(padding=12, expand=True)
        self.view.content = ft.Container(ft.Column([
            self.bar_box, self.tiles_box,
            ft.Row([theme.panel(self.detail_box, width=DETAIL_WIDTH, padding=12),
                    theme.panel(self._deck_panel(s), expand=True),
                    theme.panel(ft.Column([self.tab_row, self.body_box], spacing=0, expand=True), width=BROWSER_WIDTH)],
                   expand=True, spacing=14, vertical_alignment=ft.CrossAxisAlignment.STRETCH)],
            spacing=12, expand=True), padding=ft.Padding.symmetric(horizontal=PAGE_PADDING, vertical=12), expand=True)
        self._fill_deck(s)
        self.show_tab(update=False)
        self.page.update()

    def update_deck(self, browser=False):
        """After an edit: the tiles, the list and the selected card again, and the grids' marks.
        The open tab keeps its place (Stats, or every tab when browser, is worked out again)."""
        s = self._state()
        if s is None:
            return self.show_home()
        self.bar_box.content = self._deck_bar(s)
        self.tiles_box.content = self._tiles(s)
        self.detail_box.content = self._detail(s)
        self._fill_deck(s)
        in_list = {e["name"] for e in s["entries"]}
        for name, marks in self.badges.items():
            for mark in marks:
                mark.value = "✓" if name in in_list else "+"
        self.stale |= set(range(len(TABS))) if browser else {STATS, RECOMMENDED}
        if self.tab == STATS or browser:
            self.show_tab(update=False)
        else:
            self.stale.discard(self.tab)  # the open tab stays as it is until its filters change
        self.page.update()

    def _deck_bar(self, s):
        info, is_deck = s["info"], s["is_deck"]
        controls = [theme.button("← All decks", self.close),
                    ft.Text(info["name"], font_family=theme.TITLE_FONT, size=22, weight=ft.FontWeight.W_700),
                    *[_dot(c) for c in _colors(s["entries"])]]
        if is_deck:
            controls.append(_dropdown(info["format"], [(k, f.label) for k, f in formats.FORMATS.items()],
                                      self.set_format, 230))
            if s["fmt"].commander:
                controls.append(_dropdown(str(info["bracket"] or ""), [("", "No target bracket")] + [
                    (str(b.number), f"Aiming for {brackets.label(b.number)}") for b in brackets.BRACKETS],
                    self.set_bracket, 300))
        else:
            controls.append(theme.pill(KINDS[info["kind"]]))
        controls += [ft.Container(expand=True), theme.button("Import…", lambda e: self.import_dialog()),
                     theme.button("Export…", lambda e: self.export_dialog(s["entries"])),
                     theme.button("Rename…", lambda e: self.rename(info)), theme.button("Delete", lambda e: self.delete(info))]
        return ft.Row(controls, spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _tiles(self, s):
        entries, fmt, is_deck = s["entries"], s["fmt"], s["is_deck"]
        cards, value, got, missing, cost = deck_stats.summary(entries, s["have"])
        size = sum(e["quantity"] for e in deck_stats.counted(entries))
        if is_deck and fmt.deck_size:
            first = tile("Cards", f"{size} / {fmt.deck_size}", "")
            first.content.controls[2] = _bar(size / fmt.deck_size)
        else:
            first = tile("Cards", str(cards), _plural(len({e['name'] for e in entries}), "different card"))
        tiles = [first,
                 tile("Value", f"${value:,.2f}", f"avg {_money(value / cards)} per card" if cards else "no cards yet",
                      value_color=theme.GOLD),
                 tile("You own", f"{got} of {cards}",
                      f"{missing} missing · {_money(cost)} to buy" if missing else "every card",
                      note_color=theme.LOSS if missing else theme.GAIN)]
        if s["report"] is not None:
            report, target = s["report"], s["info"]["bracket"]
            broken = report.broken(target) if target else []
            tiles.append(tile("Bracket", f"Fits {report.minimum()}" + (f" · aiming {target}" if target else ""),
                              f"Game Changers {len(report.game_changers)} · "
                              + ("combos checked" if report.combos_checked else "combos not checked"),
                              value_color=theme.LOSS if broken else None, small=True))
        elif is_deck:
            side = sum(e["quantity"] for e in entries if e["section"] in formats.SIDE_SECTIONS)
            tiles.append(tile("Sideboard", f"{side}" + (f" / {fmt.sideboard}" if fmt.sideboard is not None else ""),
                              "no limit" if fmt.sideboard is None else "cards at most", small=True))
        else:
            top = deck_stats.priciest(entries, 1)
            tiles.append(tile("Most valuable", top[0]["name"] if top else "—", _money(top[0]["price"]) if top else "",
                              small=True))
        if is_deck:
            tiles.append(tile("Legality", "Legal" if not s["problems"] else _plural(len(s["problems"]), "problem"),
                              s["problems"][0] if s["problems"] else f"in {fmt.label}",
                              value_color=theme.GAIN if not s["problems"] else theme.LOSS, small=True))
        else:
            tiles.append(tile("Unique cards", str(len({e['name'] for e in entries})), f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'}"))
        return ft.Row(tiles, spacing=12, height=92, vertical_alignment=ft.CrossAxisAlignment.STRETCH)

    # Left: the selected card

    def _selected_card(self, s):
        if self.selected is None:
            return None, None
        kind, value = self.selected
        if kind == "entry":
            entry = next((e for e in s["entries"] if e["id"] == value), None)
            return (entry, entry) if entry else (None, None)
        return value, None

    def _detail(self, s):
        card, entry = self._selected_card(s)
        if card is None:
            return ft.Column([ft.Text("Click a card in the deck or on the right to see it here.", italic=True,
                                      color=theme.MUTED, text_align=ft.TextAlign.CENTER)],
                             alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        info, fmt = s["info"], s["info"]["format"]
        in_list = sum(e["quantity"] for e in s["entries"] if e["name"] == card["name"])
        owned = s["owned"].get(card["name"].lower(), 0)
        legality = formats.legality(card, fmt) if s["is_deck"] and fmt != "casual" and card["legalities"] else None
        where = " · ".join(x for x in (card["set_name"], f"#{card['collector_number']}" if card["collector_number"] else "",
                                       scryfall.finish_label(card["foil"] or 0)) if x)
        lines = [ft.Text(where, size=12, color=theme.MUTED),
                 ft.Text(f"You own {owned} · In this {KINDS[info['kind']].lower()} {in_list} · {_money(card['price'])}",
                         size=12.5)]
        if legality:
            ok = legality in ("legal", "restricted")
            lines.append(ft.Text(f"{formats.label(fmt)}: {legality.replace('_', ' ').capitalize()}", size=12.5,
                                 color=theme.GAIN if ok else theme.LOSS))
        if entry is not None and entry["id"] in s["statuses"]:
            lines.append(ft.Text(s["statuses"][entry["id"]], size=12.5, color=theme.LOSS))
        if card["game_changer"]:
            lines.append(ft.Text("◆ Game Changer", size=12.5, color=theme.GOLD))
        if entry is not None:
            sections = [(sec, SECTION_TITLES[sec]) for sec in SECTIONS] if s["is_deck"] else []
            actions = [theme.button("−1", lambda e: self.change_quantity(entry, -1)),
                       theme.button("+1", lambda e: self.change_quantity(entry, 1)),
                       theme.button("Printing…", lambda e: self.pick_printing(entry)),
                       *([ft.PopupMenuButton(content=ft.Container(ft.Text("Move ▾", size=13), border_radius=6,
                                                                  border=ft.Border.all(1, theme.COLORS["outline"]),
                                                                  padding=ft.Padding.symmetric(horizontal=12, vertical=8)),
                                             items=[ft.PopupMenuItem(content=f"To {title}",
                                                                     on_click=lambda e, sec=sec: self.move(entry, sec))
                                                    for sec, title in sections if sec != entry["section"]])]
                         if sections else []),
                       theme.button("Remove", lambda e: self.change_quantity(entry, -entry["quantity"]))]
        else:
            target = SECTION_TITLES[self.add_to] if s["is_deck"] else "the list"
            actions = [theme.button(f"+ Add to {target}", lambda e: self.add(card), primary=True),
                       *([theme.button("+4", lambda e: self.add(card, 4))] if s["fmt"].copies != 1 else [])]
        return ft.Column([
            *([ft.Image(src=card["image_url"], width=DETAIL_WIDTH - 24, border_radius=10)] if card["image_url"] else []),
            ft.Text(card["name"], font_family=theme.TITLE_FONT, size=15, weight=ft.FontWeight.W_700, color=theme.GOLD),
            ft.Row([mana(card["mana_cost"]), ft.Text(card["type_line"] or "", size=12, color=theme.MUTED, expand=True)],
                   spacing=6, vertical_alignment=ft.CrossAxisAlignment.START),
            *([ft.Text(card["oracle_text"], size=12.5)] if card["oracle_text"] else []),
            *lines, ft.Row(actions, spacing=6, wrap=True, run_spacing=6)], spacing=7, scroll=ft.ScrollMode.AUTO)

    # Middle: the list

    def _deck_panel(self, s):
        quick = _field('+ Quick add: type "4 Lightning Bolt" and press Enter', expand=True,
                       on_submit=lambda e: self.quick_add(e.control.value))
        tools = [quick]
        if s["is_deck"]:
            tools += [_dropdown(self.add_to, [(sec, f"Add to: {SECTION_TITLES[sec]}") for sec in SECTIONS],
                                lambda e: self.set_add_to(e.control.value), 190),
                      _dropdown(self.group, [("Section", "Group: Section"), ("Type", "Group: Type")],
                                lambda e: self.set_group(e.control.value), 160)]
        header = ft.Container(ft.Row([self._cell(ft.Text(label.upper(), size=11, weight=ft.FontWeight.W_600,
                                                         color=theme.GOLD), width, right)
                                      for label, width, right in GRID_HEADERS], spacing=8),
                              bgcolor=theme.COLORS["surface_container"], padding=ft.Padding.symmetric(horizontal=10, vertical=8))
        return ft.Column([
            ft.Container(ft.Row(tools, spacing=8), padding=10, border=ft.Border.only(bottom=ft.BorderSide(1, theme.LINE))),
            self.warn_box, header, self.deck_rows], spacing=0, expand=True)

    def _fill_deck(self, s):
        # The list's rows, into the same list (so it keeps its scroll position)
        self.warn_box.content = (ft.Container(_warn(s["problems"]), padding=ft.Padding.only(left=10, right=10, top=8, bottom=8))
                                 if s["problems"] else None)
        rows, self.row_boxes = [], {}
        for title, group in self._groups(s):
            rows.append(ft.Container(
                ft.Text(f"{title} — {sum(e['quantity'] for e in group)}", font_family=theme.TITLE_FONT, size=12.5,
                        weight=ft.FontWeight.W_600, color=theme.GOLD),
                bgcolor=theme.COLORS["surface_container_low"], padding=ft.Padding.symmetric(horizontal=10, vertical=6)))
            rows += [self._deck_row(e, s) for e in group]
        if not s["entries"]:
            rows.append(ft.Container(ft.Text("No cards yet: quick add above, or pick some from the right.", color=theme.MUTED),
                                     padding=20))
        self.deck_rows.controls = rows

    def set_add_to(self, section):
        self.add_to = section
        self.detail_box.content = self._detail(self.s)  # its Add button names the section
        self.page.update()

    def set_group(self, group):
        self.group = group
        self._fill_deck(self.s)
        self.page.update()

    @staticmethod
    def _cell(control, width, right=False):
        share = width <= FLEX
        return ft.Container(control, width=None if share else width, expand=width if share else None,
                            alignment=ft.Alignment.CENTER_RIGHT if right else ft.Alignment.CENTER_LEFT)

    @staticmethod
    def _front_type(entry):
        front = (entry["type_line"] or "").split("//")[0]
        return next((t for t in formats.CARD_TYPES if t in front), "Other")

    def _groups(self, s):
        entries, is_deck = s["entries"], s["is_deck"]
        if not is_deck:
            return [("Cards", entries)] if entries else []
        if self.group == "Type":
            main = [e for e in entries if e["section"] == "Main"]
            groups = [("Commander", [e for e in entries if e["section"] == "Commander"])]
            groups += [(_type_title(t), [e for e in main if self._front_type(e) == t]) for t in formats.CARD_TYPES + ["Other"]]
            groups += [(SECTION_TITLES[sec], [e for e in entries if e["section"] == sec])
                       for sec in SECTIONS if sec not in ("Commander", "Main")]
            return [(t, g) for t, g in groups if g]
        groups = [(SECTION_TITLES.get(sec, sec), [e for e in entries if e["section"] == sec])
                  for sec in SECTIONS + sorted({e["section"] for e in entries} - set(SECTIONS))]
        return [(t, g) for t, g in groups if g or t == "Main Deck"]

    def _deck_row(self, e, s):
        status = s["statuses"].get(e["id"])
        have = s["have"].get(e["id"], 0)
        legal = formats.legality(e, s["info"]["format"]) if s["is_deck"] and s["info"]["format"] != "casual" else "legal"
        # The name shrinks, with an ellipsis, before its labels do
        name = [ft.Text(e["name"], color=theme.LOSS if status else None, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS,
                        expand=True, tooltip=e["name"])]
        if e["game_changer"]:
            name.append(ft.Container(ft.Text("◆ GC", size=10.5, color=theme.GOLD), bgcolor="#3A3020", border_radius=8,
                                     padding=ft.Padding.symmetric(horizontal=6, vertical=1), tooltip="Game Changer"))
        if status:
            name.append(ft.Text(status, size=11, color=theme.LOSS))
        mark = "?" if legal is None else "✗" if status else "✓"
        cells = [ft.Text(str(e["quantity"])), ft.Row(name, spacing=6),
                 ft.Text(e["type_line"] or "", color=theme.MUTED, size=12, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                 mana(e["mana_cost"], 15), ft.Text(_money(e["price"])),
                 ft.Text(f"{have}/{e['quantity']}", color=theme.GAIN if have >= e["quantity"] else theme.LOSS),
                 ft.Text(mark, color=theme.MUTED if legal is None else theme.LOSS if status else theme.GAIN,
                         tooltip="Legality not looked up yet" if legal is None else status)]
        on = self.selected == ("entry", e["id"])
        box = ft.Container(
            ft.Row([self._cell(c, w, r) for c, (_, w, r) in zip(cells, GRID_HEADERS)], spacing=8),
            bgcolor=theme.COLORS["primary_container"] if on else None, on_click=lambda ev: self.click_entry(e),
            padding=ft.Padding.symmetric(horizontal=10, vertical=5),
            border=ft.Border.only(bottom=ft.BorderSide(1, theme.LINE)))
        self.row_boxes[e["id"]] = box
        return ft.ContextMenu(box, secondary_items=self._entry_menu(e, s), secondary_trigger=ft.ContextMenuTrigger.DOWN)

    def _entry_menu(self, e, s):
        # Right-click on a card in the list
        def item(text, action):
            return ft.PopupMenuItem(content=text, on_click=lambda ev: action())

        items = [item("Add one", lambda: self.change_quantity(e, 1)),
                 item("Remove one", lambda: self.change_quantity(e, -1)),
                 item(f"Remove all {e['quantity']}", lambda: self.change_quantity(e, -e["quantity"])),
                 item("Change printing…", lambda: self.pick_printing(e))]
        if s["is_deck"]:
            if s["fmt"].commander and e["section"] != "Commander":
                items.append(item("Make it the commander", lambda: self.move(e, "Commander")))
            items += [item(f"Move to {SECTION_TITLES[sec]}", lambda sec=sec: self.move(e, sec))
                      for sec in SECTIONS if sec != e["section"] and not (sec == "Commander" and s["fmt"].commander)]
        return items + self._card_links(e)

    def _card_links(self, card):
        # Menu items every card gets: its Scryfall page, and copying its name
        items = [ft.PopupMenuItem(content="Copy name",
                                  on_click=lambda ev: (self.page.run_task(ft.Clipboard().set, card["name"]),
                                                       self.toast(f"Copied {card['name']}.")))]
        if card["set_code"] and card["collector_number"]:
            url = scryfall.scryfall_page(card["set_code"], card["collector_number"])
            items.insert(0, ft.PopupMenuItem(content="View on Scryfall",
                                             on_click=lambda ev: self.page.run_task(ft.UrlLauncher().launch_url, url)))
        return items

    def click_entry(self, entry):
        # A second click on the same row soon after adds a copy, like +1
        now = time.monotonic()
        last, at = self.clicked_at
        self.clicked_at = (entry["id"], now)
        if last == entry["id"] and now - at < 0.5 and self.selected == ("entry", entry["id"]):
            self.change_quantity(entry, 1)
            return
        self.select(("entry", entry["id"]))

    def select(self, selected):
        # Moves the highlight and shows the card on the left, leaving everything else in place
        if self.selected and self.selected[0] == "entry" and self.selected[1] in self.row_boxes:
            self.row_boxes[self.selected[1]].bgcolor = None
        self.selected = selected
        if selected[0] == "entry" and selected[1] in self.row_boxes:
            self.row_boxes[selected[1]].bgcolor = theme.COLORS["primary_container"]
        self.detail_box.content = self._detail(self.s)
        self.page.update()

    # Right: cards to add, and the deck's stats

    def show_tab(self, index=None, update=True):
        """Shows a tab of the right panel. Each keeps its own contents and scroll position; one
        is only worked out again when it's stale (its filters changed, or the deck did)."""
        s = self.s
        if index is not None:
            self.tab = index

        def tab(i, label):
            on = i == self.tab
            usable = i != RECOMMENDED or s["is_deck"]
            return ft.Container(ft.Text(label, font_family=theme.TITLE_FONT, size=12, weight=ft.FontWeight.W_600, no_wrap=True,
                                        color=theme.GOLD if on else theme.MUTED if usable else theme.LINE,
                                        text_align=ft.TextAlign.CENTER),
                                expand=True, padding=ft.Padding.symmetric(vertical=9), alignment=ft.Alignment.CENTER,
                                bgcolor=theme.COLORS["surface_container"] if on else None,
                                border=ft.Border.only(bottom=ft.BorderSide(2, theme.GOLD if on else ft.Colors.TRANSPARENT)),
                                on_click=(lambda e: self.show_tab(i)) if usable else None,
                                tooltip=None if usable else "Recommendations are for decks")

        self.tab_row.controls = [tab(i, label) for i, label in enumerate(TABS)]
        if self.tab in self.stale:
            self.refill_tab(update=False)
        self.body_box.content = self.bodies[self.tab]
        if update:
            self.page.update()

    def refill_tab(self, update=True):
        # Works the open tab out again, into the same column (so a Show More keeps its place)
        self.stale.discard(self.tab)
        self.filling = self.tab
        built = [self._my_cards, self._explore, self._recommended, self._stats][self.tab](self.s)
        self.bodies[self.tab].controls = built.controls if isinstance(built, ft.Column) else [built]
        if update:
            self.page.update()

    def _card_grid(self, cards, s):
        # Cards as small images with a caption and a + button; click one to see it on the left,
        # right-click for more
        in_list = {e["name"] for e in s["entries"]}

        def item(card):
            owned = s["owned"].get(card["name"].lower(), 0)
            caption = card.get("note") or (f"Own {owned} · {_money(card['price'])}" if owned else _money(card["price"]))
            mark = ft.Text("✓" if card["name"] in in_list else "+", size=13, weight=ft.FontWeight.BOLD, color="#1A1300")
            self.badges.setdefault(card["name"], []).append(mark)
            box = ft.Container(ft.Column([
                ft.Image(src=_small(card["image_url"]), width=GRID_CARD, border_radius=6,
                         error_content=ft.Text(card["name"], size=11)),
                ft.Row([ft.Text(caption, size=10.5, color=theme.GOLD if card.get("note") else theme.MUTED, expand=True,
                                no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Container(mark, width=20, height=20, border_radius=10, bgcolor=theme.GOLD,
                                     alignment=ft.Alignment.CENTER, on_click=lambda e: self.add(card),
                                     tooltip=f"Add to {SECTION_TITLES[self.add_to] if s['is_deck'] else 'the list'}")],
                       spacing=4)], spacing=3, tight=True),
                width=GRID_CARD, on_click=lambda e: self.select(("card", card)))
            return ft.ContextMenu(box, secondary_items=self._card_menu(card, s), secondary_trigger=ft.ContextMenuTrigger.DOWN)

        return ft.Row([item(c) for c in cards], wrap=True, spacing=8, run_spacing=10)

    def _card_menu(self, card, s):
        # Right-click on a card to add: where it goes, and how many
        def add(section, quantity=1):
            return lambda ev: self.add(card, quantity, section)

        items = [ft.PopupMenuItem(content="Show it on the left", on_click=lambda ev: self.select(("card", card)))]
        if s["is_deck"]:
            sections = ([self.add_to] + [sec for sec in SECTIONS if sec != self.add_to])
            items += [ft.PopupMenuItem(content=f"Add to {SECTION_TITLES[sec]}", on_click=add(sec)) for sec in sections]
            if s["fmt"].copies != 1:
                items.append(ft.PopupMenuItem(content=f"Add 4 to {SECTION_TITLES[self.add_to]}", on_click=add(self.add_to, 4)))
        else:
            items.append(ft.PopupMenuItem(content="Add to the list", on_click=add("")))
        items.append(ft.PopupMenuItem(content="Add to my collection…", on_click=lambda ev: self.to_collection(card)))
        return items + self._card_links(card)

    def to_collection(self, card):
        # The Add Card window, already looking at this card
        def saved(data):
            db.add_card(**data)
            self.s["owned"] = db.owned_by_name()
            self.toast(f"Added {data['quantity']}× {data['name']} to your collection.")

        card_form.open_card_form(self.page, saved, name=card["name"])

    @staticmethod
    def _type_options():
        return [("", "Any type")] + [(t, t) for t in formats.CARD_TYPES]

    def _my_cards(self, s):
        if not self.collection_looked_up:
            # Once a visit: the types, colors and legality of collection cards not looked up yet
            self.collection_looked_up = True
            rows, _ = db.search_cards(True, limit=1_000_000)
            missing = sorted({r["name"] for r in rows if r["type_line"] is None})
            if missing:
                found = self.busy("Looking up your cards", lambda: scryfall.fetch_card_data(missing))
                if found:
                    db.add_oracle_cards(found)
        fmt = s["info"]["format"] if s["is_deck"] else None
        identity = _colors(s["entries"]) if s["is_deck"] and s["fmt"].commander and any(
            e["section"] == "Commander" for e in s["entries"]) else None
        legal = self.mine["legal"] and fmt not in (None, "casual")
        rows, total = db.search_cards(True, self.mine["search"], self.mine["type"], format_key=fmt if legal else None,
                                      identity=identity if legal else None, limit=MY_CARDS_SHOWN, sort="Owned (most first)")
        search = _field("Search your cards: name, type or rules text", expand=True, value=self.mine["search"],
                        on_submit=lambda e: self._mine(search=e.control.value))
        filters = ft.Row([_dropdown(self.mine["type"], self._type_options(), lambda e: self._mine(type=e.control.value), 150),
                          ft.Checkbox(label="Legal here only",
                                      tooltip="Cards legal in this format" + (" and the commander's colors" if identity else ""),
                                      value=self.mine["legal"], visible=fmt not in (None, "casual"),
                                      on_change=lambda e: self._mine(legal=e.control.value))], spacing=10)
        note = ft.Text(f"{total} of your cards" + (f", showing the first {MY_CARDS_SHOWN}" if total > MY_CARDS_SHOWN else ""),
                       size=12, color=theme.MUTED)
        return ft.Column([ft.Row([search]), filters, note, self._card_grid([dict(r) for r in rows], s)],
                         spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)

    def _mine(self, **changes):
        self.mine.update(changes)
        self.refill_tab()

    def _scope(self, s, commander_only=False):
        # The Scryfall filter for cards that could go in this deck: its format, and a
        # Commander deck's color identity (or, for Explore's Deck's colors, another deck's colors)
        parts = []
        if s["is_deck"] and s["info"]["format"] != "casual":
            parts.append(f"legal:{s['info']['format']}")
            if not s["fmt"].commander:
                # Cards made for Commander (Command Tower, Arcane Signet) can be legal elsewhere,
                # but only do anything with a commander
                parts.append("-o:commander")
        colors = _colors(s["entries"])
        has_commander = any(e["section"] == "Commander" for e in s["entries"])
        if s["is_deck"] and ((s["fmt"].commander and has_commander) or (not commander_only and colors)):
            parts.append(f"id<={colors or 'c'}")
        return " ".join(parts)

    def _explore(self, s):
        # A Commander deck always stays in its commander's colors (a rule); other decks can look further
        scope = self._scope(s, commander_only=not self.explore["colors"])
        query = " ".join(x for x in (self.explore["query"], f"t:{self.explore['type']}" if self.explore["type"] else "",
                                     scope) if x) or "game:paper"
        if self.explore["for"] != query:
            self.explore.update(rows=[], page=0, more=True, total=0, format=s["info"]["format"], **{"for": query})
            self.load_explore(show=False)
        search = _field("Search Scryfall: a name, or t:dragon, o:\"draw a card\", cmc<=2…", expand=True,
                        value=self.explore["query"], on_submit=lambda e: self._explore_set(query=e.control.value.strip()))
        filters = ft.Row([_dropdown(self.explore["type"], self._type_options(),
                                    lambda e: self._explore_set(type=e.control.value), 150),
                          ft.Checkbox(label="Deck's colors", value=self.explore["colors"],
                                      visible=s["is_deck"] and not s["fmt"].commander and bool(_colors(s["entries"])),
                                      on_change=lambda e: self._explore_set(colors=e.control.value)),
                          ft.Text(f"Within: {scope}" if scope else "Every card", size=12, color=theme.MUTED, expand=True,
                                  no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)], spacing=8)
        found = self.explore["rows"]
        order = popularity_order(s["info"]["format"])[2]
        note = ft.Text(f"{self.explore['total']:,} cards, {order}" if found else "No cards match.", size=12,
                       color=theme.MUTED)
        more = theme.button(f"Load {scryfall.SEARCH_PAGE} more", lambda e: self.load_explore())
        more.visible = self.explore["more"] and bool(found)
        return ft.Column([ft.Row([search]), filters, note, self._card_grid(found, s), more],
                         spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)

    def _explore_set(self, **changes):
        self.explore.update(changes)
        self.refill_tab()

    def load_explore(self, show=True):
        page = self.explore["page"] + 1
        order, direction, _ = popularity_order(self.explore["format"])
        result = self.busy("Searching Scryfall", lambda: scryfall.search(self.explore["for"], page, order, direction))
        if result:
            rows, more, total = result
            self.explore.update(rows=self.explore["rows"] + rows, page=page, more=more, total=total)
        else:
            self.explore["more"] = False
        if show:
            self.refill_tab()

    def _search(self, query, pages, format_key):
        # One Scryfall search's first pages, most played first; kept for the visit
        key = (query, pages)
        if key not in self.searches:
            order, direction, _ = popularity_order(format_key)
            rows = []
            for page in range(1, pages + 1):
                found, more, _ = scryfall.search(query, page, order, direction)
                rows += found
                if not more:
                    break
            self.searches[key] = rows
        return self.searches[key]

    def _commander_pool(self, scope, theme_keys):
        """(pool, {tag: names}) for a Commander deck, like the desktop's whole card database but
        fetched to fit: the most played cards in its colors, plus for each theme the cards its
        rules-text pattern finds and the cards Scryfall tags for it (which also give the tags)."""
        queries = [(scope, GENERAL_PAGES, None)]
        for key in theme_keys:
            if key.startswith("tribal:"):
                creature_type = key.split(":", 1)[1]
                queries.append((f"{scope} (t:{creature_type} or o:/\\b{creature_type}s?\\b/)", THEME_PAGES, None))
                continue
            chosen = synergy.theme(key)
            # A / would end Scryfall's regular expression early (+1/+1)
            queries.append((f"{scope} o:/{chosen.cards.replace('/', chr(92) + '/')}/", THEME_PAGES, None))
            if chosen.tags:
                # One search for all of a theme's tags: scoring only asks whether a card has any of them
                queries.append((f"{scope} ({' or '.join(f'otag:{t}' for t in chosen.tags)})", TAG_PAGES, chosen.tags))
        found = self.busy("Loading cards for these themes",
                          lambda: [(tag_names, self._search(q, pages, "commander")) for q, pages, tag_names in queries])
        if found is None:
            return None, None
        pool, tags = {}, {}
        for tag_names, rows in found:
            for r in rows:
                pool.setdefault(r["name"], r)
            for tag in tag_names or ():
                tags[tag] = {r["name"] for r in rows}
        return [self._prepared(r) for r in pool.values()], tags

    def _prepared(self, row):
        # A card ready for synergy's scoring, worked out once per card
        if row["name"] not in self.prepared:
            self.prepared[row["name"]] = {**row, "owned": 0,
                                          "text": f"{row['type_line'] or ''}\n{row['oracle_text'] or ''}",
                                          "phrases": synergy.phrases(row["oracle_text"], row["name"])}
        return self.prepared[row["name"]]

    def _commander_sections(self, s, commanders, identity):
        rec, report = self.rec, s["report"]
        scope = self._scope(s)
        key = (scope, tuple(rec["themes"]))
        if key not in self.scored:
            pool, tags = self._commander_pool(scope, rec["themes"])
            if pool is None:
                return None
            self.scored[key] = synergy.score(pool, rec["themes"], tags, commanders)
        owned = s["owned"]
        scored = [{**r, "owned": owned.get(r["name"].lower(), 0)} for r in self.scored[key]] if rec["owned"] else self.scored[key]
        return synergy.recommend(
            commanders, scored, in_deck=[e["name"] for e in s["entries"]], owned_only=rec["owned"],
            max_price=PRICES[rec["price"]], staples=rec["staples"], bracket=s["info"]["bracket"], precon_title="",
            game_changers=len(report.game_changers) if report else 0, more=dict(rec["shown"]))

    def _theme_picker(self, commanders):
        # Suggested themes as chips, every other theme (and tribe) under More themes, like the desktop
        rec = self.rec

        def chip(key):
            on = key in rec["themes"]
            return ft.Container(ft.Text(synergy.theme(key).label, size=12, color=theme.COLORS["on_surface"] if on else theme.MUTED),
                                bgcolor=theme.COLORS["primary_container"] if on else None, border_radius=14,
                                border=ft.Border.all(1, theme.COLORS["primary_container"] if on else theme.COLORS["outline"]),
                                padding=ft.Padding.symmetric(horizontal=11, vertical=4), on_click=lambda e: self.toggle_theme(key))

        shown = list(dict.fromkeys(rec["offered"] + rec["themes"]))
        own_types = [f"tribal:{t}" for c in commanders for t in synergy.creature_types(c)]
        others = [k for k in dict.fromkeys(list(synergy.THEMES) + own_types) if k not in shown]
        more = ft.PopupMenuButton(
            content=ft.Container(ft.Text("More themes ▾", size=12, color=theme.GOLD), border_radius=14,
                                 border=ft.Border.all(1, theme.COLORS["outline"]),
                                 padding=ft.Padding.symmetric(horizontal=11, vertical=4)),
            items=[ft.PopupMenuItem(content=synergy.theme(k).label, on_click=lambda e, k=k: self.toggle_theme(k))
                   for k in sorted(others, key=lambda k: synergy.theme(k).label)]
                  + [ft.PopupMenuItem(content="Another creature type…", on_click=lambda e: self.ask_tribe())])
        return ft.Row([chip(k) for k in shown] + [more], wrap=True, spacing=4, run_spacing=4)

    def ask_tribe(self):
        name = _field("e.g. Elf, Dragon, Zombie", width=260)

        def go(e):
            self.page.pop_dialog()
            kind = name.value.strip().title()
            if kind and f"tribal:{kind}" not in self.rec["themes"]:
                self.toggle_theme(f"tribal:{kind}")

        name.on_submit = go
        self.page.show_dialog(ft.AlertDialog(title=ft.Text("Build Around a Creature Type"), content=name, actions=[
            theme.button("Cancel", lambda e: self.page.pop_dialog()), theme.button("Add", go, primary=True)]))

    def _recommended(self, s):
        entries = s["entries"]
        if not s["fmt"].commander:
            # As on the desktop (lists.py): recommendations are for Commander decks only
            return ft.Text("Recommendations are for Commander decks. Pick a deck with a Commander-style "
                           "format (Commander, Brawl, Oathbreaker…), or start one with New….", color=theme.MUTED)
        commanders = [dict(e) for e in entries if e["section"] == "Commander" and e["oracle_text"] is not None]
        if not commanders:
            return ft.Text("Put a card in the Commander section (select it, then Move ▾ on the left) to get "
                           "recommendations for it.", color=theme.MUTED)
        rec = self.rec
        identity = synergy.identity_of(commanders)
        if rec["list"] != self.list_id:
            # The commander's own suggestions, as on the desktop: creature types it names count
            # as tribes (known types: the ones in its colors' most played cards)
            common = self.busy("Loading cards", lambda: self._search(self._scope(s), GENERAL_PAGES, "commander")) or []
            offered = synergy.suggest_themes(commanders, synergy.known_types(r["type_line"] for r in common))
            rec.update(list=self.list_id, offered=offered[:THEMES_OFFERED], themes=offered[:2], shown={})
        sections = self._commander_sections(s, commanders, identity)
        if sections is None:
            return ft.Text("Couldn't load cards from Scryfall. Try again in a moment.", color=theme.MUTED)

        filters = [ft.Checkbox(label="Cards I own", value=rec["owned"], on_change=lambda e: self._rec(owned=e.control.value)),
                   ft.Checkbox(label="Staples", value=rec["staples"], on_change=lambda e: self._rec(staples=e.control.value)),
                   _dropdown(rec["price"], [(k, k) for k in PRICES], lambda e: self._rec(price=e.control.value), 130)]
        controls = [ft.Text(f"Build around (color identity {identity or 'colorless'}):", size=12, color=theme.MUTED),
                    self._theme_picker(commanders), ft.Row(filters, spacing=4)]
        if s["info"]["bracket"]:
            controls.append(ft.Text(f"Aiming for {brackets.label(s['info']['bracket'])}: cards that don't fit are left out.",
                                    size=11.5, color=theme.MUTED))
        for title, rows, more in sections:
            shown = min(len(rows), SHOWN + rec["shown"].get(title, 0))
            left = len(rows) - shown + more
            controls += [ft.Row([ft.Text(title, font_family=theme.TITLE_FONT, size=14, weight=ft.FontWeight.W_700),
                                 ft.Text(str(len(rows) + more), color=theme.MUTED), ft.Container(expand=True),
                                 ft.TextButton(f"Show more ({left} left)", visible=left > 0,
                                               on_click=lambda e, t=title: self._show_more(t))]),
                         self._card_grid(rows[:shown], s)]
        if not sections:
            controls.append(ft.Text("Nothing fits these filters.", color=theme.MUTED))
        return ft.Column(controls, spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)

    def toggle_theme(self, key):
        themes = self.rec["themes"]
        self.rec["themes"] = [k for k in themes if k != key] if key in themes else themes + [key]
        self.rec["shown"] = {}
        self.refill_tab()

    def _rec(self, **changes):
        self.rec.update(changes)
        self.refill_tab()

    def _show_more(self, title):
        self.rec["shown"][title] = self.rec["shown"].get(title, 0) + SHOW_MORE
        self.refill_tab()

    def _stats(self, s):
        # Binders and wishlists count every card; decks their main deck and command zone
        counted = deck_stats.counted(s["entries"]) if s["is_deck"] else [{**dict(e), "section": "Main"} for e in s["entries"]]
        if not counted:
            return ft.Text("Add cards to see their stats.", color=theme.MUTED)
        curve = deck_stats.mana_curve(counted)
        peak = max(curve.values()) or 1
        bars = ft.Row([ft.Column([
            ft.Text(str(n), size=11, color=theme.MUTED, text_align=ft.TextAlign.CENTER),
            ft.Container(height=max(2, 100 * n / peak), border_radius=ft.BorderRadius.only(top_left=4, top_right=4),
                         gradient=theme.gradient([theme.GOLD, theme.COLORS["secondary"]], vertical=True)),
            ft.Text(f"{mv}+" if mv == deck_stats.CURVE_TOP else str(mv), size=11, text_align=ft.TextAlign.CENTER)],
            spacing=3, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, alignment=ft.MainAxisAlignment.END, expand=True)
            for mv, n in curve.items()], spacing=6, height=140, vertical_alignment=ft.CrossAxisAlignment.END)
        average = deck_stats.average_mana_value(counted)
        symbols = deck_stats.color_symbols(counted)
        all_symbols = sum(symbols.values()) or 1
        colors = [ft.Row([_dot(c, 12), ft.Text(COLOR_NAMES[c], size=12, width=70),
                          ft.Container(_bar(n / all_symbols, color=MANA.get(c, GENERIC)[0]), expand=True),
                          ft.Text(f"{n} · {round(100 * n / all_symbols)}%", size=11.5, width=64, text_align=ft.TextAlign.RIGHT)],
                         spacing=6) for c, n in symbols.items()]
        types = formats.type_counts(counted)
        most = max(types.values(), default=1)
        type_rows = [ft.Row([ft.Text(_type_title(t), size=12, width=96), ft.Container(_bar(n / most), expand=True),
                             ft.Text(str(n), size=11.5, width=28, text_align=ft.TextAlign.RIGHT)], spacing=6)
                     for t, n in sorted(types.items(), key=lambda kv: -kv[1])]
        lands, size = types.get("Land", 0), sum(e["quantity"] for e in counted)
        controls = [_heading("Mana curve"), bars,
                    ft.Text(f"Average mana value {average:.2f}, lands left out" if average is not None
                            else "No spells looked up yet.", size=12, color=theme.MUTED),
                    _heading("Colors"), *(colors or [ft.Text("No colored mana symbols.", size=12, color=theme.MUTED)]),
                    _heading("Types"), *type_rows,
                    ft.Text(f"{lands} lands of {size} cards ({round(100 * lands / size)}%)", size=12, color=theme.MUTED),
                    _heading("Most valuable"),
                    *[ft.Row([ft.Text(e["name"], size=12.5, expand=True, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                              ft.Text(_money(e["price"]), size=12.5, color=theme.GOLD)])
                      for e in deck_stats.priciest(s["entries"])]]
        if s["is_deck"]:
            controls += [_heading("Checks"), *self._checks(s)]
        return ft.Column(controls, spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)

    def _checks(self, s):
        fmt, report = s["fmt"], s["report"]
        lines = [_check(False, p) for p in s["problems"]]
        if not s["problems"]:
            lines.append(_check(True, f"Follows the {fmt.label} rules: size, copies, bans"
                                      + (" and color identity" if fmt.commander else "")))
        if report is not None:
            target = s["info"]["bracket"]
            broken = dict(report.broken(target)) if target else {}
            lines.append(_check(not broken.get("Game Changers"), f"Game Changers: {', '.join(report.game_changers) or 'none'}"))
            for title, names in (("Mass land denial", report.mass_land_denial), ("Extra turns", report.extra_turns)):
                lines.append(_check(not broken.get(title), f"{title}: {', '.join(names) or 'none'}"))
            if report.combos_checked:
                combos = [" + ".join(c.cards) for c in report.combos]
                lines.append(_check(not broken.get("Two-card combos"), f"Two-card combos: {', '.join(combos) or 'none'}"))
            else:
                lines.append(theme.button("Check for combos (Commander Spellbook)", lambda e: self.check_combos(s)))
            lines.append(ft.Text(f"These cards fit {brackets.label(report.minimum())}.", size=12, color=theme.MUTED))
        return lines

    def check_combos(self, s):
        commanders = [e["name"] for e in s["entries"] if e["section"] == "Commander"]
        main = [e["name"] for e in s["entries"] if e["section"] == "Main"]
        found = self.busy("Checking combos", lambda: brackets.fetch_spellbook(commanders, main))
        if found is not None:
            self.spellbook[self.list_id] = found
            self.update_deck()

    # Editing

    def add(self, card, quantity=1, section=None):
        if "oracle_id" in card and card.get("legalities") is not None:
            db.add_oracle_cards([_oracle(card)])  # its type, colors and legality, for the checks
        db.add_list_entries(self.list_id, [{
            "name": card["name"], "set_name": card["set_name"], "price": card["price"], "quantity": quantity,
            "scryfall_id": card["scryfall_id"], "set_code": card["set_code"], "collector_number": card["collector_number"],
            "foil": card["foil"] or 0, "image_url": card["image_url"]}], self.add_to if section is None else section)
        self.toast(f"Added {quantity}× {card['name']}.")
        self.changed()

    def change_quantity(self, entry, delta):
        count = entry["quantity"] + delta
        if count < 1:
            db.remove_list_entries([entry["id"]])
            self.selected = None
        else:
            db.update_list_entry(entry["id"], quantity=count)
        self.changed()

    def move(self, entry, section):
        db.update_list_entry(entry["id"], section=section)
        self.rec["list"] = None  # a new commander changes the recommendations
        self.changed()

    def quick_add(self, text):
        if text.strip():
            self.import_text(text, section=self.add_to)
            self.fill_card_data()
            self.changed()

    def import_text(self, text, section=None, is_deck=None):
        """Adds a pasted list: lines like "4 Lightning Bolt (M11) 149" under optional section
        headers. Cards go to section, or to the list's own headers when section is None."""
        is_deck = self._info()["kind"] == "deck" if is_deck is None else is_deck
        rows, errors = importer.parse_text(text)
        if not rows:
            self.toast(errors[0] if errors else "No cards found in that text.")
            return
        result = self.busy("Looking up cards", lambda: importer.resolve(rows))
        if result is None:
            return
        records = [{**scryfall.card_record(card, row.foil, row.quantity),
                    "section": (section if section is not None else row.section) if is_deck else ""}
                   for row, card in result.matched]
        db.add_list_entries(self.list_id, records)
        missing = [r.name for r in result.unmatched]
        message = f"Added {sum(r['quantity'] for r in records)} cards."
        if result.approximate:
            message += f" {len(result.approximate)} matched by name only, so check their printing."
        if missing:
            message += f" Not found: {', '.join(missing[:5])}{'…' if len(missing) > 5 else ''}."
        self.toast(message)

    def import_dialog(self):
        text = _field("Paste a deck list (Arena, Moxfield, MTGO, or \"4 Lightning Bolt\" lines, with Commander, "
                      "Sideboard… headers if you like)", multiline=True, width=536)

        def go(e):
            self.page.pop_dialog()
            self.import_text(text.value)
            self.fill_card_data()
            self.changed()

        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("Import Cards"), content=ft.Container(text, width=560),
            actions=[theme.button("Cancel", lambda e: self.page.pop_dialog()), theme.button("Import", go, primary=True)]))

    def export_dialog(self, entries):
        text = deck_stats.deck_text(entries)

        def copy(e):
            self.page.run_task(ft.Clipboard().set, text)
            self.toast("Copied. Paste it into Arena, Moxfield or anywhere else.")

        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("Export"),
            content=ft.Container(ft.TextField(value=text, multiline=True, read_only=True, min_lines=10, max_lines=18,
                                              text_size=12.5), width=520),
            actions=[theme.button("Close", lambda e: self.page.pop_dialog()), theme.button("Copy", copy, primary=True)]))

    def rename(self, info):
        name = _field("Name", value=info["name"], width=360)

        def save(e):
            if name.value.strip():
                db.rename_list(self.list_id, name.value.strip())
            self.page.pop_dialog()
            self.update_deck()

        name.on_submit = save
        self.page.show_dialog(ft.AlertDialog(title=ft.Text("Rename"), content=name, actions=[
            theme.button("Cancel", lambda e: self.page.pop_dialog()), theme.button("Save", save, primary=True)]))

    def delete(self, info):
        def confirmed(e):
            self.page.pop_dialog()
            db.delete_list(self.list_id)
            self.toast(f"Deleted {info['name']}.")
            self.close()

        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text(f"Delete {info['name']}?"), content=ft.Text("The cards stay in your collection."),
            actions=[theme.button("Cancel", lambda e: self.page.pop_dialog()), theme.button("Delete", confirmed, primary=True)]))

    def set_format(self, e):
        db.set_list_format(self.list_id, e.control.value)
        self.rec["list"] = None  # the recommendation pool depends on the format
        self.spellbook.pop(self.list_id, None)
        self.update_deck(browser=True)  # legality and every tab's filters change with it

    def set_bracket(self, e):
        db.set_list_bracket(self.list_id, int(e.control.value) if e.control.value else None)
        self.update_deck(browser=True)

    def pick_printing(self, entry):
        found = self.busy("Looking up printings", lambda: scryfall.get_printings(entry["name"]))
        if not found:
            return
        printing = _dropdown(str(next((i for i, c in enumerate(found) if c.id == entry["scryfall_id"]), 0)),
                             [(str(i), scryfall.printing_label(c)) for i, c in enumerate(found)], None, 480)
        finish = _dropdown(str(entry["foil"]), [], None, 200)
        image = ft.Image(src=scryfall.image_url_for(found[int(printing.value)]), width=200, border_radius=8)

        def shown(e=None):
            card = found[int(printing.value)]
            codes = scryfall.finish_codes(card) or [0]
            finish.options = [ft.DropdownOption(key=str(c), text=scryfall.FINISHES[c][1]) for c in codes]
            if finish.value not in {str(c) for c in codes}:
                finish.value = str(codes[0])
            image.src = scryfall.image_url_for(card)
            self.page.update()

        def save(e):
            self.page.pop_dialog()
            card = found[int(printing.value)]
            if (card.id, int(finish.value)) != (entry["scryfall_id"], entry["foil"]):
                # Like the desktop: the entry becomes the chosen printing (merging with one already there)
                db.remove_list_entries([entry["id"]])
                db.add_list_entries(self.list_id, [scryfall.card_record(card, int(finish.value), entry["quantity"])],
                                    entry["section"])
            self.changed()

        printing.on_select = shown
        card_form.arrow_keys(self.page, [(printing, shown), (finish, self.page.update)])(printing)
        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text(entry["name"]),
            content=ft.Row([ft.Column([printing, finish], tight=True, spacing=12), image], spacing=16,
                           vertical_alignment=ft.CrossAxisAlignment.START, tight=True),
            actions=[theme.button("Cancel", lambda e: self.page.pop_dialog()), theme.button("Save", save, primary=True)]))
        shown()
