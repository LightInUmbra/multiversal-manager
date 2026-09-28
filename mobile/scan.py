# The phone's card scanner: point the camera at a card and tap the button. The text on the
# photo is read on the phone (card_reader/, Google ML Kit, offline), card_scan.py recognizes
# the card from it, and it's ready to add with its printing, finish and condition.
import asyncio
import json

import flet as ft
import flet_camera as fc
from flet_card_reader import CardReader

import card_scan
import copy_details
import database as db
import rules
import scryfall

MUTED = ft.Colors.ON_SURFACE_VARIANT
READY = "Fill the frame with one card, flat and well lit, then tap the button."


def _number(card):
    # A printing's collector number without leading zeros, as a photo's is read
    return (card.collector_number or "").lstrip("0")


def pick_printing(printings, set_code, number):
    """(index of the printing the photo showed, how sure: "exact", "set" or "newest"): the
    one with its set code and collector number, else its set, else the newest"""
    same_set = [i for i, c in enumerate(printings) if set_code and (c.set or "").upper() == set_code.upper()]
    exact = [i for i in same_set if number and _number(printings[i]) == number]
    if exact:
        return exact[0], "exact"
    return (same_set[0], "set") if same_set else (0, "newest")


class Scanner:
    def __init__(self, page, toast, on_added):
        self.page, self.toast, self.on_added = page, toast, on_added
        self.view = ft.Column(expand=True)
        self.active = False
        self.camera = None
        self.reader = None
        self._names = None
        self._reading = False
        self.status = ft.Text(READY, color=ft.Colors.WHITE, text_align=ft.TextAlign.CENTER)

    def names(self):
        # Every card name (the Rules tab's list, downloaded here if the rules haven't been)
        if self._names is None:
            path = rules.rules_dir() / "card_names.json"
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(scryfall.card_name_catalog()), encoding="utf-8")
            self._names = card_scan.Names(json.loads(path.read_text(encoding="utf-8")))
        return self._names

    def _say(self, text):
        self.status.value = text
        self.page.update()

    async def open(self):
        self.active = True
        if self.reader is None:
            self.reader = CardReader()
        self.camera = fc.Camera(expand=True)
        shutter = ft.FloatingActionButton(icon=ft.Icons.CAMERA_ALT, on_click=self.capture, tooltip="Scan")
        self.status.value = "Starting the camera…"
        self.view.controls = [ft.Stack([
            self.camera,
            ft.Container(ft.Column([self.status, shutter], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                   spacing=12, tight=True),
                         bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK), padding=16,
                         left=0, right=0, bottom=0),
        ], expand=True)]
        self.page.update()
        try:
            cameras = await self.camera.get_available_cameras()
            back = next((c for c in cameras if c.lens_direction == fc.CameraLensDirection.BACK), cameras[0])
            await self.camera.initialize(back, fc.ResolutionPreset.HIGH, enable_audio=False)
            self._say(READY)
        except Exception as error:
            self._say(f"The camera didn't start ({error}). Allow the camera for this app in Android's settings.")

    def close(self):
        self.active = False
        self.camera = None
        self.view.controls = []

    async def capture(self, e):
        if self._reading or self.camera is None:
            return
        self._reading = True
        try:
            self._say("Reading the card…")
            photo = await self.camera.take_picture()
            lines = await self.reader.read_text(photo)
            names = await asyncio.to_thread(self.names)
            name, set_code, number = card_scan.identify(lines, names)
            if not name:
                read = " / ".join(line["text"] for line in sorted(lines, key=lambda l: l["top"])[:3])
                self._say("Couldn't find a card name" + (f" in “{read}”" if read else "") + ". " + READY)
                return
            self._say(f"Found {name}. Looking up its printings…")
            printings = await asyncio.to_thread(scryfall.get_printings, name)
            if not printings:
                self._say(f"Found {name}, but Scryfall didn't answer. Check the internet and try again.")
                return
            self.confirm(printings, set_code, number)
            self._say(READY)
        except Exception as error:
            self._say(f"That didn't work ({error}). Try again.")
        finally:
            self._reading = False

    def confirm(self, printings, set_code, number):
        chosen, sure = pick_printing(printings, set_code, number)
        card = printings[chosen]
        image = ft.Image(src=scryfall.image_url_for(card) or "", height=300)
        printing = ft.Dropdown(label="Printing", value=str(chosen), options=[
            ft.DropdownOption(key=str(i), text=scryfall.printing_label(c)) for i, c in enumerate(printings)])
        finish = ft.Dropdown(label="Finish")
        quantity = ft.TextField(label="Quantity", value="1", keyboard_type=ft.KeyboardType.NUMBER)
        condition = ft.Dropdown(label="Condition", value=copy_details.DEFAULT_CONDITION, options=[
            ft.DropdownOption(key=k, text=v) for k, v in copy_details.CONDITIONS.items()])
        language = ft.Dropdown(label="Language", value=copy_details.DEFAULT_LANGUAGE, options=[
            ft.DropdownOption(key=k, text=v) for k, v in copy_details.LANGUAGES.items()])
        note = ft.Text({"exact": "Matched the set and number printed on the card.",
                        "set": "Matched the set printed on the card; check the number.",
                        "newest": "Couldn't read the set, so this is the newest printing: pick yours."}[sure],
                       size=12, color=MUTED)

        def show_finishes(e=None):
            chosen_card = printings[int(printing.value)]
            image.src = scryfall.image_url_for(chosen_card) or ""
            codes = scryfall.finish_codes(chosen_card) or [0]
            finish.options = [ft.DropdownOption(key=str(c), text=scryfall.FINISHES[c][1]) for c in codes]
            if finish.value not in {str(c) for c in codes}:
                finish.value = str(codes[0])
            self.page.update()

        def add(e):
            try:
                count = int(quantity.value)
            except (TypeError, ValueError):
                count = 0
            if count < 1:
                quantity.error_text = "Enter a number"
                self.page.update()
                return
            chosen_card = printings[int(printing.value)]
            db.add_card(**scryfall.card_record(chosen_card, int(finish.value), count),
                        condition=condition.value, language=language.value)
            self.page.pop_dialog()
            self.toast(f"Added {count}× {chosen_card.name}.")
            self.on_added()
            self._say(f"Added {chosen_card.name}. " + READY)

        printing.on_select = show_finishes
        show_finishes()
        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text(card.name), scrollable=True,
            content=ft.Column([image, note, printing, finish, quantity, condition, language], tight=True, spacing=12),
            actions=[ft.TextButton("Not this card", on_click=lambda e: self.page.pop_dialog()),
                     ft.TextButton("Add", on_click=add)]))
