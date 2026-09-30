# The desktop's File → Import (import_review_dialog.py), for the website's desktop layout: pick a
# file, confirm what was found, look the cards up on Scryfall, then review them in the same Review
# Import window (entries on the left, the selected one's printing on the right) before saving.
import flet as ft

import importer
import scryfall
import theme
from card_form import arrow_keys

EXTENSIONS = ["csv", "txt", "dec", "dek"]
IMAGE_WIDTH = 230
SIDE_WIDTH = 300
# The table's columns: (heading, width; None stretches)
COLUMNS = [("Import", 60), ("Qty", 64), ("Name", None), ("Printing", None), ("Finish", 90), ("Status", 300)]


async def start_import(page, picker, destination, on_done, busy, review=None):
    """The whole import: pick a file, confirm what was found, look the cards up, review.
    on_done(records) gets the add_card keyword dicts to save, or None if it was cancelled.
    picker: the page's ft.FilePicker. destination says where the cards go ("your collection").
    review(page, result, on_done): the review screen, with show(); ReviewDialog by default,
    the phone layout's is phone_import.PhoneReview."""
    # A phone's file picker goes by file type, and .dec / .dek have none it knows, so it offers every file
    by_extension = page.web or not page.platform.is_mobile()
    files = await picker.pick_files(
        dialog_title="Import Cards", with_data=True,
        file_type=ft.FilePickerFileType.CUSTOM if by_extension else ft.FilePickerFileType.ANY,
        allowed_extensions=EXTENSIONS if by_extension else None)
    if files:
        # The rest waits on the network, so it runs like any other handler (a thread on a computer)
        page.run_thread(_read, page, files[0], destination, on_done, busy, review or ReviewDialog)


def _message(page, text):
    page.show_dialog(ft.AlertDialog(title=ft.Text("Import"), content=ft.Text(text),
                                    actions=[theme.button("OK", lambda e: page.pop_dialog(), primary=True)]))


def _read(page, file, destination, on_done, busy, review):
    try:
        rows, errors = importer.parse((file.bytes or b"").decode("utf-8-sig"), file.name)
    except UnicodeDecodeError as error:
        _message(page, f"Couldn't read that file:\n{error}")
        return
    if not rows:
        _message(page, "\n".join(errors) or "No cards found in the file.")
        return

    def look_up(e):
        page.pop_dialog()
        result = busy("Looking up cards on Scryfall", lambda: importer.resolve(rows))
        if result is not None:
            review(page, result, on_done).show()

    total = sum(row.quantity for row in rows)
    content = [ft.Text(f"Found {importer.count(total, 'card')} in {importer.count(len(rows), 'entry')}.\n\n"
                       "Look them up on Scryfall? You'll be able to review them and choose printings before "
                       f"anything is added to {destination}.")]
    if errors:
        content.append(ft.Text(f"{importer.count(len(errors), 'line')} couldn't be read and will be skipped.",
                               color=theme.MUTED))
        content.append(ft.ExpansionTile(title=ft.Text("Show Details…", size=13), controls=[
            ft.Text("\n".join(errors), size=12, selectable=True)]))
    page.show_dialog(ft.AlertDialog(
        title=ft.Text("Import"), content=ft.Column(content, tight=True, width=min(460, (page.width or 460) - 80)),
        actions=[theme.button("No", lambda e: (page.pop_dialog(), on_done(None))),
                 theme.button("Yes", look_up, primary=True)]))


class ReviewDialog:
    """Shows every imported entry before anything is saved. Entries whose printing isn't
    certain are listed first; select one to pick the printing you own."""

    def __init__(self, page, result, on_done):
        self.page, self.on_done = page, on_done
        self.entries = importer.build_entries(result)
        self.current = None
        self.printings = {}  # card name -> its printings, looked up once
        self.summary = ft.Text()
        needs_review = any(e.state in importer.NEEDS_REVIEW for e in self.entries)
        self.review_only = ft.Checkbox(label="Show only entries that need a printing chosen", value=needs_review,
                                       on_change=lambda e: self.fill_table())
        self.table = ft.ListView(expand=True, spacing=0)
        self.rows = [self.row(entry) for entry in self.entries]

        self.image = ft.Container(width=IMAGE_WIDTH, height=IMAGE_WIDTH * 1.4, alignment=ft.Alignment.CENTER,
                                  border=ft.Border.all(1, theme.LINE), border_radius=8)
        self.title = ft.Text(size=15, weight=ft.FontWeight.BOLD)
        self.hint = ft.Text(size=12, color=theme.MUTED)
        self.printing = ft.Dropdown(dense=True, width=SIDE_WIDTH - 20, label="Printing", text_size=13,
                                     on_select=self.picked)
        self.finish = ft.Dropdown(dense=True, width=150, label="Finish", on_select=self.picked)
        self.price = ft.TextField(prefix="$", dense=True, width=120, label="Price (each)",
                                  on_submit=self.picked, on_blur=self.picked,
                                  tooltip="Filled in from Scryfall's USD price; you can override it")
        self.next = theme.button("Next Entry to Review ›", self.next_to_review)
        self.import_button = theme.button("Import", self.confirm, primary=True)
        self.use_dropdown = arrow_keys(page, [(self.printing, lambda: self.picked(None)),
                                              (self.finish, lambda: self.picked(None))], fields=[self.price])

    def show(self):
        page = self.page
        width = min(1200, (page.width or 1200) - 80)
        height = min(700, (page.height or 800) - 180)
        header = ft.Container(ft.Row([self.cell(ft.Text(h, size=12, weight=ft.FontWeight.BOLD, color=theme.GOLD), w)
                                      for h, w in COLUMNS], spacing=8),
                              bgcolor=theme.COLORS["surface_container_high"], padding=ft.Padding.symmetric(horizontal=8, vertical=6))
        side = ft.Column([self.image, self.title, self.hint, self.printing, ft.Row([self.finish, self.price]),
                          self.next], width=SIDE_WIDTH, spacing=10, scroll=ft.ScrollMode.AUTO)
        page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text("Review Import"),
            content=ft.Column([self.summary, self.review_only, ft.Row([
                theme.panel(ft.Column([header, self.table], spacing=0, expand=True), expand=True),
                side], expand=True, spacing=16, vertical_alignment=ft.CrossAxisAlignment.START)],
                width=width, height=height, spacing=8),
            actions=[theme.button("Cancel", lambda e: self.close(None)), self.import_button]))
        self.update_summary()
        self.fill_table(update=False)
        first = next((e for e in self.entries if self.visible(e)), self.entries[0] if self.entries else None)
        if first:
            self.select(first)
        page.update()

    # The table

    @staticmethod
    def cell(control, width):
        return ft.Container(control, width=width, expand=width is None)

    def row(self, entry):
        found = entry.card is not None
        include = ft.Checkbox(value=entry.include, disabled=not found,
                              on_change=lambda e, entry=entry: self.included(entry, e.control.value))
        quantity = ft.TextField(value=str(entry.quantity), dense=True, disabled=not found, text_size=13,
                                keyboard_type=ft.KeyboardType.NUMBER, content_padding=ft.Padding.symmetric(horizontal=6, vertical=4),
                                on_blur=lambda e, entry=entry: self.quantity(entry, e.control),
                                on_submit=lambda e, entry=entry: self.quantity(entry, e.control))
        if found:
            name, printing = entry.card.name, f"{entry.card.set_name} ({entry.card.set}) #{entry.card.collector_number}"
        else:
            name, printing = entry.row.name, entry.row.describe()
        color = (theme.GOLD if entry.state in importer.NEEDS_REVIEW
                 else theme.LOSS if entry.state == importer.NOT_FOUND else None)
        cells = [include, quantity, ft.Text(name, size=13, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                 ft.Text(printing, size=13, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                 ft.Text(scryfall.finish_label(entry.foil), size=13),
                 ft.Text(importer.STATUS_TEXT[entry.state], size=13, color=color)]
        return ft.Container(ft.Row([self.cell(c, w) for c, (_, w) in zip(cells, COLUMNS)], spacing=8),
                            padding=ft.Padding.symmetric(horizontal=8, vertical=2), on_click=lambda e, entry=entry: self.select(entry),
                            bgcolor=self.shade(entry), border=ft.Border.only(bottom=ft.BorderSide(1, theme.LINE)))

    def shade(self, entry):
        return theme.COLORS["primary_container"] if entry is self.current else None

    def visible(self, entry):
        return not self.review_only.value or entry.state in importer.NEEDS_REVIEW or entry is self.current

    def fill_table(self, update=True):
        self.table.controls = [row for entry, row in zip(self.entries, self.rows) if self.visible(entry)]
        if update:
            self.page.update()

    def refill(self, entry):
        index = self.entries.index(entry)
        self.rows[index] = self.row(entry)
        self.fill_table(update=False)

    def included(self, entry, value):
        entry.include = value
        self.update_summary()
        self.page.update()

    def quantity(self, entry, field):
        try:
            amount = int(field.value)
        except ValueError:
            amount = 0
        if amount > 0:
            entry.quantity = amount
        field.value = str(entry.quantity)
        self.update_summary()
        self.page.update()

    def update_summary(self):
        text, button = importer.review_summary(self.entries)
        self.summary.value = text
        self.import_button.content = button
        self.import_button.disabled = not any(e.include and e.card is not None for e in self.entries)
        self.next.disabled = not any(e.state in importer.NEEDS_REVIEW for e in self.entries)

    # Picking a printing

    def select(self, entry):
        previous, self.current = self.current, entry
        if previous is not None and previous in self.entries:
            self.rows[self.entries.index(previous)].bgcolor = None
        self.rows[self.entries.index(entry)].bgcolor = self.shade(entry)
        self.hint.value = f"From your file: {entry.row.describe()}"
        if entry.card is None:
            self.title.value = entry.row.name
            self.show_image(message="Not found on Scryfall")
            self.printing.options, self.printing.disabled, self.finish.disabled = [], True, True
            self.price.disabled = True
            self.page.update()
            return
        self.title.value = entry.card.name
        name = entry.card.name
        if name not in self.printings:
            try:
                self.printings[name] = scryfall.get_printings(name) or [entry.card]
            except Exception:
                self.printings[name] = [entry.card]  # offline: at least the matched printing
        printings = self.printings[name]
        ids = [c.id for c in printings]
        if entry.card.id not in ids:
            printings.insert(0, entry.card)
            ids.insert(0, entry.card.id)
        self.printing.options = [ft.DropdownOption(key=str(i), text=scryfall.printing_label(c))
                                 for i, c in enumerate(printings)]
        self.printing.value = str(ids.index(entry.card.id))
        self.printing.disabled = self.price.disabled = False
        self.show_printing(entry.card, entry.foil, entry.price)
        self.use_dropdown(self.printing)  # Up / Down browse the printings, like the desktop
        self.page.update()

    def show_printing(self, card, foil, price=None):
        codes = scryfall.finish_codes(card) or [0]
        self.finish.options = [ft.DropdownOption(key=str(c), text=scryfall.FINISHES[c][1]) for c in codes]
        self.finish.value = str(foil if foil in codes else codes[0])
        self.finish.disabled = len(codes) < 2
        self.price.value = f"{price if price is not None else scryfall.price_for(card, int(self.finish.value)):.2f}"
        self.show_image(scryfall.image_url_for(card))

    def show_image(self, url=None, message=""):
        self.image.content = (ft.Image(src=url, width=IMAGE_WIDTH, border_radius=8) if url else
                              ft.Text(message, italic=True, color=theme.MUTED, text_align=ft.TextAlign.CENTER))

    def picked(self, e):
        entry = self.current
        if entry is None or entry.card is None or self.printing.value is None:
            return
        card = self.printings[entry.card.name][int(self.printing.value)]
        foil = int(self.finish.value or 0)
        if card.id != entry.card.id:
            self.show_printing(card, foil)  # a new printing: its finishes and price
            foil = int(self.finish.value)
        elif e is None or e.control is self.finish:
            self.price.value = f"{scryfall.price_for(card, foil):.2f}"  # a new finish: its price
        try:
            price = float(self.price.value or 0)
        except ValueError:
            price = scryfall.price_for(card, foil)
        importer.choose_printing(entry, card, foil, price, scryfall.price_for(card, foil))
        self.refill(entry)
        self.update_summary()
        self.page.update()

    def next_to_review(self, e):
        # The next entry (after the selected one, wrapping around) still needing a decision
        start = self.entries.index(self.current) + 1 if self.current in self.entries else 0
        for offset in range(len(self.entries)):
            entry = self.entries[(start + offset) % len(self.entries)]
            if entry.state in importer.NEEDS_REVIEW:
                self.select(entry)
                self.fill_table()
                return
        self.fill_table()
        _message(self.page, "Every entry has a printing chosen.")

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
                            "may not be the one you own. Import anyway?\n\n(You can fix any entry later: select it "
                            "in your collection and choose Edit.)", width=440),
            actions=[theme.button("No", lambda e: self.page.pop_dialog()),
                     theme.button("Yes", anyway, primary=True)]))

    def records(self):
        return [e.record() for e in self.entries if e.include and e.card is not None]

    def close(self, records):
        self.page.pop_dialog()
        self.page.on_keyboard_event = None
        self.on_done(records)
