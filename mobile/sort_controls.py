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
    ]


def _chip(text, on, on_click):
    return ft.Container(ft.Text(text, size=12.5, color=None if on else theme.MUTED), on_click=on_click,
                        bgcolor=theme.COLORS["primary_container"] if on else None,
                        border=ft.Border.all(1, theme.COLORS["primary_container"] if on else theme.COLORS["outline"]),
                        border_radius=8, padding=ft.Padding.symmetric(horizontal=11, vertical=6))


def chip(page, state):
    # The phone's control: the current order ("Price ↓ · Type"); tapping it opens the sheet
    return _chip(f"⇅ {card_sorting.label(state.view)}", True, lambda e: open_sheet(page, state))


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
