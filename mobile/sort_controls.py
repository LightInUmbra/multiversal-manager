# Sort / direction / Group controls for the website and the phone (card_sorting.py does the
# sorting): a toolbar row on the website, like the desktop's, and on the phone a chip beside the
# filter that opens a sheet of every choice. Groups show as a heading line that folds them away.
import flet as ft

import card_sorting
import theme


class SortState:
    """One list's view, remembered under key (card_sorting.load/save). on_change() redraws the
    list; extra_sorts: sorts beyond card_sorting's (the website table's own columns)."""

    def __init__(self, kind, key, on_change, extra_sorts=()):
        self.kind, self.key, self.on_change, self.extra_sorts = kind, key, on_change, list(extra_sorts)
        self.view = card_sorting.load(key, kind, self.extra_sorts)
        self.folded = set()  # group titles folded away

    def set_key(self, key, kind=None):
        # Another list's view (and kind, e.g. a binder after a deck)
        if (key, kind or self.kind) != (self.key, self.kind):
            self.key, self.kind = key, kind or self.kind
            self.view = card_sorting.load(key, self.kind, self.extra_sorts)
            self.folded = set()

    def sorts(self):
        return card_sorting.sorts_for(self.kind) + self.extra_sorts

    def pick(self, sort):
        # A sort chosen from the controls or a column header: the same one again flips the order
        self.set(card_sorting.picked(self.view, sort))

    def set(self, view):
        if view != self.view:
            self.view = view
            card_sorting.save(self.key, view)
            self.on_change()

    def toggle(self, title):
        self.folded ^= {title}
        self.on_change()

    def arrange(self, rows, busy=None, extra_keys=None):
        """card_sorting.arrange for this view. busy (main.py's): rows are the collection's, which
        lack card rules; they're added, looking up on Scryfall the ones the card database lacks."""
        if busy is not None and card_sorting.needs_rules(self.view):
            rows, missing = card_sorting.with_rules(rows)
            if missing and busy("Looking up cards", lambda: card_sorting.fetch_rules(missing)):
                rows, _ = card_sorting.with_rules(rows)
        return card_sorting.arrange(rows, self.view, self.kind, extra_keys)


def _dropdown(value, options, on_select, width):
    return ft.Dropdown(value=value, options=[ft.DropdownOption(key=k, text=t) for k, t in options], dense=True,
                       width=width, text_size=13, on_select=on_select, filled=True,
                       content_padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                       bgcolor=theme.COLORS["surface_container_low"],
                       border=ft.OutlineInputBorder(side=ft.BorderSide(1, theme.LINE), border_radius=6))


def toolbar(state):
    # The website's controls: Sort, direction and Group, for a toolbar row
    ascending, descending = card_sorting.direction_labels(state.view["sort"])
    return [
        _dropdown(state.view["sort"], [(s, f"Sort: {s}") for s in state.sorts()],
                  lambda e: state.pick(e.control.value), 170),
        theme.button(f"↓ {descending}" if state.view["descending"] else f"↑ {ascending}",
                     lambda e: state.set({**state.view, "descending": not state.view["descending"]})),
        _dropdown(state.view["group"], [(g, f"Group: {g}") for g in card_sorting.GROUPS[state.kind]],
                  lambda e: state.set({**state.view, "group": e.control.value}), 190),
        *([view_switch(state)] if state.kind in card_sorting.DISPLAY_KINDS else []),
    ]


def view_switch(state):
    # The website's View for a deck or list: List, Text, Grid or Stacks side by side
    def side(display):
        on = state.view["display"] == display
        return ft.Container(ft.Text(display, size=12.5, color=None if on else theme.MUTED),
                            bgcolor=theme.COLORS["primary_container"] if on else None,
                            padding=ft.Padding.symmetric(horizontal=10, vertical=7), tooltip=f"Show the cards as {display.lower()}",
                            on_click=lambda e: state.set({**state.view, "display": display}))

    return ft.Container(ft.Row([side(d) for d in card_sorting.DISPLAYS], spacing=0, tight=True),
                        border=ft.Border.all(1, theme.COLORS["outline"]), border_radius=6)


def _chip(text, on, on_click):
    return ft.Container(ft.Text(text, size=12.5, color=None if on else theme.MUTED), on_click=on_click,
                        bgcolor=theme.COLORS["primary_container"] if on else None,
                        border=ft.Border.all(1, theme.COLORS["primary_container"] if on else theme.COLORS["outline"]),
                        border_radius=8, padding=ft.Padding.symmetric(horizontal=11, vertical=6))


def chip(page, state):
    # The phone's control: the current order ("Price ↓ · Type", and a deck's View unless it's
    # List); tapping it opens the sheet
    display = state.view["display"] if state.kind in card_sorting.DISPLAY_KINDS else "List"
    return _chip(f"⇅ {card_sorting.label(state.view)}" + ("" if display == "List" else f" · {display}"), True,
                 lambda e: open_sheet(page, state))


def open_sheet(page, state):
    # Every choice at once, as a bottom sheet; each tap applies straight away
    body = ft.Column(tight=True, spacing=10, scroll=ft.ScrollMode.AUTO)

    def pick(**changes):
        state.set({**state.view, **changes})
        draw()

    def pick_sort(sort):
        if sort != state.view["sort"]:
            state.pick(sort)
        draw()

    def draw():
        view = state.view
        ascending, descending = card_sorting.direction_labels(view["sort"])

        def side(text, on_value):
            on = view["descending"] == on_value
            return ft.Container(ft.Text(text, size=12.5, color=None if on else theme.MUTED), expand=True,
                                alignment=ft.Alignment.CENTER, padding=ft.Padding.symmetric(vertical=7),
                                bgcolor=theme.COLORS["primary_container"] if on else None,
                                border=ft.Border.all(1, theme.COLORS["outline"]),
                                on_click=lambda e: pick(descending=on_value))

        body.controls = [
            ft.Text("Sort by", size=12, color=theme.MUTED),
            ft.Row([_chip(s, s == view["sort"], lambda e, s=s: pick_sort(s)) for s in state.sorts()],
                   wrap=True, spacing=6, run_spacing=6),
            ft.Row([side(ascending, False), side(descending, True)], spacing=0),
            ft.Text("Group by", size=12, color=theme.MUTED),
            ft.Row([_chip(g, g == view["group"], lambda e, g=g: pick(group=g)) for g in card_sorting.GROUPS[state.kind]],
                   wrap=True, spacing=6, run_spacing=6),
            *([ft.Text("View", size=12, color=theme.MUTED),
               ft.Row([_chip(d, d == view["display"], lambda e, d=d: pick(display=d)) for d in card_sorting.DISPLAYS],
                      wrap=True, spacing=6, run_spacing=6)] if state.kind in card_sorting.DISPLAY_KINDS else []),
            ft.Row([ft.FilledButton("Done", on_click=lambda e: page.pop_dialog(), expand=True)]),
        ]
        page.update()

    draw()
    page.show_dialog(ft.BottomSheet(ft.Container(body, padding=ft.Padding.only(left=16, right=16, top=18, bottom=20)),
                                    show_drag_handle=True))


def heading(state, title, rows, noun="card"):
    # A group's heading line on the phone (tap to fold): "▾ Creatures — 32 cards · $145.20"
    arrow = "▸" if title in state.folded else "▾"
    return ft.Container(ft.Text(f"{arrow} {card_sorting.heading(title, rows, noun)}", size=13,
                                weight=ft.FontWeight.W_600, color=theme.GOLD),
                        padding=ft.Padding.only(left=4, top=10, bottom=4),
                        border=ft.Border.only(bottom=ft.BorderSide(1, theme.COLORS["outline"])),
                        on_click=lambda e: state.toggle(title))


# A deck's or list's other views (card_sorting.DISPLAYS), for the website and the phone

CARD_RATIO = 680 / 488
STACK_SHOWN = 0.14  # the share of a card's height each card in a stack leaves showing (its name bar)
ITEM_PAD = 2        # room item() may add around each card (the website's selection highlight)


class ViewTip:
    """Tells people once that decks have other views, until they dismiss it or pick one
    (remembered on the device, in the browser too, where the database doesn't last)"""

    KEY = "tip:deck_views"

    def __init__(self, page):
        self.page, self.seen = page, True  # seen until the device says otherwise
        self.prefs = ft.SharedPreferences()
        page.run_task(self._load)

    async def _load(self):
        self.seen = bool(await self.prefs.get(self.KEY))

    def dismiss(self):
        if not self.seen:
            self.seen = True
            self.page.run_task(self.prefs.set, self.KEY, "1")

    def control(self, state, on_dismiss):
        # The tip for state's list, or None: not for the collection or sealed, nor once it's been seen
        if self.seen or state.kind not in card_sorting.DISPLAY_KINDS:
            return None
        if state.view["display"] != "List":
            self.dismiss()
            return None
        return ft.Container(ft.Row([
            ft.Text("New", size=12.5, weight=ft.FontWeight.BOLD, color=theme.GOLD),
            ft.Text(card_sorting.VIEW_TIP, size=12.5, expand=True),
            ft.TextButton("Got it", on_click=lambda e: (self.dismiss(), on_dismiss()))], spacing=10),
            bgcolor=theme.COLORS["surface_container_high"], border=ft.Border.all(1, theme.GOLD), border_radius=8,
            padding=ft.Padding.only(left=12, right=4, top=2, bottom=2))


def card_views(state, groups, item, width, columns=1):
    """state's list in its Text, Grid or Stacks view. groups: [(title, entries)]; item(entry,
    control) makes a card's control clickable (it may add ITEM_PAD around it); width: a card
    image's width; columns: the Text view's columns. Headings fold their group, as in List."""
    display, height = state.view["display"], width * CARD_RATIO

    def heading_line(title, rows):
        arrow = "▸" if title in state.folded else "▾"
        return ft.Container(ft.Text(f"{arrow} {title} ({card_sorting.totals(rows)[0]})", size=12.5, color=theme.GOLD,
                                    weight=ft.FontWeight.W_600, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                            padding=ft.Padding.only(top=8, bottom=4), on_click=lambda e: state.toggle(title))

    def shown(title, rows):
        return [] if title in state.folded else rows

    def image(e):
        url = e["image_url"].replace("/normal/", "/small/") if e["image_url"] else None
        placeholder = ft.Container(ft.Text(e["name"], size=11), width=width, height=height, padding=6, border_radius=8,
                                   bgcolor=theme.COLORS["surface_container_high"])
        badge = [ft.Container(ft.Text(f"×{e['quantity']}", size=11, weight=ft.FontWeight.BOLD, color="#FFFFFF"),
                              bgcolor="#C0000000", border_radius=9, right=5, top=height * 0.035,
                              padding=ft.Padding.symmetric(horizontal=6, vertical=1))] if e["quantity"] > 1 else []
        card = ft.Image(src=url, width=width, height=height, border_radius=width * 0.05,
                        error_content=placeholder) if url else placeholder
        return ft.Stack([card, *badge], width=width, height=height)

    if display == "Text":
        return ft.Row([ft.Column([line for title, rows in column for line in [heading_line(title, rows)] + [
            item(e, ft.Text(f"{e['quantity']}   {e['name']}", size=13.5)) for e in shown(title, rows)]],
            spacing=1, expand=True) for column in card_sorting.balance(groups, columns)],
            vertical_alignment=ft.CrossAxisAlignment.START, spacing=20)
    if display == "Stacks":
        size = width + 2 * ITEM_PAD

        def stack(title, rows):
            cards = shown(title, rows)
            step = height * STACK_SHOWN
            return ft.Column([heading_line(title, rows), ft.Stack(
                [ft.Container(item(e, image(e)), top=i * step) for i, e in enumerate(cards)],
                width=size, height=(len(cards) - 1) * step + height + 2 * ITEM_PAD if cards else 0)], spacing=0, width=size)

        return ft.Row([stack(title, rows) for title, rows in groups], wrap=True, spacing=12, run_spacing=12,
                      vertical_alignment=ft.CrossAxisAlignment.START)
    return ft.Column([part for title, rows in groups for part in [heading_line(title, rows)] + (
        [ft.Row([item(e, image(e)) for e in shown(title, rows)], wrap=True, spacing=8, run_spacing=8)]
        if shown(title, rows) else [])], spacing=4)


# Swiping between cards on the phone: a card opened from a list moves to the next one (swipe
# left) or the one before (swipe right), in the order the list shows them

SWIPE_DISTANCE = 60  # pixels sideways that count as a swipe


def _step(rows, index, go, delta):
    if 0 <= index + delta < len(rows):
        go(index + delta)


def swipe(content, rows, index, go):
    # content (a card's dialog, sheet or page) that calls go(the next or previous index) when
    # dragged sideways. By distance, from where the drag starts to where it ends: the drag's
    # reported velocity can have the wrong sign (it did in the browser)
    start = {}

    def ended(e):
        moved = e.global_position.x - start.get("x", e.global_position.x)
        if abs(moved) > SWIPE_DISTANCE:
            _step(rows, index, go, 1 if moved < 0 else -1)

    return ft.GestureDetector(content, on_horizontal_drag_start=lambda e: start.update(x=e.global_position.x),
                              on_horizontal_drag_end=ended)


def pager(rows, index, go):
    # "‹  3 of 41  ›" above a card, so swiping is found (and there's a way without it)
    return ft.Row([
        ft.IconButton(ft.Icons.CHEVRON_LEFT, tooltip="Previous card", disabled=index == 0,
                      on_click=lambda e: _step(rows, index, go, -1)),
        ft.Text(f"{index + 1} of {len(rows)}", size=12.5, color=theme.MUTED, expand=True, text_align=ft.TextAlign.CENTER),
        ft.IconButton(ft.Icons.CHEVRON_RIGHT, tooltip="Next card", disabled=index == len(rows) - 1,
                      on_click=lambda e: _step(rows, index, go, 1))], spacing=0)
