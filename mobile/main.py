# Multiversal Manager for phones, in Flet. The collection, prices and sync are the desktop
# app's own modules (database, scryfall, sync, copy_details); build_apk.py copies them in
# next to this file. The phone keeps its own collection.db and syncs it like the desktop.
# build_web.py builds the same app for the browser, where Python has no threads and its
# files are gone after a reload (see WEB).
import asyncio
import sys
import threading
import time
from pathlib import Path

# Run from the repo (flet run mobile/main.py), the shared modules are one folder up
_REPO = Path(__file__).resolve().parent.parent
if (_REPO / "database.py").exists():
    sys.path.insert(0, str(_REPO))

import flet as ft  # noqa: E402

import card_form  # noqa: E402
import copy_details  # noqa: E402
import database as db  # noqa: E402
import decks  # noqa: E402
import importer  # noqa: E402
import rules_tab  # noqa: E402
import scan  # noqa: E402
import scryfall  # noqa: E402
import sync  # noqa: E402
import theme  # noqa: E402
import web_decks  # noqa: E402
import web_desktop  # noqa: E402
import phone_finance  # noqa: E402
import phone_import as phone_import_review  # noqa: E402
import phone_sealed  # noqa: E402
import web_finance  # noqa: E402
import web_import  # noqa: E402
import web_rules  # noqa: E402
import web_sealed  # noqa: E402

APP_NAME = "Multiversal Manager"
BACK_TO_EXIT = 2  # seconds to press back again to leave the app
# In the browser (Pyodide): no threads, no camera reader, and a database that starts empty on
# every visit, so the sign-in is kept in the browser's storage and sync brings the cards back
WEB = sys.platform == "emscripten"
ACCOUNT_KEYS = ("account_token", "account_email")
# Below this width, the first-visit question suggests the phone layout
WIDE = 900
LAYOUT_KEY = "layout"  # the browser's answer: "desktop" or "mobile"
TOAST_WIDTH = 380  # a message's width in the desktop layout
GITHUB_URL = "https://github.com/LightInUmbra/multiversal-manager"

def _money(value):
    # Scryfall has no price for some printings; a dash, like the desktop, rather than $0.00
    return f"${value:,.2f}" if value else "—"


def _options(mapping):
    return [ft.DropdownOption(key=code, text=name) for code, name in mapping.items()]


def main(page: ft.Page):
    page.title = APP_NAME
    theme.apply(page)
    if page.web:  # right-click opens the app's own menus (the deck builder's), not the browser's
        page.run_task(ft.BrowserContextMenu().disable)
    db.create_table()

    # The sign-in lives in the phone's own database, next to the sync cursors
    # (and in the browser's storage too on the web, since the database doesn't last there)
    prefs = ft.SharedPreferences()

    def setting(key, value=...):
        with db._connect() as conn:
            if value is ...:
                return sync._get(conn, key)
            sync._set(conn, key, value)
        if WEB and key in ACCOUNT_KEYS:
            page.run_task(prefs.remove, key) if value is None else page.run_task(prefs.set, key, value)

    # Feedback

    progress = ft.ProgressBar(visible=False)

    def toast(message):
        # On a wide screen, a compact card at the bottom; on a phone, the width of the screen
        page.show_dialog(ft.SnackBar(ft.Text(message), width=TOAST_WIDTH if desktop_layout() else None))

    def busy(label, fn):
        # Runs fn with the progress bar showing; a failure becomes a message instead of a crash.
        # Event handlers already run on worker threads, so waiting on the network here is fine.
        progress.visible = True
        page.update()
        try:
            return fn()
        except Exception as error:
            toast(f"{label} failed: {error}")
        finally:
            progress.visible = False
            page.update()

    # Collection

    search = ft.TextField(hint_text="Filter by name, set or artist", prefix_icon=ft.Icons.SEARCH,
                          dense=True, on_change=lambda e: show_cards())
    summary = ft.Text(weight=ft.FontWeight.BOLD)
    card_list = ft.ListView(expand=True)

    def details(row):
        printing = row["set_name"] + (f" #{row['collector_number']}" if row["collector_number"] else "")
        parts = (printing, scryfall.finish_label(row["foil"]),
                 row["condition"] if row["condition"] != copy_details.DEFAULT_CONDITION else "",
                 copy_details.language_label(row["language"]) if row["language"] != copy_details.DEFAULT_LANGUAGE else "")
        return " · ".join(p for p in parts if p)

    # The website asks each browser once whether to look like the desktop app or the phone app
    # (see choose_layout); the phone app is always the phone layout
    layout = {"desktop": False}

    def desktop_layout():
        return layout["desktop"]

    def resized(e):
        # The desktop layout's table widths follow the window
        if desktop_layout() and tab_index() == 0:
            cards_page.refresh()
        elif desktop_layout() and tab_index() == 3:
            finance_page.fill()

    page.on_resize = resized

    def show_cards():
        if desktop_layout():
            cards_page.refresh()
            return
        if collection_mode["sealed"]:
            phone_sealed_view.refresh()
            return
        text = (search.value or "").lower()
        rows = [r for r in db.get_all_cards()
                if text in f"{r['name']} {r['set_name']} {r['artist'] or ''}".lower()]
        card_list.controls = [
            ft.ListTile(title=ft.Text(f"{r['quantity']}× {r['name']}"), subtitle=ft.Text(details(r)),
                        trailing=ft.Text(_money(r["price"])), on_click=lambda e, r=r: edit_card(r))
            for r in rows]
        _, cards, value = db.get_summary()
        summary.value = f"{cards} cards · ${value:,.2f}"
        page.update()

    def edit_card(row):
        quantity = ft.TextField(label="Quantity", value=str(row["quantity"]), keyboard_type=ft.KeyboardType.NUMBER)
        condition = ft.Dropdown(label="Condition", value=row["condition"], options=_options(copy_details.CONDITIONS))
        language = ft.Dropdown(label="Language", value=row["language"], options=_options(copy_details.LANGUAGES))
        notes = ft.TextField(label="Notes", value=row["notes"], multiline=True)
        remove = ft.TextButton("Remove")

        def save(e):
            try:
                count = int(quantity.value)
            except ValueError:
                quantity.error_text = "Enter a number"
                page.update()
                return
            page.pop_dialog()
            if count < 1:
                db.remove_card(row["id"])
            else:
                fields = {k: row[k] for k in ("scryfall_id", "set_code", "collector_number", "foil", "rarity",
                                              "artist", "image_url")}
                db.update_card(row["id"], row["name"], row["set_name"], row["price"], count, **fields,
                               condition=condition.value, language=language.value, notes=notes.value)
            show_cards()

        def remove_clicked(e):
            # A second tap confirms, so a stray one can't lose a card
            if remove.data:
                page.pop_dialog()
                db.remove_card(row["id"])
                show_cards()
                toast(f"Removed {row['name']}.")
            else:
                remove.data = True
                remove.content = "Tap again to remove"
                page.update()

        remove.on_click = remove_clicked
        image = [ft.Image(src=row["image_url"], height=280)] if row["image_url"] else []
        page.show_dialog(ft.AlertDialog(
            title=ft.Text(row["name"]), scrollable=True,
            content=ft.Column([*image, ft.Text(details(row)), ft.Text(f"{_money(row['price'])} each"),
                               quantity, condition, language, notes], tight=True),
            actions=[remove, ft.TextButton("Cancel", on_click=lambda e: page.pop_dialog()),
                     ft.TextButton("Save", on_click=save)]))

    def card_dialog(title, extras, on_done):
        # Finds a card and printing on Scryfall, then calls on_done(card, finish code, quantity).
        # extras are more fields shown under the quantity (condition, deck section…).
        name = ft.TextField(label="Card name", autofocus=True)
        suggestions = ft.Column(tight=True)
        printing = ft.Dropdown(label="Printing", visible=False, expand=True)
        finish = ft.Dropdown(label="Finish", visible=False)
        quantity = ft.TextField(label="Quantity", value="1", keyboard_type=ft.KeyboardType.NUMBER)
        printings = []

        def typed(e):
            typed_name = name.value.strip()
            if len(typed_name) < 2:
                suggestions.controls = []
                page.update()
                return
            try:
                names = scryfall.autocomplete(typed_name)
            except Exception:
                return  # the next keystroke tries again
            if name.value.strip() != typed_name:
                return  # typing moved on while this was loading
            suggestions.controls = [ft.ListTile(title=ft.Text(n), dense=True, on_click=lambda e, n=n: pick(n))
                                    for n in names[:8]]
            page.update()

        def pick(card_name):
            name.value = card_name
            suggestions.controls = []
            found = busy("Looking up printings", lambda: scryfall.get_printings(card_name))
            if not found:
                toast(f"No printings found for {card_name}.")
                return
            printings[:] = found
            printing.options = [ft.DropdownOption(key=str(i), text=scryfall.printing_label(c))
                                for i, c in enumerate(found)]
            printing.value = "0"
            printing.visible = True
            printing_picked(None)

        def printing_picked(e):
            card = printings[int(printing.value)]
            codes = scryfall.finish_codes(card) or [0]
            finish.options = [ft.DropdownOption(key=str(c), text=scryfall.FINISHES[c][1]) for c in codes]
            finish.value = str(codes[0])
            finish.visible = True
            page.update()

        def add(e):
            if not printings:
                if name.value.strip():
                    pick(name.value.strip())
                return
            try:
                count = int(quantity.value)
            except ValueError:
                count = 0
            if count < 1:
                quantity.error_text = "Enter a number"
                page.update()
                return
            page.pop_dialog()
            on_done(printings[int(printing.value)], int(finish.value), count)

        name.on_change = typed
        name.on_submit = lambda e: pick(name.value.strip()) if name.value.strip() else None
        printing.on_select = printing_picked
        page.show_dialog(ft.AlertDialog(
            title=ft.Text(title), scrollable=True,
            content=ft.Column([name, suggestions, printing, finish, quantity, *extras], tight=True),
            actions=[ft.TextButton("Cancel", on_click=lambda e: page.pop_dialog()),
                     ft.TextButton("Add", on_click=add)]))

    def add_card():
        condition = ft.Dropdown(label="Condition", value=copy_details.DEFAULT_CONDITION,
                                options=_options(copy_details.CONDITIONS))
        language = ft.Dropdown(label="Language", value=copy_details.DEFAULT_LANGUAGE,
                               options=_options(copy_details.LANGUAGES))

        def added(card, finish, count):
            db.add_card(**scryfall.card_record(card, finish, count), condition=condition.value, language=language.value)
            search.value = ""
            show_cards()
            toast(f"Added {count}× {card.name}.")

        card_dialog("Add Card", [condition, language], added)

    def refresh_prices(e):
        rows = [(r["id"], r["scryfall_id"], r["foil"]) for r in db.get_all_cards() if r["scryfall_id"]]
        if not rows:
            toast("No cards to refresh.")
            return
        result = busy("Refreshing prices", lambda: scryfall.fetch_prices(rows))
        if result:
            updates, missing = result
            db.update_prices(updates)
            show_cards()
            toast(f"Updated {len(updates)} prices." + (f" {missing} weren't found." if missing else ""))

    # Sync

    remote = {}  # the signed-in session and the token it's for
    sync_lock = threading.Lock()  # one sync at a time: the button's and the automatic one
    last_sync = {"at": float("-inf"), "failed": False}  # time.monotonic() of the last one started

    def sync_now(e=None, quiet=False):
        # quiet: a sync the app starts itself, with no progress bar and no message unless cards arrived
        token = setting("account_token")
        if not token:
            if not quiet:
                account(None)
            return
        if not sync_lock.acquire(blocking=False):
            return

        def run():
            # One session kept between syncs, so syncing every few seconds doesn't sign in every time
            if remote.get("token") != token:
                remote.update(token=token, session=sync.SupabaseRemote(token))
            try:
                return sync.sync(remote["session"])
            finally:
                # Signing in uses up the saved token, so its replacement is saved even on failure
                remote["token"] = remote["session"].refresh_token
                setting("account_token", remote["token"])

        try:
            last_sync["at"] = time.monotonic()
            if quiet:
                try:
                    result = run()
                except Exception:
                    result = None
            else:
                result = busy("Sync", run)
            last_sync["failed"] = result is None
        finally:
            sync_lock.release()
        if result:
            pushed, applied = result
            if applied:
                show_cards()
                (decks_page if desktop_layout() else deck_builder).refresh()
            if not quiet or applied:
                toast(f"Synced: sent {pushed}, received {applied}.")

    def auto_sync_check():
        # While signed in: shortly after an edit, and every couple of minutes for other devices' changes
        try:
            waited = time.monotonic() - last_sync["at"]
            if setting("account_token") and not (last_sync["failed"] and waited < sync.RETRY_AFTER):
                with db._connect() as conn:
                    changed = sync.has_local_changes(conn)
                if changed or waited >= sync.PULL_EVERY:
                    sync_now(quiet=True)
        except Exception:
            pass  # e.g. the database busy for a moment; the next round tries again

    async def auto_sync():
        if WEB:
            for key in ACCOUNT_KEYS:
                value = await prefs.get(key)
                if value:
                    setting(key, value)
        while True:
            # The browser has no threads, so there the check (and any sync) runs in place
            auto_sync_check() if WEB else await asyncio.to_thread(auto_sync_check)
            await asyncio.sleep(sync.EDIT_DELAY)

    def account(e):
        if setting("account_token"):
            def sign_out(e):
                setting("account_token", None)
                page.pop_dialog()
                toast("Signed out. Your cards stay on this phone.")

            page.show_dialog(ft.AlertDialog(
                title=ft.Text("Sync Account"),
                content=ft.Text(f"Signed in as {setting('account_email')}."),
                actions=[ft.TextButton("Sign Out", on_click=sign_out),
                         ft.TextButton("Close", on_click=lambda e: page.pop_dialog())]))
            return

        email = ft.TextField(label="Email", value=setting("account_email") or "",
                             keyboard_type=ft.KeyboardType.EMAIL)
        password = ft.TextField(label="Password", password=True, can_reveal_password=True)

        def go(action):
            if not (email.value.strip() and password.value):
                return
            # Wrapped, since busy() gives None on failure and sign_up gives None when the email needs confirming
            result = busy("Signing in", lambda: [action(email.value.strip(), password.value)])
            if not result:
                return
            (token,) = result
            if token is None:
                toast("Account created. Open the link in the email from Supabase, then sign in.")
                return
            setting("account_token", token)
            setting("account_email", email.value.strip())
            page.pop_dialog()
            sync_now()

        page.show_dialog(ft.AlertDialog(
            title=ft.Text("Sync Account"), scrollable=True,
            content=ft.Column([ft.Text("Sign in with the same account as your other devices to keep your "
                                       "cards, decks and sealed product the same everywhere."),
                               email, password], tight=True),
            actions=[ft.TextButton("Create Account", on_click=lambda e: go(sync.sign_up)),
                     ft.TextButton("Sign In", on_click=lambda e: go(sync.sign_in))]))

    # Layout

    page.appbar = ft.AppBar(title=ft.Text(APP_NAME), actions=[
        ft.IconButton(ft.Icons.DOCUMENT_SCANNER_OUTLINED, tooltip="Scan cards", visible=not WEB,
                      on_click=lambda e: page.run_task(open_scanner)),
        ft.IconButton(ft.Icons.SYNC, tooltip="Sync now", on_click=sync_now),
        # The occasional ones, like the desktop's menus
        ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, tooltip="More", items=[
            ft.PopupMenuItem(content="Sync account…", on_click=account),
            ft.PopupMenuItem(content="Import cards…", on_click=lambda e: phone_import()),
            ft.PopupMenuItem(content="Refresh prices", on_click=refresh_prices),
            *([ft.PopupMenuItem(content="Desktop layout", on_click=lambda e: set_layout(True))] if page.web else []),
        ]),
    ])
    deck_builder = decks.Decks(page, toast, busy, card_dialog)
    body = ft.Container(expand=True)

    # The phone's Collection switches between cards and sealed product, like the desktop's two tabs
    collection_mode = {"sealed": False}

    def show_sealed(on):
        collection_mode["sealed"] = on
        body.content = collection_view()
        show_cards()

    def collection_switch():
        def side(label, on):
            chosen = on == collection_mode["sealed"]
            return ft.Container(ft.Text(label, size=13, color=None if chosen else theme.MUTED), expand=True,
                                alignment=ft.Alignment.CENTER, padding=ft.Padding.symmetric(vertical=7),
                                bgcolor=theme.COLORS["primary_container"] if chosen else None,
                                border=ft.Border.all(1, theme.COLORS["outline"]), on_click=lambda e: show_sealed(on))
        return ft.Row([side("Cards", False), side("Sealed", True)], spacing=0)

    def collection_view():
        if desktop_layout():
            return cards_page.view
        shown = phone_sealed_view.view if collection_mode["sealed"] else ft.Column([search, summary, card_list],
                                                                                    expand=True)
        return ft.Column([collection_switch(), shown], expand=True, spacing=8)

    # The desktop layout's header, in place of the phone's app bar and bottom bar
    def open_url(url):
        page.run_task(ft.UrlLauncher().launch_url, url)

    # The desktop layout's header has more tabs than the phone's bottom bar (Finance), so it
    # keeps its own place; the two agree on the tabs they share
    desktop_tab = {"index": 0}

    def tab_index():
        return desktop_tab["index"] if desktop_layout() else page.navigation_bar.selected_index

    def go_to(index):
        desktop_tab["index"] = index
        if index < len(page.navigation_bar.destinations):
            page.navigation_bar.selected_index = index
        switch(None)

    desktop_top = ft.Column(spacing=0, visible=False)

    def show_header():
        desktop_top.controls = [web_desktop.header(
            tab_index(), go_to, sync_now, setting("account_email"),
            [("Sync account…", account), ("Refresh prices", refresh_prices),
             ("Mobile layout", lambda e: set_layout(False)),
             ("Multiversal Manager on GitHub", lambda e: open_url(GITHUB_URL)),
             ("Scryfall", lambda e: open_url("https://scryfall.com"))])]

    def relayout():
        # Swaps between the phone's layout and the desktop's
        is_desktop = desktop_layout()
        page.appbar.visible = not is_desktop
        page.navigation_bar.visible = not is_desktop
        desktop_top.visible = is_desktop
        page.padding = 0 if is_desktop else 10  # the website's header runs edge to edge
        switch(None)

    def set_layout(desktop, remember=True):
        layout["desktop"] = desktop
        if remember:
            page.run_task(prefs.set, LAYOUT_KEY, "desktop" if desktop else "mobile")
        relayout()

    def choose_layout():
        # Asked on a browser's first visit; either layout can switch to the other later
        suggested = (page.width or 0) >= WIDE

        def option(desktop, icon, title, text):
            return ft.Card(ft.Container(ft.ListTile(
                leading=ft.Icon(icon, size=36), title=ft.Text(title, weight=ft.FontWeight.BOLD),
                subtitle=ft.Text(text + ("\nSuggested for this screen." if desktop == suggested else "")),
                on_click=lambda e: (page.pop_dialog(), set_layout(desktop))), padding=6), margin=0)

        page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text(f"Welcome to {APP_NAME}", text_align=ft.TextAlign.CENTER),
            # The options fill the box's width, so they sit centered under the title
            content=ft.Column(width=min(460, (page.width or 460) - 96), horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=[
                ft.Text("Are you on a computer or a phone?"),
                option(True, ft.Icons.DESKTOP_WINDOWS_OUTLINED, "Desktop",
                       "The full desktop app: menus, tables and side panels. Best with a mouse and a big screen."),
                option(False, ft.Icons.PHONE_ANDROID_OUTLINED, "Mobile",
                       "The phone app: big buttons and one thing at a time, made for touch."),
                ft.Text("You can switch later: View → Mobile Layout, or the desktop button at the top of the phone layout.",
                        size=12, color=ft.Colors.ON_SURFACE_VARIANT)], tight=True)))

    async def start():
        # The phone app is always the phone layout; the website asks once, then remembers
        saved = await prefs.get(LAYOUT_KEY) if page.web else "mobile"
        if saved:
            set_layout(saved == "desktop", remember=False)
        else:
            relayout()
            choose_layout()

    def desktop_add():
        def saved(data):
            card_id = db.add_card(**data)
            cards_page.search.value = ""
            cards_page.refresh(select_id=card_id)  # shown in the detail panel, like the desktop
            toast(f"Added {data['quantity']}× {data['name']}.")

        card_form.open_card_form(page, saved)

    def desktop_edit(row):
        def saved(data):
            surviving_id = db.update_card(row["id"], **data)
            cards_page.refresh(select_id=surviving_id)
            if surviving_id != row["id"]:
                toast("You already had that printing, so the two entries were combined.")

        if row:
            card_form.open_card_form(page, saved, existing=row)

    file_picker = ft.FilePicker()

    def desktop_import():
        page.run_task(web_import.start_import, page, file_picker, "your collection", imported, busy)

    def imported(records):
        # The desktop's _on_import_reviewed: save, show the new cards, say how many
        if records is None:
            toast("Import cancelled, nothing was added.")
            return
        card_ids = db.add_cards(records)
        if desktop_layout():
            cards_page.search.value = ""
            cards_page.refresh(select_id=card_ids[0] if card_ids else None)
        else:
            search.value = ""
            show_cards()
        cards = sum(record["quantity"] for record in records)
        toast(f"Imported {importer.count(cards, 'card')} ({importer.count(len(records), 'entry')}).")

    cards_page = web_desktop.CardsPage(page, toast, desktop_add, desktop_edit, refresh_prices, desktop_import)
    cards_page.sealed = web_sealed.SealedPanel(page, toast, busy, on_change=cards_page.update_total)
    decks_page = web_decks.DecksPage(page, toast, busy)

    rules_view = rules_tab.Rules(page, toast, busy)
    rules_page = web_rules.RulesPage(page, toast, busy)  # the desktop layout's
    finance_page = web_finance.FinancePage(page, busy)  # the desktop layout's
    # The phone app keeps the day's market file; the website downloads it per visit
    finance_view = phone_finance.PhoneFinance(page, toast, busy,
                                              cache=None if WEB else Path(db.DB_NAME).with_name("market.json.gz"))
    # The tabs after Collection, in the bar's order; each has view, refresh() and back()
    tabs = [deck_builder, rules_view, finance_view]

    # The phone layout's import: its review takes the Collection's place, like the scanner
    reviewing = {"review": None}

    def open_review(review):
        reviewing["review"] = review
        page.navigation_bar.selected_index = 0
        page.navigation_bar.visible = page.floating_action_button.visible = False
        body.content = review.view
        page.update()

    def close_review():
        reviewing["review"] = None
        page.navigation_bar.visible = page.floating_action_button.visible = True
        body.content = collection_view()
        page.update()

    # The Sealed side of the phone's Collection; its Add Sealed Product screen opens like the review
    phone_sealed_view = phone_sealed.PhoneSealed(page, toast, busy, (open_review, close_review))

    def phone_import():
        page.run_task(web_import.start_import, page, file_picker, "your collection", imported, busy,
                      lambda page, result, on_done: phone_import_review.PhoneReview(
                          page, result, on_done, (open_review, close_review)))

    scanner = scan.Scanner(page, toast, on_added=show_cards)

    async def open_scanner():
        # The scanner takes the Collection tab's place until back (or another tab) closes it
        page.navigation_bar.selected_index = 0
        body.content = scanner.view
        page.floating_action_button.visible = False
        await scanner.open()

    def close_scanner():
        scanner.close()
        body.content = collection_view()
        page.floating_action_button.visible = True
        show_cards()

    def switch(e):
        if scanner.active:
            scanner.close()
        if not desktop_layout():
            desktop_tab["index"] = page.navigation_bar.selected_index
        index = tab_index()
        # The desktop layout has its own pages where they're built (Cards, Decks), else the phone's
        pages = [collection_view()] + ([decks_page, rules_page, finance_page] if desktop_layout()
                                       else [deck_builder, rules_view, finance_view])
        current = pages[index]
        body.content = current if index == 0 else current.view
        # The phone's + button, on Collection and Decks; the desktop layout has buttons instead
        page.floating_action_button.visible = not desktop_layout() and index in (0, 1)
        show_header()
        current.refresh() if index else show_cards()

    page.navigation_bar = ft.NavigationBar(on_change=switch, destinations=[
        ft.NavigationBarDestination(icon=ft.Icons.STYLE_OUTLINED, label="Collection"),
        ft.NavigationBarDestination(icon=ft.Icons.MENU_BOOK_OUTLINED, label="Decks"),
        ft.NavigationBarDestination(icon=ft.Icons.GAVEL_OUTLINED, label="Rules"),
        ft.NavigationBarDestination(icon=ft.Icons.TRENDING_UP, label="Finance")])
    # Android's back button steps back through the app instead of closing it: back through a
    # tab's pages, then to Collection, and on Collection it takes a second press to exit.
    # (An open dialog closes first on its own.)
    last_back = [float("-inf")]

    async def on_back(e):
        index = page.navigation_bar.selected_index
        if reviewing["review"] is not None:
            reviewing["review"].back()  # cancels the import
            await e.control.confirm_pop(False)
        elif scanner.active:
            close_scanner()
            await e.control.confirm_pop(False)
        elif index:
            if not tabs[index - 1].back():
                page.navigation_bar.selected_index = 0
                switch(None)
            await e.control.confirm_pop(False)
        elif time.monotonic() - last_back[0] < BACK_TO_EXIT:
            await e.control.confirm_pop(True)
        else:
            last_back[0] = time.monotonic()
            page.show_dialog(ft.SnackBar(ft.Text("Tap back again to exit"), duration=int(BACK_TO_EXIT * 1000)))
            await e.control.confirm_pop(False)

    page.views[0].can_pop = False
    page.views[0].on_confirm_pop = on_back
    page.floating_action_button = ft.FloatingActionButton(
        icon=ft.Icons.ADD, tooltip="Add",
        on_click=lambda e: deck_builder.fab() if page.navigation_bar.selected_index == 1
        else phone_sealed_view.add() if collection_mode["sealed"] else add_card())
    page.add(ft.SafeArea(ft.Column([desktop_top, progress, body], expand=True, spacing=4), expand=True))
    page.run_task(start)
    page.run_task(auto_sync)


if __name__ == "__main__":
    ft.run(main)
