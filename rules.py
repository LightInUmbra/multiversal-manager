"""
The official rules of Magic, kept on disk so they work offline:

- The Comprehensive Rules (Wizards' plain-text file), parsed into sections, rules
  and the glossary.
- Tournament documents (Wizards' PDFs): the Magic Tournament Rules, the Infraction
  Procedure Guide and Judging at Regular REL, split into their numbered sections.
- Format rules: Commander (the Commander Format Panel's page), Brawl (Wizards' page)
  and Oathbreaker (its rules committee's page).
- Card rulings: every card's official rulings, from Scryfall's bulk data.

Everything is fetched by update(); the rest of this module only reads what's on
disk, so the rules window (rules_window.py) works the same online or off.
"""

# Imports
import gzip
import html
import io
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import requests

import brackets
import database as db
import scryfall

HEADERS = {"User-Agent": scryfall.HEADERS["User-Agent"]}
TIMEOUT = 60
CHECK_EVERY = timedelta(days=7)  # how often to look for new versions

CR_PAGE = "https://magic.wizards.com/en/rules"
WPN_PAGES = ["https://wpn.wizards.com/en/rules-documents", "https://blogs.magicjudges.org/rules/jar/"]
WPN_FILES = "https://media.wizards.com/ContentResources/WPN/"

# key -> (title, what it is)
DOCUMENTS = {
    "cr": ("Comprehensive Rules", "Every rule of the game, maintained by Wizards of the Coast"),
    "mtr": ("Magic Tournament Rules", "How sanctioned tournaments are run"),
    "ipg": ("Infraction Procedure Guide", "Infractions and penalties at Competitive and Professional REL"),
    "jar": ("Judging at Regular REL", "Infractions and fixes at Regular REL (local events)"),
    "commander": ("Commander", "The Commander Format Panel's rules"),
    "brawl": ("Brawl", "Wizards' rules for Brawl"),
    "oathbreaker": ("Oathbreaker", "The Oathbreaker Rules Committee's rules"),
}
FORMAT_PAGES = {
    "commander": "https://mtgcommander.net/index.php/rules/",
    "brawl": "https://magic.wizards.com/en/formats/brawl",
    "oathbreaker": "https://oathbreakermtg.org/rules/",
}
# Comprehensive Rules chapters for the casual variants and multiplayer
CR_FORMATS = {"Commander": "903", "Two-Headed Giant": "810", "Planechase": "901", "Vanguard": "902",
              "Archenemy": "904", "Conspiracy Draft": "905", "Multiplayer": "800"}

RULE_ID = re.compile(r"\b(\d{3}(?:\.\d+[a-z]?)?)\b")


# The website's copy of the rules (mobile/build_web.py puts it next to the code): browsers
# can't download them from Wizards of the Coast, whose sites don't allow it, so it reads this
BUNDLED = Path(__file__).resolve().parent / "rules_bundle"


def rules_dir():
    # Next to the collection, so the whole app folder stays portable; the bundled copy until
    # there's one of its own (on the website, always)
    own = Path(db.DB_NAME).parent / "rules"
    return BUNDLED if not (own / "cr.txt").exists() and (BUNDLED / "cr.txt").exists() else own


def _manifest_path():
    return rules_dir() / "sources.json"


def _manifest():
    try:
        return json.loads(_manifest_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def text(key):
    # A document's text as saved, or None before it's been downloaded
    path = rules_dir() / f"{key}.txt"
    return path.read_text(encoding="utf-8") if path.exists() else None


def fetched(key):
    # (the version's file name or URL, the day it was last checked) or None
    entry = _manifest().get(key)
    return (entry["source"], entry["fetched"]) if entry else None


# Parsing the Comprehensive Rules

@dataclass
class Rule:
    id: str            # "702.85a"
    text: str
    examples: list = field(default_factory=list)


@dataclass
class Chapter:
    number: str        # "702"
    title: str         # "Keyword Abilities"
    rules: list


@dataclass
class Section:
    number: str        # "7"
    title: str         # "Additional Rules"
    chapters: list


@dataclass
class ComprehensiveRules:
    effective: str
    sections: list
    glossary: list     # [(term, definition)]

    def chapter(self, number):
        return next((c for s in self.sections for c in s.chapters if c.number == number), None)

    def rule(self, rule_id):
        chapter = self.chapter(rule_id[:3])
        return next((r for r in chapter.rules if r.id == rule_id), None) if chapter else None

    def keywords(self):
        # {lowercased keyword: rule id} for keyword actions (701) and abilities (702), e.g. "cascade": "702.85"
        return {r.text.lower(): r.id for number in ("701", "702") if self.chapter(number)
                for r in self.chapter(number).rules if re.fullmatch(r"70[12]\.\d+", r.id) and len(r.text) < 40}


_SECTION = re.compile(r"^(\d)\. (.+)$")
_CHAPTER = re.compile(r"^(\d{3})\. (.+)$")
_RULE = re.compile(r"^(\d{3}\.\d+[a-z]?)\.? (.+)$")


def parse_cr(raw):
    """The Comprehensive Rules text -> ComprehensiveRules. The file starts with a table
    of contents, so the rules proper begin at the second "1. Game Concepts"."""
    lines = [line.strip() for line in raw.replace("\r", "").split("\n")]
    effective = next((line for line in lines if line.startswith("These rules are effective")), "")
    starts = [i for i, line in enumerate(lines) if line == "1. Game Concepts"]
    body = lines[starts[1] if len(starts) > 1 else starts[0]:]
    glossary_at = body.index("Glossary") if "Glossary" in body else len(body)
    sections, rule = [], None
    for line in body[:glossary_at]:
        if not line:
            continue
        if match := _RULE.match(line):
            rule = Rule(match.group(1), match.group(2))
            sections[-1].chapters[-1].rules.append(rule)
        elif match := _CHAPTER.match(line):
            sections[-1].chapters.append(Chapter(match.group(1), match.group(2), []))
            rule = None
        elif match := _SECTION.match(line):
            sections.append(Section(match.group(1), match.group(2), []))
            rule = None
        elif rule is not None:
            if line.startswith("Example"):
                rule.examples.append(line)
            else:
                rule.text += "\n" + line

    glossary, term, definition = [], None, []
    tail = body[glossary_at + 1:]
    for line in tail[:tail.index("Credits")] if "Credits" in tail else tail:
        if not line:
            if term:
                glossary.append((term, " ".join(definition)))
            term, definition = None, []
        elif term is None:
            term = line
        else:
            definition.append(line)
    if term:
        glossary.append((term, " ".join(definition)))
    return ComprehensiveRules(effective, sections, glossary)


# Parsing the other documents

@dataclass
class Part:
    heading: str       # "3.2", or "" before the first heading
    title: str
    text: str


# A numbered heading in the tournament documents: "3.2 Tardiness", "2. Game Play Errors",
# or an appendix: "Appendix A – Penalty Quick Reference"
_HEADING = re.compile(r"^(\d{1,2}(?:\.\d{1,2})?)\.?\s+([A-Z][^.]{2,80}?)\s*$")
_APPENDIX = re.compile(r"^(Appendix [A-Z])\s*[—–-]\s*(.{3,80})$")
_PAGE_FURNITURE = re.compile(r"^(?:Magic: The Gathering .*|Page \d+(?: of \d+)?|\d+)$")


def _next_heading(number, last):
    # Headings come in order (1, 1.1, 1.2, 2, 2.1…); a numbered list item out of order isn't one
    top, _, sub = number.partition(".")
    last_top, _, last_sub = last.partition(".")
    if not last:
        return number in ("1", "1.1")
    if not sub:
        return int(top) == int(last_top) + 1
    return int(top) == int(last_top) and int(sub) == (int(last_sub) + 1 if last_sub else 1)


_CONTENTS_LINE = re.compile(r"^(\d{1,2}(?:\.\d{1,2})?)\.?\s+(.+?)\s*(?:\.\s?){3,}\s*\d+\s*$")


def _words(title):
    return re.sub(r"\s+", " ", title).strip().lower()


def parse_numbered(raw):
    """A tournament document's text (from its PDF) -> [Part]: split at its numbered
    headings and appendices, skipping the table of contents (its lines have dot
    leaders) and running page headers and footers. Lines are joined back into paragraphs.
    A heading counts if the table of contents lists it by that number and a similar
    title (numbered lists inside a section look just like headings); headings the
    contents don't list must come next in order."""
    lines = [line.strip() for line in raw.replace("\r", "").split("\n")]
    contents = {m.group(1): _words(m.group(2)) for m in map(_CONTENTS_LINE.match, lines) if m}
    parts = [Part("", "Introduction", "")]
    last = ""
    for line in lines:
        if not line or "....." in line or ". . ." in line or _PAGE_FURNITURE.match(line):
            continue
        match = _HEADING.match(line) or _APPENDIX.match(line)
        if match and not match.group(1).startswith("Appendix"):
            number, title = match.group(1), _words(match.group(2))
            listed = contents.get(number)
            if not ((listed in title or title in listed) if listed else _next_heading(number, last)):
                match = None
        if match:
            title = match.group(2).strip()
            parts.append(Part(match.group(1), title.title() if title.isupper() else title, ""))
            if not match.group(1).startswith("Appendix"):
                last = match.group(1)
            continue
        part = parts[-1]
        if part.text and not part.text.endswith("\n"):
            part.text += " "
        part.text += line
        if line.endswith((".", ":", "?", "!")):
            part.text += "\n"
    return [part for part in parts if part.text.strip() or part.heading]


def html_to_text(page):
    # A web page's readable text, keeping paragraphs and list items on their own lines
    page = re.sub(r"(?is)<(script|style|nav|header|footer|form|noscript)[^>]*>.*?</\1>", "", page)
    main = re.search(r"(?is)<(?:main|article)[^>]*>(.*)</(?:main|article)>", page)
    page = main.group(1) if main else page
    page = re.sub(r"(?i)<(?:br|/p|/li|/h\d|/tr|/div)[^>]*>", "\n", page)
    page = re.sub(r"(?i)<li[^>]*>", "• ", page)
    text = html.unescape(re.sub(r"<[^>]+>", "", page))
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


# Downloading (on a worker thread)

def _get(url):
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    return response


def latest_wpn_files(pages):
    """{"mtr": "MTG_MTR_2026_Feb27_EN.pdf", …}: the newest file of each tournament
    document named in these pages' text (Wizards' page keeps them in escaped JSON,
    where \\u002F is "/")."""
    newest = {}
    for name, doc in re.findall(r"(MTG_(MTR|IPG|JAR)_[A-Za-z0-9_]+?_EN\.pdf)", pages.replace("\\u002F", "/")):
        stamp = re.search(r"(\d{4})_?([A-Za-z]{3})(\d{1,2})", name)
        try:
            when = datetime.strptime("".join(stamp.groups()), "%Y%b%d") if stamp else datetime.min
        except ValueError:
            when = datetime.min
        key = doc.lower()
        if key not in newest or when > newest[key][0]:
            newest[key] = (when, name)
    return {key: name for key, (_, name) in newest.items()}


def _pdf_text(content):
    import pypdf  # only needed here: without it, just the tournament documents are missing
    return "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(content)).pages)


def _save(key, source, content=None):
    folder = rules_dir()
    folder.mkdir(exist_ok=True)
    if content is not None:
        (folder / f"{key}.txt").write_text(content, encoding="utf-8")
    manifest = _manifest()
    manifest[key] = {"source": source, "fetched": date.today().isoformat()}
    _manifest_path().write_text(json.dumps(manifest, indent=1), encoding="utf-8")


def due(today=None):
    # Whether anything is missing, or it's been a week since checking for new versions
    today = today or date.today()
    manifest = _manifest()
    return any(key not in manifest or date.fromisoformat(manifest[key]["fetched"]) + CHECK_EVERY <= today
               for key in [*DOCUMENTS, "rulings"])


def update(progress=None, notes=True):
    """Downloads whatever's missing or has a newer version: every document, and the card
    rulings, plus (with notes) every set's notes and MTG Wiki's pages, which the phone app
    leaves for later. Returns (titles of what changed, errors). Anything that fails to
    download keeps its saved copy."""
    scryfall._require_online()
    changed, errors = [], []
    total = len(DOCUMENTS) + 1

    def title(key):
        return DOCUMENTS[key][0] if key in DOCUMENTS else "Card rulings"

    def attempt(key, number, fetch):
        # fetch() -> (version, text or None); only a new version counts as a change
        if progress:
            progress((f"Downloading {title(key)}…", number, total))
        try:
            source, content = fetch()
            new = fetched(key) is None or fetched(key)[0] != source or (content is not None and text(key) is None)
            _save(key, source, content)
            if new:
                changed.append(title(key))
        except (requests.RequestException, ValueError, OSError, ImportError, AttributeError) as error:
            errors.append(f"{title(key)}: {error}")

    def comprehensive():
        link = re.search(r"https://media\.wizards\.com/[^\"'<>]+?\.txt", _get(CR_PAGE).text).group(0)
        response = _get(link.replace(" ", "%20"))
        response.encoding = "utf-8-sig"
        return link.rsplit("/", 1)[-1], response.text.replace("\r", "")
    attempt("cr", 1, comprehensive)

    try:
        files = latest_wpn_files("".join(_get(url).text for url in WPN_PAGES))
    except requests.RequestException as error:
        files = {}
        errors.append(f"Tournament documents: {error}")
    for number, key in enumerate(("mtr", "ipg", "jar"), start=2):
        if key in files:
            attempt(key, number, lambda name=files[key]: (name, _pdf_text(_get(WPN_FILES + name).content)))

    for number, (key, url) in enumerate(FORMAT_PAGES.items(), start=5):
        # Web pages have no version name; the text itself tells whether it changed
        def page(key=key, url=url):
            content = html_to_text(_get(url).text)
            if content == text(key) and fetched(key):
                return fetched(key)[0], content
            return f"{url} ({date.today().isoformat()})", content
        attempt(key, number, page)

    def rulings():
        info = scryfall._get_json("/bulk-data/rulings")
        if fetched("rulings") and fetched("rulings")[0] == info["updated_at"] and db.has_rulings():
            return info["updated_at"], None
        return download_rulings(info), None
    attempt("rulings", total, rulings)

    if not notes:
        return changed, errors
    # Every set's notes and MTG Wiki's mechanic and set pages (see set_notes.py)
    import set_notes  # here: it builds on this module
    cr = parse_cr(text("cr")) if text("cr") else None
    notes_changed, notes_errors = set_notes.update(progress, cr.keywords() if cr else {}, ability_words(cr))
    return changed + notes_changed, errors + notes_errors


def download_rulings(info=None):
    # Every card's rulings from Scryfall's bulk file into the database (replacing what's there);
    # returns the file's updated_at. info: its bulk-data entry, if already asked for
    info = info or scryfall._get_json("/bulk-data/rulings")
    with requests.get(info["jsonl_download_uri"], headers=HEADERS, timeout=TIMEOUT, stream=True) as response:
        response.raise_for_status()
        with gzip.open(response.raw, "rt", encoding="utf-8") as lines:
            db.replace_rulings(json.loads(line) for line in lines if line.strip())
    return info["updated_at"]


def ability_words(cr):
    # "adamant", "landfall"…: the ability words rule 207.2c lists
    rule = cr.rule("207.2c") if cr else None
    listed = re.search(r"The ability words are (.+?)\.", rule.text) if rule else None
    return [w.strip() for w in re.split(r",\s*(?:and\s+)?|\s+and\s+", listed.group(1)) if w.strip()] if listed else []


# Finding the rules a question is about (what the rules judge reasons from)

# Game concepts -> (how a question tends to mention them, the rules that govern them). A
# three-digit reference is a whole chapter; "510.4" is that rule and its lettered parts.
CONCEPTS = {
    "Priority and the stack": (
        r"\bstack\b|priority|\brespond|in response|resolv|split second|fizzl|"
        r"counter(?:ed|s)? (?:a |the |that |target )?(?:spell|ability)",
        ["117.1", "117.3", "117.4", "117.7", "405.1", "405.2", "405.5", "608.1", "608.2b"]),
    "APNAP order": (
        r"apnap|napap|active player|nonactive|at the same time|simultaneous|each player|both (?:players?|triggers?)|"
        r"\border\b.{0,40}\btrigger|\btriggers?\b.{0,40}\border\b|\b\d[- ]player|(?:three|four|five)[- ]player",
        ["101.4", "603.3b"]),
    "Layers and continuous effects": (
        r"\blayers?\b|timestamp|dependen|characteristic-defining|base (?:power|toughness)|loses? all abilities|"
        r"sets? (?:its|their|the) (?:base )?power|becomes? an? (?:\d+/\d+|artifact|creature|land|copy)|anthem|"
        r"\b\d+/\d+\b.*\b(?:gets?|becomes?)\b|\bgets? [+-]\d+/[+-]\d+|in addition to its other|land types?|"
        r"are (?:mountains|swamps|islands|forests|plains)\b",
        ["613", "611.3"]),
    "State-based actions": (
        r"state[- ]based|\b0 toughness|toughness (?:of |is |becomes )?0\b|zero toughness|legend rule|lethal damage|"
        r"\b0 life|zero life|less than 1|life total is -?\d|poison|two legendary|same name|indestructible|"
        r"\bdies? (?:right away|immediately)",
        ["704.3", "704.5"]),
    "Replacement and prevention effects": (
        r"replacement|\binstead\b|\bwould\b|enters? (?:the battlefield )?with|as .{0,40} enters|prevent",
        ["614.1", "614.5", "614.6", "614.12", "615.1", "616.1"]),
    "Triggered abilities": (
        r"trigger|whenever|\bwhen\b|at the beginning",
        ["603.2", "603.3", "603.4", "603.6", "603.10", "113.7a"]),
    "Zone changes": (
        r"leaves? the battlefield|\bdies\b|\bdie\b|graveyard|\bexile|new object|last known|returns? (?:it )?to|"
        r"\bzones?\b|bounce|\bblink|flicker",
        ["400.7", "603.10", "608.2h"]),
    "Copies": (r"\bcop(?:y|ies|ied|ying)\b|\bclones?\b", ["707.2", "707.3", "707.9", "707.10"]),
    "Face-down permanents": (
        r"face[- ](?:down|up)|\bmorph|manifest|disguise|\bcloak", ["708.2", "708.3", "708.8", "116.2b"]),
    "Combat": (
        r"combat|\battack|\bblock|damage step|first strike|double strike|unblocked|trample",
        ["506.4", "508.1", "509.1", "510", "511.3"]),
    "Mana abilities": (r"mana abilit|tap(?:s|ped)? for mana|\badd (?:one|two|\{)", ["605.1", "605.3", "605.5"]),
    "Mana pools": (r"mana pool|unspent mana|mana burn|left over mana|leftover mana", ["106.4", "500.5"]),
    "Casting spells and costs": (
        r"\bcast|\bcosts?\b|additional cost|alternative cost|\btax\b|without paying|\bfree\b",
        ["601.2", "118.9"]),
    "Special actions": (
        r"special action|turn(?:ed|s|ing)? (?:it )?face up|play(?:s|ing|ed)? a land|suspend|foretell|\bplot\b",
        ["116.1", "116.2", "305.1"]),
    "Activated abilities": (r"activat", ["602.1", "602.2", "602.5"]),
    "Summoning sickness": (
        r"summoning sick|\bhaste\b|came under .{0,20}control|continuously controlled|\{t\} abilit",
        ["302.6"]),
    "Tokens": (r"\btokens?\b", ["111.1", "111.7", "111.8"]),
    "Counters on permanents": (r"\+1/\+1|-1/-1|counters? on|loyalty counter", ["122.1", "122.3", "704.5q"]),
    "Control": (r"gain(?:s|ed)? control|\bsteal|control of|\bcontroller|\bowner", ["108.3", "108.4", "110.2"]),
    "Commander": (r"commander|command zone|color identity|\bpartner|companion", ["903"]),
    "Commander Brackets": (r"\bbrackets?\b|game[- ]changers?|\bcedh\b|rule (?:zero|0)\b|power level", ["903.1"]),
    "Multiplayer": (r"multiplayer|free-for-all|two-headed|four[- ]player|\bpod\b", ["800.4"]),
    "Mulligans": (r"mulligan|opening hand|starting hand", ["103.5"]),
    "Turn structure": (
        r"untap step|upkeep|draw step|end step|cleanup|end of (?:the )?turn|hand size|main phase",
        ["502", "503", "504", "513", "514"]),
    "Targets": (r"\btarget|hexproof|shroud|protection from|ward\b", ["115.1", "115.2", "608.2b"]),
    "Winning and losing": (r"lose the game|win the game|draw the game|can't lose|\blose\b",
                           ["104.2", "104.3", "704.5a"]),
    "Planeswalkers": (r"planeswalker|loyalty", ["306.5", "606.3"]),
    "Auras and Equipment": (r"\baura|\bequip|attach|enchanted", ["303.4", "301.5"]),
}

# Concepts that nearly every question touches ("when", "target", "cast"…): their rules come
# after the specific concepts' and the best word matches, so they can't crowd those out
BROAD_CONCEPTS = {"Priority and the stack", "Triggered abilities", "Zone changes", "Casting spells and costs",
                  "Activated abilities", "Targets", "Control", "Winning and losing"}

_TOKEN = re.compile(r"[a-z0-9+/'-]+")
_QUESTION_STOPWORDS = {"a", "an", "the", "of", "to", "and", "or", "it", "its", "is", "are", "in", "on", "with",
                       "if", "i", "my", "me", "you", "your", "can", "do", "does", "what", "when", "how", "that",
                       "this", "be", "for", "at", "as", "by", "from", "then", "will", "would", "happens", "have",
                       "has", "there", "one", "they", "their", "card", "cards", "creature", "creatures",
                       "just", "still", "also", "even", "really", "actually", "ever"}


@dataclass
class Passage:
    kind: str          # "card", "ruling", "rule" or "glossary"
    ref: str           # "702.49a", a card name, or a glossary term
    text: str
    why: str           # what in the question brought it in


_EVERYDAY_WORDS = {
    "a", "an", "the", "of", "to", "in", "on", "at", "and", "or", "for", "with", "from", "by", "as", "into", "up",
    "down", "out", "over", "off", "all", "no", "not", "it", "its", "is", "be", "my", "your", "their", "i", "you",
    "we", "they", "me", "each", "other", "more", "one", "two", "three", "first", "last", "next", "end", "turn",
    "step", "phase", "combat", "damage", "life", "card", "cards", "draw", "play", "cast", "attack", "block",
    "creature", "creatures", "spell", "spells", "time", "way", "back", "go", "take", "make", "stand", "hold",
    "line", "day", "game", "win", "lose", "again", "now", "new", "enter", "leave", "this", "that", "what", "when",
    "if", "do", "does", "can", "will", "same", "top", "bottom", "hand", "library", "graveyard", "stack", "land",
    "lands", "mana", "counter", "token", "tokens", "target", "control", "pay", "cost", "double", "strike", "here",
    "deal", "deals", "dealt", "dies", "die", "gain", "gains", "lose", "loses", "blocker", "attacker",
}


@lru_cache(maxsize=1 << 16)  # every card name, every question
def _plain(text):
    # "Kaya, Geist Hunter's" -> "kaya geist hunters": names as people type them
    return re.sub(r"\s+", " ", re.sub(r"[,'’]", "", text.lower()))


def mentioned_cards(question, names, rules_terms=()):
    """The card names (out of names) a question mentions, longest first, leaving out
    names that are only part of a longer one mentioned ("Iron" in "Iron Maiden"). Names of
    several words can be typed any way ("kaya geist hunter" for Kaya, Geist Hunter); a
    one-word name has to be capitalized ("Clone", not "clone"). A split card's one-word
    half ("Turn" of Turn // Burn) and names that are also rules terms (rules_terms:
    "Exile", "Lifelink") only count as part of the full name."""
    terms = {t.lower() for t in rules_terms}
    plain_question = _plain(question)
    forms = []      # (the way it can be written, name): the full name, and a split or two-faced card's front
    for name in names:
        forms.append((name, name))
        front = name.split(" // ")[0]
        if front != name and " " in front:
            forms.append((front, name))
    found, matched = [], []
    # Longest first, so "Elesh Norn, Grand Cenobite" wins over "Elesh Norn" (of Elesh Norn // The Argent Etchings)
    for form, name in sorted(forms, key=lambda f: len(f[0]), reverse=True):
        if name in found or len(form) < 4 or (form == name and name.lower() in terms):
            continue
        plain = _plain(form)
        # Several words, not all everyday ones ("The End" needs its capitals: "the end of turn")
        if " " in form and not set(plain.split()) <= _EVERYDAY_WORDS:
            hit = plain in plain_question and re.search(rf"(?<!\w){re.escape(plain)}s?(?!\w)", plain_question)
        else:   # "Liliana's" counts; "Iron" in "Iron's-Edge" doesn't
            hit = form in question and re.search(rf"(?<![\w']){re.escape(form)}(?!\w|'(?!s\b))", question)
        if hit and not any(plain in longer for longer in matched):
            found.append(name)
            matched.append(plain)
    return found


def rules_for_ref(cr, ref):
    # The rules a reference stands for: a whole chapter, or a rule and its lettered parts
    if re.fullmatch(r"\d{3}", ref):
        chapter = cr.chapter(ref)
        return chapter.rules if chapter else []
    chapter = cr.chapter(ref[:3])
    pattern = re.compile(rf"^{re.escape(ref)}[a-z]?$")
    return [r for r in chapter.rules if pattern.match(r.id)] if chapter else []


def _rule_text(rule):
    return rule.text + "".join(f"\n{example}" for example in rule.examples)


def find_rules(question, cr, cards=(), budget=30000):
    """The rules, card text and rulings a rules question is about, most relevant first,
    up to about budget characters: cards is [(name, oracle text, [ruling texts])] for
    the cards it mentions. Brought in, in order: those cards and their rulings; the rules
    for every keyword the question or the cards use; the rules for the game concepts it
    touches (combat, the stack, layers, APNAP…); glossary terms it uses; then whichever
    other rules share the most (and rarest) words with it."""
    passages, seen = [], set()
    text = question + "\n" + "\n".join(oracle or "" for _, oracle, _ in cards)
    lowered = text.lower()

    def add(kind, ref, body, why):
        if ref not in seen:
            seen.add(ref)
            passages.append(Passage(kind, ref, body, why))

    for name, oracle, rulings in cards:
        add("card", name, oracle or "", "Mentioned in the question")
        for index, ruling in enumerate(rulings):
            add("ruling", f"{name} ruling {index + 1}", ruling, f"Official ruling for {name}")

    for keyword, rule_id in rules_for_keywords(lowered, cr):
        for rule in rules_for_ref(cr, rule_id):
            add("rule", rule.id, _rule_text(rule), f"Keyword: {keyword.title()}")

    def concepts(broad):
        for concept, (pattern, refs) in CONCEPTS.items():
            if (concept in BROAD_CONCEPTS) == broad and re.search(pattern, lowered, re.IGNORECASE):
                for ref in refs:
                    for rule in rules_for_ref(cr, ref):
                        add("rule", rule.id, _rule_text(rule), concept)

    concepts(broad=False)

    for term, definition in cr.glossary:
        word = re.split(r"[,(]", term)[0].strip().lower()
        if len(word) > 3 and word not in _EVERYDAY_TERMS and re.search(rf"\b{re.escape(word)}\b", lowered):
            add("glossary", term, definition, "Glossary term in the question")

    # The best word matches among all the rules, rarer words counting more: the top few
    # before the broad concepts, the rest after them
    words = {w for w in _TOKEN.findall(question.lower()) if w not in _QUESTION_STOPWORDS and len(w) > 2}
    index = _word_index(cr)
    scored = []
    for rule, rule_words in index["rules"]:
        score = sum(index["idf"].get(w, 0) for w in words & rule_words)
        if score:
            scored.append((score, rule))
    best = [rule for _, rule in sorted(scored, key=lambda s: -s[0])[:40]]
    for rule in best[:10]:
        add("rule", rule.id, _rule_text(rule), "Matches the question's wording")
    concepts(broad=True)
    for rule in best[10:]:
        add("rule", rule.id, _rule_text(rule), "Matches the question's wording")

    kept, used = [], 0
    for passage in passages:
        size = len(passage.text) + len(passage.ref) + 20
        if used + size <= budget or passage.kind in ("card", "ruling"):
            kept.append(passage)
            used += size
    return kept


def rules_for_keywords(text, cr):
    # [(keyword, rule id)] for every keyword ability or action named in text, in rule order
    keywords = cr.keywords()
    found = [(k, r) for k, r in keywords.items() if re.search(rf"\b{re.escape(k)}\b", text, re.IGNORECASE)]
    return sorted(found, key=lambda kv: [int(n) for n in kv[1].split(".")])


_indexes = {}


def _word_index(cr):
    # Each rule's words and every word's rarity (inverse document frequency), worked out once
    key = id(cr)
    if key not in _indexes:
        rules_words = [(r, set(_TOKEN.findall(_rule_text(r).lower())))
                       for s in cr.sections for c in s.chapters for r in c.rules]
        counts = Counter(w for _, words in rules_words for w in words)
        idf = {w: math.log(len(rules_words) / n) for w, n in counts.items()}
        _indexes.clear()
        _indexes[key] = {"rules": rules_words, "idf": idf}
    return _indexes[key]


def prompt_context(passages):
    # The passages as plain text for a language model, each labeled with its source
    labels = {"card": "CARD", "ruling": "RULING", "rule": "RULE", "glossary": "GLOSSARY"}
    return "\n\n".join(f"[{labels[p.kind]} {p.ref}]\n{p.text}" for p in passages)


# The verified library: Game Concepts guides and interaction rulings (rules_library.json,
# plain data so the website and mobile app can share it)

LIBRARY_PATH = Path(__file__).resolve().parent / "rules_library.json"

# Concepts whose guide has a different title
GUIDE_FOR = {"Zone changes": "Zone changes and new objects", "Special actions": "Special actions and mana",
             "Mana abilities": "Special actions and mana", "Mana pools": "Special actions and mana",
             "Targets": "Targets, hexproof and protection"}


def load_library(path=LIBRARY_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def concepts_in(text):
    # The CONCEPTS a text touches, in CONCEPTS order
    return [concept for concept, (pattern, _) in CONCEPTS.items() if re.search(pattern, text, re.IGNORECASE)]


def guides_for(text, library):
    # The Game Concepts guides for the concepts a text touches (specific ones first)
    concepts = sorted(concepts_in(text), key=lambda c: c in BROAD_CONCEPTS)
    by_title = {guide["title"]: guide for guide in library["concepts"]}
    titles = dict.fromkeys(GUIDE_FOR.get(concept, concept) for concept in concepts)
    return [by_title[title] for title in titles if title in by_title]


# How players write keywords, as the rules do
_SHORTHAND = [(re.compile(r"\bfl[iy]ers?\b"), "flying"), (re.compile(r"\btramplers?\b"), "trample"),
              (re.compile(r"\b(first|double)[- ]strikers?\b"), r"\1 strike"),
              (re.compile(r"\b(?:steal|steals|stole|stolen|stealing)\b"), "gain control of"),
              (re.compile(r"\bbounc(?:e|es|ed|ing)\b"), "return to its owner's hand"),
              (re.compile(r"\bfloat(?:s|ed|ing)? mana\b|\bmana float(?:s|ed|ing)?\b"), "unspent mana"),
              (re.compile(r"\bfetch(?:es|ed|ing)? (?:a |my |the )?(?:basic )?lands?\b"), "put a land onto the battlefield"),
              *((re.compile(rf"\b{digit}\b(?![/+-]|\d)"), word) for digit, word in
                (("2", "two"), ("3", "three"), ("4", "four"), ("5", "five"), ("6", "six"), ("7", "seven"),
                 ("8", "eight"), ("9", "nine"), ("10", "ten")))]
# Word forms the endings below don't bring together
_IRREGULAR = {"dies": "die", "died": "die", "dying": "die", "lost": "lose", "dealt": "deal", "chose": "choose",
              "chosen": "choose", "paid": "pay", "spent": "spend", "drew": "draw", "drawn": "draw"}


def _shorthand(text):
    for pattern, written in _SHORTHAND:
        text = pattern.sub(written, text)
    return text


def _stem(word):
    # "blocked", "blocking" and "blocks" -> "block"; "copies" -> "copy"; "tapped" -> "tap"
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) > 3:
        word = word[:-1]
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[:-len(suffix)]
            if word[-1] == word[-2] and word[-1] not in "ls":  # "tapp" -> "tap", not "kill" -> "kil"
                word = word[:-1]
            break
    return word[:-1] if word.endswith("e") and len(word) > 4 else word


def _content_words(text):
    return {_stem(w) for w in _TOKEN.findall(_shorthand(text.lower()))
            if w not in _QUESTION_STOPWORDS and len(w) > 2}


# "Without reach" and "with reach" share every other word, so a word negated in one question
# and plainly there in the other means they ask opposite things. (A negation that just describes
# the situation, like "it wasn't blocked", clashes with nothing when the other doesn't mention it.)
_NEGATED_WORD = re.compile(r"\b(?:not|no|without|never|cannot|\w+n't)\s+(?:(?:a|an|the|have|has|be|any)\s+)?"
                           r"(?:(?:paying|using|having|getting)\s+(?:the\s+|its\s+|any\s+|a\s+)?)?([a-z0-9+/-]+)")
# How much a question asked the other way round counts: never enough to be given as its answer
NEGATION_MISMATCH = 0.4
# How much a question about other keywords counts: enough to be the closest ruling, rarely its answer
KEYWORD_MISMATCH = 0.5


# "without flying or reach" negates both; "noncombat" is "not combat"
_NEGATED_LIST = re.compile(r"\b(?:not|no|without|never)\s+(?:a |an |the )?[a-z0-9+/-]+\s+(?:or|nor|and)\s+([a-z0-9+/-]+)")
_NON = re.compile(r"\bnon-?([a-z]{3,})")
_WITHOUT_PAYING = re.compile(r"\bwithout paying (?:the |its |any |a |my |your )?(?:[a-z]+ )?([a-z]+)")  # "…commander tax"
# Asking whether something stops, prevents or saves turns the answer round: "Does indestructible
# stop sacrifice?" is No where "Can I sacrifice an indestructible creature?" is Yes
_STOPS = re.compile(r"\b(?:stop|stops|stopped|prevent|prevents|prevented|protect|protects|save|saves|saved|"
                    r"skip|skips|skipped)\b")
# How many, and which card types: "if one creature attacks alone" isn't "if two attack", and
# prowess on instants isn't prowess on creature spells. Only told apart when both say.
_COUNTS = re.compile(r"\b(two|three|four|five|six|seven|eight|nine|ten|single|alone|both|several|multiple)\b")
_NOT_A_COUNT = re.compile(r"\b(?:more than|at least|fewer than|less than|up to) \w+")  # "more than one copy"
_TYPES = re.compile(r"\b(instant|sorcer|creature|artifact|enchantment|aura|equipment|land|planeswalker|battle|token)")


def _told_apart(pattern, question, other):
    asked, theirs = (set(pattern.findall(_NOT_A_COUNT.sub(" ", text.lower()))) for text in (question, other))
    return bool(asked and theirs and not asked & theirs)


# The library's side of matching is the same for every question, so each ruling's text is
# worked through once (cached by text) rather than on every question
_TEXTS = 4096


@lru_cache(maxsize=_TEXTS)
def _negations(text):
    # (words negated in text, words it has plainly)
    text = _shorthand(text.lower().replace("’", "'"))
    negated = {_stem(w) for w in [*_NEGATED_WORD.findall(text), *_NEGATED_LIST.findall(text), *_NON.findall(text),
                                  *_WITHOUT_PAYING.findall(text)]}
    plain = _content_words(_NON.sub(" ", _NEGATED_WORD.sub(" ", _NEGATED_LIST.sub(" ", _WITHOUT_PAYING.sub(" ", text)))))
    # A word it has both ways ("with flying … doesn't have flying") takes no side
    return frozenset(negated - plain), frozenset(plain - negated)


def _asked_the_other_way(question, other):
    (negated_q, plain_q), (negated_o, plain_o) = _negations(question), _negations(other)
    return bool(negated_q & plain_o or negated_o & plain_q)


_REACH_A_NUMBER = re.compile(r"\breach(?:es|ed|ing)? (?:\d+|zero|one|ten)\b")  # "reach 0 life" isn't reach


@lru_cache(maxsize=_TEXTS)
def _keywords_in(text, pattern):
    return frozenset(pattern.findall(_REACH_A_NUMBER.sub(" ", _shorthand(text.lower())))) if pattern else frozenset()


def _mine(text):
    # "my own creature" (or "a planeswalker I control?") isn't any creature: whose it is can
    # decide the answer. "I control a permanent with…" just sets the scene.
    return bool(re.search(r"\bown\b|\b(?:i|you) control\s*(?:[?,.;]|$)", text.lower()))


@lru_cache(maxsize=_TEXTS)
def _matching_words(text):
    return frozenset(_content_words(text) | {f"concept:{c}" for c in concepts_in(text)})


@lru_cache(maxsize=_TEXTS)
def _pairs(text):
    # Words in order: what tells "two creatures block one attacker" from "one creature blocks two attackers"
    stems = [_stem(w) for w in _TOKEN.findall(_shorthand(text.lower()))]
    return frozenset(zip(stems, stems[1:]))


@lru_cache(maxsize=16)
def _keyword_pattern(keywords):
    # The keywords worth telling questions apart by (keywords: sorted (keyword, rule id) pairs)
    named = sorted((k for k, rule_id in keywords if rule_id.startswith("702") or k not in _COMMON_ACTIONS),
                   key=len, reverse=True)
    return re.compile(rf"\b({'|'.join(map(re.escape, named))})(?:s|es)?\b") if named else None  # "partners"


def similar_interactions(question, library, limit=3, threshold=0.25, keywords=()):
    """The library's verified interactions closest to a question: [(score 0-1, entry)],
    best first. Words they share count by how rare they are in the library ("ninjutsu"
    says more than "attack"), and so do game concepts they share. A question asked the
    other way round ("without reach" for "with reach", "my own" for anyone's) counts for
    less, and so does one about other keywords (keywords from ComprehensiveRules.keywords()):
    a sorcery cast with cascade isn't a sorcery cast on its own. An entry's "also" lists
    other ways the question is asked, for ones shared words can't tell apart ("two creatures
    block one attacker" isn't "one creature blocks two attackers"); the closest one counts."""
    entries = library["interactions"]
    pattern = _keyword_pattern(tuple(sorted(dict(keywords).items())))
    asked_keywords = _keywords_in(question, pattern)
    phrasings = [[(text, _matching_words(text)) for text in [e["question"], *e.get("also", [])]] for e in entries]
    counts = Counter(w for ways in phrasings for w in set().union(*(ws for _, ws in ways)))
    idf = {w: math.log((len(entries) + 1) / n) + 0.5 for w, n in counts.items()}
    asked = _matching_words(question)
    asked_weight = sum(idf.get(w, math.log(len(entries) + 1) + 0.5) for w in asked) or 1

    def score(text, text_words):
        shared = sum(idf[w] for w in asked & text_words)
        value = shared / math.sqrt(asked_weight * sum(idf[w] for w in text_words))
        if (_asked_the_other_way(question, text) or _mine(question) != _mine(text)
                or bool(_STOPS.search(question.lower())) != bool(_STOPS.search(text.lower()))
                or _told_apart(_COUNTS, question, text) or _told_apart(_TYPES, question, text)):
            value *= NEGATION_MISMATCH
        if asked_keywords != _keywords_in(text, pattern):
            value *= KEYWORD_MISMATCH
        return value

    asked_pairs = _pairs(question)
    scored = []
    for entry, ways in zip(entries, phrasings):
        best = max(score(text, text_words) for text, text_words in ways)
        if best >= threshold:
            order = max(len(asked_pairs & _pairs(text)) for text, _ in ways)
            scored.append((round(best, 2), order, entry))
    # Equal scores go to the one sharing the most word pairs
    return [(value, entry) for value, _, entry in sorted(scored, key=lambda s: (-s[0], -s[1]))][:limit]


# Rules terms cards have in common

# Glossary terms nearly every card uses, which say nothing about how two cards interact
_EVERYDAY_TERMS = {"card", "player", "turn", "game", "ability", "spell", "object", "effect", "you", "target",
                   "cost", "mana", "control", "controller", "owner", "choose", "may", "text", "name", "type",
                   "color", "hand", "draw", "life", "damage", "counter"}


def shared_terms(card_texts, glossary):
    """Glossary terms that at least two of the cards' rules texts use: [(term, definition,
    how many cards)], most shared first. "Artifact" for Imotekh the Stormlord ("artifact
    cards leave your graveyard") and Mycosynth Lattice ("all permanents are artifacts")."""
    texts = [re.sub(r"\([^)]*\)", "", t or "") for t in card_texts]
    found = []
    for term, definition in glossary:
        word = re.split(r"[,(]", term)[0].strip()
        if not word or word.lower() in _EVERYDAY_TERMS:
            continue
        pattern = re.compile(rf"\b{re.escape(word)}(?:s|es)?\b", re.IGNORECASE)
        count = sum(bool(pattern.search(text)) for text in texts)
        if count >= 2:
            found.append((term, definition, count))
    return sorted(found, key=lambda t: -t[2])


# Keyword rules for a card

# Keyword actions nearly every card performs, whose rules nobody looks up for a card
_COMMON_ACTIONS = {"activate", "attach", "cast", "counter", "create", "destroy", "discard", "double", "exchange",
                   "exile", "play", "reveal", "sacrifice", "search", "shuffle", "tap", "untap", "detach"}


def keyword_rules(card_text, keywords):
    """The keyword rules that apply to a card's rules text: [(keyword, rule id)], in
    rule order, for the keyword abilities it has and keyword actions it performs
    (keywords from ComprehensiveRules.keywords())."""
    card_text = re.sub(r"\([^)]*\)", "", card_text or "")
    found = [(keyword, rule_id) for keyword, rule_id in keywords.items()
             if not (rule_id.startswith("701") and keyword in _COMMON_ACTIONS)
             and re.search(rf"\b{re.escape(keyword)}\b", card_text, re.IGNORECASE)]
    return sorted(found, key=lambda kv: [int(n) for n in kv[1].split(".")])


# Searching everything

NOTE_SOURCES = {"release": "Release Notes", "faq": "Set FAQ", "mechanic": "MTG Wiki", "set": "MTG Wiki"}


def search(needle, cr, library, document_parts, notes=()):
    """Everything with every word of needle in it, in the order the Rules window lists them:
    Game Concepts, verified rulings, the glossary, rules (also by number: "702.1"), the
    tournament documents, set notes and MTG Wiki pages, format rules and Commander Brackets.
    Each result is a dict: kind and key (what it opens), title and snippet, plus chapter (a
    rule's), heading (a document part's) or label (a note's source). document_parts(key) gives
    a tournament document's parts; notes are (id, info, text, lowercased text)."""
    words = needle.lower().split()

    def hit(text):
        text = text.lower()
        return all(word in text for word in words)

    def snippet(text):
        at = max(0, text.lower().find(words[0]) - 80)
        return ("…" if at else "") + text[at:at + 260] + ("…" if len(text) > at + 260 else "")

    found = [{"kind": "concept", "key": i, "title": g["title"], "snippet": snippet(" ".join(g["summary"]))}
             for i, g in enumerate(library["concepts"]) if hit(g["title"] + " " + " ".join(g["summary"]))]
    found += [{"kind": "interaction", "key": e, "title": e["question"], "snippet": e["explanation"]}
              for e in library["interactions"] if hit(e["question"] + " " + e["explanation"])]
    if cr:
        found += [{"kind": "glossary", "key": term, "title": term, "snippet": snippet(definition)}
                  for term, definition in cr.glossary if hit(term + " " + definition)]
        found += [{"kind": "rule", "key": rule.id, "title": rule.id, "chapter": chapter.title,
                   "snippet": snippet(rule.text)}
                  for section in cr.sections for chapter in section.chapters for rule in chapter.rules
                  if rule.id.startswith(needle) or hit(rule.text + " " + " ".join(rule.examples))]
    for key in ("mtr", "ipg", "jar"):
        found += [{"kind": "doc", "key": (key, index), "title": part.title, "heading": part.heading,
                   "snippet": snippet(part.text)}
                  for index, part in enumerate(document_parts(key)) if hit(part.title + " " + part.text)]
    # Set notes and MTG Wiki pages: the first line in each that matches
    for note_id, info, content, lower in notes:
        if all(word in lower for word in words):
            line = next((l for l in content.split("\n") if hit(l)), None)
            if line:
                found.append({"kind": "note", "key": note_id, "title": info["title"],
                              "label": NOTE_SOURCES[info["kind"]], "snippet": snippet(line)})
    for key in ("commander", "brawl", "oathbreaker"):
        if text(key) and hit(text(key)):
            found.append({"kind": "format", "key": key, "title": f"{DOCUMENTS[key][0]} format rules",
                          "snippet": snippet(text(key))})
    about_brackets = " ".join([b.name + " " + b.decks + " " + " ".join(b.limits) for b in brackets.BRACKETS]
                              + [term + " " + text for term, text in brackets.TERMS])
    if hit("commander brackets " + about_brackets):
        found.append({"kind": "brackets", "key": None, "title": "Commander Brackets", "snippet": snippet(about_brackets)})
    return found

