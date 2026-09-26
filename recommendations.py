"""
The deck builder's Recommended tab: an EDHREC-style page for the deck's commander.
The commander up top, with theme buttons for the direction you want to take the deck
and a few filters, then sections of card images: High Synergy Cards, the staples,
then each card type. How cards are picked is in synergy.py.
"""

# Imports
import math

from PySide6.QtCore import Qt, QPoint, QRect, QSize, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QToolButton, QMenu, QCheckBox,
    QDoubleSpinBox, QScrollArea, QProgressBar, QSizePolicy, QInputDialog, QLayout,
)

import background
import database as db
import scryfall
import synergy
from card_browser import CardBrowser, OWNED_COLOR, money
from card_image import CardImage

TILE = QSize(146, 204)   # Scryfall's "small" card images, at their own size
MAX_CHIPS = 6            # suggested themes shown as buttons; the rest are under More Themes
CHIP_STYLE = """
    QPushButton { border: 1px solid #9e9e9e; border-radius: 11px; padding: 3px 12px; }
    QPushButton:checked { background: #5e35b1; border-color: #5e35b1; color: white; }
"""

_known_types = None


def known_creature_types():
    # Every creature type in the card database, for spotting tribal commanders (worked out once)
    global _known_types
    if _known_types is None:
        _known_types = synergy.known_types(db.creature_type_lines())
    return _known_types


def _owned(row):
    return f"×{row['owned']} owned" if row["owned"] else "Not owned"


def _tooltip(row):
    return "\n".join(filter(None, [row["name"], row["type_line"], row["note"],
                                   f"Price: {money(row['price'])}", _owned(row)]))


class _FlowLayout(QLayout):
    """Lays widgets out left to right, wrapping onto more lines when there isn't room,
    like words in a paragraph. It's only ever as wide as its widest item, so a row of
    theme buttons can't force the window wider. (Qt's own FlowLayout example, trimmed.)"""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, move=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect, move):
        # Places the items (if move) and returns the height they need at rect's width
        x, y, line_height = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line_height:
                x, y, line_height = rect.x(), y + line_height + self.spacing(), 0
            if move:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


def _load(identity, theme_keys, commanders, tags, cards, fetch, progress=None):
    # synergy.load and synergy.score, tagged with the identity, themes and commanders they were for
    names = [c["name"] for c in commanders]
    cards, found, missing = synergy.load(identity, tags, names, cards, fetch, progress)
    pool = synergy.score(cards, theme_keys, found, commanders)
    return (identity, theme_keys, names), cards, pool, missing, found["precon-decks"]


class _Section(QWidget):
    """A titled group of cards, exactly as tall as its cards so the whole page
    scrolls as one rather than every section scrolling on its own."""

    def __init__(self, title, rows, hidden, lightweight, panel):
        # hidden: how many more cards the section has than it shows
        super().__init__()
        self.browser = CardBrowser(
            columns=[("Card", lambda r: r["name"]),
                     ("Type", lambda r: (r["type_line"] or "").split(" — ")[0]),
                     ("Why", lambda r: r["note"]),
                     ("Price", lambda r: money(r["price"])),
                     ("Owned", lambda r: (_owned(r), OWNED_COLOR if r["owned"] else None))],
            caption=lambda r: (f"{r['note']}\n{money(r['price'])}" + (f" · ×{r['owned']} owned" if r["owned"] else ""),
                               OWNED_COLOR if r["owned"] else None),
            tooltip=_tooltip, thumb_size=TILE, caption_lines=2,
        )
        for view in (self.browser.grid, self.browser.table):
            view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.browser.set_lightweight(lightweight)
        self.browser.set_rows(rows)
        self.browser.selected.connect(panel.selected)
        self.browser.activated.connect(panel.activated)
        self.browser.menu_requested.connect(panel.menu_requested)

        label = QLabel(f"{title}  <span style='color: gray; font-weight: normal;'>{len(rows)}</span>")
        label.setStyleSheet("font-size: 16px; font-weight: bold; padding-top: 10px;")
        header = QHBoxLayout()
        header.addWidget(label)
        header.addStretch()
        if hidden:
            more = QPushButton(f"Show {min(hidden, synergy.SHOW_MORE)} More ({hidden:,} left)")
            more.setFlat(True)
            more.setStyleSheet("color: #5e35b1;")
            more.clicked.connect(lambda: panel.show_more(title))
            header.addWidget(more, alignment=Qt.AlignmentFlag.AlignBottom)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(header)
        layout.addWidget(self.browser)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        count = len(self.browser.rows)
        if self.browser.lightweight:
            table = self.browser.table
            height = (table.horizontalHeader().height() + sum(table.rowHeight(r) for r in range(count))
                      + 2 * table.frameWidth())
        else:
            grid = self.browser.grid
            per_row = max(1, (self.width() - 2 * grid.frameWidth() - 4) // grid.gridSize().width())
            height = math.ceil(count / per_row) * grid.gridSize().height() + 2 * grid.frameWidth() + 4
        self.browser.setFixedHeight(height)


class RecommendationsPanel(QWidget):
    """Call show_deck() with a Commander deck's commanders, or show_message() to
    explain why there's nothing to recommend. Emits the card row selected,
    double-clicked (activated) or right-clicked (menu_requested)."""

    selected = Signal(object)
    activated = Signal(object)
    menu_requested = Signal(object)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.lightweight = False
        self._deck_id = self._identity = self._cards = self._pool = self._fetched = None
        self._commanders, self._names, self._in_deck = [], [], []
        self._themes, self._suggested, self._missing, self._precons = [], [], [], set()
        self._more = {}  # section title -> extra cards shown with Show More
        self._loading = self._pending = False

        # Header: the commander, the themes to build around, and filters
        self.commander_image = CardImage(width=170)
        self.commander_image.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.commander_name = QLabel()
        self.commander_name.setStyleSheet("font-size: 20px; font-weight: bold;")
        self.commander_name.setWordWrap(True)
        self.commander_info = QLabel()
        self.commander_info.setStyleSheet("color: gray;")
        self.commander_info.setWordWrap(True)

        # Theme buttons and filters wrap onto more lines rather than widening the window
        self.chip_row = _FlowLayout()
        self.more_button = QToolButton()
        self.more_button.setText("More Themes")
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_button.setMenu(QMenu(self.more_button))
        self.chip_row.addWidget(self.more_button)

        self.owned_check = QCheckBox("Cards I own")
        self.owned_check.setToolTip("Only recommend cards in your collection")
        self.price_input = QDoubleSpinBox()
        self.price_input.setPrefix("$")
        self.price_input.setMaximum(100000.00)
        self.price_input.setSpecialValueText("Any price")
        self.price_input.setToolTip("Leave out cards that cost more than this each")
        self.hide_check = QCheckBox("Hide cards in the deck")
        self.staples_check = QCheckBox("Staples")
        self.staples_check.setToolTip("Ramp, card draw, removal and board wipes in the commander's colors")
        self.owned_check.setChecked(self.settings.value("recommend_owned", False, type=bool))
        self.price_input.setValue(self.settings.value("recommend_max_price", 0.0, type=float))
        self.hide_check.setChecked(self.settings.value("recommend_hide_in_deck", True, type=bool))
        self.staples_check.setChecked(self.settings.value("recommend_staples", True, type=bool))
        self.owned_check.toggled.connect(lambda on: self._filter_changed("recommend_owned", on))
        self.hide_check.toggled.connect(lambda on: self._filter_changed("recommend_hide_in_deck", on))
        self.staples_check.toggled.connect(lambda on: self._filter_changed("recommend_staples", on, reload=on))
        self._price_timer = QTimer(self, singleShot=True, interval=400)
        self._price_timer.timeout.connect(lambda: self._filter_changed("recommend_max_price", self.price_input.value()))
        self.price_input.valueChanged.connect(lambda _: self._price_timer.start())
        price = QWidget()  # the label and its box wrap together
        price_layout = QHBoxLayout(price)
        price_layout.setContentsMargins(0, 0, 0, 0)
        price_layout.addWidget(QLabel("Max price:"))
        price_layout.addWidget(self.price_input)
        filters = _FlowLayout(spacing=12)
        for widget in (self.owned_check, price, self.hide_check, self.staples_check):
            filters.addWidget(widget)

        right = QVBoxLayout()
        right.addWidget(self.commander_name)
        right.addWidget(self.commander_info)
        right.addWidget(QLabel("Build around:"))
        right.addLayout(self.chip_row)
        right.addLayout(filters)
        right.addStretch()
        self.header = QWidget()
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(self.commander_image)
        header_layout.addLayout(right, stretch=1)

        self.status = QLabel()
        self.status.setStyleSheet("color: gray;")
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(200)
        self.progress.hide()
        status_row = QHBoxLayout()
        status_row.addWidget(self.status, stretch=1)
        status_row.addWidget(self.progress)

        self.page = QWidget()
        self.page_layout = QVBoxLayout(self.page)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.page)

        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setStyleSheet("color: gray; font-size: 14px; padding: 40px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.header)
        layout.addLayout(status_row)
        layout.addWidget(self.scroll, stretch=1)
        layout.addWidget(self.message, stretch=1)
        self.show_message("")

    # Showing a deck

    def show_message(self, text):
        # Nothing to recommend, and why
        for widget in (self.header, self.status, self.scroll):
            widget.hide()
        self.message.setText(text)
        self.message.show()
        self._deck_id = None

    def show_deck(self, deck_id, commanders, in_deck):
        # commanders: the deck's Commander section entries; in_deck: every card name in the deck
        for widget in (self.header, self.status, self.scroll):
            widget.show()
        self.message.hide()
        self._in_deck = list(in_deck)
        names = [c["name"] for c in commanders]
        if deck_id == self._deck_id and names == self._names:
            self.render()  # the deck changed, not the commander
            return
        self._deck_id, self._commanders, self._names = deck_id, commanders, names
        identity = synergy.identity_of(commanders)
        if identity != self._identity:
            self._identity, self._cards, self._pool = identity, None, None
        self.commander_image.set_image_url(commanders[0]["image_url"])
        self.commander_name.setText(" + ".join(names))
        self.commander_info.setText(f"Color identity: {identity or 'Colorless'}  ·  Picked from each card's "
                                    "rules text and Scryfall's card tags, ranked by how well they fit the "
                                    "themes you choose, then by how much they're played in Commander.")
        self._suggested = synergy.suggest_themes(commanders, known_creature_types())
        saved = self.settings.value(f"deck_themes/{deck_id}")
        self._themes = [k for k in saved.split(",") if k] if isinstance(saved, str) else self._suggested[:2]
        self._build_themes()
        self.load()

    def invalidate(self):
        # The card database changed: reload everything next time
        self._deck_id = self._identity = self._cards = self._pool = None

    def set_lightweight(self, on):
        self.lightweight = on
        if self._pool is not None:
            self.render()

    # Themes

    def _build_themes(self):
        while self.chip_row.count():
            widget = self.chip_row.takeAt(0).widget()
            if widget is not self.more_button:
                widget.deleteLater()
        chips = list(dict.fromkeys(self._suggested[:MAX_CHIPS] + self._themes))
        for key in chips:
            chip = QPushButton(synergy.theme(key).label)
            chip.setCheckable(True)
            chip.setChecked(key in self._themes)
            chip.setStyleSheet(CHIP_STYLE)
            chip.setToolTip("Suggested for this commander" if key in self._suggested else "")
            chip.toggled.connect(lambda on, key=key: self._toggle_theme(key, on))
            self.chip_row.addWidget(chip)
        self.chip_row.addWidget(self.more_button)  # always last

        menu = self.more_button.menu()
        menu.clear()
        own_types = [f"tribal:{t}" for c in self._commanders for t in synergy.creature_types(c)]
        for key in dict.fromkeys(list(synergy.THEMES) + own_types):
            if key in chips:
                continue
            action = QAction(synergy.theme(key).label, menu, checkable=True)
            action.toggled.connect(lambda on, key=key: self._toggle_theme(key, on))
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction("Any Creature Type…", self._pick_creature_type)

    def _pick_creature_type(self):
        types = known_creature_types()
        creature_type, ok = QInputDialog.getItem(self, "Creature Type", "Build around which creature type?",
                                                 types, 0, True)
        if ok and creature_type.strip() and f"tribal:{creature_type.strip()}" not in self._themes:
            self._toggle_theme(f"tribal:{creature_type.strip()}", True)

    def _toggle_theme(self, key, on):
        self._themes = [k for k in self._themes if k != key] + ([key] if on else [])
        self.settings.setValue(f"deck_themes/{self._deck_id}", ",".join(self._themes))
        QTimer.singleShot(0, self._build_themes)  # not while the clicked button's signal is still running
        self.load()

    def _filter_changed(self, setting, value, reload=False):
        self.settings.setValue(setting, value)
        if reload:
            self.load()  # staples need their own tags
        elif self._pool is not None:
            self.render()

    # Loading and showing cards

    def load(self, fetch=False):
        # Shows what the saved tags allow first; missing tags are then fetched (fetch)
        # and the page refined, so nobody waits on Scryfall to see cards
        if self._deck_id is None:
            return
        if self._loading:
            self._pending = True
            return
        self._loading = True
        if self._pool is None:
            self.status.setText("Finding cards…")
        tags = synergy.needed_tags(self._themes, self.staples_check.isChecked())
        background.run(_load, self._identity, list(self._themes), list(self._commanders), tags, self._cards, fetch,
                       on_success=self._on_loaded, on_error=self._on_failed, on_progress=self._on_progress)

    def _on_progress(self, value):
        label, done, total = value
        self.status.setText(label)
        self.progress.show()
        self.progress.setValue(done * 100 // max(total, 1))

    def _on_loaded(self, result):
        self._loading = False
        self.progress.hide()
        (identity, theme_keys, names), cards, pool, self._missing, self._precons = result
        if identity == self._identity:
            self._cards = cards
        if self._pending or (identity, theme_keys, names) != (self._identity, self._themes, self._names):
            self._pending = False
            self.load()
            return
        self._pool = pool
        self._more = {}
        self.render()
        if self._missing and not scryfall.offline and self._fetched != (identity, theme_keys, names):
            self._fetched = (identity, theme_keys, names)  # one try per commander and themes
            self.load(fetch=True)

    def _on_failed(self, message):
        self._loading = False
        self.progress.hide()
        self.status.setText(f"Couldn't load recommendations: {message}")

    def show_more(self, title):
        self._more[title] = self._more.get(title, 0) + synergy.SHOW_MORE
        self.render()

    def render(self):
        if self._pool is None or self._deck_id is None:
            return
        scroll = self.scroll.verticalScrollBar().value()
        sections = synergy.recommend(
            self._commanders, self._pool,
            in_deck=self._in_deck if self.hide_check.isChecked() else (),
            owned_only=self.owned_check.isChecked(), max_price=self.price_input.value() or None,
            staples=self.staples_check.isChecked(),
            # The Collector's Edition of a precon has the same cards, so the shortest name does
            precon_title=f"From {min(self._precons, key=len)}" if self._precons else "From the Precon",
            more=self._more)

        while self.page_layout.count():
            item = self.page_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for title, rows, hidden in sections:
            self.page_layout.addWidget(_Section(title, rows, hidden, self.lightweight, self))
        self.page_layout.addStretch()
        # Adding a card re-renders the page; stay where the user was
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(scroll))

        shown = sum(len(rows) for _, rows, _ in sections)
        if self._themes:
            text = f"{shown} cards for " + ", ".join(synergy.theme(k).label for k in self._themes)
        else:
            text = f"{shown} cards. Pick a theme above to see the cards with the most synergy"
        if self._missing:
            text += ("  ·  Working offline, so Scryfall's card tags aren't used" if scryfall.offline
                     else "  ·  Fetching Scryfall's card tags to sharpen these…")
        self.status.setText(text + "  ·  Double-click a card to add it, right-click for more.")
