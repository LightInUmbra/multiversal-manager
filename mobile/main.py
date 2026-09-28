# Multiversal Manager for phones, in Flet. The collection, prices and sync are the desktop
# app's own modules (database, scryfall, sync, copy_details); build_apk.py copies them in
# next to this file. The phone keeps its own collection.db and syncs it like the desktop.
import sys
import threading
import time
from pathlib import Path

# Run from the repo (flet run mobile/main.py), the shared modules are one folder up
_REPO = Path(__file__).resolve().parent.parent
if (_REPO / "database.py").exists():
    sys.path.insert(0, str(_REPO))

import flet as ft  # noqa: E402

import copy_details  # noqa: E402
import database as db  # noqa: E402
import decks  # noqa: E402
import scryfall  # noqa: E402
import sync  # noqa: E402

APP_NAME = "Multiversal Manager"
BACK_TO_EXIT = 2  # seconds to press back again to leave the app


def _money(value):
    return f"${value:,.2f}" if value is not None else "—"


def _options(mapping):
    return [ft.DropdownOption(key=code, text=name) for code, name in mapping.items()]


def main(page: ft.Page):
    page.title = APP_NAME
    db.create_table()

    # The sign-in lives in the phone's own database, next to the sync cursors
    def setting(key, value=...):
        with db._connect() as conn:
            if value is ...:
                return sync._get(conn, key)
            sync._set(conn, key, value)

    # Feedback

    progress = ft.ProgressBar(visible=False)

    def toast(message):
        page.show_dialog(ft.SnackBar(ft.Text(message)))

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

    def show_cards():
        text = (search.value or "").lower()
        rows = [r for r in db.get_all_cards()
                if text in f"{r['name']} {r['set_name']} {r['artist'] or ''}".lower()]
        card_list.controls = [
            ft.ListTile(title=ft.Text(f"{r['quantity']}× {r['name']}"), subtitle=ft.Text(details(r)),
                        trailing=ft.Text(_money(r["price"])), on_click=lambda e, r=r: edit_card(r))
            for r in rows]
        _, cards, value = db.get_summary()
        summary.value = f"{cards} cards · {_money(value)}"
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
                deck_builder.refresh()
            if not quiet or applied:
                toast(f"Synced: sent {pushed}, received {applied}.")

    def auto_sync():
        # While signed in: shortly after an edit, and every couple of minutes for other devices' changes
        while True:
            try:
                waited = time.monotonic() - last_sync["at"]
                if setting("account_token") and not (last_sync["failed"] and waited < sync.RETRY_AFTER):
                    with db._connect() as conn:
                        changed = sync.has_local_changes(conn)
                    if changed or waited >= sync.PULL_EVERY:
                        sync_now(quiet=True)
            except Exception:
                pass  # e.g. the database busy for a moment; the next round tries again
            time.sleep(sync.EDIT_DELAY)

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
        ft.IconButton(ft.Icons.PRICE_CHANGE_OUTLINED, tooltip="Refresh prices", on_click=refresh_prices),
        ft.IconButton(ft.Icons.SYNC, tooltip="Sync now", on_click=sync_now),
        ft.IconButton(ft.Icons.ACCOUNT_CIRCLE_OUTLINED, tooltip="Sync account", on_click=account),
    ])
    deck_builder = decks.Decks(page, toast, busy, card_dialog)
    collection = ft.Column([search, summary, card_list], expand=True)
    body = ft.Container(collection, expand=True)

    def switch(e):
        on_decks = page.navigation_bar.selected_index == 1
        body.content = deck_builder.view if on_decks else collection
        deck_builder.refresh() if on_decks else show_cards()

    page.navigation_bar = ft.NavigationBar(on_change=switch, destinations=[
        ft.NavigationBarDestination(icon=ft.Icons.STYLE_OUTLINED, label="Collection"),
        ft.NavigationBarDestination(icon=ft.Icons.MENU_BOOK_OUTLINED, label="Decks")])
    # Android's back button steps back through the app instead of closing it: out of a list,
    # then from Decks to Collection, and on Collection it takes a second press to exit.
    # (An open dialog closes first on its own.)
    last_back = [float("-inf")]

    async def on_back(e):
        if page.navigation_bar.selected_index == 1:
            if not deck_builder.back():
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
        on_click=lambda e: deck_builder.fab() if page.navigation_bar.selected_index == 1 else add_card())
    page.add(ft.SafeArea(ft.Column([progress, body], expand=True), expand=True))
    show_cards()
    page.run_thread(auto_sync)


if __name__ == "__main__":
    ft.run(main)
