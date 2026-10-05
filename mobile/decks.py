# The phone's Deck Builder: decks, binders and wishlists (the desktop's lists), with each
# format's rules and Commander brackets. Rules, legality and brackets are the desktop's own
# (formats.py, brackets.py). Instead of the desktop's whole card database, the phone looks
# up just the cards in its lists on Scryfall.
import flet as ft

import brackets
import database as db
import deck_stats
import formats
import scryfall
import sort_controls
import web_decks
from importer import SECTIONS

# The same names as the desktop's lists.py (a Qt window, so not importable here)
KINDS = {"deck": "Deck", "binder": "Binder", "wishlist": "Wishlist"}
SECTION_TITLES = {"Commander": "Commander", "Companion": "Companion", "Main": "Main Deck",
                  "Sideboard": "Sideboard", "Maybeboard": "Maybeboard", "": "Cards"}
MUTED = ft.Colors.ON_SURFACE_VARIANT


def _money(value):
    return f"${value:,.2f}" if value is not None else "—"


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _box(controls, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH):
    # A rounded panel that sets a group of lines apart from the rest of the page
    return ft.Container(ft.Column(controls, spacing=8, tight=True), bgcolor=bgcolor, border_radius=12, padding=12)


def _warning(text, color=None, icon=ft.Icons.WARNING_AMBER_ROUNDED):
    # A line with a red icon; the text is red too when color is given (a card breaking a rule)
    return ft.Row([ft.Icon(icon, color=ft.Colors.ERROR, size=18), ft.Text(text, color=color, expand=True)],
                  vertical_alignment=ft.CrossAxisAlignment.START, spacing=8)


def _number(field):
    # A text field's whole number, or None (with the field marked) when it isn't one
    try:
        return int(field.value)
    except (TypeError, ValueError):
        field.error_text = "Enter a number"
        return None


class PhoneRecommendations(web_decks.DecksPage):
    """The website's Recommended tab on the phone: its card pool, themes, sections and
    Available Combos, all the website's code, with its three panels swapped for the phone's
    one column. Tapping a card opens it in a dialog with an Add button."""

    def __init__(self, page, toast, busy):
        super().__init__(page, toast, busy)
        self.tab, self.badges = web_decks.RECOMMENDED, {}
        self.shown = []  # every card in the sections, in order, which swiping follows
        self.column = ft.Column(spacing=10)

    def show_for(self, list_id):
        self.list_id = list_id
        self._state()
        self.refill_tab()

    def refill_tab(self, update=True):
        # The sections, into the phone's column (a theme, filter or Show More works them out again)
        self.badges, self.shown = {}, []
        built = self._recommended(self.s)
        self.column.controls = built.controls if isinstance(built, ft.Column) else [built]
        if update:
            self.page.update()

    def changed(self):
        # After adding a card: its +/✓ marks, leaving the sections where they are
        self.spellbook.pop(self.list_id, None)
        in_list = {e["name"] for e in self._state()["entries"]}
        for name, marks in self.badges.items():
            for mark in marks:
                mark.value = "✓" if name in in_list else "+"
        self.page.update()

    def _card_menu(self, card, s):
        return []  # no right-click on a phone: the card's dialog has Add

    def _card_grid(self, cards, s):
        self.shown += cards
        return super()._card_grid(cards, s)

    def select(self, selected):
        kind, card = selected
        if kind != "card":
            return
        index = next((i for i, c in enumerate(self.shown) if c is card), None)
        if index is None:
            self.shown, index = [card], 0
        self.show_card(self.shown, index)

    def show_card(self, rows, index):
        # rows[index]'s dialog; swiping moves along rows
        card = rows[index]

        def go(to):
            self.page.pop_dialog()
            self.show_card(rows, to)

        def add(e):
            self.page.pop_dialog()
            self.add(card)

        self.page.show_dialog(ft.AlertDialog(
            content=sort_controls.swipe(ft.Column([
                sort_controls.pager(rows, index, go),
                *([ft.Image(src=card["image_url"], width=260, border_radius=10)] if card["image_url"] else []),
                ft.Text(card["name"], size=17, weight=ft.FontWeight.BOLD),
                ft.Text(card["type_line"] or "", size=13, color=MUTED),
                ft.Text(card["oracle_text"] or "", size=13.5),
                *([ft.Text(card["note"], size=13, color=ft.Colors.PRIMARY)] if card.get("note") else []),
                *web_decks.works_well_with(card)], tight=True, spacing=8, scroll=ft.ScrollMode.AUTO), rows, index, go),
            actions=[ft.TextButton("Close", on_click=lambda e: self.page.pop_dialog()),
                     ft.FilledButton(f"Add to {SECTION_TITLES[self.add_to]}", on_click=add)]))


class Decks:
    def __init__(self, page, toast, busy, card_dialog, scan=None):
        # scan(list id): main.py's scanner, adding into that list (None on the website: no camera)
        self.page, self.toast, self.busy, self.card_dialog, self.scan = page, toast, busy, card_dialog, scan
        self.list_id = None  # the open list, or None for the list of lists
        self.spellbook = {}  # list id -> Commander Spellbook's reading, until the list changes
        self.mode = "cards"  # what a list shows: its "cards", "stats" or "recommended" cards
        self.recommendations = None  # PhoneRecommendations, made the first time they're shown
        # Sort and group the open list (card_sorting.py); each list remembers its own
        self.sorting = sort_controls.SortState("deck", "list:none", lambda: self.show_list())
        self.view_tip = sort_controls.ViewTip(page)
        self.view = ft.Column(expand=True)

    def refresh(self):
        # Redraws whatever is showing, e.g. after a sync (which may have deleted the open list)
        if self.list_id is not None and self._info() is None:
            self.list_id = None
        self.show_list() if self.list_id is not None else self.show_all()

    def back(self):
        # Android's back button: from a list to all lists. False when there's nowhere to go back to.
        if self.list_id is None:
            return False
        self.list_id = None
        self.show_all()
        return True

    def fab(self):
        # What the + button does here
        self.add_card() if self.list_id is not None else self.new_list()

    def _info(self):
        return next((l for l in db.get_lists() if l["id"] == self.list_id), None)

    def _changed(self):
        self.spellbook.pop(self.list_id, None)
        self.show_list()

    def toggle(self, mode):
        # Stats or Recommended instead of the cards, and back
        self.mode = "cards" if self.mode == mode else mode
        self.show_list()

    # Every list

    def show_all(self):
        tiles = [ft.ListTile(
            title=ft.Text(l["name"]),
            subtitle=ft.Text(" · ".join([KINDS.get(l["kind"], l["kind"]),
                                         *([formats.label(l["format"])] if l["kind"] == "deck" else []),
                                         _plural(l["cards"], "card")])),
            trailing=ft.Text(_money(l["value"])), on_click=lambda e, l=l: self.open(l["id"]))
            for l in db.get_lists()]
        self.view.controls = [ft.ListView(tiles or [ft.Text("No decks yet. Tap + to make one.")], expand=True)]
        self.page.update()

    def new_list(self):
        name = ft.TextField(label="Name", autofocus=True)
        kind = ft.Dropdown(label="Kind", value="deck", options=[ft.DropdownOption(key=k, text=t) for k, t in KINDS.items()])
        fmt = ft.Dropdown(label="Format", value="commander", options=[
            ft.DropdownOption(key=k, text=f.label) for k, f in formats.FORMATS.items()])
        kind.on_select = lambda e: (setattr(fmt, "visible", kind.value == "deck"), self.page.update())

        def create(e):
            if not name.value.strip():
                return
            self.page.pop_dialog()
            self.open(db.create_list(name.value.strip(), kind.value, fmt.value if kind.value == "deck" else "casual"))

        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("New List"), content=ft.Column([name, kind, fmt], tight=True),
            actions=[ft.TextButton("Cancel", on_click=lambda e: self.page.pop_dialog()),
                     ft.TextButton("Create", on_click=create)]))

    # One list

    def open(self, list_id):
        self.list_id = list_id
        self.show_list()
        self.fill_card_data()

    def fill_card_data(self):
        # Types, colors and legality of cards this phone hasn't looked up yet
        missing = [e["name"] for e in db.get_list_entries(self.list_id) if e["legalities"] is None]
        if missing:
            rows = self.busy("Looking up cards", lambda: scryfall.fetch_card_data(missing))
            if rows:
                db.add_oracle_cards(rows)
                self.show_list()

    def show_list(self):
        info = self._info()
        entries = db.get_list_entries(self.list_id)
        owned = db.owned_by_name()
        is_deck = info["kind"] == "deck"
        problems, statuses = formats.validate(entries, info["format"]) if is_deck else ([], {})

        def back(e):
            self.list_id = None
            self.show_all()

        cards = sum(e["quantity"] for e in entries)
        value = sum(e["quantity"] * (e["price"] or 0) for e in entries)
        facts = [_plural(cards, "card"), _money(value), *([formats.label(info["format"])] if is_deck else [])]
        types = formats.type_counts(entries) if is_deck else {}
        commander = is_deck and formats.FORMATS.get(info["format"], formats.FORMATS["casual"]).commander
        if self.mode == "recommended" and not commander:
            self.mode = "cards"  # recommendations are for Commander decks, as everywhere

        def switch(mode, icon, tooltip):
            # A header button that shows the list's stats or recommendations, and back to its cards
            on = self.mode == mode
            return ft.IconButton(ft.Icons.LIST if on else icon, tooltip="Cards" if on else tooltip,
                                 on_click=lambda e: self.toggle(mode))

        controls = [ft.Row([
            ft.IconButton(ft.Icons.ARROW_BACK, tooltip="All lists", on_click=back),
            ft.Column([ft.Text(info["name"], size=20, weight=ft.FontWeight.BOLD),
                       ft.Text(" · ".join(facts), color=MUTED),
                       *([ft.Text(" · ".join(f"{n} {t}" for t, n in types.items()), size=13, color=MUTED)]
                         if types else [])], spacing=2, expand=True),
            *([switch("recommended", ft.Icons.AUTO_AWESOME, "Recommended")] if commander else []),
            switch("stats", ft.Icons.BAR_CHART, "Stats"),
            *([ft.IconButton(ft.Icons.DOCUMENT_SCANNER_OUTLINED, tooltip="Scan cards into this list",
                             on_click=lambda e: self.scan(self.list_id))] if self.scan else []),
            ft.IconButton(ft.Icons.EDIT_OUTLINED, tooltip="Rename, format or delete",
                          on_click=lambda e: self.edit_list(info))], vertical_alignment=ft.CrossAxisAlignment.START)]
        if self.mode == "recommended":
            # The website's Recommended tab (its themes, sections and Available Combos), phone-sized
            if self.recommendations is None:
                self.recommendations = PhoneRecommendations(self.page, self.toast, self.busy)
            self.view.controls = [ft.ListView([*controls, self.recommendations.column], expand=True, spacing=8,
                                              padding=ft.Padding.symmetric(horizontal=4))]
            self.recommendations.show_for(self.list_id)
            return
        if problems:
            controls.append(_box([_warning(p) for p in problems]))
        if commander:
            controls.append(self.bracket_panel(info, entries))
        if self.mode == "stats":
            # The website's Stats tab, on the phone: curve, colors, types, most valuable
            st = deck_stats.stats(entries, is_deck)
            controls += web_decks.stats_controls(st) if st else [ft.Text("Add cards to see their stats.", color=MUTED)]
            self.view.controls = [ft.ListView(controls, expand=True, spacing=8, padding=ft.Padding.symmetric(horizontal=4))]
            self.page.update()
            return

        # The cards in the list's sort and grouping (a deck keeps its sections apart)
        self.sorting.set_key(f"list:{self.list_id}", "deck" if is_deck else "list")
        controls.append(ft.Row([ft.Container(expand=True), sort_controls.chip(self.page, self.sorting)]))
        tip = self.view_tip.control(self.sorting, self.show_list)
        if tip:
            controls.append(tip)
        groups = [(title or "Cards", group) for title, group in self.sorting.arrange(entries)]
        shown = [e for title, group in groups if title not in self.sorting.folded for e in group]  # swiping's order

        def open_entry(e):
            self.edit_entry(shown, next(i for i, s in enumerate(shown) if s["id"] == e["id"]), is_deck)

        if self.sorting.view["display"] != "List":
            # Text, Grid or Stacks (three cards across); tapping a card opens it, as in the list
            width = ((self.page.width or 400) - 60) / 3 - 2 * sort_controls.ITEM_PAD
            controls.append(sort_controls.card_views(
                self.sorting, groups,
                lambda e, control: ft.Container(control, padding=sort_controls.ITEM_PAD, on_click=lambda ev: open_entry(e)),
                width, columns=2 if (self.page.width or 400) >= 600 else 1))
            self.view.controls = [ft.ListView(controls, expand=True, spacing=4, padding=ft.Padding.symmetric(horizontal=4))]
            self.page.update()
            return
        for title, group in groups:
            controls.append(sort_controls.heading(self.sorting, title, group))
            if title in self.sorting.folded:
                continue
            for e in group:
                status = statuses.get(e["id"])
                have = owned.get(e["name"].lower(), 0)
                controls.append(ft.ListTile(
                    title=ft.Text(f"{e['quantity']}× {e['name']}"),
                    subtitle=(_warning(status, ft.Colors.ERROR, ft.Icons.ERROR_OUTLINE) if status
                              else ft.Text(e["type_line"] or "", color=MUTED)),
                    trailing=ft.Text(f"{have} owned" if have else "not owned", size=12,
                                     color=ft.Colors.PRIMARY if have else MUTED),
                    dense=True, content_padding=ft.Padding.symmetric(horizontal=4),
                    on_click=lambda ev, e=e: open_entry(e)))
        if not entries:
            controls.append(ft.Text("No cards yet. Tap + to add some.", color=MUTED))
        self.view.controls = [ft.ListView(controls, expand=True, spacing=4, padding=ft.Padding.symmetric(horizontal=4))]
        self.page.update()

    def bracket_panel(self, info, entries):
        spellbook = self.spellbook.get(self.list_id)
        report = brackets.check(entries, spellbook)
        low = report.minimum()
        fits = {1: "Bracket 1 or 2 (Exhibition or Core: that's down to the deck's intent)",
                4: "Bracket 4 or 5 (Optimized or cEDH: that's down to the deck's intent)"}.get(low, brackets.label(low))
        target = ft.Dropdown(label="Aiming for", value=str(info["bracket"] or ""), dense=True, options=[
            ft.DropdownOption(key="", text="No bracket chosen"),
            *[ft.DropdownOption(key=str(b.number), text=brackets.label(b.number)) for b in brackets.BRACKETS]])

        def aim(e):
            db.set_list_bracket(self.list_id, int(target.value) if target.value else None)
            self.show_list()

        target.on_select = aim
        found = [("Game Changers", report.game_changers), ("Mass land denial", report.mass_land_denial),
                 ("Extra turns", report.extra_turns)]
        if spellbook is not None:
            found.append(("Two-card combos", [f"{' + '.join(c.cards)} ({c.results})" for c in report.combos]))
        lines = [ft.Text("Bracket", weight=ft.FontWeight.BOLD), ft.Container(target, padding=ft.Padding.only(top=6)),
                 ft.Text(f"These cards fit {fits}.")]
        if info["bracket"]:
            lines += [_warning(f"{why}: {', '.join(names)}", ft.Colors.ERROR, ft.Icons.ERROR_OUTLINE)
                      for why, names in report.broken(info["bracket"])]
        lines += [ft.Row([ft.Text(title, color=MUTED, size=13, width=130),
                          ft.Text(", ".join(names) or "none", size=13, expand=True)],
                         vertical_alignment=ft.CrossAxisAlignment.START) for title, names in found]
        if spellbook is None and not brackets.SPELLBOOK_REACHABLE:
            lines.append(ft.Text(brackets.NO_SPELLBOOK, size=12, color=MUTED))
        elif spellbook is None:
            lines.append(ft.OutlinedButton("Check for combos (Commander Spellbook)", icon=ft.Icons.SEARCH,
                                           on_click=self.check_combos))
        return _box(lines)

    def check_combos(self, e):
        entries = db.get_list_entries(self.list_id)
        commanders = [x["name"] for x in entries if x["section"] == "Commander"]
        main = [x["name"] for x in entries if x["section"] == "Main"]
        found = self.busy("Checking combos", lambda: brackets.fetch_spellbook(commanders, main))
        if found is not None:
            self.spellbook[self.list_id] = found
            self.show_list()

    def edit_list(self, info):
        name = ft.TextField(label="Name", value=info["name"])
        fmt = ft.Dropdown(label="Format", value=info["format"], visible=info["kind"] == "deck", options=[
            ft.DropdownOption(key=k, text=f.label) for k, f in formats.FORMATS.items()])
        delete = ft.TextButton("Delete")

        def save(e):
            self.page.pop_dialog()
            if name.value.strip() and name.value.strip() != info["name"]:
                db.rename_list(self.list_id, name.value.strip())
            if fmt.value != info["format"]:
                db.set_list_format(self.list_id, fmt.value)
            self._changed()

        def delete_clicked(e):
            # A second tap confirms
            if delete.data:
                self.page.pop_dialog()
                db.delete_list(self.list_id)
                self.list_id = None
                self.show_all()
                self.toast(f"Deleted {info['name']}.")
            else:
                delete.data = True
                delete.content = "Tap again to delete"
                self.page.update()

        delete.on_click = delete_clicked
        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text(KINDS.get(info["kind"], "List")), content=ft.Column([name, fmt], tight=True),
            actions=[delete, ft.TextButton("Cancel", on_click=lambda e: self.page.pop_dialog()),
                     ft.TextButton("Save", on_click=save)]))

    def edit_entry(self, rows, index, is_deck):
        # rows[index]'s dialog; swiping moves along rows, saving any change first
        entry = rows[index]
        quantity = ft.TextField(label="Quantity", value=str(entry["quantity"]), keyboard_type=ft.KeyboardType.NUMBER)
        section = ft.Dropdown(label="Section", value=entry["section"], visible=is_deck,
                              options=[ft.DropdownOption(key=s, text=SECTION_TITLES[s]) for s in SECTIONS])
        remove = ft.TextButton("Remove")
        printing = ft.Dropdown(editable=True, enable_filter=True, label="Printing", visible=False)
        finish = ft.Dropdown(label="Finish", visible=False)
        printings = []

        def show_finishes(e=None):
            card = printings[int(printing.value)]
            codes = scryfall.finish_codes(card) or [0]
            finish.options = [ft.DropdownOption(key=str(c), text=scryfall.FINISHES[c][1]) for c in codes]
            if finish.value not in {str(c) for c in codes}:
                finish.value = str(codes[0])
            self.page.update()

        def load_printings(e):
            found = self.busy("Looking up printings", lambda: scryfall.get_printings(entry["name"]))
            if not found:
                return
            printings[:] = found
            printing.options = [ft.DropdownOption(key=str(i), text=scryfall.printing_label(c)) for i, c in enumerate(found)]
            printing.value = str(next((i for i, c in enumerate(found) if c.id == entry["scryfall_id"]), 0))
            finish.value = str(entry["foil"])
            printing.visible = finish.visible = True
            change.visible = False
            show_finishes()

        change = ft.OutlinedButton("Change printing", icon=ft.Icons.COLLECTIONS_OUTLINED, on_click=load_printings)
        printing.on_select = show_finishes

        def go(to):
            chosen = (printings[int(printing.value)].id, int(finish.value)) if printings else None
            if (quantity.value != str(entry["quantity"]) or (is_deck and section.value != entry["section"])
                    or chosen not in (None, (entry["scryfall_id"], entry["foil"]))):
                if not save(None):
                    return  # the quantity isn't a number: stay to fix it
            else:
                self.page.pop_dialog()
            self.edit_entry(rows, to, is_deck)

        def save(e):
            count = _number(quantity)
            if count is None:
                self.page.update()
                return False
            self.page.pop_dialog()
            where = section.value if is_deck else entry["section"]
            card = printings[int(printing.value)] if printings else None
            if count < 1:
                db.remove_list_entries([entry["id"]])
            elif card and (card.id, int(finish.value)) != (entry["scryfall_id"], entry["foil"]):
                # Like the desktop: the entry becomes the chosen printing (merging with one already there)
                db.remove_list_entries([entry["id"]])
                db.add_list_entries(self.list_id, [scryfall.card_record(card, int(finish.value), count)], where)
            else:
                db.update_list_entry(entry["id"], quantity=count, section=where)
            self._changed()
            return True

        def remove_clicked(e):
            if remove.data:
                self.page.pop_dialog()
                db.remove_list_entries([entry["id"]])
                self._changed()
            else:
                remove.data = True
                remove.content = "Tap again to remove"
                self.page.update()

        remove.on_click = remove_clicked
        details = [ft.Image(src=entry["image_url"], height=280)] if entry["image_url"] else []
        if entry["oracle_text"]:
            details.append(ft.Text(entry["oracle_text"], size=13))
        where = " · ".join(x for x in (entry["set_name"], f"#{entry['collector_number']}" if entry["collector_number"] else "",
                                       scryfall.finish_label(entry["foil"])) if x)
        if where:
            details.append(ft.Text(where, color=MUTED, size=13))
        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text(entry["name"]), scrollable=True,
            content=sort_controls.swipe(ft.Column([sort_controls.pager(rows, index, go), *details, change, printing,
                                                   finish, quantity, section], tight=True, spacing=12), rows, index, go),
            actions=[remove, ft.TextButton("Cancel", on_click=lambda e: self.page.pop_dialog()),
                     ft.TextButton("Save", on_click=save)]))

    def add_card(self):
        info = self._info()
        is_deck = info["kind"] == "deck"
        section = ft.Dropdown(label="Section", value="Main" if is_deck else "", visible=is_deck,
                              options=[ft.DropdownOption(key=s, text=SECTION_TITLES[s]) for s in SECTIONS])

        def added(card, finish, count):
            db.add_list_entries(self.list_id, [scryfall.card_record(card, finish, count)],
                                section.value if is_deck else "")
            self.toast(f"Added {count}× {card.name} to {info['name']}.")
            self._changed()
            self.fill_card_data()

        self.card_dialog(f"Add to {info['name']}", [section], added)
