"""
The Rules window: every official rules document, categorized and searchable, readable
offline once downloaded (see rules.py).

Left, the categories: the Comprehensive Rules (by section and chapter) and its
glossary, the rules of each format (with its banned list from the card database),
the tournament documents, and card rulings. Right, the page. Rule numbers anywhere
("see rule 702.19") are links. On the Card Rulings page, add one card or several to
see their text, the rules for their keywords and their official rulings side by side:
the rules that come up when those cards meet.

Ask a Rules Question takes a question in plain English and gathers, all offline: the
verified rulings from the library (rules_library.json) that match it, the Game
Concepts guides for the systems it touches (APNAP, layers, combat…), the cards it
names with their rulings, and the rules that govern it. No AI: every answer shown is
either a checked ruling or the official text.
"""

# Imports
import html
import re
from datetime import date

from PySide6.QtCore import Qt, QEvent, QStringListModel, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter, QTreeWidget,
    QTreeWidgetItem, QTextBrowser, QProgressBar, QStackedWidget, QCompleter, QPlainTextEdit, QButtonGroup,
)

import background
import database as db
import finance
import formats
import rules
import scryfall

ROLE = Qt.ItemDataRole.UserRole
# How closely a verified ruling has to match a question to be given as its answer; a looser
# match is offered as "the closest verified ruling"
CONFIDENT_MATCH = 0.45
SIMPLE, NERDS = "simple", "nerds"
SEARCH_RESULTS = 150
PAGE_STYLE = """
<style>
  body { font-size: 14px; }
  h1 { font-size: 22px; margin-bottom: 4px; }
  h2 { font-size: 17px; margin-top: 18px; }
  .id { font-weight: bold; }
  .example { color: #555; font-style: italic; margin-left: 24px; }
  .muted { color: gray; }
  .ruling { margin: 6px 0; }
  a { color: #5e35b1; text-decoration: none; }
</style>
"""

# Formats with rules of their own beyond deck construction: (document, Comprehensive Rules chapter)
FORMAT_SOURCES = {"commander": ("commander", "903"), "brawl": ("brawl", None),
                  "oathbreaker": ("oathbreaker", None)}

# Parsed once, and again after an update
_cr = None
_parts = {}


def comprehensive_rules():
    global _cr
    if _cr is None and rules.text("cr"):
        _cr = rules.parse_cr(rules.text("cr"))
    return _cr


def document_parts(key):
    if key not in _parts and rules.text(key):
        _parts[key] = rules.parse_numbered(rules.text(key))
    return _parts.get(key, [])


_library = None
_card_names = None


def library():
    # The verified guides and interactions (rules_library.json), read once
    global _library
    if _library is None:
        _library = rules.load_library()
    return _library


def card_names():
    global _card_names
    if _card_names is None:
        _card_names = db.card_name_list()
    return _card_names


def forget_parsed():
    global _cr, _card_names
    _cr = None
    _card_names = None
    _parts.clear()


def link_rules(text):
    """Escapes text for the page and turns rule numbers into links: "rule 702.19",
    "see rule 903", and bare rule ids like "100.2a"."""
    escaped = html.escape(text)
    escaped = re.sub(r"\b(\d{3}\.\d+[a-z]?)\b", r'<a href="rule:\1">\1</a>', escaped)
    escaped = re.sub(r"\b((?:rules?|section) )(\d{3})\b(?!\.\d)", r'\1<a href="rule:\2">\2</a>', escaped)
    return escaped.replace("\n", "<br>")


def _paragraphs(text):
    return "".join(f"<p>{link_rules(p)}</p>" for p in text.split("\n") if p.strip())


def _update_everything(progress=None):
    # The rules documents and card rulings, plus the card database when rulings can't be
    # matched to cards without it (it has to know each card's Scryfall oracle id)
    changed, errors = rules.update(progress)
    bulk = None
    if not db.has_card_database() or db.card_database_outdated():
        step = (lambda value: progress(("Downloading the card database…", *value))) if progress else None
        bulk = finance.update_market(None, None, history=False, progress=step).get("bulk")
        changed.append("Card database")
    return changed, errors, bulk


class RulesWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Rules")
        self.resize(1300, 850)
        self.settings = finance._settings()
        self._cards = []  # names on the Card Rulings page
        self._updating = False

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search every rule, glossary term and tournament document…")
        self.search_input.setClearButtonEnabled(True)
        self._search_timer = QTimer(self, singleShot=True, interval=350)
        self._search_timer.timeout.connect(self.search)
        self.search_input.textChanged.connect(lambda _: self._search_timer.start())
        self.update_button = QPushButton("Check for Updates")
        self.update_button.setToolTip("Download new versions of the rules and card rulings")
        self.update_button.clicked.connect(lambda: self.update_rules())
        top = QHBoxLayout()
        top.addWidget(self.search_input, stretch=1)
        top.addWidget(self.update_button)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(lambda item, _: item and self.show_item(item))

        self.page = QTextBrowser()
        self.page.setOpenLinks(False)
        self.page.anchorClicked.connect(self.open_link)

        # Card Rulings: a card box above its own page
        self.card_input = QLineEdit()
        self.card_input.setPlaceholderText("Card name… (add several to see how they interact)")
        self._names = QStringListModel(self)
        completer = QCompleter(self._names, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        completer.activated.connect(self.add_card)
        self.card_input.setCompleter(completer)
        self.card_input.textEdited.connect(self._suggest)
        self.card_input.returnPressed.connect(lambda: self.add_card(self.card_input.text()))
        add_button = QPushButton("Add Card")
        add_button.clicked.connect(lambda: self.add_card(self.card_input.text()))
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(lambda: (self._cards.clear(), self.show_cards()))
        card_row = QHBoxLayout()
        card_row.addWidget(self.card_input, stretch=1)
        card_row.addWidget(add_button)
        card_row.addWidget(clear_button)
        self.card_page = QTextBrowser()
        self.card_page.setOpenLinks(False)
        self.card_page.anchorClicked.connect(self.open_link)
        cards = QWidget()
        cards_layout = QVBoxLayout(cards)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.addLayout(card_row)
        cards_layout.addWidget(self.card_page)

        self.pages = QStackedWidget()
        self.pages.addWidget(self.page)
        self.pages.addWidget(cards)

        # Ask a Rules Question: a question box above its own page
        self.question_input = QPlainTextEdit()
        self.question_input.setPlaceholderText(
            "Ask a rules question in plain English, e.g. “I attack with a first striker and have a creature "
            "with ninjutsu in hand. Does the Ninja deal combat damage?” Name cards with their capitals.")
        self.question_input.setFixedHeight(72)
        self.question_input.setTabChangesFocus(True)
        self.question_input.installEventFilter(self)  # Enter looks it up
        ask_button = QPushButton("Look It Up")
        ask_button.setToolTip("Or press Enter (Shift+Enter for a new line)")
        ask_button.clicked.connect(self.ask)
        # Simple Judge: just the answer, with the explanation a click away.
        # Rules for Nerds: the answer with everything behind it shown underneath.
        self.simple_button = QPushButton("Simple Judge")
        self.simple_button.setToolTip("Just the answer; open the explanation and rulings when you want them")
        self.nerds_button = QPushButton("Rules for Nerds")
        self.nerds_button.setToolTip("The answer plus every ruling, guide, card and rule behind it")
        modes = QButtonGroup(self)
        for button, mode in ((self.simple_button, SIMPLE), (self.nerds_button, NERDS)):
            button.setCheckable(True)
            modes.addButton(button)
            button.clicked.connect(lambda _, mode=mode: self.set_mode(mode))
        self._mode = self.settings.value("rules_ask_mode", SIMPLE)
        (self.nerds_button if self._mode == NERDS else self.simple_button).setChecked(True)
        self._answer = self._details = ""
        self._show_details = False
        side = QVBoxLayout()
        side.addWidget(ask_button)
        side.addWidget(self.simple_button)
        side.addWidget(self.nerds_button)
        side.addStretch()
        ask_row = QHBoxLayout()
        ask_row.addWidget(self.question_input, stretch=1)
        ask_row.addLayout(side)
        self.ask_page = QTextBrowser()
        self.ask_page.setOpenLinks(False)
        self.ask_page.anchorClicked.connect(self.open_link)
        ask = QWidget()
        ask_layout = QVBoxLayout(ask)
        ask_layout.setContentsMargins(0, 0, 0, 0)
        ask_layout.addLayout(ask_row)
        ask_layout.addWidget(self.ask_page, stretch=1)  # the answer gets the room, not the question box
        self.pages.addWidget(ask)

        splitter = QSplitter()
        splitter.addWidget(self.tree)
        splitter.addWidget(self.pages)
        splitter.setSizes([330, 970])

        self.status = QLabel()
        self.status.setStyleSheet("color: gray;")
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(240)
        self.progress.hide()
        bottom = QHBoxLayout()
        bottom.addWidget(self.status, stretch=1)
        bottom.addWidget(self.progress)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(splitter, stretch=1)
        layout.addLayout(bottom)

        self.build_tree()
        if rules.due() and not scryfall.offline:
            self.update_rules()

    # Categories

    def build_tree(self):
        forget_parsed()
        self.tree.clear()

        def add(parent, text, data, tooltip=""):
            item = QTreeWidgetItem([text])
            item.setData(0, ROLE, data)
            item.setToolTip(0, tooltip)
            (parent.addChild if parent else self.tree.addTopLevelItem)(item)
            return item

        cr = comprehensive_rules()
        add(None, "Ask a Rules Question", ("ask",),
            "Matching verified rulings, the game concepts involved, and the rules that apply")
        home = add(None, "About These Rules", ("home",))
        top = add(None, "Comprehensive Rules", ("home",), rules.DOCUMENTS["cr"][1])
        if cr:
            for section in cr.sections:
                section_item = add(top, f"{section.number}. {section.title}", ("section", section.number))
                for chapter in section.chapters:
                    add(section_item, f"{chapter.number}. {chapter.title}", ("chapter", chapter.number))
            glossary = add(top, "Glossary", ("glossary", ""))
            for letter in sorted({term[0].upper() for term, _ in cr.glossary if term[:1].isalpha()}):
                add(glossary, letter, ("glossary", letter))

        concepts_item = add(None, "Game Concepts", ("concepts",), "Plain-English guides to how interactions work")
        for index, guide in enumerate(library()["concepts"]):
            add(concepts_item, guide["title"], ("concept", index))
        interactions_item = add(None, "Verified Interactions", ("interactions", None),
                                "Checked answers to common and tricky interactions")
        for topic in dict.fromkeys(entry["topic"] for entry in library()["interactions"]):
            add(interactions_item, topic, ("interactions", topic))

        formats_item = add(None, "Formats", ("formats",))
        for key, fmt in formats.FORMATS.items():
            if key != "casual":
                add(formats_item, fmt.label + (" (Arena)" if fmt.arena else ""), ("format", key))
        for name, chapter in rules.CR_FORMATS.items():
            if name != "Commander":
                add(formats_item, f"{name} (variant)", ("chapter", chapter))

        tournament = add(None, "Tournament Rules", ("tournament",))
        for key in ("mtr", "ipg", "jar"):
            doc_item = add(tournament, rules.DOCUMENTS[key][0], ("document", key, None), rules.DOCUMENTS[key][1])
            for index, part in enumerate(document_parts(key)):
                if part.heading and "." not in part.heading:  # sections and appendices; subsections are on their page
                    add(doc_item, f"{part.heading}. {part.title}", ("document", key, index))

        add(None, "Card Rulings", ("cards",), "Official rulings for any card, and the rules for its keywords")
        self.tree.expandItem(top)
        self.tree.setCurrentItem(home)

    def show_item(self, item):
        kind, *args = item.data(0, ROLE)
        if kind == "cards":
            self.pages.setCurrentIndex(1)
            self.show_cards()
            return
        if kind == "ask":
            self.pages.setCurrentIndex(2)
            if not self.ask_page.toPlainText():
                self.ask_page.setHtml(PAGE_STYLE + self.ask_intro())
            self.question_input.setFocus()
            return
        page = {"home": self.home_page, "section": self.section_page, "chapter": self.chapter_page,
                "glossary": self.glossary_page, "format": self.format_page, "document": self.document_page,
                "formats": self.formats_page, "tournament": self.tournament_page, "concepts": self.concepts_page,
                "concept": self.concept_page, "interactions": self.interactions_page}[kind](*args)
        self.show_page(page)

    def show_page(self, page):
        self.pages.setCurrentIndex(0)
        self.page.setHtml(PAGE_STYLE + page)

    # Pages

    def home_page(self):
        rows = []
        for key, (title, about) in rules.DOCUMENTS.items():
            version = rules.fetched(key)
            state = (f"checked {version[1]}" if version and rules.text(key) else "not downloaded yet")
            rows.append(f"<li><b>{title}</b>: {about}. <span class='muted'>({state})</span></li>")
        rulings = rules.fetched("rulings")
        rows.append(f"<li><b>Card rulings</b>: official rulings for every card, from Scryfall. "
                    f"<span class='muted'>({'checked ' + rulings[1] if rulings else 'not downloaded yet'})</span></li>")
        cr = comprehensive_rules()
        count = (f"<p>{sum(len(c.rules) for s in cr.sections for c in s.chapters):,} rules and "
                 f"{len(cr.glossary):,} glossary terms. {html.escape(cr.effective)}</p>") if cr else ""
        return (f"<h1>Magic: The Gathering Rules</h1>{count}<ul>{''.join(rows)}</ul>"
                "<p class='muted'>Everything here is kept on this computer, so it works offline. New versions "
                "are checked for once a week, or with Check for Updates. The Comprehensive Rules and tournament "
                "documents are © Wizards of the Coast; card rulings come from Scryfall.</p>")

    def section_page(self, number):
        section = next(s for s in comprehensive_rules().sections if s.number == number)
        chapters = "".join(f"<li><a href='rule:{c.number}'>{c.number}. {html.escape(c.title)}</a></li>"
                           for c in section.chapters)
        return f"<h1>{number}. {html.escape(section.title)}</h1><ul>{chapters}</ul>"

    def chapter_page(self, number):
        cr = comprehensive_rules()
        chapter = cr.chapter(number) if cr else None
        if chapter is None:
            return "<p class='muted'>The Comprehensive Rules haven't been downloaded yet.</p>"
        body = [f"<h1>{number}. {html.escape(chapter.title)}</h1>"]
        for rule in chapter.rules:
            body.append(f"<p><a name='{rule.id}'></a><span class='id'>{rule.id}</span> {link_rules(rule.text)}</p>")
            body += [f"<p class='example'>{link_rules(example)}</p>" for example in rule.examples]
        return "".join(body)

    def glossary_page(self, letter):
        terms = [(t, d) for t, d in comprehensive_rules().glossary if not letter or t[:1].upper() == letter]
        return (f"<h1>Glossary{' — ' + letter if letter else ''}</h1>"
                + "".join(f"<p><a name='{html.escape(t)}'></a><b>{html.escape(t)}</b><br>{link_rules(d)}</p>"
                          for t, d in terms))

    def formats_page(self):
        return ("<h1>Formats</h1><p>Each format's deck rules and banned list (from the card database), "
                "and the full rules for formats that have their own: Commander, Brawl and Oathbreaker. The casual "
                "variants (Two-Headed Giant, Planechase, Archenemy…) come from section 9 of the Comprehensive "
                "Rules.</p>")

    def format_page(self, key):
        fmt = formats.FORMATS[key]
        body = [f"<h1>{html.escape(fmt.label)}</h1>"]
        deck = [f"Decks have {'exactly' if fmt.exact else 'at least'} {fmt.deck_size} cards"
                + (", including the commander" if fmt.commander else "") + "."]
        if fmt.copies:
            deck.append("No more than one copy of any card other than basic lands." if fmt.copies == 1 else
                        f"No more than {fmt.copies} copies of any card other than basic lands.")
        if fmt.sideboard:
            deck.append(f"Sideboards have up to {fmt.sideboard} cards.")
        if fmt.commander:
            deck.append("Every card must fit within the commander's color identity.")
        if fmt.arena:
            deck.append("Played on MTG Arena.")
        body.append("<h2>Deck Construction</h2><p>" + " ".join(deck) + "</p>")

        doc, chapter = FORMAT_SOURCES.get(key, (None, None))
        cr = comprehensive_rules()
        if chapter and cr and cr.chapter(chapter):
            body.append(f"<p>Comprehensive Rules: <a href='rule:{chapter}'>{chapter}. "
                        f"{html.escape(cr.chapter(chapter).title)}</a></p>")
        if doc and rules.text(doc):
            body.append(f"<h2>{html.escape(rules.DOCUMENTS[doc][1])}</h2>{_paragraphs(rules.text(doc))}")

        if not db.has_card_database():
            body.append("<p class='muted'>The banned list comes from the card database, which hasn't been "
                        "downloaded yet.</p>")
        for status, title in (("banned", "Banned"), ("restricted", "Restricted (one copy)")):
            names = db.cards_with_legality(key, status)
            if names:
                cards = ", ".join(f"<a href='card:{html.escape(n)}'>{html.escape(n)}</a>" for n in names)
                body.append(f"<h2>{title} ({len(names)})</h2><p>{cards}</p>")
        return "".join(body)

    def tournament_page(self):
        return "<h1>Tournament Rules</h1>" + "".join(
            f"<p><b>{rules.DOCUMENTS[key][0]}</b>: {rules.DOCUMENTS[key][1]}.</p>" for key in ("mtr", "ipg", "jar"))

    def document_page(self, key, index):
        parts = document_parts(key)
        if not parts:
            return f"<p class='muted'>The {rules.DOCUMENTS[key][0]} hasn't been downloaded yet.</p>"
        if index is None:  # the whole document's contents, or the document itself if it has no sections
            items = "".join(f"<li><a href='doc:{key}:{i}'>{p.heading} {html.escape(p.title)}</a></li>"
                            for i, p in enumerate(parts) if p.heading)
            if not items:
                return f"<h1>{rules.DOCUMENTS[key][0]}</h1>" + "".join(_paragraphs(p.text) for p in parts)
            return f"<h1>{rules.DOCUMENTS[key][0]}</h1><p>{rules.DOCUMENTS[key][1]}.</p><ul>{items}</ul>"
        # A section and its subsections, up to the next top-level section
        body = []
        for part in parts[index:]:
            if body and part.heading and "." not in part.heading:
                break
            level = "h1" if "." not in part.heading else "h2"
            body.append(f"<{level}>{part.heading} {html.escape(part.title)}</{level}>" + _paragraphs(part.text))
        return "".join(body)

    def concepts_page(self):
        items = "".join(f"<li><a href='concept:{i}'><b>{html.escape(g['title'])}</b></a>: "
                        f"{html.escape(g['summary'][0])}</li>" for i, g in enumerate(library()["concepts"]))
        return ("<h1>Game Concepts</h1><p>Plain-English guides to the systems behind most interactions, each "
                f"with the official rules it's based on.</p><ul>{items}</ul>")

    def concept_page(self, index):
        guide = library()["concepts"][index]
        body = [f"<h1>{html.escape(guide['title'])}</h1>"] + [f"<p>{link_rules(p)}</p>" for p in guide["summary"]]
        cr = comprehensive_rules()
        if cr:
            body.append("<h2>The official rules</h2>")
            for ref in guide["rules"]:
                for rule in rules.rules_for_ref(cr, ref):
                    body.append(f"<p><span class='id'><a href='rule:{rule.id}'>{rule.id}</a></span> "
                                f"{link_rules(rule.text)}</p>")
        return "".join(body)

    def interactions_page(self, topic):
        entries = [e for e in library()["interactions"] if topic in (None, e["topic"])]
        return (f"<h1>{html.escape(topic or 'Verified Interactions')}</h1><p class='muted'>Checked answers, each "
                "with the rules that settle it.</p>" + "".join(self._interaction(e) for e in entries))

    def _interaction(self, entry, note=""):
        links = ", ".join(f"<a href='rule:{r}'>{r}</a>" for r in entry["rules"])
        return (f"<p><b>Q:</b> {html.escape(entry['question'])}<br><b>A: {html.escape(entry['answer'])}.</b> "
                f"{link_rules(entry['explanation'])}<br><span class='muted'>{note}Rules: {links}</span></p>")

    # Ask a Rules Question

    def ask_intro(self):
        return ("<h1>Ask a Rules Question</h1><p>Type a question above and choose Look It Up. You'll get:</p><ul>"
                "<li><b>Verified rulings</b> that match it, with checked answers</li>"
                "<li>The <b>game concepts</b> it involves (the stack, APNAP, layers, combat…), explained</li>"
                "<li>The <b>cards</b> you name, with their official rulings</li>"
                "<li>The <b>rules</b> that govern it, straight from the Comprehensive Rules</li></ul>"
                "<p><b>Simple Judge</b> shows just the answer, with the explanation a click away. <b>Rules for "
                "Nerds</b> shows the answer with everything behind it underneath.</p>"
                "<p class='muted'>Press Enter to look it up (Shift+Enter for a new line). Everything works offline. "
                "Name cards with their capital letters (Blood Artist, not blood artist) so they're recognized.</p>")

    def eventFilter(self, watched, event):
        # Enter in the question box looks it up; Shift+Enter starts a new line
        if (watched is self.question_input and event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.ask()
            return True
        return super().eventFilter(watched, event)

    def set_mode(self, mode):
        self._mode = mode
        self.settings.setValue("rules_ask_mode", mode)
        self._show_details = mode == NERDS
        self.show_answer()

    def show_answer(self):
        if not self._answer:
            return
        if self._mode == NERDS:
            details = self._details
        else:
            label = "▾ Hide the explanation and rulings" if self._show_details else "▸ See the explanation and rulings"
            details = f"<p><a href='toggle:details'><b>{label}</b></a></p>"
            if self._show_details:
                details += self._details
        self.ask_page.setHtml(PAGE_STYLE + self._answer + details)

    def _answer_card(self, heading, verdict, body):
        # The answer, set apart from everything else on the page (in light or dark mode)
        dark = self.palette().base().color().lightness() < 128
        background, accent = ("#2e2540", "#b39ddb") if dark else ("#ede7f6", "#5e35b1")
        verdict = f"<p style='font-size:24px; margin:4px 0'><b>{verdict}</b></p>" if verdict else ""
        return (f"<table width='100%' cellpadding='14' cellspacing='0' style='background-color:{background}; "
                f"margin-top:6px'><tr><td><p style='color:{accent}; font-size:12px; margin:0'><b>{heading}</b></p>"
                f"{verdict}{body}</td></tr></table>")

    def ask(self):
        question = self.question_input.toPlainText().strip()
        if not question:
            return
        self.pages.setCurrentIndex(2)
        cr = comprehensive_rules()
        if cr is None:
            self.ask_page.setHtml(PAGE_STYLE + "<p class='muted'>The rules haven't been downloaded yet. Use Check "
                                  "for Updates while you're online.</p>")
            return
        terms = [term for term, _ in cr.glossary] + list(cr.keywords())
        cards = [(name, db.card_info(name)["oracle_text"], [r["comment"] for r in db.card_rulings(name)])
                 for name in rules.mentioned_cards(question, card_names(), terms)]
        matches = rules.similar_interactions(question, library())
        guides = rules.guides_for(question + "\n" + "\n".join(text or "" for _, text, _ in cards), library())
        passages = [p for p in rules.find_rules(question, cr, cards, budget=24000) if p.kind in ("rule", "glossary")]

        index_of = {g["title"]: i for i, g in enumerate(library()["concepts"])}
        concept_links = ", ".join(f"<a href='concept:{index_of[g['title']]}'>{html.escape(g['title'])}</a>"
                                  for g in guides[:3])
        if matches and matches[0][0] >= CONFIDENT_MATCH:
            entry = matches[0][1]
            rule_links = ", ".join(f"<a href='rule:{r}'>{r}</a>" for r in entry["rules"])
            card = self._answer_card("ANSWER", html.escape(entry["answer"]) + ".",
                                     f"<p>{link_rules(entry['explanation'])}</p>"
                                     f"<p class='muted'>From a verified ruling · Rules: {rule_links}</p>")
        elif matches:
            entry = matches[0][1]
            card = self._answer_card("CLOSEST VERIFIED RULING", "",
                                     "<p>This may not be exactly your situation. The closest checked ruling is:</p>"
                                     f"<p><i>{html.escape(entry['question'])}</i></p>"
                                     f"<p><b>{html.escape(entry['answer'])}.</b> {link_rules(entry['explanation'])}</p>")
        else:
            card = self._answer_card("NO VERIFIED ANSWER YET", "",
                                     "<p>There's no checked ruling for this situation in the library yet, so the app "
                                     "can't give a yes or no. "
                                     + (f"What decides it: {concept_links}. " if concept_links else "")
                                     + "The explanation below gathers the guides, cards and rules for it.</p>")
        self._answer = f"<h2 style='margin-bottom:0'>{html.escape(question)}</h2>" + card

        body = []
        if matches[1:]:
            body.append("<h2>Other verified rulings that may help</h2>")
            body += [self._interaction(entry, f"{round(score * 100)}% match · ") for score, entry in matches[1:]]
        if guides:
            body.append("<h2>Game concepts involved</h2>")
            for guide in guides[:4]:
                body.append(f"<h3><a href='concept:{index_of[guide['title']]}'>{html.escape(guide['title'])}</a></h3>"
                            + "".join(f"<p>{link_rules(p)}</p>" for p in guide["summary"]))
        if cards:
            body.append("<h2>Cards</h2>")
            for name, text, rulings in cards:
                body.append(f"<h3>{html.escape(name)}</h3><p>{link_rules(text or '')}</p>"
                            + "".join(f"<p class='ruling'><span class='muted'>Ruling:</span> {link_rules(r)}</p>"
                                      for r in rulings))
        body.append("<h2>Rules that apply</h2>")
        groups = {}
        for passage in passages:
            groups.setdefault(passage.why, []).append(passage)
        for why, group in groups.items():
            body.append(f"<h3>{html.escape(why)}</h3>")
            for p in group:
                label = (f"<a href='rule:{p.ref}' class='id'>{p.ref}</a>" if p.kind == "rule"
                         else f"<b>Glossary: {html.escape(p.ref)}</b>")
                body.append(f"<p>{label} {link_rules(p.text)}</p>")
        body.append("<p class='muted'>Verified rulings are checked answers. Everything else here is the official "
                    "text, gathered for your question: read it to decide, or ask a judge at a sanctioned event.</p>")
        self._details = "".join(body)
        self._show_details = self._mode == NERDS
        self.show_answer()

    # Links

    def open_link(self, url):
        kind, _, value = url.toString().partition(":")
        if kind == "rule":
            self.select_tree(("chapter", value[:3]))
            if "." in value:
                QTimer.singleShot(0, lambda: self.page.scrollToAnchor(value))
        elif kind == "gloss":
            self.select_tree(("glossary", value[:1].upper()))
            QTimer.singleShot(0, lambda: self.page.scrollToAnchor(value))
        elif kind == "format":
            self.select_tree(("format", value))
        elif kind == "concept":
            self.select_tree(("concept", int(value)))
        elif kind == "toggle":
            self._show_details = not self._show_details
            self.show_answer()
        elif kind == "card":
            self.add_card(value)
            self.select_tree(("cards",))
        elif kind == "doc":
            key, index = value.split(":")
            if not self.select_tree(("document", key, int(index))):
                self.show_page(self.document_page(key, int(index)))  # a subsection: no entry of its own

    def select_tree(self, data):
        # Selects the category with this data (which shows its page); False if there's none
        items = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while items:
            item = items.pop(0)
            if item.data(0, ROLE) == data:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                return True
            items += [item.child(i) for i in range(item.childCount())]
        return False

    # Search

    def search(self):
        needle = self.search_input.text().strip()
        if len(needle) < 3:
            return
        words = needle.lower().split()
        results = []

        def hit(text):
            text = text.lower()
            return all(word in text for word in words)

        def snippet(text):
            at = max(0, text.lower().find(words[0]) - 80)
            return ("…" if at else "") + text[at:at + 260] + ("…" if len(text) > at + 260 else "")

        cr = comprehensive_rules()
        if cr:
            for term, definition in cr.glossary:
                if hit(term + " " + definition):
                    results.append(f"<p><b>Glossary: <a href='gloss:{html.escape(term)}'>{html.escape(term)}</a></b>"
                                   f"<br>{link_rules(snippet(definition))}</p>")
            for section in cr.sections:
                for chapter in section.chapters:
                    for rule in chapter.rules:
                        if rule.id.startswith(needle) or hit(rule.text + " " + " ".join(rule.examples)):
                            results.append(f"<p><a href='rule:{rule.id}' class='id'>{rule.id}</a> "
                                           f"<span class='muted'>({html.escape(chapter.title)})</span><br>"
                                           f"{link_rules(snippet(rule.text))}</p>")
        for key in ("mtr", "ipg", "jar"):
            for index, part in enumerate(document_parts(key)):
                if hit(part.title + " " + part.text):
                    results.append(f"<p><a href='doc:{key}:{index}'><b>{rules.DOCUMENTS[key][0]} "
                                   f"{part.heading} {html.escape(part.title)}</b></a><br>"
                                   f"{link_rules(snippet(part.text))}</p>")
        for key in ("commander", "brawl", "oathbreaker"):
            if rules.text(key) and hit(rules.text(key)):
                results.append(f"<p><a href='format:{key}'><b>{rules.DOCUMENTS[key][0]} format rules</b></a><br>"
                               f"{link_rules(snippet(rules.text(key)))}</p>")
        found = [(i, g) for i, g in enumerate(library()["concepts"]) if hit(g["title"] + " " + " ".join(g["summary"]))]
        interactions = [e for e in library()["interactions"] if hit(e["question"] + " " + e["explanation"])]
        results = ([f"<p><a href='concept:{i}'><b>Game Concept: {html.escape(g['title'])}</b></a><br>"
                    f"{link_rules(snippet(' '.join(g['summary'])))}</p>" for i, g in found]
                   + [self._interaction(e) for e in interactions] + results)
        shown = results[:SEARCH_RESULTS]
        more = f" (showing the first {SEARCH_RESULTS})" if len(results) > SEARCH_RESULTS else ""
        self.tree.setCurrentItem(None)
        self.show_page(f"<h1>“{html.escape(needle)}”</h1><p class='muted'>{len(results)} matches{more}</p>"
                       + ("".join(shown) or "<p>Nothing matches.</p>"))

    # Card Rulings

    def _suggest(self, text):
        self._names.setStringList(db.card_names(text.strip()) if len(text.strip()) >= 2 else [])

    def add_card(self, name):
        info = db.card_info(name.strip())
        if info is None:
            matches = db.card_names(name.strip(), limit=1)
            info = db.card_info(matches[0]) if matches else None
        if info is None:
            self.status.setText(f"No card named “{name}” in the card database.")
            return
        if info["name"] not in self._cards:
            self._cards.append(info["name"])
        self.card_input.clear()
        self.show_cards()

    def show_cards(self):
        cr = comprehensive_rules()
        keywords = cr.keywords() if cr else {}
        if not self._cards:
            note = "" if db.has_rulings() else ("<p class='muted'>Card rulings download with the rules "
                                                 "(Check for Updates).</p>")
            self.card_page.setHtml(PAGE_STYLE + "<h1>Card Rulings</h1><p>Type a card's name above to see its "
                                   "official rulings and the rules for its keywords. Add more cards to see "
                                   "them side by side, with the rules that come up between them.</p>" + note)
            return
        body, shared = [], {}
        for name in self._cards:
            info = db.card_info(name)
            found = rules.keyword_rules(info["oracle_text"], keywords)
            for keyword, rule_id in found:
                shared.setdefault(rule_id, (keyword, []))[1].append(name)
            body.append(f"<h1>{html.escape(name)}</h1><p class='muted'>{html.escape(info['mana_cost'] or '')} "
                        f"{html.escape(info['type_line'] or '')}</p><p>{link_rules(info['oracle_text'] or '')}</p>")
            if found:
                body.append("<h2>Rules for its keywords</h2>" + "".join(
                    self._keyword_rule(cr, keyword, rule_id) for keyword, rule_id in found))
            rulings = db.card_rulings(name)
            body.append(f"<h2>Official rulings ({len(rulings)})</h2>" + ("".join(
                f"<p class='ruling'><span class='muted'>{r['published'] or ''}</span> {link_rules(r['comment'])}</p>"
                for r in rulings) or "<p class='muted'>No rulings for this card.</p>"))
        if len(self._cards) > 1:
            common = [(rule_id, keyword, names) for rule_id, (keyword, names) in shared.items() if len(names) > 1]
            terms = rules.shared_terms([db.card_info(n)["oracle_text"] for n in self._cards],
                                       cr.glossary if cr else [])
            summary = ["<h1>Between these cards</h1>"]
            if common:
                summary.append("<h2>Keywords they share</h2>" + "".join(
                    f"<p><a href='rule:{rule_id}' class='id'>{rule_id}</a> {html.escape(keyword.title())}: "
                    f"{html.escape(', '.join(names))}</p>" for rule_id, keyword, names in common))
            if terms:
                summary.append("<h2>Rules terms they both use</h2><p class='muted'>Where their rules text "
                               "overlaps, and the rules that govern it:</p>" + "".join(
                                   f"<p><b>{html.escape(term)}</b> ({count} of {len(self._cards)} cards): "
                                   f"{link_rules(definition)}</p>" for term, definition, count in terms))
            if not common and not terms:
                summary.append("<p class='muted'>No keywords or rules terms in common. Each card's rules and "
                               "rulings are below.</p>")
            body.insert(0, "".join(summary))
        self.card_page.setHtml(PAGE_STYLE + "".join(body))

    def _keyword_rule(self, cr, keyword, rule_id):
        # The keyword's rule and its first part: 702.85 Cascade: Cascade is a triggered ability…
        chapter = cr.chapter(rule_id[:3])
        first = next((r for r in chapter.rules if r.id.startswith(rule_id) and r.id != rule_id), None)
        text = link_rules(first.text) if first else ""
        return f"<p><a href='rule:{rule_id}' class='id'>{rule_id}</a> <b>{html.escape(keyword.title())}</b>: {text}</p>"

    # Updating

    def update_rules(self):
        if self._updating:
            return
        if scryfall.offline:
            self.status.setText("Offline mode is on (File → Work Offline), so nothing is downloaded.")
            return
        self._updating = True
        self.update_button.setEnabled(False)
        self.status.setText("Checking for new versions of the rules…")
        background.run(_update_everything, on_success=self._on_updated, on_error=self._on_update_failed,
                       on_progress=self._on_progress)

    def _on_progress(self, value):
        label, done, total = value
        self.status.setText(label)
        self.progress.show()
        self.progress.setValue(min(99, done * 100 // max(total, 1)))

    def _on_updated(self, result):
        changed, errors, bulk = result
        self._finish()
        if bulk:  # the card database came along; the deck builder and Finance needn't fetch it again
            self.settings.setValue("finance_bulk_updated", bulk)
            self.settings.setValue("carddb_checked", date.today().isoformat())
        if changed:
            current = self.tree.currentItem().data(0, ROLE) if self.tree.currentItem() else ("home",)
            self.build_tree()
            self.select_tree(current)
        message = f"Updated: {', '.join(changed)}." if changed else "The rules are up to date."
        if errors:
            message += "  Couldn't download " + "; ".join(errors)
        self.status.setText(message)

    def _on_update_failed(self, message):
        self._finish()
        self.status.setText(f"Couldn't check for new rules: {message}")

    def _finish(self):
        self._updating = False
        self.update_button.setEnabled(True)
        self.progress.hide()
