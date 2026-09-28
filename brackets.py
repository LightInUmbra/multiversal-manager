"""
Commander Brackets: Wizards' optional 1-5 scale for matching Commander decks by power
and intent, and what the deck builder checks a deck against.

- Game Changers come from Scryfall's card data (its game_changer flag follows Wizards'
  official list), so they work offline.
- Two-card infinite combos, mass land denial and extra-turn cards come from Commander
  Spellbook's bracket estimate when online. Offline, mass land denial and extra turns
  are read from the cards' rules text, and combos go unchecked.

Brackets 1 and 2, and 4 and 5, can't be told apart from a deck list: the difference is
intent (a theme deck, a cEDH deck). The rest is the official wording, as of the
October 21, 2025 update and the Game Changers changes of February 9, 2026.
"""

# Imports
import re
from dataclasses import dataclass, field

import requests

import scryfall

SPELLBOOK = "https://backend.commanderspellbook.com/estimate-bracket"
FEW_EXTRA_TURNS = 2  # ponytail: "low quantities" isn't a number; 2 is a guess, tune if it flags fair decks


@dataclass(frozen=True)
class Bracket:
    number: int
    name: str
    decks: str
    win_conditions: str
    gameplay: str
    turns: str
    limits: tuple  # the deck-building limits, as sentences


BRACKETS = [
    Bracket(1, "Exhibition", "Prioritize a goal, theme or idea over power. Rules around card legality or "
            "viable commanders can have some flexibility depending on the pod.",
            "Highly thematic or substandard.", "An opportunity to show off your creations.",
            "at least nine turns",
            ("No Game Changers.", "No two-card infinite combos.", "No mass land denial.", "No extra-turn cards.")),
    Bracket(2, "Core", "Unoptimized and straightforward, with some cards chosen to maximize creativity.",
            "Incremental, telegraphed on the board, and disruptable.",
            "Low pressure with an emphasis on social interaction; proactive and considerate, letting each deck "
            "showcase its plan.", "at least eight turns",
            ("No Game Changers.", "No two-card infinite combos.", "No mass land denial.",
             "Extra-turn cards only in low quantities, never chained or looped.")),
    Bracket(3, "Upgraded", "Powered up with strong synergy and high card quality; they can effectively disrupt "
            "opponents. Game Changers are likely to be value engines and game-ending spells.",
            "Can be deployed in one big turn from hand, usually because of steadily accrued resources.",
            "Many proactive and reactive plays.", "at least six turns",
            ("Up to three Game Changers.", "No early-game two-card infinite combos.", "No mass land denial.",
             "Extra-turn cards only in low quantities, never chained or looped.")),
    Bracket(4, "Optimized", "Lethal, consistent and fast, designed to take people down as fast as possible, but "
            "not built for the cEDH metagame. Game Changers are likely to be fast mana, snowballing resource "
            "engines, free disruption and tutors.", "Vary, but are efficient and instantaneous.",
            "Explosive and powerful, with huge threats and efficient disruption to match.", "at least four turns",
            ("Any number of Game Changers.", "No other limits beyond the banned list.")),
    Bracket(5, "cEDH", "Meticulously designed to battle in the cEDH (competitive Commander) metagame.",
            "Optimized for efficiency and consistency.",
            "Intricate and advanced, with razor-thin margins for error.", "any turn",
            ("Any number of Game Changers.", "No other limits beyond the banned list.")),
]

# The terms the limits use, for the rules window
TERMS = [
    ("Game Changers", "A list of cards, kept by the Commander Format Panel, that dramatically warp Commander "
     "games: efficient resource engines, fast mana, free interaction, the most efficient tutors, lock pieces "
     "and single-card wins. They aren't banned; they set the lowest bracket a deck can be. Your commander counts "
     "if it's on the list. The list is reviewed every few months."),
    ("Two-card infinite combos", "Two cards that together, with nothing else needed, make an infinite loop or "
     "win the game (Thassa's Oracle and Demonic Consultation, Kiki-Jiki and Zealous Conscripts). Brackets 1 and 2 "
     "have none. Bracket 3 allows combos that win late, after resources have built up, but not cheap ones that "
     "can go off in the early turns."),
    ("Mass land denial", "Cards that destroy, exile or bounce many lands, keep lands tapped, or change what "
     "mana lands make, without giving them back: Armageddon, Ruination, Winter Orb, Blood Moon. None below "
     "Bracket 4."),
    ("Extra turns", "Cards that give extra turns (Time Warp, Nexus of Fate). None in Bracket 1; a few in "
     "Brackets 2 and 3, but never chained one after another or looped."),
    ("Tutors", "Since October 2025 tutors have no limit of their own: the most efficient ones (Demonic Tutor, "
     "Vampiric Tutor, Mystical Tutor…) are Game Changers, and that covers them."),
    ("Rule zero", "Brackets are an optional way to find games with people who want the same kind of game. Say "
     "your deck's bracket before the game, and talk about anything unusual in it. A deck's intent matters more "
     "than its card list."),
]

HISTORY = [
    ("February 11, 2025", "Wizards introduces the Commander Brackets beta and the first Game Changers list."),
    ("April 22, 2025", "Game Changers changes and clarifications to the bracket definitions."),
    ("October 21, 2025", "The brackets are rewritten around intent and how many turns a game lasts. Tutor limits "
     "are removed (Game Changers cover the best ones), Bracket 2 is no longer tied to preconstructed decks, and "
     "ten cards leave the Game Changers list (among them Food Chain, Deflecting Swat, Kinnan, Urza, Winota and "
     "Yuriko)."),
    ("February 9, 2026", "Farewell becomes a Game Changer, and Biorhythm is unbanned as one. Lutri, the "
     "Spellchaser is unbanned without being a Game Changer."),
]

SOURCES = [
    ("Wizards: Commander format and brackets", "https://magic.wizards.com/en/formats/commander"),
    ("Commander Brackets update, October 21, 2025",
     "https://magic.wizards.com/en/news/announcements/commander-brackets-beta-update-october-21-2025"),
    ("Commander Brackets update, February 9, 2026",
     "https://magic.wizards.com/en/news/announcements/commander-brackets-beta-update-february-9-2026"),
    ("Commander Spellbook (combos)", "https://commanderspellbook.com"),
]


def bracket(number):
    return BRACKETS[number - 1]


def label(number):
    return f"Bracket {number}: {bracket(number).name}"


# Reading cards offline

_EXTRA_TURN = re.compile(r"(?<!can't )(?<!not )\btakes? (?:an?|one|two|three|x) extra turns?\b", re.IGNORECASE)
_MASS_LAND_DENIAL = re.compile(
    r"\b(?:destroy|exile|return) all [^.]{0,40}\blands\b|\beach player sacrifices (?:all|[a-z]+) [^.]{0,15}lands\b"
    r"|\blands don't untap\b|\bnonbasic lands are (?:mountains|islands|swamps|forests|plains)\b"
    r"|\bplayers can't untap more than\b", re.IGNORECASE)


def is_game_changer(card):
    return bool(card["game_changer"])


def is_extra_turn(card):
    return bool(_EXTRA_TURN.search(card["oracle_text"] or ""))


def is_mass_land_denial(card):
    return bool(_MASS_LAND_DENIAL.search(card["oracle_text"] or ""))


# Checking a deck

@dataclass(frozen=True)
class Combo:
    cards: tuple       # card names
    results: str       # what it makes ("Infinite damage, …")
    early: bool        # cheap and fast, or a lock / extra-turn loop: only Bracket 4+


@dataclass
class Report:
    game_changers: list = field(default_factory=list)
    mass_land_denial: list = field(default_factory=list)
    extra_turns: list = field(default_factory=list)
    combos: list = field(default_factory=list)
    combos_checked: bool = False  # False offline: combos are unknown, not absent

    def minimum(self):
        # The lowest bracket this deck's cards allow (1 means 1 or 2; 4 means 4 or 5)
        return next(n for n in (1, 2, 3, 4) if not self.broken(n))

    def broken(self, target):
        """[(why, card names)] for everything that keeps this deck out of bracket target"""
        found = []
        gcs = self.game_changers
        if target <= 2 and gcs:
            found.append((f"Bracket {target} has no Game Changers ({len(gcs)} here)", gcs))
        elif target == 3 and len(gcs) > 3:
            found.append((f"Bracket 3 allows up to three Game Changers ({len(gcs)} here)", gcs))
        if target <= 3 and self.mass_land_denial:
            found.append((f"Bracket {target} has no mass land denial", self.mass_land_denial))
        if target == 1 and self.extra_turns:
            found.append(("Bracket 1 has no extra-turn cards", self.extra_turns))
        elif target <= 3 and len(self.extra_turns) > FEW_EXTRA_TURNS:
            found.append((f"Bracket {target} keeps extra turns to a few ({len(self.extra_turns)} here)",
                          self.extra_turns))
        combos = self.combos if target <= 2 else [c for c in self.combos if c.early] if target == 3 else []
        for combo in combos:
            kind = "two-card infinite combos" if target <= 2 else "early-game two-card combos"
            found.append((f"Bracket {target} has no {kind} ({combo.results})", list(combo.cards)))
        return found


def counted(entries):
    # The cards that count toward brackets: the main deck and the command zone
    return [e for e in entries if e["section"] in ("Main", "Commander")]


def check(entries, spellbook=None):
    """A Report for a deck's entries (with game_changer and oracle_text). spellbook is
    fetch_spellbook()'s result for the same cards, or None to read the cards offline."""
    cards = counted(entries)
    report = Report(game_changers=sorted({e["name"] for e in cards if is_game_changer(e)}))
    if spellbook is None:
        report.mass_land_denial = sorted({e["name"] for e in cards if is_mass_land_denial(e)})
        report.extra_turns = sorted({e["name"] for e in cards if is_extra_turn(e)})
    else:
        report.game_changers = sorted(set(report.game_changers) | set(spellbook["game_changers"]))
        report.mass_land_denial = spellbook["mass_land_denial"]
        report.extra_turns = spellbook["extra_turns"]
        report.combos = spellbook["combos"]
        report.combos_checked = True
    return report


def fetch_spellbook(commanders, main):
    """Commander Spellbook's reading of a deck (card names): {"game_changers",
    "mass_land_denial", "extra_turns": names, "combos": [Combo]} with the two-card combos
    it finds. One request per call; raises OfflineError or requests errors."""
    scryfall._require_online()
    response = requests.post(SPELLBOOK, headers=scryfall.HEADERS, timeout=30, json={
        "commanders": [{"card": name} for name in commanders], "main": [{"card": name} for name in main]})
    response.raise_for_status()
    return read_spellbook(response.json())


def read_spellbook(data):
    # fetch_spellbook's result from Spellbook's JSON
    def names(flag):
        return sorted({c["card"]["name"] for c in data["cards"] if c.get(flag)})

    combos = []
    for found in data["combos"]:
        if not found.get("arguablyTwoCard"):
            continue
        variant = found["combo"]
        results = ", ".join(p["feature"]["name"] for p in variant["produces"][:3])
        early = (variant.get("bracketTag") == "R" or any(found.get(k) for k in
                 ("extraTurn", "lock", "massLandDenial", "skipTurns", "controlAllOpponents")))
        combos.append(Combo(tuple(u["card"]["name"] for u in variant["uses"]), results, early))
    return {"game_changers": names("gameChanger"), "mass_land_denial": names("massLandDenial"),
            "extra_turns": names("extraTurn"), "combos": combos}


def card_allowed(card, target, game_changers_left):
    # Whether a recommended card fits a deck aiming for bracket target (None: any)
    if target is None or target >= 4:
        return True
    if is_game_changer(card) and (target <= 2 or game_changers_left <= 0):
        return False
    if is_mass_land_denial(card):
        return False
    return not (target == 1 and is_extra_turn(card))
