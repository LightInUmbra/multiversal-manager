"""
Magic formats and deck legality: deck size, sideboard size, copy limits, banned and
restricted cards, and commander color identity. Card legality comes from Scryfall
(per format: legal, not_legal, restricted or banned).
"""

# Imports
import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Format:
    label: str
    deck_size: int = 60          # minimum main deck size (exact for commander-style formats)
    exact: bool = False          # deck must be exactly deck_size
    sideboard: int | None = 15   # most cards allowed in the sideboard (+ companion); None = no limit
    copies: int = 4              # most copies of a card, basic lands aside; 0 = no limit
    commander: bool = False      # has a command zone; every card must fit its color identity
    arena: bool = False          # an MTG Arena format


# Keys are Scryfall's legality keys. Commander-style decks count the command zone
# toward their size (100 cards including the commander).
FORMATS = {
    "casual": Format("Casual (no restrictions)", deck_size=0, sideboard=None, copies=0),
    "standard": Format("Standard"),
    "pioneer": Format("Pioneer"),
    "modern": Format("Modern"),
    "legacy": Format("Legacy"),
    "vintage": Format("Vintage"),
    "pauper": Format("Pauper"),
    "premodern": Format("Premodern"),
    "oldschool": Format("Old School"),
    "penny": Format("Penny Dreadful"),
    "commander": Format("Commander", 100, True, None, 1, True),
    "oathbreaker": Format("Oathbreaker", 60, True, None, 1, True),
    "paupercommander": Format("Pauper Commander", 100, True, None, 1, True),
    "duel": Format("Duel Commander", 100, True, None, 1, True),
    "predh": Format("PreDH", 100, True, None, 1, True),
    "future": Format("Future Standard"),
    "historic": Format("Historic", arena=True),
    "timeless": Format("Timeless", arena=True),
    "explorer": Format("Explorer", arena=True),
    "alchemy": Format("Alchemy", arena=True),
    "brawl": Format("Brawl", 100, True, None, 1, True, arena=True),
    "standardbrawl": Format("Standard Brawl", 60, True, None, 1, True, arena=True),
    "gladiator": Format("Gladiator", 100, True, None, 1, arena=True),
}

# Sections that count toward the deck. Maybeboard never counts.
MAIN_SECTIONS = {"Main", "Commander"}
SIDE_SECTIONS = {"Sideboard", "Companion"}

_ANY_NUMBER = re.compile(r"A deck can have any number of cards named", re.IGNORECASE)
_UP_TO = re.compile(r"A deck can have up to (\w+) cards named", re.IGNORECASE)
_NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def label(key):
    return FORMATS[key].label if key in FORMATS else key


def copy_limit(entry, fmt):
    # Most copies allowed of a card, or None for no limit
    type_line, text = entry["type_line"] or "", entry["oracle_text"] or ""
    if not fmt.copies or ("Basic" in type_line and "Land" in type_line) or _ANY_NUMBER.search(text):
        return None
    match = _UP_TO.search(text)
    if match:
        word = match.group(1).lower()
        return _NUMBER_WORDS.get(word) or (int(word) if word.isdigit() else fmt.copies)
    return fmt.copies


def can_be_commander(entry, key):
    # Legendary creatures (and cards that say so) lead commander decks; Brawl also allows
    # legendary planeswalkers, and Oathbreaker uses a planeswalker plus a signature spell
    if entry["legalities"] is None:
        return True  # unknown card: don't guess
    front = (entry["type_line"] or "").split("//")[0]
    if key == "oathbreaker":
        return any(t in front for t in ("Planeswalker", "Instant", "Sorcery"))
    return ("can be your commander" in (entry["oracle_text"] or "")
            or ("Legendary" in front and "Creature" in front)
            or "Background" in front  # partners with a "Choose a Background" creature
            or (key in ("brawl", "standardbrawl") and "Legendary" in front and "Planeswalker" in front))


def legality(entry, key):
    # Scryfall's legality of a card in a format, or None when the card isn't in the card database
    if not entry["legalities"]:
        return None
    return json.loads(entry["legalities"]).get(key, "not_legal")


def validate(entries, key):
    """Checks a deck against a format. entries need id, name, quantity, section,
    legalities (Scryfall's JSON), type_line, color_identity and oracle_text.
    Returns (problems, statuses): deck-level problems as sentences, and {entry id:
    short status} for every entry that breaks a rule."""
    fmt = FORMATS.get(key, FORMATS["casual"])
    problems, statuses = [], {}
    if key not in FORMATS or key == "casual":
        return problems, statuses

    counted = [e for e in entries if e["section"] in MAIN_SECTIONS | SIDE_SECTIONS]
    main = sum(e["quantity"] for e in entries if e["section"] == "Main")
    commanders = [e for e in entries if e["section"] == "Commander"]
    in_command_zone = sum(e["quantity"] for e in commanders)
    side = sum(e["quantity"] for e in entries if e["section"] in SIDE_SECTIONS)

    # Deck size
    size = main + in_command_zone
    if fmt.exact and size != fmt.deck_size:
        problems.append(f"{fmt.label} decks have exactly {fmt.deck_size} cards"
                        f"{' including the commander' if fmt.commander else ''} (this one has {size}).")
    elif not fmt.exact and size < fmt.deck_size:
        problems.append(f"{fmt.label} decks need at least {fmt.deck_size} main deck cards (this one has {size}).")
    if fmt.sideboard is not None and side > fmt.sideboard:
        problems.append(f"Sideboards hold at most {fmt.sideboard} cards (this one has {side}).")

    # Command zone and color identity
    if fmt.commander:
        if not commanders:
            problems.append("Choose a commander: right-click a card and move it to Commander.")
        else:
            identity = set("".join(e["color_identity"] or "" for e in commanders))
            for e in counted:
                if e["color_identity"] is not None and not set(e["color_identity"]) <= identity:
                    statuses[e["id"]] = "Outside color identity"
            for e in commanders:
                if not can_be_commander(e, key):
                    statuses[e["id"]] = "Can't be a commander"
    elif commanders:
        problems.append(f"{fmt.label} has no commander; move {commanders[0]['name']} to Main.")

    # Copies, bans and restrictions
    by_name = {}
    for e in counted:
        by_name.setdefault(e["name"].lower(), []).append(e)
    unknown = 0
    for group in by_name.values():
        copies = sum(e["quantity"] for e in group)
        status = legality(group[0], key)
        limit = copy_limit(group[0], fmt)
        if status is None:
            unknown += 1
        if any(e["id"] in statuses for e in group):
            continue  # already marked (color identity or commander) -- one reason per card
        if status == "banned":
            text = "Banned"
        elif status == "not_legal":
            text = "Not legal"
        elif status == "restricted" and copies > 1:
            text = "Restricted (1 copy)"
        elif limit is not None and copies > limit:
            text = f"Too many ({copies}, max {limit})"
        else:
            continue
        for e in group:
            statuses[e["id"]] = text

    broken = len({e["name"].lower() for e in counted if e["id"] in statuses})
    if broken:
        problems.append(f"{broken} card{'s break' if broken != 1 else ' breaks'} the {fmt.label} rules "
                        "(marked in red).")
    if unknown:
        problems.append(f"Legality unknown for {unknown} card{'s' if unknown != 1 else ''} until the "
                        "card database is downloaded.")
    return problems, statuses


# Card types, in the order decks are usually summarized; a card counts as its first match
CARD_TYPES = ["Creature", "Planeswalker", "Battle", "Instant", "Sorcery", "Artifact", "Enchantment", "Land"]


def type_counts(entries):
    # {card type: copies} over the main deck and command zone
    counts = {}
    for e in entries:
        if e["section"] in MAIN_SECTIONS:
            front = (e["type_line"] or "").split("//")[0]
            kind = next((t for t in CARD_TYPES if t in front), "Other")
            counts[kind] = counts.get(kind, 0) + e["quantity"]
    return counts
