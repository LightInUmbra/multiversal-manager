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
from pathlib import Path

import requests

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


def rules_dir():
    # Next to the collection, so the whole app folder stays portable
    return Path(db.DB_NAME).parent / "rules"


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


def update(progress=None):
    """Downloads whatever's missing or has a newer version: every document, and the card
    rulings. Returns (titles of what changed, errors). Anything that fails to download
    keeps its saved copy."""
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
        with requests.get(info["jsonl_download_uri"], headers=HEADERS, timeout=TIMEOUT, stream=True) as response:
            response.raise_for_status()
            with gzip.open(response.raw, "rt", encoding="utf-8") as lines:
                db.replace_rulings(json.loads(line) for line in lines if line.strip())
        return info["updated_at"], None
    attempt("rulings", total, rulings)
    return changed, errors


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
                       "has", "there", "one", "they", "their", "card", "cards", "creature", "creatures"}


@dataclass
class Passage:
    kind: str          # "card", "ruling", "rule" or "glossary"
    ref: str           # "702.49a", a card name, or a glossary term
    text: str
    why: str           # what in the question brought it in


def mentioned_cards(question, names, rules_terms=()):
    """The card names (out of names) a question mentions, longest first, leaving out
    names that are only part of a longer one mentioned ("Iron" in "Iron Maiden"). Names
    have to be written as names, capitalized ("Clone", not "clone"); a split card's
    one-word half ("Turn" of Turn // Burn) and names that are also rules terms
    (rules_terms: "Exile", "Lifelink") only count as part of the full name."""
    terms = {t.lower() for t in rules_terms}
    found = []
    for name in sorted(names, key=len, reverse=True):
        forms = [name]
        front = name.split(" // ")[0]
        if front != name and " " in front:
            forms.append(front)
        for form in forms:
            if len(form) < 4 or (form == name and name.lower() in terms):
                continue
            if re.search(rf"(?<![\w']){re.escape(form)}(?![\w'])", question):
                if not any(form in longer for longer in found):
                    found.append(name)
                break
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


def _content_words(text):
    return {w for w in _TOKEN.findall(text.lower()) if w not in _QUESTION_STOPWORDS and len(w) > 2}


def similar_interactions(question, library, limit=3, threshold=0.25):
    """The library's verified interactions closest to a question: [(score 0-1, entry)],
    best first. Words they share count by how rare they are in the library ("ninjutsu"
    says more than "attack"), and so do game concepts they share."""
    entries = library["interactions"]
    words_of = [_content_words(e["question"]) | {f"concept:{c}" for c in concepts_in(e["question"])}
                for e in entries]
    counts = Counter(w for words in words_of for w in words)
    idf = {w: math.log((len(entries) + 1) / n) + 0.5 for w, n in counts.items()}
    asked = _content_words(question) | {f"concept:{c}" for c in concepts_in(question)}
    asked_weight = sum(idf.get(w, math.log(len(entries) + 1) + 0.5) for w in asked) or 1
    scored = []
    for entry, words in zip(entries, words_of):
        shared = sum(idf[w] for w in asked & words)
        score = shared / math.sqrt(asked_weight * sum(idf[w] for w in words))
        if score >= threshold:
            scored.append((round(score, 2), entry))
    return sorted(scored, key=lambda s: -s[0])[:limit]


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
