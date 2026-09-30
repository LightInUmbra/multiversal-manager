"""
The deck builder: decks, binders and wishlists in three panels.

- Left: the selected card -- image, rules text, legality, how many you own, -1 / +1.
- Middle: the selected list, grouped by section. Decks have a format, and every card
  and the deck as a whole are checked against it (see formats.py). Commander decks
  also get their Commander bracket, and can aim for one (see brackets.py).
- Right: cards to add -- My Cards (your collection) or Explore (every card, from the
  card database), with search and filters, or Recommended: a page of cards for a
  Commander deck's commander, worked out from the cards themselves (see recommendations.py),
  or Stats: the mana curve, colors, card types and most valuable cards (deck_stats.stats).

Any printing you own counts toward a list's cards.
"""

# Imports
import html
from datetime import date, datetime, timedelta, timezone

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit, QComboBox, QTreeWidget,
    QTreeWidgetItem, QHeaderView, QAbstractItemView, QPushButton, QSplitter, QMessageBox, QDialog,
    QDialogButtonBox, QInputDialog, QMenu, QFileDialog, QTabBar, QCheckBox, QTextBrowser, QProgressBar,
    QToolButton, QMenuBar,
)

import background
import brackets
import card_sorting
import database as db
import deck_stats
import finance
import formats
import interactions
import scryfall
from card_browser import CardBrowser, PrintingDialog
from card_image import CardImage
from import_review_dialog import count, start_import
from deck_stats import completion, deck_text, summary  # noqa: F401
from importer import SECTIONS
from recommendations import RecommendationsPanel
from sort_bar import SortBar

KINDS = {"deck": "Deck", "binder": "Binder", "wishlist": "Wishlist"}
SECTION_TITLES = {"Commander": "Commander", "Companion": "Companion", "Main": "Main Deck",
                  "Sideboard": "Sideboard", "Maybeboard": "Maybeboard", "": "Cards"}

DECK_COLUMNS = ["Qty", "Card", "Type", "Mana", "Price", "Owned", "Legal"]
QTY_COL, NAME_COL, TYPE_COL, MANA_COL, PRICE_COL, OWNED_COL, LEGAL_COL = range(len(DECK_COLUMNS))

ID_ROLE = Qt.ItemDataRole.UserRole
GOOD = QColor("#1a8f3c")
BAD = QColor("#c62828")
MUTED = QColor("gray")
PRICE_MAX_AGE = timedelta(hours=24)
CARD_DB_MAX_AGE = timedelta(days=7)  # the deck builder re-checks Scryfall's bulk data weekly
RESULTS_SHOWN = 600
WORKS_SHOWN = 6  # lines of a card's "Works well with" (interactions.py) in its details


def _plural(card_type, n):
    return card_type if n == 1 or card_type == "Other" else (
        "Sorceries" if card_type == "Sorcery" else card_type + "s")


def _stale(entry):
    if not entry["scryfall_id"]:
        return False
    if not entry["price_updated"]:
        return True
    return datetime.now(timezone.utc) - datetime.fromisoformat(entry["price_updated"]) > PRICE_MAX_AGE


def _money(value):
    return f"${value:,.2f}" if value else "—"


# The Stats tab's colors: the five mana colors, and colorless
STAT_COLORS = {"W": ("White", "#c9b458"), "U": ("Blue", "#1f7bc8"), "B": ("Black", "#5e4b6b"),
               "R": ("Red", "#d9453b"), "G": ("Green", "#2e9e5b"), "C": ("Colorless", "#8c8c8c")}
STAT_BAR = "#4a78c2"


def stats_html(st):
    """The Stats tab (deck_stats.stats()) as plain HTML tables for a QTextBrowser: a row per
    mana value, color and card type, each with a bar that's a shaded cell."""
    def bar(fraction, color=STAT_BAR):
        filled = max(1, round(100 * fraction)) if fraction else 0
        return (f"<table width='100%' cellspacing='0' cellpadding='0'><tr>"
                f"<td width='{filled}%' bgcolor='{color}'>&nbsp;</td><td width='{100 - filled}%'></td></tr></table>")

    def rows(items):
        # items: (label, bar html, number text)
        return ("<table width='100%' cellspacing='2' cellpadding='1'>"
                + "".join(f"<tr><td width='90'>{label}</td><td>{graph}</td><td width='70' align='right'>{number}</td></tr>"
                          for label, graph, number in items) + "</table>")

    curve, peak = st["curve"], max(st["curve"].values()) or 1
    top = deck_stats.CURVE_TOP
    parts = ["<h3>Mana curve</h3>",
             rows([(f"{mv}+" if mv == top else str(mv), bar(n / peak), n) for mv, n in curve.items()]),
             f"<p>Average mana value {st['average']:.2f}, lands left out.</p>" if st["average"] is not None
             else "<p>No spells with a mana value yet.</p>"]
    total = sum(st["colors"].values()) or 1
    parts += ["<h3>Colors</h3>",
              rows([(STAT_COLORS[c][0], bar(n / total, STAT_COLORS[c][1]), f"{n} · {round(100 * n / total)}%")
                    for c, n in st["colors"].items()]) if st["colors"] else "<p>No colored mana symbols.</p>"]
    most = max(st["types"].values(), default=1)
    parts += ["<h3>Types</h3>", rows([(_plural(t, 2), bar(n / most), n) for t, n in st["types"].items()]),
              f"<p>{st['lands']} lands of {st['size']} cards ({round(100 * st['lands'] / st['size'])}%).</p>",
              "<h3>Most valuable</h3>",
              "<table width='100%'>" + "".join(f"<tr><td>{html.escape(e['name'])}</td><td align='right'>{_money(e['price'])}</td></tr>"
                                               for e in st["priciest"]) + "</table>"]
    return "".join(parts)


def _format_combo(current="casual"):
    combo = QComboBox()
    for key, fmt in formats.FORMATS.items():
        combo.addItem(fmt.label + (" (Arena)" if fmt.arena else ""), key)
    combo.setCurrentIndex(max(0, combo.findData(current)))
    return combo


def ask_new_list(parent, kind="deck"):
    # Asks for a list's name, kind and (for decks) format. Returns the new list's id, or None.
    dialog = QDialog(parent)
    dialog.setWindowTitle("New List")
    name_input = QLineEdit()
    name_input.setPlaceholderText("e.g. Mono-Red Aggro, Trade Binder, Birthday Wishlist")
    kind_combo = QComboBox()
    for key, text in KINDS.items():
        kind_combo.addItem(text, key)
    kind_combo.setCurrentIndex(kind_combo.findData(kind))
    format_combo = _format_combo("standard")
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
    ok.setEnabled(False)
    name_input.textChanged.connect(lambda text: ok.setEnabled(bool(text.strip())))
    form = QFormLayout(dialog)
    form.addRow("Name:", name_input)
    form.addRow("Type:", kind_combo)
    form.addRow("Format:", format_combo)
    kind_combo.currentIndexChanged.connect(
        lambda: form.setRowVisible(format_combo, kind_combo.currentData() == "deck"))
    form.addRow(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    kind = kind_combo.currentData()
    return db.create_list(name_input.text().strip(), kind, format_combo.currentData() if kind == "deck" else "casual")


# Background work

def _update_card_database(last_bulk, track_new, progress=None):
    return finance.update_market(last_bulk, None, track_new, history=False, progress=progress)


def _check_combos(key):
    # (key, Commander Spellbook's reading) for a deck's (commanders, main deck) names
    return key, brackets.fetch_spellbook(list(key[0]), list(key[1]))


class ListsWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Deck Builder")
        self.resize(1500, 860)
        self.settings = finance._settings()
        self._list = None             # the selected list's row
        self._entries = []            # its entries
        self._card = None             # the card shown on the left: (row, entry id or None)
        self._refreshing = False
        self._updating_cards = False
        self._price_checked = set()   # entries refreshed this session, so a card Scryfall
                                      # can't find isn't retried on every reload
        self._spellbook = {}          # deck cards -> Commander Spellbook's reading (None while
                                      # asking, False if it couldn't be reached)

        splitter = QSplitter()
        splitter.addWidget(self._build_detail_panel())
        splitter.addWidget(self._build_deck_panel())
        splitter.addWidget(self._build_card_panel())
        # The deck and the cards share extra width in proportion to these sizes (a splitter
        # grows every stretching panel by its share of their total), so the card panel gets
        # the larger part: card names rarely need a wide column
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([300, 560, 640])
        layout = QVBoxLayout(self)
        layout.setMenuBar(self._build_menu())
        layout.addWidget(splitter)
        self.set_lightweight(self.settings.value("deckbuilder_lightweight", False, type=bool))

        self.reload()
        self.search_cards()
        # Without a card database, the card panel offers the download instead
        if db.has_card_database() and (self._card_db_stale() or db.card_database_outdated()):
            self.update_card_database(quiet=True)

    # Layout

    def _build_menu(self):
        menu_bar = QMenuBar()
        view = menu_bar.addMenu("&View")
        modes = QActionGroup(self)
        self.standard_action = QAction("&Standard (card images)", self, checkable=True)
        self.lightweight_action = QAction("&Lightweight (text only)", self, checkable=True)
        self.lightweight_action.setStatusTip("The card list is a plain table and downloads no images")
        for action, on in ((self.standard_action, False), (self.lightweight_action, True)):
            modes.addAction(action)
            view.addAction(action)
            action.triggered.connect(lambda _, on=on: self.set_lightweight(on))
        return menu_bar

    def set_lightweight(self, on):
        # Lightweight mode shows the card list (and printing picker) as plain tables,
        # which download no card images: easier on slower computers and connections
        self.settings.setValue("deckbuilder_lightweight", on)
        (self.lightweight_action if on else self.standard_action).setChecked(True)
        self.card_browser.set_lightweight(on)
        self.recommend_panel.set_lightweight(on)

    def _build_detail_panel(self):
        self.card_image = CardImage(width=240)
        self.detail_name = QLabel()
        self.detail_name.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.detail_name.setWordWrap(True)
        self.detail_type = QLabel()
        self.detail_type.setWordWrap(True)
        self.detail_text = QTextBrowser()
        self.detail_text.setMaximumHeight(170)
        self.detail_info = QLabel()
        self.detail_info.setWordWrap(True)
        self.detail_works = QLabel()  # "Works well with" (interactions.py)
        self.detail_works.setWordWrap(True)
        self.detail_works.setStyleSheet("color: palette(placeholder-text);")
        self.minus_button = QPushButton("−1")
        self.minus_button.setToolTip("Take one copy out of this list")
        self.minus_button.clicked.connect(lambda: self.change_selected(-1))
        self.plus_button = QPushButton("+1")
        self.plus_button.setToolTip("Put one more copy in this list")
        self.plus_button.clicked.connect(lambda: self.change_selected(1))
        buttons = QHBoxLayout()
        buttons.addWidget(self.minus_button)
        buttons.addWidget(self.plus_button)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(self.card_image, stretch=1)
        layout.addWidget(self.detail_name)
        layout.addWidget(self.detail_type)
        layout.addWidget(self.detail_text)
        layout.addWidget(self.detail_info)
        layout.addWidget(self.detail_works)
        layout.addLayout(buttons)
        return panel

    def _build_deck_panel(self):
        self.list_combo = QComboBox()
        self.list_combo.currentIndexChanged.connect(lambda: (self.load_entries(), self.search_cards()))
        new_button = QPushButton("New…")
        new_button.clicked.connect(self.new_list)
        self.rename_button = QPushButton("Rename…")
        self.rename_button.clicked.connect(self.rename_list)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_list)
        top = QHBoxLayout()
        top.addWidget(self.list_combo, stretch=1)
        for button in (new_button, self.rename_button, self.delete_button):
            top.addWidget(button)

        self.format_label = QLabel("Format:")
        self.format_combo = _format_combo()
        self.format_combo.currentIndexChanged.connect(self.on_format_changed)
        self.section_label = QLabel("Add to:")
        self.section_combo = QComboBox()
        for section in SECTIONS:
            self.section_combo.addItem(SECTION_TITLES[section], section)
        self.section_combo.setCurrentIndex(self.section_combo.findData("Main"))
        self.bracket_title = QLabel("Bracket:")
        self.bracket_combo = QComboBox()
        self.bracket_combo.addItem("No target", None)
        for number in range(1, 6):
            self.bracket_combo.addItem(brackets.label(number), number)
        self.bracket_combo.setToolTip("The Commander bracket this deck aims for: the deck is checked against it, "
                                      "and Recommended leaves out cards that don't fit")
        self.bracket_combo.currentIndexChanged.connect(self.on_bracket_changed)
        self.import_button = QPushButton("Import…")
        self.import_button.setToolTip("Add cards from a deck list or CSV file")
        self.import_button.clicked.connect(self.import_cards)
        self.export_button = QPushButton("Export…")
        self.export_button.setToolTip("Save as a text deck list other apps can import")
        self.export_button.clicked.connect(self.export_list)
        # Sized to a dozen characters, not their longest item, so this panel can stay narrow
        # and the card panel gets the room (the lists still show full names when opened)
        for combo in (self.format_combo, self.section_combo, self.bracket_combo):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(12)
        second = QHBoxLayout()
        for widget in (self.format_label, self.format_combo, self.section_label, self.section_combo):
            second.addWidget(widget)
        second.addStretch()
        second.addWidget(self.import_button)
        second.addWidget(self.export_button)
        third = QHBoxLayout()
        third.addWidget(self.bracket_title)
        third.addWidget(self.bracket_combo)
        third.addStretch()

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.types_label = QLabel()
        self.types_label.setStyleSheet("color: gray;")
        self.types_label.setWordWrap(True)
        self.problems_label = QLabel()
        self.problems_label.setWordWrap(True)
        self.bracket_label = QLabel()
        self.bracket_label.setWordWrap(True)
        self.bracket_label.setStyleSheet("color: gray;")

        # Sort and group the list (card_sorting.py); each list remembers its own
        self.sort_bar = SortBar("deck", "list:none")
        self.sort_bar.changed.connect(self.load_entries)

        self.deck_tree = QTreeWidget()
        self.deck_tree.setColumnCount(len(DECK_COLUMNS))
        self.deck_tree.setHeaderLabels(DECK_COLUMNS)
        self.deck_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.deck_tree.setRootIsDecorated(False)
        self.deck_tree.setAlternatingRowColors(True)
        header = self.deck_tree.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(NAME_COL, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(False)
        self.deck_tree.itemSelectionChanged.connect(self.on_deck_selection)
        self.deck_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.deck_tree.customContextMenuRequested.connect(self.show_deck_menu)
        remove_action = QAction("Remove", self.deck_tree, shortcut=QKeySequence.StandardKey.Delete)
        remove_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        remove_action.triggered.connect(self.remove_selected)
        self.deck_tree.addAction(remove_action)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addLayout(top)
        layout.addLayout(second)
        layout.addLayout(third)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.types_label)
        layout.addWidget(self.problems_label)
        layout.addWidget(self.bracket_label)
        layout.addWidget(self.sort_bar)
        layout.addWidget(self.deck_tree, stretch=1)
        return panel

    def _build_card_panel(self):
        self.card_tabs = QTabBar()
        self.card_tabs.addTab("My Cards")
        self.card_tabs.addTab("Explore")
        self.card_tabs.addTab("Recommended")
        self.card_tabs.addTab("Stats")
        self.card_tabs.setTabToolTip(0, "Cards in your collection")
        self.card_tabs.setTabToolTip(1, "Every card in Magic, owned or not")
        self.card_tabs.setTabToolTip(2, "Cards for a Commander deck's commander, by the themes you pick")
        self.card_tabs.setTabToolTip(3, "The list's mana curve, colors, card types and most valuable cards")
        self.card_tabs.currentChanged.connect(lambda _: self.search_cards())

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search name, type or rules text…")
        self.search_input.setClearButtonEnabled(True)
        self._search_timer = QTimer(self, singleShot=True, interval=250)
        self._search_timer.timeout.connect(self.search_cards)
        self.search_input.textChanged.connect(lambda _: self._search_timer.start())

        self.type_combo = QComboBox()
        self.type_combo.addItem("Any type", "")
        for card_type in formats.CARD_TYPES:
            self.type_combo.addItem(card_type, card_type)
        self.type_combo.currentIndexChanged.connect(lambda _: self.search_cards())
        self.color_buttons = {}
        self.filters = QWidget()
        filters = QHBoxLayout(self.filters)
        filters.setContentsMargins(0, 0, 0, 0)
        filters.addWidget(self.type_combo)
        for color, name in zip("WUBRGC", ("White", "Blue", "Black", "Red", "Green", "Colorless")):
            button = QToolButton()
            button.setText(color)
            button.setCheckable(True)
            button.setToolTip(f"{name} cards (select several to see any of them)")
            button.toggled.connect(lambda _: self.search_cards())
            self.color_buttons[color] = button
            filters.addWidget(button)
        filters.addStretch()
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(list(db.CARD_SORTS))
        self.sort_combo.setToolTip("Sort the card list")
        self.sort_combo.currentIndexChanged.connect(lambda _: self.search_cards())
        filters.addWidget(self.sort_combo)
        self.legal_check = QCheckBox("Legal for this deck")
        self.legal_check.setToolTip("Only cards legal in the deck's format (and its commander's colors)")
        self.legal_check.setChecked(True)
        self.legal_check.toggled.connect(lambda _: self.search_cards())

        self.db_notice = QLabel()
        self.db_notice.setWordWrap(True)
        self.db_button = QPushButton("Download Card Database")
        self.db_button.setToolTip("Every card's rules, types and legality from Scryfall (about 80 MB)")
        self.db_button.clicked.connect(lambda: self.update_card_database())
        self.db_progress = QProgressBar()
        self.db_progress.hide()

        def owned(row):
            return (f"×{row['owned']}", GOOD) if row["owned"] else ("0", MUTED)

        self.card_browser = CardBrowser(
            columns=[("Card", lambda row: row["name"]),
                     ("Type", lambda row: (row["type_line"] or "").split(" — ")[0]),
                     ("Mana", lambda row: row["mana_cost"] or ""),
                     ("Set", lambda row: (row["set_code"] or "") + (" ✦" if row["foil"] else "")),
                     ("Price", lambda row: _money(row["price"])),
                     ("Owned", owned)],
            caption=owned,
            tooltip=lambda row: "\n".join(filter(None, [
                row["name"], row["type_line"], f"{row['set_name']} ({row['set_code']})",
                f"Price: {_money(row['price'])}", f"You own {row['owned']}"])),
        )
        self.card_browser.selected.connect(self.show_card)
        self.card_browser.activated.connect(lambda row: self.add_card(row, 1))
        self.card_browser.menu_requested.connect(self.show_card_menu)
        self.recommend_panel = RecommendationsPanel(self.settings)
        self.recommend_panel.selected.connect(self.show_card)
        self.recommend_panel.activated.connect(lambda row: self.add_card(row, 1))
        self.recommend_panel.menu_requested.connect(self.show_card_menu)
        self.stats_view = QTextBrowser()  # the Stats tab (stats_html)
        self._results = []
        self.results_label = QLabel()
        self.results_label.setStyleSheet("color: gray;")
        self.results_label.setWordWrap(True)  # a long unwrapped line would force the window wider

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(self.card_tabs)
        layout.addWidget(self.search_input)
        layout.addWidget(self.filters)
        layout.addWidget(self.legal_check)
        layout.addWidget(self.db_notice)
        layout.addWidget(self.db_button)
        layout.addWidget(self.db_progress)
        layout.addWidget(self.card_browser, stretch=1)
        layout.addWidget(self.recommend_panel, stretch=1)
        layout.addWidget(self.stats_view, stretch=1)
        layout.addWidget(self.results_label)
        return panel

    # Lists

    def reload(self, select_id=None):
        # Refills the list picker, keeping (or moving to) the selected list
        if select_id is None and self._list is not None:
            select_id = self._list["id"]
        self.list_combo.blockSignals(True)
        self.list_combo.clear()
        for row in db.get_lists():
            kind = KINDS.get(row["kind"], row["kind"])
            if row["kind"] == "deck":
                kind += f", {formats.label(row['format'])}"
            self.list_combo.addItem(f"{row['name']}  ({kind} · {count(row['cards'], 'card')})", row["id"])
        index = self.list_combo.findData(select_id)
        self.list_combo.setCurrentIndex(index if index >= 0 else 0)
        self.list_combo.blockSignals(False)
        self.load_entries()

    def select_list(self, list_id):
        self.reload(select_id=list_id)
        self.show()
        self.raise_()
        self.activateWindow()

    def new_list(self):
        list_id = ask_new_list(self)
        if list_id is not None:
            self.reload(select_id=list_id)

    def rename_list(self):
        name, ok = QInputDialog.getText(self, "Rename", "Name:", text=self._list["name"])
        if ok and name.strip():
            db.rename_list(self._list["id"], name.strip())
            self.reload()

    def delete_list(self):
        answer = QMessageBox.question(
            self, "Delete", f"Delete “{self._list['name']}”? Its cards stay in your collection; "
            "only the list is deleted.")
        if answer == QMessageBox.StandardButton.Yes:
            db.delete_list(self._list["id"])
            self._list = None
            self.reload()

    def on_format_changed(self):
        if self._list is not None and self._list["kind"] == "deck":
            db.set_list_format(self._list["id"], self.format_combo.currentData())
            self.reload()
            self.search_cards()

    def on_bracket_changed(self):
        if self.is_commander_deck():
            db.set_list_bracket(self._list["id"], self.bracket_combo.currentData())
            self.reload()

    def is_deck(self):
        return self._list is not None and self._list["kind"] == "deck"

    def deck_format(self):
        return self._list["format"] if self.is_deck() else "casual"

    def is_commander_deck(self):
        # Brackets are for Commander only
        return self.deck_format() == "commander"

    # Commander brackets

    def bracket_report(self):
        # (the deck's brackets.Report, Spellbook's answer: a dict, None while asking, False if it
        # failed, "offline"), asking Commander Spellbook about combos once per set of cards
        cards = brackets.counted(self._entries)
        key = (tuple(sorted({e["name"] for e in cards if e["section"] == "Commander"})),
               tuple(sorted({e["name"] for e in cards if e["section"] == "Main"})))
        if key not in self._spellbook and not scryfall.offline and cards:
            self._spellbook[key] = None
            # Bound methods, so nothing is delivered if the window is gone by the time it answers
            background.run(_check_combos, key, on_success=self._on_spellbook, on_error=self._on_spellbook_failed)
        found = self._spellbook.get(key) if key in self._spellbook else "offline"
        if not cards:  # nothing to ask about
            found = brackets.read_spellbook({"cards": [], "combos": []})
        return brackets.check(self._entries, found if isinstance(found, dict) else None), found

    def _on_spellbook(self, result):
        key, found = result
        self._spellbook[key] = found
        if self.is_commander_deck():
            self.reload()

    def _on_spellbook_failed(self, message):
        # The error doesn't say which deck it was for: every check still waiting has failed
        for key, found in self._spellbook.items():
            if found is None:
                self._spellbook[key] = False
        if self.is_commander_deck():
            self.reload()

    def _show_bracket(self, report, found, target):
        low = report.minimum()
        fits = {1: "Bracket 1 or 2 (Exhibition or Core: that's down to the deck's intent)",
                4: "Bracket 4 or 5 (Optimized or cEDH: that's down to the deck's intent)"}.get(
            low, brackets.label(low))

        def listed(title, names, limit=None):
            if not names:
                return f"{title}: none"
            return f"{title} {len(names)}{'/' + str(limit) if limit else ''}: {', '.join(names)}"

        parts = [f"<b>Fits {fits}</b>" + (f" · aiming for {brackets.label(target)}" if target else ""),
                 listed("Game Changers", report.game_changers, 3 if target == 3 else None),
                 listed("Mass land denial", report.mass_land_denial),
                 listed("Extra turns", report.extra_turns)]
        if report.combos_checked:
            parts.append(listed("Two-card combos", [f"{' + '.join(c.cards)} ({c.results})" for c in report.combos]))
        else:
            parts.append({None: "Two-card combos: checking Commander Spellbook…",
                          False: "Two-card combos: couldn't reach Commander Spellbook"}.get(
                found, "Two-card combos: not checked while offline"))
        self.bracket_label.setText("  ·  ".join(parts))

    # The selected list

    def load_entries(self):
        list_id = self.list_combo.currentData()
        self._list = next((row for row in db.get_lists() if row["id"] == list_id), None)
        for widget in (self.rename_button, self.delete_button, self.import_button, self.export_button):
            widget.setEnabled(self._list is not None)
        deck = self.is_deck()
        for widget in (self.format_label, self.format_combo, self.section_label, self.section_combo):
            widget.setVisible(deck)
        commander = self.is_commander_deck()
        for widget in (self.bracket_title, self.bracket_combo, self.bracket_label):
            widget.setVisible(commander)
        self.legal_check.setVisible(deck and not self.recommending() and not self.showing_stats())
        self.deck_tree.setColumnHidden(LEGAL_COL, not deck)
        self.deck_tree.clear()
        if self._list is None:
            self._entries = []
            self.summary_label.setText("No lists yet. Use New… to start a deck, binder or wishlist.")
            self.types_label.setText("")
            self.problems_label.setText("")
            self.show_card(None)
            return

        self.format_combo.blockSignals(True)
        self.format_combo.setCurrentIndex(max(0, self.format_combo.findData(self._list["format"])))
        self.format_combo.blockSignals(False)
        self.bracket_combo.blockSignals(True)
        self.bracket_combo.setCurrentIndex(max(0, self.bracket_combo.findData(self._list["bracket"])))
        self.bracket_combo.blockSignals(False)

        self._entries = db.get_list_entries(self._list["id"])
        have = completion(self._entries, db.owned_by_name())
        cards, value, owned, missing, cost = summary(self._entries, have)
        text = f"{count(cards, 'card')} worth {_money(value)}. You own {owned:,} of them"
        text += f"; {missing:,} you don't own would cost {_money(cost)}." if missing else "."
        self.summary_label.setText(text)

        problems, statuses = formats.validate(self._entries, self.deck_format()) if deck else ([], {})
        target = self._list["bracket"] if commander else None
        if commander:
            report, found = self.bracket_report()
            self._show_bracket(report, found, target)
            for why, names in report.broken(target) if target else []:
                problems.append(f"{why}: {', '.join(names)}.")
                for e in self._entries:
                    if e["name"] in names and e["section"] in ("Main", "Commander"):
                        statuses.setdefault(e["id"], f"Not in Bracket {target}")
        types = formats.type_counts(self._entries) if deck else {}
        self.types_label.setText("  ·  ".join(f"{_plural(t, n)} {n}" for t, n in types.items()))
        if not deck or self.deck_format() == "casual":
            self.problems_label.setText("")
        elif problems:
            self.problems_label.setText("<span style='color:#c62828'>" +
                                        "<br>".join(f"• {p}" for p in problems) + "</span>")
        else:
            self.problems_label.setText(f"<span style='color:#1a8f3c'>✓ Legal in "
                                        f"{formats.label(self.deck_format())}"
                                        f"{' and fits ' + brackets.label(target) if target else ''}</span>")

        self.sort_bar.set_key(f"list:{self._list['id']}", "deck" if deck else "list")
        groups = [(title or SECTION_TITLES[""], entries) for title, entries in self.sort_bar.arrange(self._entries)]
        if deck and self.sort_bar.view["group"] == "Section":
            # The sections cards are added to show even while empty
            present = dict(groups)
            sections = [SECTION_TITLES[s] for s in SECTIONS if SECTION_TITLES[s] in present or s == "Sideboard" or (
                s == "Commander" and formats.FORMATS.get(self.deck_format(), formats.FORMATS["casual"]).commander)]
            groups = [(title, present.get(title, [])) for title in sections] + [
                (title, entries) for title, entries in groups if title not in sections]
        elif not groups:
            groups = [(SECTION_TITLES["Main"] if deck else SECTION_TITLES[""], [])]
        for title, entries in groups:
            header = QTreeWidgetItem([card_sorting.heading(title, entries)])
            font = header.font(0)
            font.setBold(True)
            header.setFont(0, font)
            header.setFirstColumnSpanned(True)
            header.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.deck_tree.addTopLevelItem(header)
            header.setFirstColumnSpanned(True)
            for entry in entries:
                header.addChild(self._deck_item(entry, have[entry["id"]], statuses.get(entry["id"])))
            header.setExpanded(True)

        self.show_card(self._card[0] if self._card else None, self._card[1] if self._card else None)
        self.refresh_prices()
        if self.recommending():
            self.update_recommendations()
        if self.showing_stats():
            self.update_stats()

    def _deck_item(self, entry, got, status):
        item = QTreeWidgetItem([
            str(entry["quantity"]), entry["name"], (entry["type_line"] or "").split(" — ")[0],
            entry["mana_cost"] or "", _money(entry["price"]), f"{got} / {entry['quantity']}",
            status or ("?" if entry["legalities"] is None else "✓"),
        ])
        item.setData(0, ID_ROLE, entry["id"])
        for column in (QTY_COL, PRICE_COL, OWNED_COL):
            item.setTextAlignment(column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setForeground(OWNED_COL, GOOD if got >= entry["quantity"] else BAD)
        item.setToolTip(OWNED_COL, "Copies in your collection (any printing)")
        if not got:  # cards you don't own at all stand out
            font = item.font(NAME_COL)
            font.setItalic(True)
            item.setFont(NAME_COL, font)
            item.setToolTip(NAME_COL, "Not in your collection")
        item.setForeground(LEGAL_COL, BAD if status else MUTED if entry["legalities"] is None else GOOD)
        if self.is_commander_deck() and entry["game_changer"]:
            item.setText(TYPE_COL, item.text(TYPE_COL) + "  ◆ Game Changer")
            item.setToolTip(TYPE_COL, "On Wizards' Game Changers list: none in Brackets 1–2, up to three in "
                                      "Bracket 3")
        if status:
            item.setForeground(NAME_COL, BAD)
        return item

    def selected_entries(self):
        ids = [item.data(0, ID_ROLE) for item in self.deck_tree.selectedItems()]
        return [e for e in self._entries if e["id"] in ids]

    def entry_by_id(self, entry_id):
        return next((e for e in self._entries if e["id"] == entry_id), None)

    # Card details (left)

    def show_card(self, row, entry_id=None):
        # row: a list entry or a card-list row (both have the card's fields), or None
        self._card = (row, entry_id) if row is not None else None
        for button in (self.minus_button, self.plus_button):
            button.setEnabled(row is not None and self._list is not None)
        if row is None:
            self.card_image.clear_image("Select a card")
            for label in (self.detail_name, self.detail_type, self.detail_info, self.detail_works):
                label.setText("")
            self.detail_text.setPlainText("")
            return
        self.card_image.set_image_url(row["image_url"])
        self.detail_name.setText(row["name"])
        self.detail_type.setText("  ".join(filter(None, [row["mana_cost"], row["type_line"]])))
        self.detail_text.setPlainText(row["oracle_text"] or "")
        owned = db.owned_by_name().get(row["name"].lower(), 0)
        in_list = sum(e["quantity"] for e in self._entries if e["name"].lower() == row["name"].lower())
        info = [f"You own {owned}", f"In this list: {in_list}", f"Price: {_money(row['price'])}"]
        if row["set_code"]:
            info.insert(0, f"{row['set_name']} ({row['set_code']}) #{row['collector_number']}"
                           + (" · Foil" if row["foil"] == 1 else " · Etched" if row["foil"] == 2 else ""))
        if self.is_deck() and self.deck_format() != "casual":
            status = formats.legality(row, self.deck_format())
            text = {"legal": "Legal", "restricted": "Restricted (1 copy)", "banned": "Banned",
                    "not_legal": "Not legal", None: "Legality unknown"}.get(status, status)
            info.append(f"{formats.label(self.deck_format())}: {text}")
        if self.is_commander_deck() and row["game_changer"]:
            info.append("Game Changer: none in Brackets 1–2, up to three in Bracket 3")
        self.detail_info.setText("\n".join(info))
        works = interactions.load().summary(row)[:WORKS_SHOWN]
        self.detail_works.setText("Works well with:\n" + "\n".join(works) if works else "")

    def on_deck_selection(self):
        entries = self.selected_entries()
        if len(entries) == 1:
            self.show_card(entries[0], entries[0]["id"])

    def change_selected(self, delta):
        # -1 / +1 on the card shown on the left
        row, entry_id = self._card
        entry = self.entry_by_id(entry_id) if entry_id else self._matching_entry(row)
        if delta > 0:
            if entry is not None:
                db.update_list_entry(entry["id"], quantity=entry["quantity"] + 1)
            else:
                self.add_card(row, 1)
                return
        elif entry is not None:
            if entry["quantity"] > 1:
                db.update_list_entry(entry["id"], quantity=entry["quantity"] - 1)
            else:
                db.remove_list_entries([entry["id"]])
                if entry_id:
                    self._card = (row, None)
        self.reload()

    def _matching_entry(self, row):
        # The list's entry for a card-list row: same printing and finish, preferring the
        # "Add to" section, else any entry with the same name
        same = [e for e in self._entries if e["name"].lower() == row["name"].lower()]
        exact = [e for e in same if e["scryfall_id"] == row["scryfall_id"] and e["foil"] == row["foil"]]
        for candidates in (exact, same):
            preferred = [e for e in candidates if e["section"] == self._add_section()]
            if preferred or candidates:
                return (preferred or candidates)[0]
        return None

    # Adding and removing

    def _add_section(self, section=None):
        return section if section is not None else self.section_combo.currentData() if self.is_deck() else ""

    def add_card(self, row, quantity, section=None):
        if self._list is None:
            QMessageBox.information(self, "Deck Builder", "Create a list with New… first.")
            return
        record = {key: row[key] for key in ("name", "scryfall_id", "foil", "set_code", "set_name",
                                             "collector_number", "image_url", "price")}
        db.add_list_entries(self._list["id"], [{**record, "quantity": quantity}], section=self._add_section(section))
        self.reload()

    def remove_selected(self):
        entries = self.selected_entries()
        if not entries:
            return
        what = entries[0]["name"] if len(entries) == 1 else count(len(entries), "entry")
        answer = QMessageBox.question(self, "Remove", f"Remove {what} from “{self._list['name']}”?")
        if answer == QMessageBox.StandardButton.Yes:
            db.remove_list_entries([e["id"] for e in entries])
            self.reload()

    def show_deck_menu(self, position):
        item = self.deck_tree.itemAt(position)
        if item is None or item.data(0, ID_ROLE) is None:
            return
        if not item.isSelected():
            self.deck_tree.clearSelection()
            item.setSelected(True)
        entries = self.selected_entries()
        menu = QMenu(self)
        if len(entries) == 1:
            entry = entries[0]
            menu.addAction("+1", lambda: (db.update_list_entry(entry["id"], quantity=entry["quantity"] + 1),
                                          self.reload()))
            menu.addAction("−1", lambda: (self.show_card(entry, entry["id"]), self.change_selected(-1)))
            menu.addAction("Change printing…", lambda: self.change_printing(entry))
        if self.is_deck():
            move = menu.addMenu("Move to")
            for section in SECTIONS:
                move.addAction(SECTION_TITLES[section], lambda s=section: self.move_to(entries, s))
        menu.addSeparator()
        menu.addAction("Remove" if len(entries) == 1 else f"Remove {count(len(entries), 'entry')}",
                       self.remove_selected)
        menu.exec(QCursor.pos())

    def show_card_menu(self, row):
        menu = QMenu(self)
        menu.addAction("Add 1", lambda: self.add_card(row, 1))
        menu.addAction("Add 4", lambda: self.add_card(row, 4))
        if self.is_deck():
            add_to = menu.addMenu("Add 1 to")
            for section in SECTIONS:
                add_to.addAction(SECTION_TITLES[section], lambda s=section: self.add_card(row, 1, s))
        menu.addAction("Add a different printing…", lambda: self.add_printing(row))
        menu.exec(QCursor.pos())

    def move_to(self, entries, section):
        for entry in entries:
            db.update_list_entry(entry["id"], section=section)
        self.reload()
        if "Commander" in {section, *(e["section"] for e in entries)}:
            self.search_cards()  # the commander's colors filter the card list

    def _pick_printing(self, name, action, current=None):
        # Opens the printing picker; returns an add_card-style record or None
        printings = db.printings_of(name)
        if not printings:
            QMessageBox.information(self, "Printings", "Download the card database to choose printings.")
            return None
        dialog = PrintingDialog(name, printings, self.card_browser.lightweight, action, current, self)
        return dialog.choice() if dialog.exec() == QDialog.DialogCode.Accepted else None

    def add_printing(self, row):
        printing = self._pick_printing(row["name"], "Add to List", (row["scryfall_id"], row["foil"]))
        if printing is not None:
            self.add_card(printing, 1)

    def change_printing(self, entry):
        printing = self._pick_printing(entry["name"], "Use This Printing", (entry["scryfall_id"], entry["foil"]))
        if printing is None:
            return
        db.remove_list_entries([entry["id"]])
        db.add_list_entries(self._list["id"], [{**printing, "quantity": entry["quantity"]}], section=entry["section"])
        self._card = None
        self.reload()

    # Card list (right)

    def recommending(self):
        return self.card_tabs.currentIndex() == 2

    def showing_stats(self):
        return self.card_tabs.currentIndex() == 3

    def update_stats(self):
        st = deck_stats.stats(self._entries, self.is_deck()) if self._list is not None else None
        self.stats_view.setHtml(stats_html(st) if st else "<p>Add cards to see their stats.</p>")

    def update_recommendations(self):
        panel = self.recommend_panel
        fmt = formats.FORMATS.get(self.deck_format(), formats.FORMATS["casual"])
        commanders = [e for e in self._entries if e["section"] == "Commander"]
        if not db.has_card_database():
            panel.show_message("Recommendations need the card database. Download it with the button above.")
        elif not self.is_deck() or not fmt.commander:
            panel.show_message("Recommendations are for Commander decks. Pick a deck with a Commander-style "
                               "format (Commander, Brawl, Oathbreaker…), or start one with New….")
        elif not commanders:
            panel.show_message("Add this deck's commander first: find it under Explore, then right-click it "
                               "→ Add 1 to → Commander.")
        else:
            target = self._list["bracket"] if self.is_commander_deck() else None
            game_changers = len({e["name"] for e in brackets.counted(self._entries) if e["game_changer"]})
            panel.show_deck(self._list["id"], commanders, {e["name"] for e in self._entries}, target,
                            game_changers)

    def search_cards(self):
        explore = self.card_tabs.currentIndex() == 1
        recommending, stats = self.recommending(), self.showing_stats()
        for widget in (self.search_input, self.filters, self.card_browser, self.results_label):
            widget.setVisible(not recommending and not stats)
        self.legal_check.setVisible(self.is_deck() and not recommending and not stats)
        self.recommend_panel.setVisible(recommending)
        self.stats_view.setVisible(stats)
        if stats:
            for widget in (self.db_notice, self.db_button):
                widget.hide()  # the stats come from the list itself, not the card database
            self.update_stats()
            return
        has_db = db.has_card_database()
        self.db_notice.setVisible(not has_db and not self._updating_cards)
        self.db_button.setVisible(not has_db and not self._updating_cards)
        self.db_notice.setText("Explore, Recommended, card types and legality need the card database: every "
                               "card's rules and legality from Scryfall (about 80 MB, once, then weekly updates).")
        if recommending:
            self.update_recommendations()
            return
        format_key = identity = None
        if self.is_deck() and self.legal_check.isChecked() and has_db:
            format_key = self.deck_format()
            fmt = formats.FORMATS.get(format_key, formats.FORMATS["casual"])
            commanders = [e for e in self._entries if e["section"] == "Commander"]
            if fmt.commander and commanders:
                identity = "".join(e["color_identity"] or "" for e in commanders)
        colors = "".join(c for c, button in self.color_buttons.items() if button.isChecked())
        if explore and not has_db:
            rows, total = [], 0
        else:
            rows, total = db.search_cards(not explore, self.search_input.text(), self.type_combo.currentData(),
                                          colors, format_key, identity, RESULTS_SHOWN,
                                          self.sort_combo.currentText())
        self._results = rows
        self.card_browser.set_rows(rows)
        where = "in your collection" if not explore else "in Magic"
        text = f"{total:,} card{'s' if total != 1 else ''} {where}"
        if total > len(rows):
            text = f"Showing the first {len(rows):,} of {total:,} cards {where}. Search to narrow it down."
        self.results_label.setText(text + "  ·  Double-click to add, right-click for more.")

    # Import / export

    def import_cards(self):
        start_import(self, f"“{self._list['name']}”", self._on_import_reviewed)

    def _on_import_reviewed(self, review):
        if review is None or self._list is None:
            return
        records = [{**entry.record(), "section": entry.row.section if self.is_deck() else ""}
                   for entry in review.included()]
        db.add_list_entries(self._list["id"], records)
        self.reload()

    def export_list(self):
        name = "".join(c for c in self._list["name"] if c not in '\\/:*?"<>|') or "list"
        path, _ = QFileDialog.getSaveFileName(self, "Export List", f"{name}.txt", "Text deck lists (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(deck_text(self._entries))
        except OSError as error:
            QMessageBox.warning(self, "Export Failed", str(error))

    # Prices and the card database

    def refresh_prices(self):
        # Prices older than a day refresh on their own (once per entry per session)
        if self._refreshing or self._list is None:
            return
        work = [(e["id"], e["scryfall_id"], e["foil"]) for e in self._entries
                if e["scryfall_id"] and _stale(e) and e["id"] not in self._price_checked]
        if not work:
            return
        self._price_checked.update(entry_id for entry_id, _, _ in work)
        self._refreshing = True
        background.run(scryfall.fetch_prices, work, on_success=self._on_prices, on_error=self._on_prices_failed)

    def _on_prices(self, result):
        self._refreshing = False
        db.update_list_prices(result[0])
        self.reload()

    def _on_prices_failed(self, message):
        self._refreshing = False

    def _card_db_stale(self):
        checked = self.settings.value("carddb_checked")
        return not checked or date.fromisoformat(checked) + CARD_DB_MAX_AGE <= date.today()

    def update_card_database(self, quiet=False):
        if self._updating_cards:
            return
        self._updating_cards = True
        self._quiet_update = quiet
        self.db_button.hide()
        self.db_notice.setText("Downloading the card database…")
        self.db_notice.setVisible(not quiet)
        # A database missing newer columns (see db.card_database_outdated) downloads again even if unchanged
        fresh = db.has_card_database() and not db.card_database_outdated()
        last_bulk = self.settings.value("finance_bulk_updated") if fresh else None
        track_new = self.settings.value("finance_mode") == finance.POPULATED
        background.run(_update_card_database, last_bulk, track_new, on_success=self._on_card_db,
                       on_error=self._on_card_db_failed, on_progress=self._on_card_db_progress)

    def _on_card_db_progress(self, value):
        _, done, total = value
        if not self._quiet_update:
            self.db_progress.show()
            self.db_progress.setValue(min(99, done * 100 // max(total, 1)))

    def _on_card_db(self, done):
        self._updating_cards = False
        self.db_progress.hide()
        self.settings.setValue("carddb_checked", date.today().isoformat())
        if "bulk" in done:
            self.settings.setValue("finance_bulk_updated", done["bulk"])
        self.recommend_panel.invalidate()
        self.reload()
        self.search_cards()

    def _on_card_db_failed(self, message):
        self._updating_cards = False
        self.db_progress.hide()
        if not self._quiet_update:
            QMessageBox.warning(self, "Card Database", f"Couldn't download the card database:\n{message}")
        self.search_cards()
