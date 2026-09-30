# The desktop's Sealed tab and its Add / Edit Sealed Product window (sealed.py), for the website's
# desktop layout: your sealed product in a table, with what you paid and what it's worth, both
# entered by hand, and MTGJSON's list of sealed products to pick from.
import time
from urllib.parse import quote_plus

import flet as ft

import database as db
import mtgjson
import price_changes
import theme
from phone_sealed import _price, gain_color, gain_text
from web_desktop import DOUBLE_CLICK, _money

COLUMNS = ["Product", "Set", "Type", "Qty", "Paid (each)", "Value (each)", "Total Value", "Gain / Loss", "Notes"]
NUMERIC = {3, 4, 5, 6, 7}
RESULTS_SHOWN = 500  # the catalog's matches listed at once, like the desktop


def _sort_key(row, column):
    change = price_changes.sealed_gain(row)
    return [(row["name"] or "").casefold(), (row["set_name"] or "").casefold(), (row["product_type"] or "").casefold(),
            row["quantity"], row["paid"] or 0, row["value"] or 0, (row["value"] or 0) * row["quantity"],
            change or 0, (row["notes"] or "").casefold()][column]


class SealedPanel:
    """The Sealed tab: view and refresh(). on_change() runs when the totals change (the Cards
    page's combined total); busy and toast are main.py's."""

    def __init__(self, page, toast, busy, on_change=None):
        self.page, self.toast, self.busy, self.on_change = page, toast, busy, on_change or (lambda: None)
        self.selected = {"id": None, "clicked_at": 0}
        self.sort = {"column": 0, "ascending": True}
        self.rows = {}
        self.search = ft.TextField(hint_text="Filter by product, set, type or notes…", prefix_icon=ft.Icons.SEARCH,
                                   dense=True, width=340, filled=True, bgcolor=theme.COLORS["surface_container_low"],
                                   border=ft.OutlineInputBorder(side=ft.BorderSide(1, theme.LINE), border_radius=6),
                                   on_change=lambda e: self.refresh())
        self.table = ft.ListView(expand=True)
        self.summary = ft.Text(size=15, weight=ft.FontWeight.BOLD)
        self.gain = ft.Text(size=14)
        self.edit_button = theme.button("Edit…", lambda e: self.edit(self.rows[self.selected["id"]]), disabled=True)
        self.remove_button = theme.button("Remove", lambda e: self.remove(self.rows[self.selected["id"]]), disabled=True)
        self.look_up_button = theme.button("Look Up on TCGplayer ↗", disabled=True)
        self.view = ft.Column([
            ft.Row([self.search]),
            theme.panel(self.table, expand=True),
            ft.Row([self.summary, self.gain, ft.Container(expand=True), self.look_up_button, self.edit_button,
                    self.remove_button, theme.button("Add Sealed Product…", lambda e: self.add(), primary=True)],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
        ], expand=True, spacing=14)

    def refresh(self):
        everything = db.get_sealed()
        needle = (self.search.value or "").strip().lower()
        rows = [r for r in everything if not needle or needle in " ".join(
            str(r[k] or "") for k in ("name", "set_name", "set_code", "product_type", "notes")).lower()]
        rows.sort(key=lambda r: _sort_key(r, self.sort["column"]), reverse=not self.sort["ascending"])
        self.rows = {r["id"]: r for r in everything}
        if self.selected["id"] not in self.rows:
            self.selected["id"] = None
        self.table.controls = [self.sealed_table(rows)]
        count, value, paid, value_of_paid = db.sealed_summary()
        self.summary.value = f"Sealed value: ${value:,.2f}    ·    {count:,} item{'s' if count != 1 else ''}"
        change = value_of_paid - paid if paid else None
        self.gain.value, self.gain.color = gain_text(change, paid), gain_color(change)
        self.gain.tooltip = "Only items with both a paid price and a value count"
        self.update_buttons()
        self.on_change()
        self.page.update()

    def sealed_table(self, rows):
        def text(value, **style):
            return ft.Text(value, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS, **style)

        def cells(r):
            change = price_changes.sealed_gain(r)
            return [text(r["name"], weight=ft.FontWeight.W_500, tooltip=r["name"]), text(r["set_name"] or ""),
                    text(r["product_type"] or ""), text(str(r["quantity"])), text(_money(r["paid"])),
                    text(_money(r["value"]), tooltip=None if r["value"] is not None else
                         "No value entered yet. Edit it to add one."),
                    text(_money((r["value"] or 0) * r["quantity"])),
                    text(gain_text(change), color=gain_color(change)),
                    text((r["notes"] or "").replace("\n", " "), color=theme.MUTED)]

        if not rows:
            return ft.Container(ft.Text("No sealed product yet. Add a booster box, bundle, precon… with Add Sealed "
                                        "Product." if not self.search.value else "Nothing matches the filter.",
                                        italic=True, color=theme.MUTED), padding=20)
        return ft.DataTable(
            sort_column_index=self.sort["column"], sort_ascending=self.sort["ascending"],
            heading_row_height=40, data_row_min_height=36, data_row_max_height=36, column_spacing=22,
            horizontal_margin=14, divider_thickness=1, horizontal_lines=ft.BorderSide(1, theme.LINE),
            heading_text_style=ft.TextStyle(size=12, weight=ft.FontWeight.W_600, color=theme.GOLD, letter_spacing=1),
            data_row_color={ft.ControlState.SELECTED: theme.COLORS["primary_container"]},
            columns=[ft.DataColumn(ft.Text(label.upper()), numeric=i in NUMERIC, on_sort=self.sorted_by)
                     for i, label in enumerate(COLUMNS)],
            rows=[ft.DataRow(selected=r["id"] == self.selected["id"],
                             cells=[ft.DataCell(c, on_tap=lambda e, r=r: self.clicked(r)) for c in cells(r)])
                  for r in rows])

    def sorted_by(self, e):
        self.sort.update(column=e.column_index, ascending=e.ascending)
        self.refresh()

    def clicked(self, row):
        # Select, or a double click (a second click soon after) to edit, like the desktop
        now = time.monotonic()
        if row["id"] == self.selected["id"] and now - self.selected["clicked_at"] < DOUBLE_CLICK:
            self.selected["clicked_at"] = 0
            self.edit(row)
            return
        self.selected.update(id=row["id"], clicked_at=now)
        self.refresh()

    def update_buttons(self):
        row = self.rows.get(self.selected["id"])
        self.edit_button.disabled = self.remove_button.disabled = self.look_up_button.disabled = row is None
        self.look_up_button.url = (f"https://www.tcgplayer.com/search/magic/product?q={quote_plus(row['name'])}"
                                   if row else None)

    # Adding, editing and removing

    def add(self):
        SealedDialog(self.page, self.busy, self.saved).open()

    def edit(self, row):
        SealedDialog(self.page, self.busy, self.saved, existing=row).open()

    def saved(self, fields, existing):
        if existing is None:
            self.selected["id"] = db.add_sealed(**fields)
            self.toast(f"Added {fields['name']}.")
        else:
            db.update_sealed(existing["id"], **fields)
        self.refresh()

    def remove(self, row):
        def confirmed(e):
            self.page.pop_dialog()
            db.remove_sealed([row["id"]])
            self.toast(f"Removed {row['name']}.")
            self.refresh()

        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("Remove"), content=ft.Text(f"Remove {row['name']} from your collection?"),
            actions=[theme.button("Cancel", lambda e: self.page.pop_dialog()),
                     theme.button("Remove", confirmed, primary=True)]))


class SealedDialog:
    """Add a sealed product (pick it from the catalog, or type your own), or edit an entry
    (existing: its row). on_save(fields for db.add_sealed / update_sealed, existing)."""

    def __init__(self, page, busy, on_save, existing=None):
        self.page, self.busy, self.on_save, self.existing = page, busy, on_save, existing
        self.results_rows = []
        self.chosen = None
        self.catalog = self.typed_form = None
        self.search = ft.TextField(hint_text="Search by product or set, e.g. “modern horizons 3 collector”…",
                                   dense=True, expand=True, on_change=lambda e: self.fill())
        self.category = ft.Dropdown(dense=True, width=230, value="", on_select=lambda e: self.fill(),
                                    options=[ft.DropdownOption(key="", text="Any type")])
        self.results = ft.ListView(height=260, spacing=0)
        self.status = ft.Text(size=12, color=theme.MUTED)
        self.custom = ft.Checkbox(label="It's not in the list: I'll type it in", on_change=lambda e: self.custom_changed())
        self.name = ft.TextField(dense=True, hint_text="e.g. Secret Lair: Bitterblossom Dreams", expand=True,
                                 on_change=lambda e: self.update_save())
        self.set_name = ft.TextField(dense=True, hint_text="Optional", expand=True)
        self.kind = ft.TextField(dense=True, hint_text="Optional, e.g. Booster Box", expand=True)
        self.quantity = ft.TextField(dense=True, width=100, value="1", keyboard_type=ft.KeyboardType.NUMBER)
        self.paid = ft.TextField(dense=True, width=160, prefix="$", hint_text="Not entered",
                                 tooltip="What you paid for each one")
        self.value = ft.TextField(dense=True, width=160, prefix="$", hint_text="Not entered",
                                  tooltip="What each one is worth now. Look it up on TCGplayer from the Sealed tab.")
        self.notes = ft.TextField(dense=True, multiline=True, min_lines=2, max_lines=3, expand=True,
                                  hint_text="Optional, e.g. bought at the prerelease, sealed in the closet")
        self.save = theme.button("Save Changes" if existing else "Add to Collection", self.saved, primary=True,
                                 disabled=True)

    @staticmethod
    def labeled(label, control):
        return ft.Row([ft.Text(label, width=130), control], vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def open(self):
        existing = self.existing
        self.typed_form = ft.Column([self.labeled("Name:", self.name), self.labeled("Set:", self.set_name),
                                     self.labeled("Type:", self.kind)], spacing=8)
        if existing is not None:
            # The product itself stays put when editing; only what you have of it changes
            self.name.value, self.set_name.value = existing["name"], existing["set_name"] or ""
            self.kind.value = existing["product_type"] or ""
            for field in (self.name, self.set_name, self.kind):
                field.disabled = existing["uuid"] is not None
            self.quantity.value = str(existing["quantity"])
            self.paid.value = f"{existing['paid']:.2f}" if existing["paid"] else ""
            self.value.value = f"{existing['value']:.2f}" if existing["value"] else ""
            self.notes.value = existing["notes"] or ""
            top = [self.typed_form]
        else:
            self.typed_form.visible = False
            self.catalog = ft.Column([ft.Row([self.search, self.category]), self.results, self.status], spacing=8)
            top = [self.catalog, self.custom, self.typed_form]
        details = [self.labeled("Quantity:", self.quantity), self.labeled("Paid (each):", self.paid),
                   self.labeled("Value now (each):", self.value), self.labeled("Notes:", self.notes)]
        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("Edit Sealed Product" if existing else "Add Sealed Product"),
            content=ft.Column([*top, ft.Divider(color=theme.LINE), *details], tight=True, spacing=10,
                              width=min(860, (self.page.width or 900) - 100), scroll=ft.ScrollMode.AUTO),
            actions=[theme.button("Cancel", lambda e: self.page.pop_dialog()), self.save]))
        if existing is None:
            self.load_catalog()
        self.update_save()
        self.page.update()

    # The catalog

    def load_catalog(self):
        if not db.has_sealed_catalog():
            self.status.value = "Downloading MTGJSON's list of sealed products…"
            self.page.update()
            if self.busy("Downloading the sealed product list", mtgjson.download_sealed_catalog) is None:
                self.status.value = "Couldn't download the sealed product list. You can still type a product in below."
                self.page.update()
                return
        self.category.options = [ft.DropdownOption(key="", text="Any type"),
                                 *[ft.DropdownOption(key=c, text=c) for c in db.sealed_categories()]]
        self.fill()

    def fill(self):
        rows = db.search_sealed_catalog(self.search.value or "", self.category.value or "", limit=RESULTS_SHOWN)
        self.results_rows = rows
        if self.chosen is not None and self.chosen["uuid"] not in {r["uuid"] for r in rows}:
            self.chosen = None
        self.results.controls = [self.result(r) for r in rows]
        more = f" (the first {RESULTS_SHOWN}; search to narrow it down)" if len(rows) == RESULTS_SHOWN else ""
        self.status.value = f"{len(rows):,} products{more}. Pick one, or type it in below if it isn't listed."
        self.update_save()
        self.page.update()

    def result(self, r):
        on = self.chosen is not None and r["uuid"] == self.chosen["uuid"]
        return ft.Container(ft.Row([
            ft.Text(r["name"], expand=3, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS, weight=ft.FontWeight.W_500),
            ft.Text(f"{r['set_name']} ({r['set_code']})", expand=2, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Text(r["product_type"] or "", expand=2, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Text(r["released"] or "", width=90, color=theme.MUTED)], spacing=12),
            padding=ft.Padding.symmetric(horizontal=10, vertical=7),
            bgcolor=theme.COLORS["primary_container"] if on else None,
            border=ft.Border.only(bottom=ft.BorderSide(1, theme.LINE)), on_click=lambda e, r=r: self.choose(r))

    def choose(self, row):
        self.chosen = row
        self.results.controls = [self.result(r) for r in self.results_rows]
        self.update_save()
        self.page.update()

    def custom_changed(self):
        on = self.custom.value
        self.catalog.disabled = on
        self.typed_form.visible = on
        self.update_save()
        self.page.update()

    def update_save(self):
        typed = self.existing is not None or self.custom.value
        self.save.disabled = not (self.name.value or "").strip() if typed else self.chosen is None

    # Saving

    def saved(self, e):
        try:
            count = max(1, int(self.quantity.value))
        except ValueError:
            self.quantity.error_text = "A number"
            self.page.update()
            return
        fields = {"quantity": count, "paid": _price(self.paid), "value": _price(self.value),
                  "notes": self.notes.value or ""}
        if self.existing is None and not self.custom.value:
            fields |= {k: self.chosen[k] for k in ("name", "set_code", "set_name", "product_type", "uuid")}
        elif self.existing is None or self.existing["uuid"] is None:
            fields |= {"name": self.name.value.strip(), "set_name": (self.set_name.value or "").strip() or None,
                       "product_type": (self.kind.value or "").strip() or None}
        self.page.pop_dialog()
        self.on_save(fields, self.existing)
