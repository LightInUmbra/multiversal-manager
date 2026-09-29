# The website's Rules page in the desktop layout: the desktop's Rules window (rules_window.py)
# in the website's style. Search along the top, the categories on the left, the page on the
# right. The pages are the phone's (rules_tab.py) where it has them; the rest are built here
# like the desktop's. The rules come with the website (rules.BUNDLED, see build_web.py),
# since browsers can't download them from Wizards of the Coast; card rulings, banned lists
# and the Game Changers come from Scryfall, which browsers can reach.
import flet as ft

import brackets
import formats
import rules
import rules_tab
import scryfall
import set_notes
import theme
from web_desktop import PAGE_PADDING

NAV_WIDTH = 330
# A format's own rules document and Comprehensive Rules chapter, as the desktop's FORMAT_SOURCES
FORMAT_DOCS = {"commander": "commander", "brawl": "brawl", "oathbreaker": "oathbreaker"}
FORMAT_CHAPTERS = {"commander": "903"}


def _heading(text, size=20):
    return ft.Text(text, font_family=theme.TITLE_FONT, size=size, weight=ft.FontWeight.W_700, color=theme.GOLD)


def _subheading(text):
    return ft.Text(text, size=15, weight=ft.FontWeight.W_700)


def _muted(text, size=12.5):
    return ft.Text(text, size=size, color=theme.MUTED)


def _labeled(label, text):
    return ft.Text(spans=[ft.TextSpan(label, ft.TextStyle(weight=ft.FontWeight.BOLD)), ft.TextSpan(text)], size=13)


class RulesPage(rules_tab.Rules):
    """The Rules page: every rules document to browse and search, Ask a Rules Question and
    Card Rulings, as the desktop has them. history holds the page showing and the pages
    opened from it (the Back arrow); picking a category starts it over, like the desktop."""

    def __init__(self, page, toast, busy):
        super().__init__(page, toast, busy)
        self.content = ft.ListView(expand=True, spacing=10, padding=ft.Padding.symmetric(horizontal=20, vertical=14))
        self.nav = ft.ListView(expand=True, spacing=0, padding=ft.Padding.symmetric(vertical=6))
        self.nav_items = {}   # category key -> its tile, to mark the one showing
        self.selected = None
        self.cards = []       # the names on the Card Rulings page
        self.card_data = {}   # name -> (card row, rulings), looked up once
        self.legal = {}       # (format, status) -> card names, from Scryfall
        search = ft.TextField(hint_text="Search every rule, glossary term, tournament document and set's notes…",
                              prefix_icon=ft.Icons.SEARCH, dense=True, expand=True,
                              on_submit=lambda e: self.search(e.control.value))
        self.version = _muted("")
        self.view = ft.Container(ft.Column([
            ft.Row([search, self.version], spacing=14),
            ft.Row([theme.panel(self.nav, width=NAV_WIDTH), theme.panel(self.content, expand=True)],
                   expand=True, spacing=14, vertical_alignment=ft.CrossAxisAlignment.STRETCH)],
            spacing=12, expand=True), padding=ft.Padding.symmetric(horizontal=PAGE_PADDING, vertical=16), expand=True)

    # Navigation

    def refresh(self):
        if not self.nav.controls:
            self.build_nav()
        (self.history[-1] if self.history else self.home)()

    def home(self):
        self.go("home", self.about_page)

    def go(self, key, show):
        # A category from the left: its page, starting the Back history over
        self.history = [show]
        if self.selected in self.nav_items:
            self.nav_items[self.selected].selected = False
        if key in self.nav_items:
            self.nav_items[key].selected = True
        self.selected = key
        show()

    def show(self, title, controls):
        back = ([ft.IconButton(ft.Icons.ARROW_BACK, tooltip="Back", on_click=lambda e: self.back())]
                if len(self.history) > 1 else [])
        self.content.controls = [*([ft.Row([*back, _heading(title)], spacing=4)] if title else []), *controls]
        self.page.update()

    def _sheet(self, body):
        # A rule over the page: a dialog, where the phone has a bottom sheet
        self.page.show_dialog(ft.AlertDialog(content=ft.Container(ft.Column(body, scroll=ft.ScrollMode.AUTO, tight=True),
                                                                  width=640), scrollable=True,
                                             actions=[theme.button("Close", lambda e: self.page.pop_dialog())]))

    def _link(self, text, show, subtitle=None):
        # A line on a page that opens another, with Back to return
        return ft.ListTile(title=ft.Text(text, size=13.5), subtitle=_muted(subtitle) if subtitle else None, dense=True,
                           on_click=lambda e: self.open(show))

    def build_nav(self):
        """The categories, as the desktop's tree: each group opens its overview and folds out
        its parts."""
        cr = self.cr()
        fetched = rules.fetched("cr")
        self.version.value = f"The rules as of {fetched[1]}, updated with every release of the website" if fetched else ""

        def item(key, text, show, indent=0):
            tile = ft.ListTile(title=ft.Text(text, size=13), dense=True, on_click=lambda e: self.go(key, show),
                               content_padding=ft.Padding.only(left=14 + 14 * indent, right=8),
                               selected_tile_color=theme.COLORS["primary_container"], selected_color=theme.GOLD)
            self.nav_items[key] = tile
            return tile

        def group(key, text, show, children, expanded=False):
            return ft.ExpansionTile(title=ft.Text(text, size=13.5, weight=ft.FontWeight.W_600), controls=children,
                                    expanded=expanded, dense=True, on_change=lambda e: self.go(key, show),
                                    controls_padding=ft.Padding.only(left=6))

        tree = [item("ask", "Ask a Rules Question", self.ask_page), item("home", "About These Rules", self.about_page)]
        if cr:
            sections = [group(f"section {s.number}", f"{s.number}. {s.title}", lambda s=s: self.section_page(s.number), [
                item(f"chapter {c.number}", f"{c.number}. {c.title}", lambda n=c.number: self.chapter_page(n), 1)
                for c in s.chapters]) for s in cr.sections]
            letters = sorted({t[:1].upper() for t, _ in cr.glossary if t[:1].isalpha()})
            glossary = group("glossary", "Glossary", self.glossary_page, [
                item(f"glossary {l}", l, lambda l=l: self.letter_page(l), 1) for l in letters])
            tree.append(group("cr", "Comprehensive Rules", self.sections_page, [*sections, glossary], expanded=True))
        library = self.library()
        tree.append(group("concepts", "Game Concepts", self.concepts_page, [
            item(f"concept {i}", g["title"], lambda i=i: self.concept_page(i), 1) for i, g in enumerate(library["concepts"])]))
        topics = list(dict.fromkeys(e["topic"] for e in library["interactions"]))
        tree.append(group("interactions", "Verified Interactions", lambda: self.interactions_page(None), [
            item(f"topic {t}", t, lambda t=t: self.interactions_page(t), 1) for t in topics]))
        format_items = []
        for key, fmt in formats.FORMATS.items():
            if key != "casual":
                format_items.append(item(f"format {key}", fmt.label + (" (Arena)" if fmt.arena else ""),
                                         lambda key=key: self.format_page(key), 1))
            if key == "commander":
                format_items.append(item("brackets", "Commander Brackets", self.brackets_page, 1))
        format_items += [item(f"variant {name}", f"{name} (variant)", lambda n=number: self.chapter_page(n), 1)
                         for name, number in rules.CR_FORMATS.items() if name != "Commander" and cr and cr.chapter(number)]
        tree.append(group("formats", "Formats", self.formats_overview, format_items))
        tournament = []
        for key in ("mtr", "ipg", "jar"):
            parts = [item(f"doc {key} {i}", f"{p.heading}. {p.title}", lambda key=key, i=i: self.document_page(key, i), 2)
                     for i, p in enumerate(self.parts(key)) if p.heading and "." not in p.heading]
            doc = rules.DOCUMENTS[key][0]
            tournament.append(group(f"doc {key}", doc, lambda key=key: self.contents_page(key), parts)
                              if parts else item(f"doc {key}", doc, lambda key=key: self.contents_page(key), 1))
        tree.append(group("tournament", "Tournament Rules", self.tournament_page, tournament))
        notes = set_notes.index()
        releases = sorted(((i, n) for i, n in notes.items() if n["kind"] in ("release", "faq")),
                          key=lambda p: p[1].get("date") or "", reverse=True)
        tree.append(group("notes", "Set Release Notes", self.notes_page, [
            item(f"note {i}", n["title"] + (f" ({n['date'][:4]})" if n.get("date") else ""),
                 lambda i=i: self.note_page(i), 1) for i, n in releases]))
        tree.append(group("wiki", "MTG Wiki", lambda: self.wiki_page(None), [
            item("wiki mechanic", "Mechanics", lambda: self.wiki_page("mechanic"), 1),
            item("wiki set", "Sets", lambda: self.wiki_page("set"), 1)]))
        tree.append(item("cards", "Card Rulings", self.cards_page))
        self.nav.controls = tree

    # Pages the phone doesn't have (the rest are rules_tab's)

    def about_page(self):
        cr = self.cr()
        if cr is None:
            self.show("Magic: The Gathering Rules", [ft.Text(
                "This copy of the website came without the rules. They're added when it's built (build_web.py).")])
            return
        lines = []
        for key, (title, about) in rules.DOCUMENTS.items():
            version = rules.fetched(key)
            state = f"checked {version[1]}" if version and rules.text(key) else "not included"
            lines.append(ft.Text(spans=[ft.TextSpan(title, ft.TextStyle(weight=ft.FontWeight.BOLD)),
                                        ft.TextSpan(f": {about}. "), ft.TextSpan(f"({state})", ft.TextStyle(color=theme.MUTED))],
                                 size=13.5))
        kinds = [n["kind"] for n in set_notes.index().values()]
        lines.append(ft.Text(f"Set release notes: {kinds.count('release') + kinds.count('faq')} sets' notes and FAQs from "
                             "Wizards of the Coast, back to Ice Age.", size=13.5))
        lines.append(ft.Text(f"MTG Wiki: {kinds.count('mechanic')} mechanic and {kinds.count('set')} set pages from the "
                             f"fan wiki ({set_notes.WIKI_LICENSE}).", size=13.5))
        rule_count = sum(len(c.rules) for s in cr.sections for c in s.chapters)
        self.show("Magic: The Gathering Rules", [
            ft.Text(f"{rule_count:,} rules and {len(cr.glossary):,} glossary terms. {cr.effective}", size=13.5), *lines,
            _muted("The rules come with the website and are brought up to date with every release. The Comprehensive "
                   "Rules and tournament documents are © Wizards of the Coast; card rulings come from Scryfall.")])

    def ask_page(self, question="", found=None):
        box = ft.TextField(value=question, multiline=True, min_lines=2, max_lines=5, shift_enter=True,
                           hint_text="Ask a rules question in plain English, e.g. “I attack with a first striker and "
                                     "have a creature with ninjutsu in hand. Does the Ninja deal combat damage?”",
                           on_submit=lambda e: self.ask(box.value))
        top = [box, ft.Row([theme.button("Look it up", lambda e: self.ask(box.value), primary=True),
                            _muted("Or press Enter (Shift+Enter for a new line). Card names can be typed any way.")],
                           spacing=12)]
        if found is None:
            top.append(_muted("You'll get a verified ruling when one matches, or an answer worked out from the rules "
                              "for combat, timing and state checks, then the guides, cards and rules behind it. No AI: "
                              "every answer is a checked ruling or the official text.", 13))
        self.show("Ask a Rules Question", top + (self.answer_controls(found) if found else []))

    def ask(self, question):
        question = (question or "").strip()
        if not question:
            return
        found = self.busy("Looking it up", lambda: rules_tab.ask.look_up(
            question, self.cr(), self.library(), self.card_names(), self.fetch_cards))
        if found:
            self.go("ask", lambda: self.ask_page(question, found))

    def section_page(self, number):
        section = next(s for s in self.cr().sections if s.number == number)
        self.show(f"{number}. {section.title}", [self._link(f"{c.number}. {c.title}", lambda n=c.number: self.chapter_page(n))
                                                 for c in section.chapters])

    def glossary_page(self):
        letters = sorted({t[:1].upper() for t, _ in self.cr().glossary if t[:1].isalpha()})
        self.show("Glossary", [ft.Row([ft.TextButton(l, on_click=lambda e, l=l: self.open(lambda: self.letter_page(l)))
                                       for l in letters], wrap=True)])

    def interactions_page(self, topic):
        entries = [e for e in self.library()["interactions"] if topic in (None, e["topic"])]
        self.show(topic or "Verified Interactions", [_muted("Checked answers, each with the rules that settle it."),
                                                     *[self._ruling(e) for e in entries]])

    def formats_overview(self):
        self.show("Formats", [ft.Text(
            "Each format's deck rules and banned list, and the full rules for formats that have their own: Commander, "
            "Brawl and Oathbreaker. The casual variants (Two-Headed Giant, Planechase, Archenemy…) come from section 9 of "
            "the Comprehensive Rules.", size=13.5)])

    def _legality(self, key, status):
        # The cards with this status in a format ("banned:modern"), from Scryfall, looked up once
        if (key, status) not in self.legal:
            def fetch():
                names, page = [], 1
                while True:
                    rows, more, _ = scryfall.search(f"{status}:{key}", page, "name", "asc")
                    names += [r["name"] for r in rows]
                    if not more:
                        return names
                    page += 1
            found = self.busy("Looking it up on Scryfall", fetch)
            if found is None:
                return None
            self.legal[(key, status)] = found
        return self.legal[(key, status)]

    def format_page(self, key):
        fmt = formats.FORMATS[key]
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
        controls = [_subheading("Deck Construction"), ft.Text(" ".join(deck), size=13.5)]
        chapter = FORMAT_CHAPTERS.get(key)
        if chapter and self.cr() and self.cr().chapter(chapter):
            controls.append(self._link(f"Comprehensive Rules {chapter}. {self.cr().chapter(chapter).title}",
                                       lambda: self.chapter_page(chapter)))
        if key == "commander":
            controls.append(self._link("Commander Brackets and the Game Changers", self.brackets_page))
        doc = FORMAT_DOCS.get(key)
        if doc and rules.text(doc):
            controls += [_subheading(rules.DOCUMENTS[doc][1]),
                         *[self.rich(p, size=13.5) for p in rules.text(doc).split("\n") if p.strip()]]
        for status, title in (("banned", "Banned"), ("restricted", "Restricted (one copy)")):
            names = self._legality(key, status)
            if names:
                controls += [_subheading(f"{title} ({len(names)})"), ft.Text(", ".join(names), size=13, selectable=True)]
            elif names is None:
                controls.append(_muted(f"The {title.lower()} list comes from Scryfall, which couldn't be reached."))
        self.show(fmt.label, controls)

    def brackets_page(self):
        controls = [rules_tab._box([
            ft.Text(brackets.label(b.number), weight=ft.FontWeight.BOLD), _labeled("Decks: ", b.decks),
            _labeled("Win conditions: ", b.win_conditions), _labeled("Gameplay: ", b.gameplay),
            _muted(f"Expect {b.turns} before you win or lose."), *[ft.Text("• " + limit, size=13) for limit in b.limits]],
            theme.COLORS["surface_container"]) for b in brackets.BRACKETS]
        controls += [_subheading("What the limits mean"), *[_labeled(term + ": ", text) for term, text in brackets.TERMS]]
        changers = self._legality("gamechanger", "is")
        if changers:
            controls += [_subheading(f"Game Changers ({len(changers)})"), ft.Text(", ".join(changers), size=13, selectable=True),
                         _muted("From Scryfall, which follows Wizards' list.")]
        controls += [_subheading("History"), *[_labeled(day + ": ", text) for day, text in brackets.HISTORY]]
        self.show("Commander Brackets", controls)

    def document_page(self, key, index):
        # A section and its subsections, up to the next top-level section, as the desktop's
        parts = self.parts(key)
        controls = []
        for part in parts[index:]:
            if controls and part.heading and "." not in part.heading:
                break
            if controls:
                controls.append(_subheading(f"{part.heading} {part.title}".strip()))
            controls += [self.rich(p, size=13.5) for p in part.text.split("\n") if p.strip()]
        self.show(f"{parts[index].heading} {parts[index].title}".strip(), controls)

    def tournament_page(self):
        self.show("Tournament Rules", [self._link(rules.DOCUMENTS[k][0], lambda k=k: self.contents_page(k), rules.DOCUMENTS[k][1])
                                       for k in ("mtr", "ipg", "jar") if self.parts(k)]
                  or [ft.Text("Not included in this copy of the website.")])

    def notes_page(self):
        notes = set_notes.index()
        releases = sum(n["kind"] == "release" for n in notes.values())
        faqs = sum(n["kind"] == "faq" for n in notes.values())
        self.show("Set Release Notes", [
            ft.Text("Every set's notes from Wizards of the Coast: the General Notes explain the set's mechanics, and the "
                    "Card-Specific Notes answer the common questions about its cards. Pick a set on the left.", size=13.5),
            ft.Text(f"{releases} release notes from Wizards' site, for the sets since 2013, and {faqs} set FAQs from before "
                    "that (Ice Age to 2013), as the Internet Archive saved them.", size=13.5),
            _muted("Rules change over the years, so older notes can be out of date: the Comprehensive Rules and card "
                   "rulings are current.")])

    def note_page(self, note_id):
        info, content = set_notes.index().get(note_id), set_notes.text(note_id)
        if not info or content is None:
            self.show("Set Release Notes", [ft.Text("This page isn't included.")])
            return
        credit = {"release": "Release notes © Wizards of the Coast, from magic.wizards.com.",
                  "faq": "© Wizards of the Coast, from Wizards' old website as the Internet Archive saved it. Rules have "
                         "changed since, so some answers may be out of date."}.get(
            info["kind"], f"From MTG Wiki, a fan wiki, used under {set_notes.WIKI_LICENSE}. It isn't official rules.")
        controls = [_muted(credit)]
        for line in content.split("\n"):
            if not line.strip():
                continue
            if line.startswith("## "):
                controls.append(_subheading(line[3:]))
            elif line.isupper() and len(line) < 60:
                controls.append(_subheading(line.title()))
            else:
                controls.append(self.rich(line, size=13.5))
        self.show(info["title"], controls)

    def wiki_page(self, kind):
        notes = set_notes.index()
        credit = _muted(f"From MTG Wiki (mtg.wiki), a fan wiki, used under {set_notes.WIKI_LICENSE}. It isn't official "
                        "rules: the Comprehensive Rules are.")
        if kind is None:
            self.show("MTG Wiki", [ft.Text("The fan-run MTG Wiki's pages on every mechanic and every set: history, design "
                                           "and how things work, in plain English.", size=13.5), credit])
            return
        pages = sorted(((i, n) for i, n in notes.items() if n["kind"] == kind), key=lambda p: p[1]["title"].lower())
        self.show(f"{'Mechanics' if kind == 'mechanic' else 'Sets'} ({len(pages)})", [
            ft.Row([ft.TextButton(n["title"], on_click=lambda e, i=i: self.open(lambda: self.note_page(i)))
                    for i, n in pages], wrap=True, spacing=0, run_spacing=0), credit])

    def cards_page(self):
        """Card Rulings, as the desktop's: add one card or several to see their text, the rules
        for their keywords and their official rulings (from Scryfall), and with several, the
        keywords and rules terms they share."""
        field = ft.TextField(hint_text="Card name… (add several to see how they interact)", dense=True, expand=True,
                             on_submit=lambda e: self.add_card(e.control.value))
        controls = [ft.Row([field, theme.button("Add Card", lambda e: self.add_card(field.value), primary=True),
                            theme.button("Clear", lambda e: (self.cards.clear(), self.cards_page()))], spacing=8)]
        if not self.cards:
            controls.append(ft.Text("Type a card's name above to see its official rulings and the rules for its keywords. "
                                    "Add more cards to see them side by side, with the rules that come up between them.",
                                    size=13.5))
            self.show("Card Rulings", controls)
            return
        cr = self.cr()
        keywords = cr.keywords() if cr else {}
        shared, texts, body = {}, [], []
        for name in self.cards:
            card, rulings = self.card_data[name]
            texts.append(card["oracle_text"] or "")
            found = rules.keyword_rules(card["oracle_text"], keywords)
            for keyword, rule_id in found:
                shared.setdefault(rule_id, (keyword, []))[1].append(name)
            body += [_subheading(card["name"]), _muted(" ".join(filter(None, [card["mana_cost"], card["type_line"]]))),
                     self.rich(card["oracle_text"] or "", size=13.5)]
            if found:
                body.append(ft.Text("Rules for its keywords", weight=ft.FontWeight.BOLD, size=13))
                body += [self.rich(f"{rule_id} {keyword.title()}", size=13) for keyword, rule_id in found]
            body.append(ft.Text(f"Official rulings ({len(rulings)})", weight=ft.FontWeight.BOLD, size=13))
            body += [self.rich(f"{day or ''}  {text}", size=13) for day, text in rulings] or [_muted("No rulings for this card.")]
        if len(self.cards) > 1:
            common = [(rule_id, keyword, names) for rule_id, (keyword, names) in shared.items() if len(names) > 1]
            terms = rules.shared_terms(texts, cr.glossary if cr else [])
            between = [_subheading("Between these cards")]
            between += [self.rich(f"{rule_id} {keyword.title()}: {', '.join(names)}", size=13)
                        for rule_id, keyword, names in common]
            between += [self.rich(f"{term} ({count} of {len(self.cards)} cards): {definition}", size=13)
                        for term, definition, count in terms]
            if len(between) == 1:
                between.append(_muted("No keywords or rules terms in common. Each card's rules and rulings are below."))
            body = between + body
        self.show("Card Rulings", controls + body)

    def add_card(self, name, guessed=False):
        name = (name or "").strip()
        if not name:
            return
        if name not in self.card_data:
            found = self.busy(f"Looking up {name}", lambda: scryfall.card_rulings(name))
            if found is None:
                return
            if found[0] is None:
                # Not an exact name: Scryfall's closest, once
                guesses = [] if guessed else scryfall.autocomplete(name)
                if not guesses:
                    self.toast(f"No card named “{name}”.")
                    return
                self.add_card(guesses[0], guessed=True)
                return
            name = found[0]["name"]
            self.card_data[name] = found
        if name not in self.cards:
            self.cards.append(name)
        self.cards_page()
