# The website's desktop layout (the user's pick, "layout B"): a navigation header, then per
# page a dashboard of summary tiles, a toolbar, and a table with the selected card beside it.
# main.py switches between this and the phone layout; the Add/Edit window is card_form.py.
import time

import flet as ft

import card_sorting
import copy_details
import database as db
import interactions
import price_changes
import scryfall
import sort_controls
import theme

TABS = ["Cards", "Decks", "Rules", "Finance"]
COLUMN_ONLY_SORTS = ["Condition", "Total", "Change"]  # the Cards table's own sorts, by its columns
DOUBLE_CLICK = 0.5  # seconds between two clicks on a row that open Edit
DETAIL_WIDTH = 300  # the selected card's panel
PAGE_PADDING = 28
CHANGE_DAYS = 7  # the tiles' and the table's price change
WORKS_SHOWN = 6  # lines of a card's "Works well with" in its details
# Name and Set share what the other columns leave (the table can't size columns itself).
# ponytail: measured at the default font; wider content just makes the table scroll
FIXED_COLUMNS = 560
NOTICE = ("Multiversal Manager is unofficial Fan Content permitted under the Fan Content Policy. "
          "Not approved/endorsed by Wizards. Portions of the materials used are property of "
          "Wizards of the Coast. ©Wizards of the Coast LLC. Card data, prices and images provided by Scryfall.")


def _money(value):
    return f"${value:,.2f}" if value else "—"


def _total(row):
    return row["price"] * row["quantity"] if row["price"] is not None else None


def _set_code(row):
    return (row["set_code"] or "").upper()


def header(active, on_tab, on_sync, email, menu_items, on_home):
    """The stripe and navigation bar: logo, the tabs as links, Sync and the account menu.
    menu_items: [(label, on_click)] for the account menu; on_home: the logo's click."""
    def link(index, label):
        on = index == active
        return ft.Container(
            ft.Text(label, font_family=theme.TITLE_FONT, size=15, weight=ft.FontWeight.W_600,
                    color=theme.GOLD if on else theme.MUTED),
            padding=ft.Padding.symmetric(horizontal=4, vertical=6), margin=ft.Margin.symmetric(horizontal=10),
            border=ft.Border.only(bottom=ft.BorderSide(2, theme.GOLD if on else ft.Colors.TRANSPARENT)),
            on_click=lambda e: on_tab(index), ink=False)

    avatar = ft.PopupMenuButton(
        tooltip=email or "Account",
        content=ft.CircleAvatar(content=ft.Text((email or "?")[0].upper(), weight=ft.FontWeight.BOLD),
                                bgcolor=theme.COLORS["primary_container"], radius=16),
        items=[ft.PopupMenuItem(content=label, on_click=action) for label, action in menu_items])
    bar = ft.Container(
        ft.Row([ft.Container(ft.Row([ft.Icon(ft.Icons.AUTO_STORIES, color=theme.GOLD, size=26),
                                     ft.Text("Multiversal Manager", font_family=theme.TITLE_FONT, size=21,
                                             weight=ft.FontWeight.W_700, color=theme.GOLD)], spacing=8),
                             on_click=on_home, tooltip="Your collection", ink=False),
                ft.Container(width=36), *[link(i, label) for i, label in enumerate(TABS)],
                ft.Container(expand=True), theme.button("⟳  Sync", on_sync), avatar],
               vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
        padding=ft.Padding.symmetric(horizontal=PAGE_PADDING, vertical=10), bgcolor=theme.COLORS["surface"],
        border=ft.Border.only(bottom=ft.BorderSide(1, theme.LINE)))
    return ft.Column([theme.stripe(), bar], spacing=0)


def tile(title, value, note, value_color=None, note_color=None, small=False):
    return ft.Container(
        ft.Column([ft.Text(title, color=theme.MUTED, size=13),
                   ft.Text(value, size=17 if small else 22, weight=ft.FontWeight.BOLD, color=value_color,
                           no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                   ft.Text(note, size=12, color=note_color or theme.MUTED, no_wrap=True,
                           overflow=ft.TextOverflow.ELLIPSIS, tooltip=note or None)], spacing=2, tight=True),
        bgcolor=theme.COLORS["surface"], border=ft.Border.all(1, theme.LINE), border_radius=10,
        padding=ft.Padding.symmetric(horizontal=16, vertical=12), expand=True)


def works_well_with(card):
    """A card's "Works well with" lines for its details (interactions.py), or none. card: a
    name, or a dict with name, type_line and oracle_text (a card newer than the data)."""
    found = interactions.load().summary(card)[:WORKS_SHOWN]
    if not found:
        return []
    return [ft.Text("Works well with", size=12.5, weight=ft.FontWeight.W_600, color=theme.GOLD),
            *[ft.Text(line, size=11.5, color=theme.MUTED) for line in found]]


class CardsPage:
    """The collection: summary tiles, search and actions, the table and the selected card.
    add(), edit(row), refresh_prices(e) and import_cards() are main.py's; remove asks here first."""

    def __init__(self, page, toast, add, edit, refresh_prices, import_cards, busy=None):
        self.page, self.toast, self.edit, self.busy = page, toast, edit, busy
        # Sort and group (card_sorting.py); a column's heading sorts by it too
        self.sorting = sort_controls.SortState("collection", "collection", lambda: self.refresh(),
                                               extra_sorts=COLUMN_ONLY_SORTS)
        self.sort_row = ft.Row(spacing=8)
        self.selected = {"id": None, "clicked_at": 0}
        self.rows = {}  # card id -> DataRow, to move the selection without rebuilding the table
        self.search = ft.TextField(hint_text="Filter by name, set or artist…", prefix_icon=ft.Icons.SEARCH, dense=True,
                                   width=340, filled=True, bgcolor=theme.COLORS["surface_container_low"],
                                   border=ft.OutlineInputBorder(side=ft.BorderSide(1, theme.LINE), border_radius=6),
                                   on_change=lambda e: self.refresh())
        self.tiles = ft.Row(spacing=14, height=96, vertical_alignment=ft.CrossAxisAlignment.STRETCH)  # tiles the same height
        self.table = ft.ListView(expand=True)
        self.detail = ft.Column(scroll=ft.ScrollMode.AUTO, spacing=8)
        self.cards_area = ft.Column([
            ft.Row([self.search, self.sort_row, ft.Container(expand=True),
                    theme.button("Import…", lambda e: import_cards()),
                    theme.button("Refresh Prices", refresh_prices),
                    theme.button("+ Add Card", lambda e: add(), primary=True)]),
            ft.Row([theme.panel(self.table, expand=True),
                    theme.panel(self.detail, width=DETAIL_WIDTH, padding=16)],
                   expand=True, spacing=20, vertical_alignment=ft.CrossAxisAlignment.START),
        ], spacing=16, expand=True)
        # Cards and sealed product each get a tab, like the desktop; the combined total shows beside them
        self.sealed = None  # main.py's web_sealed.SealedPanel (it needs this page's total, so it comes after)
        self.trends = None  # main.py's web_trends.TrendsPanel
        self.showing = {"tab": "Cards"}
        self.tabs = ft.Row(spacing=0)
        self.total = ft.Text(size=13, color=theme.MUTED)
        self.area = ft.Container(self.cards_area, expand=True)
        self.view = ft.Container(ft.Column([
            self.tiles,
            ft.Row([self.tabs, ft.Container(expand=True), self.total], vertical_alignment=ft.CrossAxisAlignment.END),
            self.area,
            ft.Text(NOTICE, size=11, color=theme.MUTED),
        ], spacing=16, expand=True), padding=ft.Padding.symmetric(horizontal=PAGE_PADDING, vertical=20), expand=True)
        self.draw_tabs()

    def draw_tabs(self):
        def tab(label):
            on = label == self.showing["tab"]
            return ft.Container(ft.Text(label, size=14, weight=ft.FontWeight.W_600, color=theme.GOLD if on else theme.MUTED),
                                padding=ft.Padding.symmetric(horizontal=14, vertical=6), on_click=lambda e: self.show(label),
                                border=ft.Border.only(bottom=ft.BorderSide(2, theme.GOLD if on else theme.LINE)))
        self.tabs.controls = [tab("Cards"), tab("Sealed"), tab("Trends")]

    def show(self, label):
        self.showing["tab"] = label
        self.draw_tabs()
        other = {"Sealed": self.sealed, "Trends": self.trends}.get(label)
        self.area.content = other.view if other else self.cards_area
        other.refresh() if other else self.refresh()

    def home(self):
        # Back to the Cards tab (the header's logo); main.py then shows and refreshes the page
        self.showing["tab"] = "Cards"
        self.draw_tabs()
        self.area.content = self.cards_area

    def update_total(self):
        # The desktop's "Collection total": cards and sealed product, separately and together
        cards, sealed = db.get_summary()[2], db.sealed_summary()[1]
        self.total.value = f"Collection total: ${cards + sealed:,.2f}   (cards ${cards:,.2f} + sealed ${sealed:,.2f})"

    # The columns: (heading, the sort its heading picks, numeric)
    COLUMNS = [("Name", "Name", False), ("Set", "Set", False), ("Cond", "Condition", False),
               ("Qty", "Quantity", True), ("Price", "Price", True), ("Total", "Total", True),
               (f"{CHANGE_DAYS}d", "Change", True)]

    @staticmethod
    def column_sort_keys(changes):
        # The sorts only this table has, by its columns
        conditions = list(copy_details.CONDITIONS)
        return {"Condition": lambda r: (conditions.index(r["condition"]) if r["condition"] in conditions else 99,
                                        r["foil"]),
                "Total": _total,
                "Change": lambda r: changes[r["id"]].percent if r["id"] in changes else None}

    def refresh(self, select_id=...):
        if select_id is not ...:
            self.selected["id"] = select_id
        everything = db.get_all_cards()
        changes = price_changes.compute_changes(everything, db.get_past_prices(CHANGE_DAYS))
        text = (self.search.value or "").lower()
        rows = [r for r in everything if text in f"{r['name']} {r['set_name']} {r['artist'] or ''}".lower()]
        if self.showing["tab"] == "Sealed" and self.sealed is not None:
            self.sealed.refresh()  # the sealed tab is showing; it updates the total itself
            return
        if self.showing["tab"] == "Trends" and self.trends is not None:
            self.show_tiles(everything, changes)
            self.update_total()
            self.trends.refresh()
            return
        self.show_tiles(everything, changes)
        self.update_total()
        self.sort_row.controls = sort_controls.toolbar(self.sorting)
        self.table.controls = [self.card_table(rows, changes)]
        if self.selected["id"] not in self.rows:
            self.selected["id"] = None
        self.show_detail(next((r for r in rows if r["id"] == self.selected["id"]), None))
        self.page.update()

    def show_tiles(self, rows, changes):
        unique, cards, value = db.get_summary()
        overall = price_changes.collection_change(changes)
        priciest = max((r for r in rows if r["price"]), key=lambda r: r["price"], default=None)
        gains = [(c, r) for r in rows if (c := changes.get(r["id"])) and c.each > 0.004]
        best = max(gains, key=lambda g: g[0].percent or 0, default=None)
        self.tiles.controls = [
            tile("Collection value", f"${value:,.2f}",
                  f"{price_changes.format_change(*overall)} this week" if overall else "No price history yet",
                  value_color=theme.GOLD,
                  note_color=(theme.GAIN if overall[0] > 0 else theme.LOSS) if overall and abs(overall[0]) > 0.004 else None),
            tile("Cards", str(cards), f"{unique} unique printing{'s' if unique != 1 else ''}"),
            tile("Most valuable", priciest["name"] if priciest else "—", _money(priciest["price"]) if priciest else "",
                  small=True),
            tile(f"Biggest gain ({CHANGE_DAYS}d)", best[1]["name"] if best else "—",
                  price_changes.format_change(best[0].each, best[0].percent) if best else "No gains yet",
                  note_color=theme.GAIN if best else None, small=True),
        ]

    def card_table(self, rows, changes):
        groups = self.sorting.arrange(rows, self.busy, self.column_sort_keys(changes))
        area = (self.page.width or 1200) - 2 * PAGE_PADDING - DETAIL_WIDTH - 20
        name_width = max(140, (area - FIXED_COLUMNS) * 0.45)
        set_width = max(140, (area - FIXED_COLUMNS) * 0.55)

        def cell(content, row):
            return ft.DataCell(content, on_tap=lambda e: self.clicked(row))

        def text(value, width=None, **style):
            return ft.Text(value, width=width, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS, **style)

        def change(row):
            c = changes.get(row["id"])
            if not c or c.percent is None:
                return text("")
            return text(f"{'+' if c.percent >= 0 else '−'}{abs(c.percent):.1f}%",
                        color=theme.GAIN if c.each > 0.004 else theme.LOSS if c.each < -0.004 else theme.MUTED)

        def card_row(r):
            finish = scryfall.finish_label(r["foil"])
            labels = [theme.pill(r["condition"])] + ([theme.pill(finish, ["#F3E3A6", "#9D8CFF"])] if finish else [])
            self.rows[r["id"]] = ft.DataRow(selected=r["id"] == self.selected["id"], cells=[
                cell(text(r["name"], name_width, weight=ft.FontWeight.W_500), r),
                cell(ft.Row([text(r["set_name"]), ft.Text(f"({_set_code(r)})", color=theme.MUTED)],
                            spacing=4, width=set_width, wrap=False), r),
                cell(ft.Row(labels, spacing=4), r),
                cell(text(str(r["quantity"])), r), cell(text(_money(r["price"])), r),
                cell(text(_money(_total(r))), r), cell(change(r), r)])
            return self.rows[r["id"]]

        def heading(title, members):
            # A group's heading row, lined up with the columns: its name, copies and value
            copies, value = card_sorting.totals(members)
            arrow = "▸" if title in self.sorting.folded else "▾"
            bold = dict(weight=ft.FontWeight.W_600, color=theme.GOLD)
            return ft.DataRow(cells=[
                ft.DataCell(text(f"{arrow} {title}", name_width, **bold), on_tap=lambda e: self.sorting.toggle(title)),
                ft.DataCell(text(f"{len(members)} printing{'s' if len(members) != 1 else ''}", color=theme.MUTED)),
                ft.DataCell(text("")), ft.DataCell(text(str(copies), **bold)), ft.DataCell(text("")),
                ft.DataCell(text(_money(value), **bold)), ft.DataCell(text(""))])

        self.rows.clear()
        lines = []
        for title, members in groups:
            if title is not None:
                lines.append(heading(title, members))
                if title in self.sorting.folded:
                    continue
            lines += [card_row(r) for r in members]
        column = next((i for i, (_, sort, _) in enumerate(self.COLUMNS) if sort == self.sorting.view["sort"]), None)
        return ft.DataTable(
            sort_column_index=column, sort_ascending=not self.sorting.view["descending"],
            heading_row_height=40, data_row_min_height=36, data_row_max_height=36,
            column_spacing=22, horizontal_margin=14, divider_thickness=1,
            horizontal_lines=ft.BorderSide(1, theme.LINE),
            heading_text_style=ft.TextStyle(size=12, weight=ft.FontWeight.W_600, color=theme.GOLD, letter_spacing=1),
            data_row_color={ft.ControlState.SELECTED: theme.COLORS["primary_container"]},
            columns=[ft.DataColumn(ft.Text(label.upper()), numeric=numeric, on_sort=self.sorted_by)
                     for label, _, numeric in self.COLUMNS],
            rows=lines)

    def sorted_by(self, e):
        self.sorting.pick(self.COLUMNS[e.column_index][1])

    def clicked(self, row):
        # A second click on the same row soon after is a double click, which edits, like the
        # desktop (the table redraws the row on the first click, so Flet's own double tap misses)
        now = time.monotonic()
        double = row["id"] == self.selected["id"] and now - self.selected["clicked_at"] < DOUBLE_CLICK
        self.selected["clicked_at"] = 0 if double else now
        if double:
            self.edit(row)
            return
        old = self.rows.get(self.selected["id"])
        if old:
            old.selected = False
        self.selected["id"] = row["id"]
        self.rows[row["id"]].selected = True
        self.show_detail(row)
        self.page.update()

    def show_detail(self, row):
        if row is None:
            self.detail.controls = [ft.Container(ft.Text("Select a card to see it here.", italic=True, color=theme.MUTED),
                                                 padding=ft.Padding.symmetric(vertical=40), alignment=ft.Alignment.CENTER)]
            return
        printing = f"{row['set_name']} ({_set_code(row)})" + (f" #{row['collector_number']}" if row["collector_number"] else "")
        fields = [("Set", printing), ("Finish", scryfall.finish_label(row["foil"]) or "Non-foil"),
                  ("Rarity", (row["rarity"] or "—").title()), ("Artist", row["artist"] or "—"),
                  ("Condition", f"{copy_details.CONDITIONS.get(row['condition'], row['condition'])} ({row['condition']})"),
                  ("Language", copy_details.language_label(row["language"])), ("Notes", row["notes"] or "—"),
                  ("Price", _money(row["price"])), ("Owned", str(row["quantity"])), ("Subtotal", _money(_total(row)))]
        link = ([theme.button("Scryfall ↗", url=scryfall.scryfall_page(row["set_code"], row["collector_number"]))]
                if row["set_code"] and row["collector_number"] else [])
        self.detail.controls = [
            *([ft.Image(src=row["image_url"], width=DETAIL_WIDTH - 32, border_radius=12)] if row["image_url"] else []),
            ft.Text(row["name"], font_family=theme.TITLE_FONT, size=18, weight=ft.FontWeight.W_700, color=theme.GOLD),
            *[ft.Row([ft.Text(label, width=80, size=13, color=theme.MUTED), ft.Text(value, size=13, expand=True)],
                     vertical_alignment=ft.CrossAxisAlignment.START, spacing=6) for label, value in fields],
            *works_well_with(row["name"]),
            ft.Row([theme.button("Edit…", lambda e: self.edit(row)), theme.button("Remove", lambda e: self.remove(row)),
                    *link], spacing=8, wrap=True)]

    def remove(self, row):
        def confirmed(e):
            self.page.pop_dialog()
            db.remove_card(row["id"])
            self.refresh(select_id=None)
            self.toast(f"Removed {row['name']}.")

        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("Remove Card"),
            content=ft.Text(f"Remove {row['quantity']}× {row['name']} from your collection?"),
            actions=[theme.button("Cancel", lambda e: self.page.pop_dialog()),
                     theme.button("Remove", confirmed, primary=True)]))
