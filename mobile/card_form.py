# The desktop's Add Card / Edit Card window (add_card_dialog.py and printing_picker.py), for
# the web app's desktop layout: the form on the left, the chosen printing's image on the right.
import flet as ft

import copy_details
import database as db
import scryfall
import theme

IMAGE_WIDTH = 220
LABEL_WIDTH = 100


def _autocomplete(text):
    # The downloaded card database when there is one (instant, works offline), else Scryfall
    return db.card_names(text) if db.has_card_database() else scryfall.autocomplete(text)


def arrow_keys(page, pairs, fields=()):
    """Up and Down step through the dropdown last used in a dialog, like the desktop's combo
    boxes (a closed Flet dropdown ignores them, and never says it has focus). pairs:
    [(dropdown, changed)], changed() running after each step; typing in one of fields stops it.
    Returns use(dropdown), for when the dialog itself picks one (after looking a card up).
    Each dialog's call replaces the one before."""
    active = {"dropdown": None}

    def use(dropdown):
        active["dropdown"] = dropdown

    def key(e):
        dropdown = active["dropdown"]
        if dropdown is None or e.key not in ("Arrow Down", "Arrow Up") or not dropdown.options:
            return
        keys = [o.key for o in dropdown.options]
        index = keys.index(dropdown.value) if dropdown.value in keys else -1
        index = max(0, min(len(keys) - 1, index + (1 if e.key == "Arrow Down" else -1)))
        if keys[index] != dropdown.value:
            dropdown.value = keys[index]
            next(changed for d, changed in pairs if d is dropdown)()

    for dropdown, changed in pairs:
        chosen = dropdown.on_select

        def selected(e, dropdown=dropdown, chosen=chosen):
            use(dropdown)
            if chosen:
                chosen(e)

        dropdown.on_select = selected
    for field in fields:
        field.on_focus = lambda e: use(None)
    page.on_keyboard_event = key
    return use


def _row(label, control):
    return ft.Row([ft.Text(f"{label}:", width=LABEL_WIDTH), control],
                  vertical_alignment=ft.CrossAxisAlignment.CENTER)


def open_card_form(page, on_save, existing=None, name=None):
    """Add a card, or edit a collection entry (its database row as existing). on_save gets
    the keyword arguments for database.add_card / update_card. name: a card to look up
    straight away (adding a card seen in the deck builder)."""
    card_name = name
    printings = []
    arrows = {"use": lambda dropdown: None}  # set once the fields exist (see arrow_keys)
    name = ft.TextField(hint_text="Start typing a card name…", dense=True, expand=True, autofocus=True)
    suggestions = ft.Column(spacing=0, tight=True)
    suggestion_box = ft.Container(suggestions, visible=False, border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                                  margin=ft.Margin.only(left=LABEL_WIDTH + 10))
    printing = ft.Dropdown(editable=True, enable_filter=True, dense=True, expand=True, disabled=True)
    finish = ft.Dropdown(dense=True, width=200, disabled=True)
    price = ft.TextField(prefix="$", dense=True, width=140, value="0.00",
                         tooltip="Filled in from Scryfall's USD price; you can override it")
    status = ft.Text(color=ft.Colors.ON_SURFACE_VARIANT, size=12)
    quantity = ft.TextField(value="1", dense=True, width=100, keyboard_type=ft.KeyboardType.NUMBER)
    condition = ft.Dropdown(dense=True, width=260, value=copy_details.DEFAULT_CONDITION, options=[
        ft.DropdownOption(key=code, text=f"{label} ({code})") for code, label in copy_details.CONDITIONS.items()])
    language = ft.Dropdown(dense=True, width=260, value=copy_details.DEFAULT_LANGUAGE,
                           tooltip="Prices are for the English printing", options=[
        ft.DropdownOption(key=code, text=label) for code, label in copy_details.LANGUAGES.items()])
    notes = ft.TextField(hint_text="Optional, e.g. signed, altered art, in the red binder…",
                         multiline=True, min_lines=2, max_lines=3, dense=True, expand=True)
    image = ft.Container(width=IMAGE_WIDTH, height=IMAGE_WIDTH * 1.4, alignment=ft.Alignment.CENTER,
                         border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT), border_radius=8)
    save = theme.button("Save Changes" if existing else "Add to Collection", primary=True, disabled=True)

    def show_image(url=None, message="Look up a card to see it here"):
        image.content = (ft.Image(src=url, width=IMAGE_WIDTH, border_radius=8) if url
                         else ft.Text(message, italic=True, text_align=ft.TextAlign.CENTER,
                                      color=ft.Colors.ON_SURFACE_VARIANT))

    def typed(e):
        text = name.value.strip()
        if len(text) < 2:
            suggestion_box.visible = False
            page.update()
            return
        try:
            names = _autocomplete(text)
        except Exception:
            return  # the next keystroke tries again
        if name.value.strip() != text:
            return  # typing moved on while this was loading
        suggestions.controls = [ft.ListTile(title=ft.Text(n, size=13), dense=True, on_click=lambda e, n=n: look_up(n))
                                for n in names[:8]]
        suggestion_box.visible = bool(names)
        page.update()

    def look_up(card_name=None, select_id=None, foil=None, price_each=None):
        card_name = (card_name or name.value).strip()
        if not card_name:
            return
        suggestion_box.visible = False
        save.disabled = True
        status.value = f"Looking up “{card_name}”…"
        page.update()
        try:
            found = scryfall.get_printings(card_name)
        except Exception as error:
            status.value = f"Couldn't reach Scryfall: {error}"
            page.update()
            return
        printings[:] = found
        if not found:
            status.value = f"No card found matching “{card_name}”."
            printing.options, printing.disabled, finish.disabled = [], True, True
            show_image(message="No card found")
            page.update()
            return
        name.value = found[0].name
        printing.options = [ft.DropdownOption(key=str(i), text=scryfall.printing_label(c)) for i, c in enumerate(found)]
        ids = [c.id for c in found]
        printing.value = str(ids.index(select_id) if select_id in ids else 0)
        printing.disabled = False
        status.value = f"{len(found)} printing{'s' if len(found) != 1 else ''} found. Pick the one you own."
        save.disabled = False
        printing_changed(foil=foil, price_each=price_each)
        arrows["use"](printing)  # Up / Down now browse the printings, like the desktop

    def selected():
        return printings[int(printing.value)]

    def printing_changed(e=None, foil=None, price_each=None):
        # Offer only the finishes this printing exists in, keeping the current one if it does
        card = selected()
        codes = scryfall.finish_codes(card) or [0]
        wanted = int(foil) if foil is not None else int(finish.value or 0)
        finish.options = [ft.DropdownOption(key=str(c), text=scryfall.FINISHES[c][1]) for c in codes]
        finish.value = str(wanted if wanted in codes else codes[0])
        finish.disabled = len(codes) < 2
        price.value = f"{price_each if price_each is not None else scryfall.price_for(card, int(finish.value)):.2f}"
        show_image(scryfall.image_url_for(card))
        page.update()

    def finish_changed(e):
        price.value = f"{scryfall.price_for(selected(), int(finish.value)):.2f}"
        page.update()

    def saved(e):
        try:
            count = int(quantity.value)
            each = float(price.value or 0)
        except ValueError:
            count = 0
        if count < 1:
            quantity.error_text = "Enter a number"
            page.update()
            return
        page.pop_dialog()
        on_save({**scryfall.card_record(selected(), int(finish.value), count, price=each),
                 "condition": condition.value, "language": language.value, "notes": notes.value or ""})

    name.on_change = typed
    name.on_submit = lambda e: look_up()
    printing.on_select = printing_changed
    finish.on_select = finish_changed
    save.on_click = saved
    arrows["use"] = arrow_keys(page, [(printing, printing_changed), (finish, lambda: finish_changed(None))],
                               fields=[name, price, quantity, notes])
    show_image()

    form = ft.Column([
        _row("Name", ft.Row([name, theme.button("Look Up", lambda e: look_up())], expand=True)),
        suggestion_box,
        _row("Printing", printing), _row("Finish", finish), _row("Price (each)", price), status,
        _row("Quantity", quantity), _row("Condition", condition), _row("Language", language), _row("Notes", notes),
    ], spacing=10, width=560, tight=True, scroll=ft.ScrollMode.AUTO)
    page.show_dialog(ft.AlertDialog(
        title=ft.Text("Edit Card" if existing else "Add Card"),
        content=ft.Row([form, image], vertical_alignment=ft.CrossAxisAlignment.START, spacing=20, tight=True),
        actions=[theme.button("Cancel", lambda e: page.pop_dialog()), save]))

    if existing is not None:
        name.value = existing["name"]
        quantity.value = str(existing["quantity"])
        condition.value = existing["condition"]
        language.value = existing["language"]
        notes.value = existing["notes"] or ""
        # Reselect the entry's printing, finish and price once its printings load
        look_up(existing["name"], select_id=existing["scryfall_id"], foil=existing["foil"], price_each=existing["price"])
    elif card_name:
        look_up(card_name)
