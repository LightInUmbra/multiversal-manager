# The phone layout's Review Import (the desktop's is import_review_dialog.py, the website desktop
# layout's web_import.ReviewDialog): the file's entries on one screen, grouped by what they need,
# and a sheet to choose an entry's printing. Picking the file and looking it up is web_import's.
import flet as ft

import importer
import scryfall
import theme

IMAGE_WIDTH = 120


class PhoneReview:
    """Takes the Collection's place until it's saved or cancelled. host: main.py's
    (open(view), close()) to show and remove it; on_done(records or None) as in web_import."""

    def __init__(self, page, result, on_done, host):
        self.page, self.on_done, self.host = page, on_done, host
        self.entries = importer.build_entries(result)
        self.printings = {}  # card name -> its printings, looked up once
        self.summary = ft.Text(size=12.5, color=theme.MUTED)
        self.list = ft.ListView(expand=True, spacing=0)
        self.import_button = ft.FilledButton("Import", expand=True, on_click=self.confirm)
        self.view = ft.Column([
            ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, tooltip="Cancel the import", on_click=lambda e: self.close(None)),
                    ft.Text("Review Import", font_family=theme.TITLE_FONT, size=18, weight=ft.FontWeight.W_600,
                            color=theme.GOLD)], spacing=4),
            self.summary, self.list,
            ft.Row([ft.OutlinedButton("Cancel", on_click=lambda e: self.close(None)), self.import_button], spacing=10),
        ], expand=True, spacing=8)

    def show(self):
        self.fill(update=False)
        self.host[0](self)

    def back(self):
        # Android's back button: an import in review is cancelled, like the arrow
        self.close(None)

    # The list

    def fill(self, update=True):
        text, button = importer.review_summary(self.entries)
        self.summary.value = text
        self.import_button.content = button
        self.import_button.disabled = not any(e.include and e.card is not None for e in self.entries)
        groups = [("Needs a printing", [e for e in self.entries if e.state in importer.NEEDS_REVIEW]),
                  ("Ready", [e for e in self.entries if e.card is not None and e.state not in importer.NEEDS_REVIEW]),
                  ("Not found", [e for e in self.entries if e.card is None])]
        self.list.controls = [control for title, entries in groups if entries
                              for control in (self.heading(f"{title} · {len(entries)}"), *map(self.row, entries))]
        if update:
            self.page.update()

    @staticmethod
    def heading(text):
        return ft.Container(ft.Text(text.upper(), size=11, weight=ft.FontWeight.BOLD, color=theme.GOLD),
                            padding=ft.Padding.only(top=12, bottom=4))

    def row(self, entry):
        if entry.card is None:
            return ft.ListTile(title=ft.Text(entry.row.name, color=theme.MUTED), dense=True,
                               subtitle=ft.Text(f"✗ Not found on Scryfall, skipped · line {entry.row.line}",
                                                color=theme.LOSS, size=12))
        finish = scryfall.finish_label(entry.foil)
        title = f"{entry.quantity}× {entry.card.name}" + (f" ✦ {finish}" if finish else "")
        printing = f"{entry.card.set_name} #{entry.card.collector_number}"
        if not entry.include:
            status, color = f"Not importing · {printing}", theme.MUTED
        elif entry.state in importer.NEEDS_REVIEW:
            reason = "File's printing not found" if entry.state == importer.FELL_BACK else "File didn't say which"
            status, color = f"⚠ {reason} · {printing}", theme.GOLD
        else:
            status, color = f"✓ {printing}", theme.MUTED
        return ft.ListTile(title=ft.Text(title, weight=ft.FontWeight.W_500), dense=True,
                           subtitle=ft.Text(status, color=color, size=12, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                           trailing=ft.Icon(ft.Icons.CHEVRON_RIGHT, color=theme.MUTED),
                           on_click=lambda e, entry=entry: self.open(entry))

    # The printing sheet

    def open(self, entry):
        name = entry.card.name
        if name not in self.printings:
            try:
                self.printings[name] = scryfall.get_printings(name) or [entry.card]
            except Exception:
                self.printings[name] = [entry.card]  # offline: at least the matched printing
        printings = self.printings[name]
        if entry.card.id not in [c.id for c in printings]:
            printings.insert(0, entry.card)
        image = ft.Container(width=IMAGE_WIDTH, height=IMAGE_WIDTH * 1.4, border_radius=8)
        printing = ft.Dropdown(dense=True, text_size=13, label="Printing", expand=True, value=str(
            [c.id for c in printings].index(entry.card.id)), options=[
            ft.DropdownOption(key=str(i), text=scryfall.printing_label(c)) for i, c in enumerate(printings)])
        finish = ft.Dropdown(dense=True, text_size=13, label="Finish", expand=True)
        price = ft.TextField(prefix="$", dense=True, width=100, label="Price", keyboard_type=ft.KeyboardType.NUMBER)
        quantity = ft.TextField(value=str(entry.quantity), dense=True, width=80, label="Qty",
                                keyboard_type=ft.KeyboardType.NUMBER)
        include = ft.Switch(label="Import this card", value=entry.include)

        def show_printing(card, foil, each=None):
            codes = scryfall.finish_codes(card) or [0]
            finish.options = [ft.DropdownOption(key=str(c), text=scryfall.FINISHES[c][1]) for c in codes]
            finish.value = str(foil if foil in codes else codes[0])
            finish.disabled = len(codes) < 2
            price.value = f"{each if each is not None else scryfall.price_for(card, int(finish.value)):.2f}"
            url = scryfall.image_url_for(card)
            image.content = ft.Image(src=url, width=IMAGE_WIDTH, border_radius=8) if url else None

        def printing_changed(e):
            show_printing(printings[int(printing.value)], int(finish.value or 0))
            self.page.update()

        def finish_changed(e):
            price.value = f"{scryfall.price_for(printings[int(printing.value)], int(finish.value)):.2f}"
            self.page.update()

        def keep(go_next):
            card = printings[int(printing.value)]
            foil = int(finish.value or 0)
            try:
                each = float(price.value or 0)
            except ValueError:
                each = scryfall.price_for(card, foil)
            importer.choose_printing(entry, card, foil, each, scryfall.price_for(card, foil))
            try:
                entry.quantity = max(1, int(quantity.value))
            except ValueError:
                pass
            entry.include = include.value
            self.page.pop_dialog()
            self.fill()
            following = self.next_after(entry)
            if go_next and following is not None:
                self.open(following)

        printing.on_select = printing_changed
        finish.on_select = finish_changed
        show_printing(entry.card, entry.foil, entry.price)
        following = self.next_after(entry)
        self.page.show_dialog(ft.BottomSheet(ft.Container(ft.Column([
            ft.Row([image, ft.Column([
                ft.Text(name, size=16, weight=ft.FontWeight.BOLD),
                ft.Text(f"From your file: {entry.row.describe()}", size=12, color=theme.MUTED),
            ], expand=True, spacing=4)], vertical_alignment=ft.CrossAxisAlignment.START),
            ft.Row([printing]), ft.Row([finish, price]), ft.Row([quantity, include], spacing=16),
            ft.Row([ft.OutlinedButton("Keep this", expand=True, on_click=lambda e: keep(False)),
                    ft.FilledButton("Next ›", expand=True, on_click=lambda e: keep(True), visible=following is not None)],
                   spacing=10),
        ], tight=True, spacing=12, scroll=ft.ScrollMode.AUTO), padding=16), show_drag_handle=True))

    def next_after(self, entry):
        # The next entry (after this one, wrapping around) still needing a printing, if any
        start = self.entries.index(entry) + 1
        for offset in range(len(self.entries)):
            candidate = self.entries[(start + offset) % len(self.entries)]
            if candidate is not entry and candidate.state in importer.NEEDS_REVIEW:
                return candidate
        return None

    # Finishing

    def confirm(self, e):
        unreviewed = sum(e.state in importer.NEEDS_REVIEW and e.include for e in self.entries)
        if not unreviewed:
            self.close(self.records())
            return

        def anyway(e):
            self.page.pop_dialog()
            self.close(self.records())

        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("Review Import"),
            content=ft.Text(f"{importer.count(unreviewed, 'included entry')} still use a suggested printing that "
                            "may not be the one you own. Import anyway?\n\n(You can fix any card later: tap it in "
                            "your collection.)"),
            actions=[ft.TextButton("No", on_click=lambda e: self.page.pop_dialog()),
                     ft.TextButton("Yes", on_click=anyway)]))

    def records(self):
        return [e.record() for e in self.entries if e.include and e.card is not None]

    def close(self, records):
        self.host[1]()
        self.on_done(records)
