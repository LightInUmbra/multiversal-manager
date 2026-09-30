# The phone's Rules tab: Ask a Rules Question (the desktop's own judge, see ask.py), search,
# and every rules document to browse, all offline once downloaded. The phone skips the set
# notes and MTG Wiki pages unless asked, and knows cards by Scryfall's list of card names,
# looking up (and keeping) just the ones a question names.
import html
import json
import re

import flet as ft

import ask
import brackets
import database as db
import rules
import scryfall
import set_notes

MUTED = ft.Colors.ON_SURFACE_VARIANT
RULE_REF = re.compile(r"\b(\d{3}\.\d+[a-z]?|\d{3}(?=\b(?!\.\d)))\b")
HEADINGS = {"verified": "ANSWER",  # a worked-out answer has its own (judge.Worked.heading)
            "closest": "CLOSEST VERIFIED RULING", "none": "NO VERIFIED ANSWER YET"}


def _plain(text):
    # judge.py's steps can hold <b> titles and escaped characters
    return html.unescape(re.sub(r"<[^>]+>", "", text or ""))


def _box(controls, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH):
    return ft.Container(ft.Column(controls, spacing=8, tight=True), bgcolor=bgcolor, border_radius=12, padding=12)


class Rules:
    def __init__(self, page, toast, busy):
        self.page, self.toast, self.busy = page, toast, busy
        self.view = ft.Column(expand=True)
        self.history = []  # pages opened from the home page, for the back button
        self._cr, self._parts, self._names, self._library = None, {}, None, None

    # Downloaded data, read once

    def cr(self):
        if self._cr is None and rules.text("cr"):
            self._cr = rules.parse_cr(rules.text("cr"))
        return self._cr

    def parts(self, key):
        if key not in self._parts and rules.text(key):
            self._parts[key] = rules.parse_numbered(rules.text(key))
        return self._parts.get(key, [])

    def library(self):
        if self._library is None:
            self._library = rules.load_library()
        return self._library

    def card_names(self):
        if self._names is None:
            try:
                self._names = json.loads((rules.rules_dir() / "card_names.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._names = []
        return self._names

    def notes(self):
        return [(i, info, t, t.lower()) for i, info in set_notes.index().items() if (t := set_notes.text(i)) is not None]

    # Navigation

    def refresh(self):
        self.history[-1]() if self.history else self.home()

    def open(self, show):
        self.history.append(show)
        show()

    def back(self):
        # Android's back button: to the page before, then home. False when already home.
        if not self.history:
            return False
        self.history.pop()
        self.refresh()
        return True

    def show(self, title, controls):
        header = [ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, tooltip="Back", on_click=lambda e: self.back()),
                          ft.Text(title, size=20, weight=ft.FontWeight.BOLD, expand=True)])] if title else []
        self.view.controls = [ft.ListView([*header, *controls], expand=True, spacing=10,
                                          padding=ft.Padding.symmetric(horizontal=4))]
        self.page.update()

    # Text with tappable rule numbers

    def rich(self, text, **style):
        spans, at = [], 0
        for m in RULE_REF.finditer(text or ""):
            if self.cr() and (self.cr().rule(m.group(1)) or self.cr().chapter(m.group(1)[:3])):
                spans += [ft.TextSpan(text[at:m.start()]),
                          ft.TextSpan(m.group(1), ft.TextStyle(color=ft.Colors.PRIMARY, decoration=ft.TextDecoration.UNDERLINE),
                                      on_click=lambda e, ref=m.group(1): self.rule_sheet(ref))]
                at = m.end()
        return ft.Text(spans=[*spans, ft.TextSpan(text[at:])] if spans else None,
                       value=None if spans else text, selectable=False, **style)

    def rule_sheet(self, ref):
        found = rules.rules_for_ref(self.cr(), ref)
        chapter = self.cr().chapter(ref[:3])
        body = [ft.Text(f"{ref} · {chapter.title}" if chapter else ref, weight=ft.FontWeight.BOLD, size=16)]
        for rule in found[:40]:
            body.append(self.rich(f"{rule.id} {rule.text}"))
            body += [ft.Text(x, italic=True, color=MUTED, size=13) for x in rule.examples]

        def whole_chapter(e):
            self.page.pop_dialog()
            self.open(lambda: self.chapter_page(ref[:3]))

        if chapter:
            body.append(ft.TextButton(f"Open chapter {chapter.number}", on_click=whole_chapter))
        self._sheet(body)

    def _sheet(self, body):
        # A rule over the page: a bottom sheet on the phone
        self.page.show_dialog(ft.BottomSheet(ft.Container(ft.Column(body, scroll=ft.ScrollMode.AUTO, tight=True),
                                                          padding=16), scrollable=True, show_drag_handle=True))

    # Home

    def home(self):
        self.history.clear()
        cr = self.cr()
        if cr is None:
            self.show(None, [
                ft.Text("Rules", size=20, weight=ft.FontWeight.BOLD),
                ft.Text("Ask rules questions and read every official rules document, all offline: the "
                        "Comprehensive Rules and glossary, format and tournament rules, and card rulings."),
                ft.Text("Downloading them takes a few minutes the first time (about 30 MB, mostly card rulings).",
                        color=MUTED),
                ft.FilledButton("Download the rules", icon=ft.Icons.DOWNLOAD, on_click=self.download)])
            return
        question = ft.TextField(hint_text="Ask a rules question", multiline=True, min_lines=1, max_lines=4,
                                shift_enter=True, on_submit=lambda e: self.ask(question.value))
        search = ft.TextField(hint_text="Search the rules", prefix_icon=ft.Icons.SEARCH, dense=True,
                              on_submit=lambda e: self.search(search.value))
        places = [
            ("Comprehensive Rules", f"Effective {cr.effective}", self.sections_page),
            ("Glossary", f"{len(cr.glossary)} terms", self.glossary_page),
            ("Formats", "Commander, Brawl, Oathbreaker and the casual variants", self.formats_page),
            ("Tournament Rules", "Tournament Rules, Infraction Procedure Guide, Judging at Regular REL",
             self.tournament_page),
            ("Game Concepts", "The stack, priority, layers, combat…", self.concepts_page),
            ("Commander Brackets", "What each bracket allows, and the Game Changers", self.brackets_page),
        ]
        tiles = [ft.ListTile(title=ft.Text(t), subtitle=ft.Text(s, color=MUTED), dense=True,
                             on_click=lambda e, show=show: self.open(show)) for t, s, show in places]
        have_notes = bool(set_notes.index())
        self.show(None, [
            _box([ft.Text("Ask a Rules Question", weight=ft.FontWeight.BOLD),
                  ft.Text("Type it like you'd ask a judge. Card names can be typed any way.", size=13, color=MUTED),
                  question, ft.FilledButton("Look it up", icon=ft.Icons.GAVEL,
                                            on_click=lambda e: self.ask(question.value))]),
            search, *tiles,
            ft.Row([ft.TextButton("Check for updates", icon=ft.Icons.REFRESH, on_click=self.download),
                    *([] if have_notes else [ft.TextButton("Get set notes too", icon=ft.Icons.DOWNLOAD,
                                                           on_click=self.download_notes)])], wrap=True),
            ft.Text("Set release notes and MTG Wiki pages aren't downloaded on the phone unless you get them "
                    "(about 20 MB); searches include them once you do." if not have_notes else
                    "Set release notes and MTG Wiki pages are included in searches.", size=12, color=MUTED)])

    # Downloading

    def _progress(self, title):
        status = ft.Text("Starting…")
        bar = ft.ProgressBar(value=0)
        self.show(title, [status, bar])

        def progress(value):
            label, number, total = value if isinstance(value, tuple) and len(value) == 3 else (str(value), None, None)
            status.value = label
            bar.value = number / total if number and total else None
            self.page.update()
        return progress

    def download(self, e=None):
        progress = self._progress("Downloading the rules")

        def work():
            changed, errors = rules.update(progress, notes=False)
            progress(("Downloading the list of card names…", 1, 1))
            (rules.rules_dir() / "card_names.json").write_text(json.dumps(scryfall.card_name_catalog()), encoding="utf-8")
            return changed, errors

        result = self.busy("Downloading the rules", work)
        self._cr, self._parts, self._names = None, {}, None
        if result:
            changed, errors = result
            self.toast("Rules up to date." if not errors else f"Some couldn't be downloaded: {'; '.join(errors)[:200]}")
        self.home()

    def download_notes(self, e):
        cr = self.cr()
        progress = self._progress("Downloading set notes")
        result = self.busy("Downloading set notes",
                           lambda: set_notes.update(progress, cr.keywords(), rules.ability_words(cr)))
        if result:
            self.toast("Set notes downloaded." if not result[1] else "Some set notes couldn't be downloaded; "
                       "Check for Updates tries again.")
        self.home()

    # Ask

    def fetch_cards(self, names):
        # Named cards this phone hasn't looked up yet; without internet, the question goes without them
        try:
            db.add_oracle_cards(scryfall.fetch_card_data(names))
        except Exception:
            pass

    def ask(self, question):
        question = (question or "").strip()
        if not question:
            return
        found = self.busy("Looking it up", lambda: ask.look_up(question, self.cr(), self.library(),
                                                                self.card_names(), self.fetch_cards))
        if found:
            self.open(lambda: self.answer_page(found))

    def answer_page(self, found):
        self.show("Answer", self.answer_controls(found))

    def answer_controls(self, found):
        # An ask.look_up answer: the verdict up top, then what's behind it, each part folded away
        kind, worked, matches = found.kind, found.worked, found.matches
        body, rule_refs = [], []
        if kind == "verified":
            entry = matches[0][1]
            verdict, rule_refs = entry["answer"] + ".", entry["rules"]
            body = [self.rich(entry["explanation"]), ft.Text("From a verified ruling", size=12, color=MUTED)]
            if found.restated:
                body.insert(0, ft.Text(spans=[ft.TextSpan("Answering: ", ft.TextStyle(color=MUTED)),
                                              ft.TextSpan(entry["question"], ft.TextStyle(italic=True))]))
        elif kind == "worked":
            verdict, rule_refs = worked.verdict + ".", worked.rules
            combat = any(s.startswith("<b>") for s in worked.steps)
            body = [self.rich(_plain(s)) for s in (worked.steps if worked.short else [] if combat else worked.steps[-1:])]
            if worked.assumes:
                body.append(ft.Text(_plain(worked.assumes), size=12, color=MUTED))
        elif kind == "closest":
            entry = matches[0][1]
            verdict = ""
            body = [ft.Text("This may not be exactly your situation. The closest checked ruling is:"),
                    ft.Text(entry["question"], italic=True),
                    ft.Text(spans=[ft.TextSpan(entry["answer"] + ". ", ft.TextStyle(weight=ft.FontWeight.BOLD)),
                                   ft.TextSpan(entry["explanation"])])]
        else:
            verdict = ""
            concepts = ", ".join(g["title"] for g in found.guides[:3])
            body = [ft.Text("There's no checked ruling for this situation in the library yet, so the app can't give "
                            "a yes or no." + (f" What decides it: {concepts}." if concepts else "")
                            + " The sections below gather the guides, cards and rules for it.")]
        if rule_refs:
            body.append(self.rich("Rules: " + ", ".join(rule_refs), size=12, color=MUTED))
        heading = worked.heading if kind == "worked" else HEADINGS[kind]
        answer = _box([ft.Text(heading, size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY),
                       *([ft.Text(verdict, size=22, weight=ft.FontWeight.BOLD)] if verdict else []), *body],
                      ft.Colors.PRIMARY_CONTAINER if kind in ("verified", "worked") else ft.Colors.SURFACE_CONTAINER_HIGH)

        sections = []
        if worked and kind != "verified" and not worked.short:
            sections.append(("How it was worked out", [self._step(s) for s in worked.steps]))
        others = matches if worked and not found.verified else matches[1:]
        if others:
            sections.append(("Other verified rulings that may help", [
                self._ruling(entry, f"{round(score * 100)}% match") for score, entry in others]))
        if found.guides:
            sections.append(("Game concepts involved", [
                c for g in found.guides[:4] for c in (ft.Text(g["title"], weight=ft.FontWeight.BOLD),
                                                     *[self.rich(p) for p in g["summary"]])]))
        if found.cards:
            sections.append(("Cards", [
                c for name, text, rulings in found.cards for c in (
                    ft.Text(name, weight=ft.FontWeight.BOLD), self.rich(text or ""),
                    *[self.rich("Ruling: " + r, size=13) for r in rulings])]))
        if found.passages:
            sections.append(("Rules that apply", [
                self.rich(f"{p.ref} {p.text}" if p.kind == "rule" else f"Glossary: {p.ref}. {p.text}", size=13)
                for p in found.passages]))
        tiles = [ft.ExpansionTile(title=ft.Text(title), controls=[ft.Container(ft.Column(items, spacing=8),
                                                                              padding=ft.Padding.only(bottom=8))],
                                  controls_padding=ft.Padding.symmetric(horizontal=12)) for title, items in sections]
        return [ft.Text(found.question, size=16, weight=ft.FontWeight.BOLD), answer, *tiles,
                ft.Text("Verified rulings are checked answers. Everything else is the official text, "
                        "gathered for your question: read it to decide, or ask a judge at a "
                        "sanctioned event.", size=12, color=MUTED)]

    def _step(self, step):
        # A combat step starts with a bold title ("<b>First strike damage</b> …")
        m = re.match(r"<b>(.*?)</b>\s*(.*)", step, re.S)
        if not m:
            return self.rich(_plain(step))
        return ft.Column([ft.Text(_plain(m.group(1)), weight=ft.FontWeight.BOLD), self.rich(_plain(m.group(2)))],
                         spacing=2, tight=True)

    def _ruling(self, entry, note=""):
        return ft.Column([ft.Text("Q: " + entry["question"], weight=ft.FontWeight.BOLD),
                          ft.Text(spans=[ft.TextSpan("A: " + entry["answer"] + ". ", ft.TextStyle(weight=ft.FontWeight.BOLD)),
                                         ft.TextSpan(entry["explanation"])]),
                          self.rich(" · ".join(filter(None, [note, "Rules: " + ", ".join(entry["rules"]) if entry["rules"]
                                                            else ""])), size=12, color=MUTED)], spacing=2, tight=True)

    # Search

    def search(self, needle):
        needle = (needle or "").strip()
        if len(needle) < 3:
            self.toast("Type at least three letters.")
            return
        found = rules.search(needle, self.cr(), self.library(), self.parts, self.notes())
        self.open(lambda: self.results_page(needle, found))

    def results_page(self, needle, found):
        shown = found[:150]
        tiles = [ft.ListTile(title=ft.Text(self._result_title(f), weight=ft.FontWeight.BOLD),
                             subtitle=ft.Text(f["snippet"], size=13, max_lines=4, overflow=ft.TextOverflow.ELLIPSIS),
                             dense=True, on_click=lambda e, f=f: self._open_result(f)) for f in shown]
        more = f" (showing the first {len(shown)})" if len(found) > len(shown) else ""
        self.show(f"“{needle}”", [ft.Text(f"{len(found)} matches{more}", color=MUTED),
                                  *(tiles or [ft.Text("Nothing matches.")])])

    def _result_title(self, f):
        kind = f["kind"]
        if kind == "concept":
            return f"Game Concept: {f['title']}"
        if kind == "interaction":
            return f"Verified ruling: {f['title']}"
        if kind == "glossary":
            return f"Glossary: {f['title']}"
        if kind == "rule":
            return f"{f['key']} ({f['chapter']})"
        if kind == "doc":
            return f"{rules.DOCUMENTS[f['key'][0]][0]} {f['heading']} {f['title']}"
        if kind == "note":
            return f"{f['label']}: {f['title']}"
        return f["title"]

    def _open_result(self, f):
        kind, key = f["kind"], f["key"]
        if kind == "rule":
            self.rule_sheet(key)
        elif kind == "concept":
            self.open(lambda: self.concept_page(key))
        elif kind == "interaction":
            self.page.show_dialog(ft.AlertDialog(content=self._ruling(key), scrollable=True, actions=[
                ft.TextButton("Close", on_click=lambda e: self.page.pop_dialog())]))
        elif kind == "glossary":
            definition = next(d for t, d in self.cr().glossary if t == key)
            self.page.show_dialog(ft.AlertDialog(title=ft.Text(key), content=self.rich(definition), scrollable=True,
                                                 actions=[ft.TextButton("Close", on_click=lambda e: self.page.pop_dialog())]))
        elif kind == "doc":
            self.open(lambda: self.document_page(*key))
        elif kind == "note":
            self.open(lambda: self.text_page(f["title"], set_notes.text(key) or ""))
        elif kind == "format":
            self.open(lambda: self.text_page(rules.DOCUMENTS[key][0], rules.text(key) or ""))
        else:
            self.open(self.brackets_page)

    # Browsing

    def sections_page(self):
        controls = []
        for section in self.cr().sections:
            controls.append(ft.Text(f"{section.number}. {section.title}", weight=ft.FontWeight.BOLD))
            controls += [ft.ListTile(title=ft.Text(f"{c.number}. {c.title}"), dense=True,
                                     on_click=lambda e, n=c.number: self.open(lambda: self.chapter_page(n)))
                         for c in section.chapters]
        self.show("Comprehensive Rules", controls)

    def chapter_page(self, number):
        chapter = self.cr().chapter(number)
        controls = []
        for rule in chapter.rules:
            controls.append(self.rich(f"{rule.id} {rule.text}"))
            controls += [ft.Text(x, italic=True, color=MUTED, size=13) for x in rule.examples]
        self.show(f"{chapter.number}. {chapter.title}", controls)

    def glossary_page(self):
        letters = sorted({t[:1].upper() for t, _ in self.cr().glossary if t[:1].isalpha()})
        self.show("Glossary", [ft.Row([ft.TextButton(letter, on_click=lambda e, l=letter: self.open(
            lambda: self.letter_page(l))) for letter in letters], wrap=True)])

    def letter_page(self, letter):
        controls = [c for term, definition in self.cr().glossary if term[:1].upper() == letter
                    for c in (ft.Text(term, weight=ft.FontWeight.BOLD), self.rich(definition))]
        self.show(f"Glossary: {letter}", controls)

    def formats_page(self):
        docs = [(rules.DOCUMENTS[k][0], rules.DOCUMENTS[k][1], lambda k=k: self.text_page(
            rules.DOCUMENTS[k][0], rules.text(k) or "")) for k in ("commander", "brawl", "oathbreaker") if rules.text(k)]
        variants = [(name, f"Comprehensive Rules chapter {number}", lambda n=number: self.chapter_page(n))
                    for name, number in rules.CR_FORMATS.items() if self.cr().chapter(number)]
        self.show("Formats", [ft.ListTile(title=ft.Text(t), subtitle=ft.Text(s, color=MUTED), dense=True,
                                          on_click=lambda e, show=show: self.open(show)) for t, s, show in docs + variants])

    def tournament_page(self):
        tiles = [ft.ListTile(title=ft.Text(rules.DOCUMENTS[k][0]), subtitle=ft.Text(rules.DOCUMENTS[k][1], color=MUTED),
                             dense=True, on_click=lambda e, k=k: self.open(lambda: self.contents_page(k)))
                 for k in ("mtr", "ipg", "jar") if self.parts(k)]
        self.show("Tournament Rules", tiles or [ft.Text("Not downloaded yet: Check for updates while online.")])

    def contents_page(self, key):
        self.show(rules.DOCUMENTS[key][0], [
            ft.ListTile(title=ft.Text(f"{p.heading} {p.title}".strip() or "Introduction"), dense=True,
                        on_click=lambda e, i=i: self.open(lambda: self.document_page(key, i)))
            for i, p in enumerate(self.parts(key))])

    def document_page(self, key, index):
        part = self.parts(key)[index]
        self.show(f"{part.heading} {part.title}".strip(), [self.rich(p) for p in part.text.split("\n") if p.strip()])

    def text_page(self, title, text):
        self.show(title, [ft.Text(p[3:], weight=ft.FontWeight.BOLD) if p.startswith("## ") else self.rich(p)
                          for p in text.split("\n") if p.strip()])

    def concepts_page(self):
        self.show("Game Concepts", [ft.ListTile(title=ft.Text(g["title"]), dense=True,
                                                on_click=lambda e, i=i: self.open(lambda: self.concept_page(i)))
                                    for i, g in enumerate(self.library()["concepts"])])

    def concept_page(self, index):
        guide = self.library()["concepts"][index]
        controls = [self.rich(p) for p in guide["summary"]]
        official = [rule for ref in guide["rules"] for rule in rules.rules_for_ref(self.cr(), ref)]
        if official:
            controls.append(ft.ExpansionTile(title=ft.Text("The official rules"), controls=[
                ft.Container(ft.Column([self.rich(f"{r.id} {r.text}", size=13) for r in official], spacing=8),
                             padding=ft.Padding.only(bottom=8))], controls_padding=ft.Padding.symmetric(horizontal=12)))
        self.show(guide["title"], controls)

    def brackets_page(self):
        controls = []
        for b in brackets.BRACKETS:
            controls.append(_box([ft.Text(brackets.label(b.number), weight=ft.FontWeight.BOLD), ft.Text(b.decks),
                                  ft.Text(f"Games last {b.turns}.", size=13, color=MUTED),
                                  *[ft.Text("• " + limit, size=13) for limit in b.limits]]))
        controls.append(ft.Text("Terms", weight=ft.FontWeight.BOLD))
        controls += [ft.Text(spans=[ft.TextSpan(term + ": ", ft.TextStyle(weight=ft.FontWeight.BOLD)), ft.TextSpan(text)],
                             size=13) for term, text in brackets.TERMS]
        self.show("Commander Brackets", controls)
