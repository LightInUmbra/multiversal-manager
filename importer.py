"""
Reads a collection or deck list from a file and matches each entry to a Scryfall printing.

Supported inputs:
- CSV exports from this app, Moxfield, ManaBox, Deckbox, and most other tools --
  columns are recognized by header name, in any order
- Plain-text lists, one card per line: "4 Lightning Bolt", "1x Sol Ring (C21) 263 *F*"

Parsing is pure Python; resolve() is the only part that touches the network.
"""

# Imports
import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field

import copy_details
import scryfall

# Header aliases (lowercased, underscores as spaces) -> field
_HEADER_ALIASES = {
    "quantity": {"quantity", "count", "qty", "amount", "copies"},
    "name": {"name", "card name", "card", "cardname"},
    "set_code": {"set code", "set", "edition code", "setcode", "set id"},
    "set_name": {"set name", "setname"},
    "edition": {"edition"},  # set code in Moxfield, full set name in Deckbox
    "collector_number": {"collector number", "card number", "number", "cn", "collector no", "collector #"},
    "foil": {"foil", "finish", "printing"},
    "scryfall_id": {"scryfall id", "scryfallid", "scryfall uuid"},
    "condition": {"condition", "cond", "grade"},
    "language": {"language", "lang"},
    "notes": {"notes", "note", "comment", "comments"},
    "section": {"board", "section", "category", "zone"},
}
_FOIL_VALUES = {"foil", "etched", "true", "yes", "y", "1"}

# Deck sections, and the headers / board names other tools use for them. Cards under
# "About" (Arena's deck name line) aren't cards at all.
SECTIONS = ["Commander", "Companion", "Main", "Sideboard", "Maybeboard"]
_SECTION_NAMES = {
    "deck": "Main", "main": "Main", "mainboard": "Main", "main deck": "Main",
    "sideboard": "Sideboard", "side": "Sideboard", "sb": "Sideboard",
    "commander": "Commander", "commanders": "Commander",
    "companion": "Companion", "maybeboard": "Maybeboard", "maybe": "Maybeboard", "considering": "Maybeboard",
    "about": None,
}
_TEXT_SIDEBOARD_PREFIX = re.compile(r"^SB:\s*", re.IGNORECASE)
_TEXT_FOIL_MARKERS = re.compile(r"\s*(\*F\*|\*E\*|\(foil\)|\[foil\])\s*$", re.IGNORECASE)
_TEXT_QUANTITY = re.compile(r"^(\d+)\s*x?\s+(.+)$", re.IGNORECASE)
_TEXT_SET = re.compile(r"^(?P<name>.+?)\s+[\(\[](?P<set>[A-Za-z0-9]{2,6})[\)\]](?:\s+(?P<cn>\S+))?$")


@dataclass
class ImportRow:
    line: int
    quantity: int
    name: str = ""
    set_code: str = ""
    set_name: str = ""
    collector_number: str = ""
    foil: bool = False
    scryfall_id: str = ""
    condition: str = copy_details.DEFAULT_CONDITION
    language: str = copy_details.DEFAULT_LANGUAGE
    notes: str = ""
    section: str = "Main"  # deck section; only used when importing into a deck

    def details(self):
        # Condition, language and notes as add_card keywords
        return {"condition": self.condition, "language": self.language, "notes": self.notes}

    def describe(self):
        text = f"Line {self.line}: {self.quantity} {self.name or self.scryfall_id}"
        if self.set_code or self.set_name:
            text += f" ({self.set_code or self.set_name})"
        if self.collector_number:
            text += f" #{self.collector_number}"
        return text


@dataclass
class ImportResult:
    # (row, card) pairs for every row that matched
    matched: list = field(default_factory=list)
    # rows that matched by name only, so the printing may not be the one in the file
    approximate: list = field(default_factory=list)
    unmatched: list = field(default_factory=list)


# Parsing

def parse_file(path):
    # (rows, errors). utf-8-sig strips the byte-order mark Excel likes to add.
    with open(path, encoding="utf-8-sig", newline="") as f:
        text = f.read()
    if path.lower().endswith(".csv") or _looks_like_csv(text):
        return parse_csv(text)
    return parse_text(text)


def _normalize_header(header):
    return " ".join((header or "").replace("_", " ").strip().lower().split())


def _looks_like_csv(text):
    first_line = text.lstrip().split("\n", 1)[0]
    headers = {_normalize_header(h) for h in re.split(r"[,;\t]", first_line)}
    return bool(headers & _HEADER_ALIASES["name"]) or bool(headers & _HEADER_ALIASES["scryfall_id"])


def parse_csv(text):
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    headers = next(reader, None)
    if not headers:
        return [], ["The file is empty."]

    columns = {}
    for index, header in enumerate(headers):
        normalized = _normalize_header(header)
        for field_name, aliases in _HEADER_ALIASES.items():
            if normalized in aliases and field_name not in columns:
                columns[field_name] = index
    if "name" not in columns and "scryfall_id" not in columns:
        return [], ["Couldn't find a card name column. Expected a header like “Name” or “Card Name”."]

    rows, errors = [], []
    for line_number, values in enumerate(reader, start=2):
        if not any(v.strip() for v in values):
            continue

        def get(field_name):
            index = columns.get(field_name)
            return values[index].strip() if index is not None and index < len(values) else ""

        quantity_text = get("quantity") or "1"
        try:
            quantity = int(float(quantity_text))
        except ValueError:
            errors.append(f"Line {line_number}: quantity “{quantity_text}” isn't a number")
            continue
        if quantity <= 0:
            continue

        set_code, set_name = get("set_code"), get("set_name")
        edition = get("edition")
        if edition:
            # Short and space-free means a set code (Moxfield), otherwise a set name (Deckbox)
            if re.fullmatch(r"[A-Za-z0-9]{2,6}", edition):
                set_code = set_code or edition
            else:
                set_name = set_name or edition

        row = ImportRow(
            line=line_number,
            quantity=quantity,
            name=get("name"),
            set_code=set_code.lower(),
            set_name=set_name,
            collector_number=get("collector_number"),
            foil=get("foil").lower() in _FOIL_VALUES,
            scryfall_id=get("scryfall_id").lower(),
            condition=copy_details.parse_condition(get("condition")),
            language=copy_details.parse_language(get("language")),
            notes=get("notes"),
            section=_SECTION_NAMES.get(get("section").lower()) or "Main",
        )
        if not row.name and not row.scryfall_id:
            errors.append(f"Line {line_number}: no card name")
            continue
        rows.append(row)
    return rows, errors


def parse_text(text):
    rows, errors = [], []
    section = "Main"
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith(("#", "//")):
            continue
        header = line.rstrip(":").strip().lower()
        if header in _SECTION_NAMES:
            section = _SECTION_NAMES[header]
            continue
        if section is None:  # lines under "About"
            continue

        row_section = section
        if _TEXT_SIDEBOARD_PREFIX.match(line):  # older .dec files: "SB: 2 Duress"
            line, row_section = _TEXT_SIDEBOARD_PREFIX.sub("", line), "Sideboard"

        foil = False
        marker = _TEXT_FOIL_MARKERS.search(line)
        if marker:
            foil = True
            line = line[:marker.start()].strip()

        quantity = 1
        match = _TEXT_QUANTITY.match(line)
        if match:
            quantity, line = int(match.group(1)), match.group(2).strip()
        if quantity <= 0:
            continue

        name, set_code, number = line, "", ""
        match = _TEXT_SET.match(line)
        if match:
            name, set_code, number = match.group("name"), match.group("set").lower(), match.group("cn") or ""

        rows.append(ImportRow(line=line_number, quantity=quantity, name=name.strip(),
                              set_code=set_code, collector_number=number, foil=foil, section=row_section))
    if not rows and not errors:
        errors.append("No cards found in the file.")
    return rows, errors


# Matching

def _front_face(name):
    # Split and double-faced cards are "Front // Back" on Scryfall (some files write
    # "Front/Back"), but Scryfall's bulk lookup only accepts the front face's name
    return re.split(r"\s*//?\s*", name, maxsplit=1)[0].strip()


def _name_key(name):
    # Files may also drop accents ("Lim-Dul's Vault") or use curly quotes
    name = _front_face(name).replace("’", "'")
    name = unicodedata.normalize("NFKD", name)
    return "".join(c for c in name if not unicodedata.combining(c)).strip().lower()


def _identifiers(row):
    # Most to least specific. Each is (Scryfall identifier, key to match the result by).
    options = []
    if row.scryfall_id:
        options.append(({"id": row.scryfall_id}, ("id", row.scryfall_id)))
    if row.set_code and row.collector_number:
        options.append(({"set": row.set_code, "collector_number": row.collector_number},
                        ("print", row.set_code, row.collector_number.lower())))
    if row.name and row.set_code:
        options.append(({"name": _front_face(row.name), "set": row.set_code},
                        ("name+set", _name_key(row.name), row.set_code)))
    if row.name:
        options.append(({"name": _front_face(row.name)}, ("name", _name_key(row.name))))
    return options


def _keys_for(card):
    set_code = card.set.lower()
    name = _name_key(card.name)
    return [
        ("id", card.id),
        ("print", set_code, (card.collector_number or "").lower()),
        ("name+set", name, set_code),
        ("name", name),
    ]


# Fuzzy lookups are one request each, so only the first this many unmatched rows get one
MAX_FUZZY_LOOKUPS = 100


def resolve(rows, lookup=None, set_codes=None, fuzzy=None):
    """Matches rows to Scryfall printings. If a row's most specific identifier
    isn't found (a typo'd collector number, say), it's retried with the next one,
    falling back to name only. Rows still unmatched get a fuzzy name lookup, which
    also catches alternate card names like Secret Lair's "Unstable Harmonics"
    (Rhystic Study); those always count as approximate so the user confirms them."""
    lookup = lookup or scryfall.get_collection
    set_codes = set_codes or scryfall.get_set_codes
    fuzzy = fuzzy or scryfall.fuzzy_card
    if any(row.set_name and not row.set_code for row in rows):
        codes = set_codes()
        for row in rows:
            if row.set_name and not row.set_code:
                row.set_code = codes.get(row.set_name.lower(), "")

    result = ImportResult()
    # (row, identifiers still to try, whether it has already fallen back from
    # what the file specified). A set name we couldn't map counts as a fallback.
    pending = [(row, _identifiers(row), bool(row.set_name and not row.set_code)) for row in rows]
    while pending:
        # Rows with the same identifier share one lookup
        by_key = {}
        for row, options, _ in pending:
            identifier, key = options[0]
            by_key.setdefault(key, (identifier, []))[1].append(row)

        found = {}
        for card in lookup([identifier for identifier, _ in by_key.values()]):
            for key in _keys_for(card):
                found.setdefault(key, card)

        still_pending = []
        for row, options, fell_back in pending:
            card = found.get(options[0][1])
            # A set + number (or id) that points at a differently named card means the
            # file's printing info is wrong -- trust the name and keep falling back
            if card is not None and row.name and _name_key(card.name) != _name_key(row.name):
                card = None
            if card is not None:
                result.matched.append((row, card))
                if fell_back:
                    result.approximate.append((row, card))
            elif len(options) > 1:
                still_pending.append((row, options[1:], True))
            else:
                result.unmatched.append(row)
        pending = still_pending

    unmatched, result.unmatched = result.unmatched, []
    for index, row in enumerate(unmatched):
        card = fuzzy(row.name) if row.name and index < MAX_FUZZY_LOOKUPS else None
        if card is None:
            result.unmatched.append(row)
        else:
            result.matched.append((row, card))
            result.approximate.append((row, card))
    return result


def card_records(result):
    # add_card keyword dicts for every matched row
    return [{**scryfall.card_record(card, foil=row.foil, quantity=row.quantity), **row.details()}
            for row, card in result.matched]
