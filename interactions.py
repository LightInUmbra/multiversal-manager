"""
Which cards work together, worked out from the cards themselves: the app's own interaction
data, with no play counts (EDHREC) involved. Two kinds of evidence:

- Rulings: an official ruling on one card that names another (Mindlock Orb's rulings name
  Arcbound Ravager). The strongest sign, since Wizards wrote it about exactly that pair.
- Roles: what a card makes (tokens, +1/+1 counters, creatures dying…) and what it pays off,
  read from its rules text. A card that makes what another pays off works with it.

Every app ships the data (interactions.json.gz, next to this file) and reads it with load().
It's built from the desktop's card database and rulings: open the Deck Builder and the Rules
window once so both are downloaded, then now and then run this and commit the file:

    python interactions.py build

Every release rebuilds it anyway (.github/workflows/release.yml), downloading both first into
a throwaway database, so each version ships up-to-date data:

    python interactions.py build --download
"""

# Imports
import gzip
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

PATH = Path(__file__).resolve().parent / "interactions.json.gz"
# A ruling naming both cards, against 1 for a role they share: strong, but a ruling says they
# interact, which isn't always in each other's favor (Humility and Me, the Immortal)
RULING_WEIGHT = 2
WORD_USES = 3       # a one-word name written in lowercase this often in rulings is a word ("Consider")
# A card the rulings of more cards than this name is their stock example ("such as Stifle",
# "if you control Doubling Season") or a term (Two-Headed Giant, the format), not a partner
MAX_REFERENCES = 15
# A ruling word for word on this many cards explains a mechanic ("prepare", cascade), not the
# card: over half of what rulings matched came from these, so they're left out
BOILERPLATE = 10
_EXAMPLE_CLAUSE = re.compile(r"(?:such as|for example|e\.g\.,?)[^.;:)]*", re.IGNORECASE)
_CAPITALIZED_RUN = re.compile(r"[A-Z][\w'-]*(?:\s+(?:(?:of|the)\s+)*[A-Z][\w'-]*)+")  # "Wizards of the Coast"
_EXAMPLE = re.compile(r"(?:such as|for example|e\.g\.,?)[^.;:)]*$", re.IGNORECASE)
SUMMARY_SHOWN = 4   # example cards per line of a card's "Works well with"


@dataclass(frozen=True)
class Mechanic:
    noun: str            # what it's about, for a card's summary ("tokens")
    makes: str           # rules text (regex) of a card that makes it
    uses: str            # rules text (regex) of a card that pays it off
    maker: str           # why a maker works with a payoff, from the maker's side ({other}: the payoff)
    user: str            # ... from the payoff's side ({other}: the maker)
    types: tuple = ()    # card types that make it by being one (an artifact is an artifact)
    weight: float = 1.0  # how much a shared role says; a broad one (blink: every enters ability) less


MECHANICS = {
    "tokens": Mechanic(
        "tokens", r"\bcreates?\b[^.]*\btokens?\b|\bpopulate\b",
        r"\bwhenever (?:a|one or more|another)\b[^.]*\btokens?\b[^.]*\benters?\b|\btokens? you control (?:get|have)\b|"
        r"\bfor each (?:creature )?token\b|\bwould create\b[^.]*\btokens?\b",
        "makes tokens for {other}", "pays off the tokens {other} makes"),
    "counters": Mechanic(
        "+1/+1 counters", r"\bput\b[^.]*\+1/\+1 counters?\b|\benters with\b[^.]*\+1/\+1 counters?|\bproliferate\b|"
                          r"\bevolve\b|\badapt\b|\bbolster\b|\boutlast\b",
        r"\bwhenever\b[^.]*\+1/\+1 counters? (?:is|are) put\b|\bwith (?:a|one or more) \+1/\+1 counters? on (?:it|them)\b|"
        r"\bfor each \+1/\+1 counter\b|\bcounters? would be put\b|\bwould put\b[^.]*\bcounters?\b",
        "puts +1/+1 counters out for {other}", "pays off the +1/+1 counters {other} puts out"),
    "deaths": Mechanic(
        "creatures dying", r"\bsacrifices? (?:a|an|another|any number of|one or more) (?:other )?(?:creatures?|permanents?|"
                           r"artifacts? or creatures?|nonland permanents?)\b|\bdestroy all creatures\b",
        r"\bwhenever\b[^.]*\bdies\b|\bwhenever you sacrifice\b|\bis put into a graveyard from the battlefield\b",
        "sacrifices creatures for {other}", "pays off the creatures {other} sacrifices"),
    "graveyard": Mechanic(
        "a full graveyard", r"\bmills?\b|\bput the top\b[^.]*\binto (?:your|their) graveyard\b|\bdiscards?\b|\bsurveil\b",
        r"\bfrom your graveyard\b|\bcards? in your graveyard\b|\bflashback\b|\bescape\b|\bunearth\b|\bdelve\b|\bdredge\b",
        "fills the graveyard for {other}", "uses the graveyard {other} fills"),
    "lifegain": Mechanic(
        "life gain", r"\bgains? (?:\d+|x|that much|twice that much) life\b|\blifelink\b",
        r"\bwhenever you gain life\b|\bif you would gain life\b|\bfor each 1 life you gained\b",
        "gains life for {other}", "pays off the life {other} gains"),
    "draw": Mechanic(
        "card draw", r"\bdraws? (?:a|an additional|two|three|four|five|seven|x|that many) cards?\b",
        r"\bwhenever (?:you|a player|an opponent|each player) draws?\b|\byour second card each turn\b",
        "draws cards for {other}", "pays off the cards {other} draws"),
    "spells": Mechanic(
        "instants and sorceries", "",
        r"\bwhenever you cast (?:an|your first|your second) instant or sorcery\b|\binstant (?:and|or) sorcery spells? you cast\b|"
        r"\bmagecraft\b|\bprowess\b|\bfor each instant (?:and|or) sorcery card\b",
        "is an instant or sorcery for {other}", "pays off instants and sorceries like {other}",
        types=("Instant", "Sorcery")),
    "artifacts": Mechanic(
        "artifacts", r"\bcreates?\b[^.]*\b(?:treasure|clue|food|blood|map|powerstone|gold|incubator)\b|"
                     r"\bartifact (?:creature )?tokens?\b",
        r"\bwhenever (?:an|another|one or more) (?:nontoken )?artifacts?\b[^.]*\benters?\b|\bfor each artifact\b|"
        r"\bartifact spells? you cast\b|\baffinity for artifacts\b|\bimprovise\b|\bmetalcraft\b|\bartifacts you control\b",
        "brings artifacts for {other}", "pays off the artifacts {other} brings", types=("Artifact",)),
    "enchantments": Mechanic(
        "enchantments", "",
        r"\bwhenever (?:an|another) (?:nontoken )?enchantment\b[^.]*\benters?\b|\bconstellation\b|"
        r"\benchantment spells? you cast\b|\bfor each enchantment\b|\benchantments you control\b",
        "is an enchantment for {other}", "pays off enchantments like {other}", types=("Enchantment",)),
    "landfall": Mechanic(
        "lands entering", r"\bplay an additional land\b|\bput (?:a|up to \w+|that|those|all) (?:basic )?lands? cards?\b"
                          r"[^.]*\bonto the battlefield\b|\bsearch your library for\b[^.]*\blands? cards?\b[^.]*"
                          r"\bonto the battlefield\b",
        r"\bwhenever (?:a|one or more) lands? (?:you control )?enters?\b|\blandfall\b",
        "puts lands out for {other}", "pays off the lands {other} puts out"),
    "blink": Mechanic(
        "enters abilities, repeated", r"\breturn (?:it|that card|them|those cards|the exiled cards?) to the battlefield\b",
        r"\bwhen\b[^.]*\benters\b(?! tapped)",
        "can blink {other} to repeat its enters ability", "has an enters ability {other} can repeat", weight=0.5),
    "attachments": Mechanic(
        "Auras and Equipment", "",
        r"\bfor each (?:aura|equipment)\b|\bwhenever (?:an? )?(?:aura|equipment)\b[^.]*\b(?:enters|becomes attached)\b|"
        r"\b(?:aura|equipment) spells? you cast\b|\b(?:equipped|enchanted) creatures you control\b",
        "is an Aura or Equipment for {other}", "pays off Auras and Equipment like {other}", types=("Aura", "Equipment")),
}
_MAKES = {key: re.compile(m.makes, re.IGNORECASE) for key, m in MECHANICS.items() if m.makes}
_USES = {key: re.compile(m.uses, re.IGNORECASE) for key, m in MECHANICS.items()}
# A replacement effect only pays off: Hardened Scales ("would be put… instead") puts no counters out itself
_REPLACEMENT = re.compile(r"\bwould\b|\binstead\b", re.IGNORECASE)
_NONE = (frozenset(), frozenset())


# Roles

def roles_of(card):
    """(makes, uses): the MECHANICS a card (name, type_line, oracle_text) makes and pays off,
    from its type line and rules text, reminder text left out."""
    front = (card["type_line"] or "").split("//")[0]
    text = re.sub(r"\([^)]*\)", "", card["oracle_text"] or "")
    plain = " ".join(s for s in re.split(r"(?<=[.\n])", text) if not _REPLACEMENT.search(s))
    makes = {key for key, m in MECHANICS.items()
             if any(t in front for t in m.types) or (key in _MAKES and _MAKES[key].search(plain))}
    uses = {key for key, pattern in _USES.items() if pattern.search(text)}
    return frozenset(makes), frozenset(uses)


# Rulings

def own_rulings(rulings):
    """{card: [ruling, …]} without the rulings shared word for word by BOILERPLATE or more
    cards: those explain a mechanic every card with it has, and say nothing about the card."""
    copies = Counter(text for texts in rulings.values() for text in set(texts))
    return {name: kept for name, texts in rulings.items() if (kept := [t for t in texts if copies[t] < BOILERPLATE])}


def ruling_links(cards, rulings, set_names=(), subtypes=()):
    """{(card, other): ruling} for the rulings on a card that name another card. rulings:
    {card: [ruling, …]}. Some names show up in rulings as something else, so they don't count:
    plain words and rules terms ("Sacrifice", "Consider"), set names ("Aether Revolt"),
    subtypes ("Shapeshifter", "Desert"), a name inside a longer one ("Excavator" in Ramunap
    Excavator), stock examples ("such as Stifle") and cards named by the rulings of more than
    MAX_REFERENCES cards. A split or two-faced card counts by either face."""
    words = Counter(w for texts in rulings.values() for text in texts for w in re.findall(r"\b[a-z][a-z']+\b", text))
    left_out = set(set_names) | set(subtypes)
    faces = {}
    for name in cards:
        for face in {name, *name.split(" // ")}:
            word_like = " " not in face and words[face.lower()] >= WORD_USES
            if len(face) >= 4 and face not in left_out and not word_like:
                faces[face] = name
    by_first = defaultdict(list)  # a name's first word -> the names starting with it, longest first
    for face in sorted(faces, key=len, reverse=True):
        by_first[face.split()[0]].append(face)
    links = {}
    for name, texts in rulings.items():
        for text in texts:
            free = 0  # where the text after the last name found starts
            for match in re.finditer(r"[A-Z][^\s]*", text):
                start = match.start()
                if start < free:
                    continue
                for face in by_first.get(match.group(), ()):
                    end = start + len(face)
                    if text.startswith(face, start) and not (end < len(text) and text[end].isalnum()):
                        free = end
                        if faces[face] != name and not _EXAMPLE.search(text[:start]):
                            links.setdefault((name, faces[face]), text)
                        break
    named_by = Counter(other for _, other in links)
    return {pair: text for pair, text in links.items() if named_by[pair[1]] <= MAX_REFERENCES}


def ruling_themes(cards, rulings, themes, creature_types=(), tribal=None):
    """{card: [theme key, …]} for the themes (synergy.THEMES) a card's rulings match but its own
    type line and rules text don't: all synergy.score() needs of the rulings, small enough for
    the website to have (the rulings themselves are about 4 MB). cards: {name: card}. With
    creature_types and tribal (synergy.tribal_theme), the creature types too, as the tribal
    theme keys ("tribal:Elf") the deck builder makes of them."""
    type_words = set(creature_types)

    def names_out(text, name):
        # Types are what's left once names and examples are out: the card's own name (Ramses,
        # Assassin Lord), examples ("such as Fungus or Archer"), and any capitalized run with a
        # word that isn't a type (Two-Headed Giant, The Lord of the Rings; "Human Wizard" stays)
        text = text.replace("’", "'")  # rulings write "Wurm’s Tooth" as often as "Wurm's Tooth"
        text = re.sub(r"\S+\.(?:com|org|net)\S*", " ", text)  # "please visit Wizards.com"
        for own in {name, *name.split(" // "), name.split(",")[0]}:
            text = text.replace(own, " ")
        text = _EXAMPLE_CLAUSE.sub(" ", text)
        return _CAPITALIZED_RUN.sub(lambda m: m.group() if set(m.group().split()) <= type_words else " ", text)

    found = {}
    for name, texts in rulings.items():
        card = cards.get(name)
        if card is None:
            continue
        own, text = f"{card['type_line'] or ''}\n{card['oracle_text'] or ''}", "\n".join(texts)
        keys = [key for key, t in themes.items()
                if re.search(t.cards, text, re.IGNORECASE) and not re.search(t.cards, own, re.IGNORECASE)]
        # Types are capitalized, so case counts ("Elf", not "itself"); a type's first letters
        # rule out most of them before any pattern runs ("Wol" finds Wolf and Wolves)
        typed = names_out(text, name) if creature_types else ""
        keys += [f"tribal:{kind}" for kind in creature_types if kind[:-1] in typed
                 and re.search(tribal(kind).cards, typed) and not re.search(tribal(kind).cards, own)]
        if keys:
            found[name] = keys
    return found


# The data

class Interactions:
    """The shipped data, ready to ask: which cards work with a card, and why."""

    def __init__(self, data=None):
        data = data or {}
        self.built = data.get("built")
        roles = data.get("roles", {})
        self.roles = {name: (frozenset(entry[0]), frozenset(entry[1])) for name, entry in roles.items()}
        self.cmc = {name: entry[2] for name, entry in roles.items() if len(entry) > 2}
        # The themes each card's rulings match (see ruling_themes), for where the rulings aren't
        self.ruling_themes = {name: frozenset(keys) for name, keys in data.get("ruling_themes", {}).items()}
        self.rulings = defaultdict(dict)
        for card, other, ruling in data.get("rulings", []):
            self.rulings[card][other] = ruling
            self.rulings[other].setdefault(card, ruling)
        self.makers, self.users = defaultdict(set), defaultdict(set)
        for name, (makes, uses) in self.roles.items():
            for key in makes:
                self.makers[key].add(name)
            for key in uses:
                self.users[key].add(name)

    def roles_for(self, card):
        # A card's roles: from the data, or worked out from its text (a card newer than the data)
        name = card if isinstance(card, str) else card["name"]
        if name in self.roles:
            return self.roles[name]
        return _NONE if isinstance(card, str) else roles_of(card)

    def reasons(self, card, other):
        """[(weight, why)] card works with other, strongest first, from card's side ("makes
        tokens for Rhys"). card and other: names, or dicts with name, type_line, oracle_text."""
        name = card if isinstance(card, str) else card["name"]
        other_name = other if isinstance(other, str) else other["name"]
        if name == other_name:
            return []
        found = []
        if other_name in self.rulings.get(name, {}):
            found.append((RULING_WEIGHT, f"a ruling covers it with {other_name}"))
        makes, uses = self.roles_for(card)
        other_makes, other_uses = self.roles_for(other)
        found += [(MECHANICS[key].weight, MECHANICS[key].maker.format(other=other_name)) for key in sorted(makes & other_uses)]
        found += [(MECHANICS[key].weight, MECHANICS[key].user.format(other=other_name)) for key in sorted(uses & other_makes)]
        return sorted(found, key=lambda f: -f[0])

    def partners(self, card):
        """{other card: total weight} for every card this works with, by rulings and roles."""
        name = card if isinstance(card, str) else card["name"]
        makes, uses = self.roles_for(card)
        found = Counter({other: RULING_WEIGHT for other in self.rulings.get(name, {})})
        for key in makes:
            for other in self.users[key]:
                found[other] += MECHANICS[key].weight
        for key in uses:
            for other in self.makers[key]:
                found[other] += MECHANICS[key].weight
        found.pop(name, None)
        return found

    def summary(self, card, shown=SUMMARY_SHOWN):
        """A card's "Works well with" lines: the cards its rulings name, then each role with how
        many cards it pairs with and a few of them (the ones sharing the most with it, then the
        most focused: fewest roles of their own, then the cheapest)."""
        name = card if isinstance(card, str) else card["name"]
        lines = [f"{other}: a ruling covers them together" for other in sorted(self.rulings.get(name, {}))[:shown]]
        makes, uses = self.roles_for(card)
        shared = self.partners(card)

        def examples(others):
            ranked = sorted(others - {name}, key=lambda o: (-shared[o], sum(map(len, self.roles.get(o, _NONE))),
                                                             self.cmc.get(o, 99), o))
            return ", ".join(ranked[:shown])

        for key in sorted(makes):
            if self.users[key] - {name}:
                lines.append(f"Provides {MECHANICS[key].noun}: {len(self.users[key] - {name}):,} cards pay it off, "
                             f"like {examples(self.users[key])}")
        for key in sorted(uses):
            if self.makers[key] - {name}:
                lines.append(f"Pays off {MECHANICS[key].noun}: {len(self.makers[key] - {name}):,} cards provide it, "
                             f"like {examples(self.makers[key])}")
        return lines


_loaded = None


def load():
    # The shipped data, read once; empty (nothing works with anything) if the file is missing
    global _loaded
    if _loaded is None:
        try:
            with gzip.open(PATH, "rt", encoding="utf-8") as file:
                _loaded = Interactions(json.load(file))
        except (OSError, ValueError):
            _loaded = Interactions()
    return _loaded


# Building the data (the desktop, now and then)

def download():
    """Fills the database (point db.DB_NAME somewhere else first) with Scryfall's card database
    and rulings, as the Deck Builder and the Rules window would: for building on a machine
    without them, like GitHub's at release time."""
    import database as db
    import finance
    import rules
    db.create_table()
    print("Downloading the card database from Scryfall…", flush=True)
    finance.update_market(None, None, history=False)
    print("Downloading the rulings from Scryfall…", flush=True)
    rules.download_rulings()


def build(path=PATH):
    import database as db
    import scryfall
    import synergy  # here: synergy imports this module
    cards = [dict(row) for row in db.card_texts()]
    rulings = own_rulings({name: text.split("\n") for name, text in db.rulings_by_name().items()})
    if not cards or not rulings:
        raise SystemExit("Needs the card database and the rulings: open the Deck Builder and the Rules window once "
                         "(or build with --download).")
    set_names = [s["name"] for s in scryfall._get_json("/sets")["data"]]
    roles = {}
    for card in cards:
        makes, uses = roles_of(card)
        if makes or uses:
            roles[card["name"]] = [sorted(makes), sorted(uses), card["cmc"] or 0]
    subtypes = {t for c in cards for line in (c["type_line"] or "").split(" // ") if "—" in line
                for t in line.split("—", 1)[1].split()}
    links = ruling_links([c["name"] for c in cards], rulings, set_names, subtypes)
    creature_types = synergy.known_types(c["type_line"] for c in cards if c["type_line"])
    themes = ruling_themes({c["name"]: c for c in cards}, rulings, synergy.THEMES, creature_types, synergy.tribal_theme)
    data = {"built": date.today().isoformat(), "roles": roles,
            "rulings": [[card, other, ruling] for (card, other), ruling in sorted(links.items())],
            "ruling_themes": themes}
    with gzip.open(path, "wt", encoding="utf-8") as file:
        json.dump(data, file, separators=(",", ":"))
    print(f"{len(roles):,} cards with roles, {len(links):,} ruling links, {len(themes):,} with themes in their "
          f"rulings -> {path} ({path.stat().st_size // 1024:,} KB)")


if __name__ == "__main__":
    import sys
    import tempfile
    if sys.argv[1:] == ["build"]:
        build()
    elif sys.argv[1:] == ["build", "--download"]:
        # A throwaway database, so the download never touches a collection on this computer
        import database as db
        with tempfile.TemporaryDirectory() as folder:
            db.DB_NAME = str(Path(folder) / "cards.db")
            download()
            build()
    else:
        sys.exit(__doc__)
