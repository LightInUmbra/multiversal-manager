# The phone layout's sealed product (the desktop's is sealed.py): the Sealed side of Collection's
# Cards | Sealed switch, a full screen to find a product in MTGJSON's list, and one sheet for what
# you have of it. Prices are yours to enter, as on the desktop: there's no free source for them.
from urllib.parse import quote_plus

import flet as ft

import database as db
import mtgjson
import price_changes
import sort_controls
import theme
from web_finance import _money

SHOWN = 200  # catalog results drawn at once; search narrows the rest down


def gain_text(change, paid=None):
    # "+$89.99", or with what it's out of: "+$212.40 (+23.4%) on $905.00 paid"
    if change is None:
        return ""
    text = f"{'+' if change >= 0 else '−'}${abs(change):,.2f}"
    return f"{text} ({'+' if change >= 0 else '−'}{abs(change) / paid * 100:.1f}%) on ${paid:,.2f} paid" if paid else text


def gain_color(change):
    return theme.MUTED if not change or abs(change) <= 0.004 else theme.GAIN if change > 0 else theme.LOSS


def _price(field):
    # A dollar field: None when it's empty or 0 (not entered), like the desktop's
    try:
        value = float((field.value or "").replace("$", "").replace(",", ""))
    except ValueError:
        return None
    return value or None


class PhoneSealed:
    """What Collection shows with Sealed switched on: view and refresh(). host: main.py's
    (open(screen), close()) for the Add Sealed Product screen; busy and toast are main.py's."""

    def __init__(self, page, toast, busy, host):
        self.page, self.toast, self.busy, self.host = page, toast, busy, host
        self.total = ft.Column(spacing=1)
        self.search = ft.TextField(hint_text="Filter by product, set, type or notes", prefix_icon=ft.Icons.SEARCH,
                                   dense=True, expand=True, on_change=lambda e: self.refresh())
        # Sort and group (card_sorting.py): a chip beside the filter opens every choice
        self.sorting = sort_controls.SortState("sealed", "sealed", lambda: self.refresh())
        self.search_row = ft.Row([self.search], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.list = ft.ListView(expand=True, spacing=0)
        self.view = ft.Column([
            ft.Container(self.total, border=ft.Border.all(1, theme.LINE), border_radius=10,
                         bgcolor=theme.COLORS["surface"], padding=ft.Padding.symmetric(horizontal=12, vertical=8)),
            self.search_row, self.list], expand=True, spacing=8)

    def refresh(self):
        count, value, paid, value_of_paid = db.sealed_summary()
        change = value_of_paid - paid if paid else None
        self.total.controls = [
            ft.Text(f"Sealed value · {count:,} item{'s' if count != 1 else ''}", size=12, color=theme.MUTED),
            ft.Text(f"${value:,.2f}", size=20, weight=ft.FontWeight.BOLD),
            *([ft.Text(gain_text(change, paid), size=12.5, color=gain_color(change),
                       tooltip="Only items with both a paid price and a value count")] if paid else [])]
        needle = (self.search.value or "").strip().lower()
        rows = [r for r in db.get_sealed() if not needle or needle in " ".join(
            str(r[k] or "") for k in ("name", "set_name", "set_code", "product_type", "notes")).lower()]
        self.search_row.controls = [self.search, sort_controls.chip(self.page, self.sorting)]
        lines, shown = [], []  # shown: the items in the order they show, which swiping follows
        for title, members in self.sorting.arrange(rows):
            if title is not None:
                lines.append(sort_controls.heading(self.sorting, title, members, noun="item"))
                if title in self.sorting.folded:
                    continue
            lines += [self.row(r, shown, len(shown) + j) for j, r in enumerate(members)]
            shown += members
        self.list.controls = lines or [ft.Container(ft.Text(
            "No sealed product yet. Tap + to add a booster box, bundle, precon…" if not needle else "Nothing matches.",
            italic=True, color=theme.MUTED), padding=ft.Padding.only(top=20))]
        self.page.update()

    def row(self, r, rows, index):
        change = price_changes.sealed_gain(r)
        worth = f"{r['quantity']} × {_money(r['value'])}"
        return ft.Container(ft.Row([
            ft.Column([ft.Text(r["name"], weight=ft.FontWeight.W_500, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                       ft.Text(" · ".join(filter(None, [r["set_name"], r["product_type"]])), size=12, color=theme.MUTED,
                               no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)], spacing=1, expand=True),
            ft.Column([ft.Text(worth),
                       ft.Text(gain_text(change) if change is not None else
                               ("No value yet" if r["value"] is None else ""), size=12,
                               color=gain_color(change) if change is not None else theme.MUTED)],
                      spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END),
        ], spacing=10), padding=ft.Padding.symmetric(horizontal=4, vertical=8),
            border=ft.Border.only(bottom=ft.BorderSide(1, theme.LINE)), on_click=lambda e: self.details(existing=r, rows=rows, index=index))

    # Adding

    def add(self):
        # The + button with Sealed switched on
        AddSealed(self).open()

    # The details sheet: adding a product from the list, typing one in, or editing one you own

    def details(self, existing=None, product=None, typed=False, on_added=None, rows=None, index=None):
        """An item's sheet: existing (one you own, which swipes along rows from index), or
        product (from the catalog) or typed (your own) to add"""
        name = ft.TextField(label="Name", dense=True, hint_text="e.g. Secret Lair: Bitterblossom Dreams")
        set_name = ft.TextField(label="Set", dense=True, hint_text="Optional", expand=True)
        kind = ft.TextField(label="Type", dense=True, hint_text="Optional, e.g. Booster Box", expand=True)
        quantity = ft.TextField(label="Qty", dense=True, width=70, value=str(existing["quantity"]) if existing else "1",
                                keyboard_type=ft.KeyboardType.NUMBER)
        paid = ft.TextField(label="Paid each", dense=True, prefix="$", expand=True, keyboard_type=ft.KeyboardType.NUMBER,
                            value=f"{existing['paid']:.2f}" if existing and existing["paid"] else "",
                            tooltip="What you paid for each one")
        value = ft.TextField(label="Value each", dense=True, prefix="$", expand=True,
                             keyboard_type=ft.KeyboardType.NUMBER,
                             value=f"{existing['value']:.2f}" if existing and existing["value"] else "",
                             tooltip="What each one is worth now. Look it up on TCGplayer from here once it's added.")
        notes = ft.TextField(label="Notes", dense=True, multiline=True, min_lines=1, max_lines=3,
                             hint_text="Optional, e.g. bought at the prerelease",
                             value=existing["notes"] if existing else "")
        custom = typed or (existing is not None and existing["uuid"] is None)  # its name, set and type are editable
        if existing is not None:
            name.value, set_name.value = existing["name"], existing["set_name"] or ""
            kind.value = existing["product_type"] or ""
        title = existing["name"] if existing else product["name"] if product else "Type in a product"
        subtitle = (" · ".join(filter(None, [existing["set_name"], existing["product_type"]])) if existing else
                    " · ".join(filter(None, [product["set_name"], product["product_type"]])) if product else "")

        inputs = [name, set_name, kind, quantity, paid, value, notes]
        start = [f.value for f in inputs]

        def go(to):
            # Swiped to another item: saves any change first
            if [f.value for f in inputs] != start:
                if not save(None):
                    return  # something to fix first
            else:
                self.page.pop_dialog()
            self.details(existing=rows[to], rows=rows, index=to)

        def save(e):
            try:
                count = max(1, int(quantity.value))
            except ValueError:
                quantity.error_text = "A number"
                self.page.update()
                return False
            fields = {"quantity": count, "paid": _price(paid), "value": _price(value), "notes": notes.value or ""}
            if custom:
                if not (name.value or "").strip():
                    name.error_text = "Name the product"
                    self.page.update()
                    return False
                fields |= {"name": name.value.strip(), "set_name": (set_name.value or "").strip() or None,
                           "product_type": (kind.value or "").strip() or None}
            self.page.pop_dialog()
            if existing is not None:
                db.update_sealed(existing["id"], **fields)
                self.toast(f"Saved {existing['name']}.")
            else:
                if product is not None:
                    fields |= {k: product[k] for k in ("name", "set_code", "set_name", "product_type", "uuid")}
                db.add_sealed(**fields)
                self.toast(f"Added {fields['name']}.")
                if on_added:
                    on_added()
            self.refresh()
            return True

        def remove(e):
            if remove_button.data:
                self.page.pop_dialog()
                db.remove_sealed([existing["id"]])
                self.toast(f"Removed {existing['name']}.")
                self.refresh()
            else:
                remove_button.data = True  # a second tap confirms, so a stray one can't lose it
                remove_button.content = "Tap again to remove"
                self.page.update()

        remove_button = ft.TextButton("Remove", on_click=remove, style=ft.ButtonStyle(color=theme.LOSS))
        controls = [sort_controls.pager(rows, index, go)] if rows else []
        controls.append(ft.Text(title, size=16, weight=ft.FontWeight.BOLD))
        if subtitle:
            controls.append(ft.Text(subtitle, size=12, color=theme.MUTED))
        if custom:
            controls += [name, ft.Row([set_name, kind], spacing=8)]
        controls += [ft.Row([quantity, paid, value], spacing=8), notes,
                     ft.FilledButton("Save Changes" if existing else "Add to Collection", on_click=save)]
        if existing is not None:
            controls.append(ft.Row([
                remove_button,
                ft.TextButton("Look up on TCGplayer ↗",
                              url=f"https://www.tcgplayer.com/search/magic/product?q={quote_plus(existing['name'])}")],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN))
        body = ft.Container(ft.Column(controls, tight=True, spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                                      scroll=ft.ScrollMode.AUTO), padding=16)
        self.page.show_dialog(ft.BottomSheet(sort_controls.swipe(body, rows, index, go) if rows else body,
                                             show_drag_handle=True))


class AddSealed:
    """The Add Sealed Product screen: search MTGJSON's list by product or set, narrow it by type,
    tap a product for its details sheet, or type one in when it isn't listed."""

    def __init__(self, sealed):
        self.sealed, self.page = sealed, sealed.page
        self.category = ""
        self.search = ft.TextField(hint_text="Search by product or set, e.g. “modern horizons 3 collector”",
                                   prefix_icon=ft.Icons.SEARCH, dense=True, on_change=lambda e: self.fill())
        self.chips = ft.Row(spacing=6, wrap=True)
        self.status = ft.Text(size=12, color=theme.MUTED)
        self.results = ft.ListView(expand=True, spacing=0)
        self.view = ft.Column([
            ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, tooltip="Back", on_click=lambda e: self.back()),
                    ft.Text("Add Sealed Product", font_family=theme.TITLE_FONT, size=18, weight=ft.FontWeight.W_600,
                            color=theme.GOLD)], spacing=4),
            self.search, self.chips,
            ft.Row([self.status, ft.TextButton("Type one in ›", on_click=lambda e: self.sealed.details(
                typed=True, on_added=self.back))], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True),
            self.results], expand=True, spacing=8)

    def open(self):
        self.sealed.host[0](self)
        if not db.has_sealed_catalog():
            self.status.value = "Downloading MTGJSON's list of sealed products…"
            self.page.update()
            if self.sealed.busy("Downloading the sealed product list", mtgjson.download_sealed_catalog) is None:
                self.status.value = "Couldn't download the product list. You can still type a product in."
                self.page.update()
                return
        self.fill()

    def back(self):
        self.sealed.host[1]()
        self.sealed.refresh()

    def fill(self):
        def choose(category):
            self.category = category
            self.fill()

        self.chips.controls = [
            ft.Container(ft.Text(label, size=12.5, color=None if category == self.category else theme.MUTED),
                         on_click=lambda e, category=category: choose(category), border_radius=8,
                         bgcolor=theme.COLORS["primary_container"] if category == self.category else None,
                         border=ft.Border.all(1, theme.COLORS["primary_container"] if category == self.category
                                              else theme.COLORS["outline"]),
                         padding=ft.Padding.symmetric(horizontal=10, vertical=5))
            for category, label in [("", "Any type"), *((c, c) for c in db.sealed_categories())]]
        rows = db.search_sealed_catalog(self.search.value or "", self.category, limit=SHOWN)
        self.status.value = (f"{len(rows):,} product{'s' if len(rows) != 1 else ''}"
                             + (f", the first {SHOWN}; search to narrow it down" if len(rows) == SHOWN else "") + ".")
        self.results.controls = [ft.ListTile(
            title=ft.Text(r["name"], weight=ft.FontWeight.W_500),
            subtitle=ft.Text(" · ".join(filter(None, [r["set_name"], r["product_type"], r["released"]])), size=12,
                             color=theme.MUTED), dense=True,
            on_click=lambda e, r=r: self.sealed.details(product=r, on_added=self.back)) for r in rows]
        self.page.update()
