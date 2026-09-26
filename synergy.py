"""
Commander recommendations, in the spirit of EDHREC: pick a commander and a direction
(themes like tokens or +1/+1 counters) and get the cards that fit it best, grouped
the way a deck is built.

It's all worked out from the local card database: each card's types and rules text
are matched against the chosen themes, boosted by Scryfall's community tags when
they've been fetched, with the cards played most in Commander (Scryfall's
edhrec_rank) winning ties. No decklists are involved, so "synergy" here means how
well a card fits the chosen themes, not how often people play it with this commander.
"""

# Imports
import math
import re
from collections import Counter
from dataclasses import dataclass

import requests

import database as db
import mtgjson
import scryfall


@dataclass(frozen=True)
class Theme:
    label: str
    commander: str      # a commander's rules text that suggests this theme (regex)
    cards: str          # a card's type line or rules text that fits it (regex)
    tags: tuple = ()    # Scryfall community tags of cards that fit it
    types: tuple = ()   # card types that fit it a little just by being that type


_TOKENS = r"create[^.]*tokens?|tokens? you control|populate"
_MILL = r"\bmills?\b|puts? the top [^.]* cards? of (?:their|target player's|each opponent's) library"
_NOT_REMOVAL = (r"(?<!destroy target )(?<!exile target )(?<!one target )(?<!destroy all )(?<!exile all )"
                r"(?<!target artifact or )(?<!target artifact and/or )")

THEMES = {
    "counters": Theme("+1/+1 Counters", r"\+1/\+1 counter|proliferate", r"\+1/\+1 counter|proliferate",
                      ("counters-matter", "counter-doubler")),
    "tokens": Theme("Tokens", _TOKENS, _TOKENS, ("repeatable-token-generator", "token-doubler", "synergy-token")),
    "sacrifice": Theme("Aristocrats / Sacrifice", r"\bsacrifices?\b|\bdies\b|\bdied\b|\bdying\b",
                       r"sacrifice (?:a|an|another|two|x|any number of) |whenever [^.]* dies|"
                       r"whenever you sacrifice|\bdied this turn",
                       ("sacrifice-outlet", "death-trigger", "synergy-sacrifice")),
    # Commanders are matched on the key word alone ("artifact cards leave your graveyard"
    # is as much a graveyard commander as "return target card from your graveyard")
    "graveyard": Theme("Graveyard / Reanimator", r"graveyard|\bmill",
                       r"(?:your|a) graveyard|graveyard to the battlefield|\bmills?\b|\bsurveil\b|\bunearth\b|"
                       r"\bdredge\b|\bembalm\b|\beternalize\b|\bscavenge\b",
                       ("reanimate", "self-mill", "recursion")),
    "spells": Theme("Spellslinger", r"instant (?:or|and) sorcery|noncreature spell|whenever you cast an? "
                    r"(?:instant|sorcery)|magecraft",
                    r"instant (?:or|and) sorcery|noncreature spells?|whenever you cast an? (?:instant|sorcery)|"
                    r"magecraft|prowess", ("synergy-instant", "synergy-sorcery", "magecraft"), ("Instant", "Sorcery")),
    # Any mention counts ("All permanents are artifacts", "artifact creature you control"),
    # except removal aimed at them ("destroy up to one target artifact")
    "artifacts": Theme("Artifacts", _NOT_REMOVAL + r"\bartifacts?\b|treasure",
                       _NOT_REMOVAL + r"\bartifacts?\b|improvise|metalcraft|\bcraft with",
                       ("synergy-artifact",), ("Artifact",)),
    "enchantments": Theme("Enchantress", _NOT_REMOVAL + r"\benchantments?\b|constellation",
                          _NOT_REMOVAL + r"\benchantments?\b|constellation",
                          ("synergy-enchantment",), ("Enchantment",)),
    "equipment": Theme("Equipment / Voltron", r"equipped|equipment", r"equipped creature|equipment|\bequip\b",
                       ("synergy-equipment",), ("Equipment",)),
    "auras": Theme("Auras / Voltron", r"enchanted creature|aura spell|auras? you control",
                   r"auras? you control|aura spells?|enchanted creature gets", ("synergy-aura",), ("Aura",)),
    "lifegain": Theme("Lifegain", r"gains? [^.]*life|lifelink",
                      r"whenever you gain life|gains? \w+ life|lifelink|gain life equal", ("lifegain", "synergy-lifegain")),
    "lands": Theme("Lands / Landfall", r"landfall|whenever a land|additional land|lands? you control|land cards?|"
                   r"put [^.]*\blands? [^.]*onto the battlefield",
                   r"landfall|whenever a land [^.]*enters|play an additional land|lands? you control",
                   ("landfall", "extra-land", "synergy-land")),
    "blink": Theme("Blink / ETB", r"exile [^.]*return (?:it|that card|them|those cards) to the battlefield|"
                   r"\bflicker|\bblink", r"exile [^.]*return (?:it|that card|them|those cards) to the battlefield|"
                   r"whenever another [^.]*enters", ("blink",)),
    "superfriends": Theme("Superfriends", r"planeswalker|loyalty|proliferate",
                          r"planeswalkers? you control|loyalty (?:counter|abilit)|proliferate",
                          ("synergy-planeswalker",), ("Planeswalker",)),
    "draw": Theme("Card Draw / Wheels", r"whenever you draw|each player draws|draws? (?:a|two|three|x) cards?",
                  r"whenever you draw|each player draws|discards? (?:their|your) hand", ("wheel",)),
    "discard": Theme("Discard / Madness", r"discard|madness", r"\bdiscard|madness|cycling",
                     ("discard-outlet", "synergy-discard")),
    "mill": Theme("Mill", _MILL, _MILL, ("mill", "synergy-mill")),
    "combat": Theme("Go Wide / Combat", r"\battack(?:s|ing|ed)?\b|combat damage to a player|"
                    r"creatures you control get", r"creatures you control get \+|whenever [^.]* attacks|"
                    r"attacking creatures|combat damage to a player|additional combat", ("anthem",)),
    "legends": Theme("Legends / Historic", r"legendary|historic",
                     r"legendary (?:creature|spell|permanent)s?|historic", ("synergy-legendary", "synergy-historic")),
    "vehicles": Theme("Vehicles", r"vehicle|crew", r"vehicles?|\bcrews?\b", ("synergy-vehicle",)),
    "mana": Theme("Big Mana", r"unspent mana|mana pool|lose [^.]*mana|add (?:an )?additional|mana abilit|"
                  r"for each [^.]*mana|\{T\}: Add", r"unspent mana|mana pools?|don't lose [^.]*mana|"
                  r"adds? (?:an |one )?additional|twice that much mana|mana of any type|add an amount of|"
                  r"add x mana|mana equal to|untap (?:all|target|up to \w+) lands?", ("mana-doubler", "ritual")),
    # An {X} to pay, not "costs {X} less" (Ghalta)
    "xspells": Theme("X Spells / Mana Sinks", r"(?<!costs )(?<!cost )\{X\}(?! less)|value of X", r"\{X\}",
                     ("mana-sink",)),
    "creatures": Theme("Creature Spells", r"creature spells?", r"creature spells?|whenever you cast a creature"),
    "power": Theme("Big Creatures / Power", r"greatest power|power \d+ or greater|total power|\bpower\b[^.]*\bdamage|"
                   r"that creature's power|\bits power\b",
                   r"power (?:\d+|x) or greater|greatest power|total power|damage equal to its power|"
                   r"with power \d", ("power-matters",)),
    "devotion": Theme("Devotion", r"devotion|mana symbols|mana costs? of permanents", r"devotion|mana symbols"),
    "flying": Theme("Flyers", r"creatures? with flying|fliers|flyers", r"creatures? with flying|flying",
                    ("synergy-flying",)),
    "etb": Theme("ETB Triggers", r"\bentering\b|enters[^.]*additional time|whenever another [^.]*enters",
                 r"\bwhen [^.]*\benters\b|whenever another [^.]*enters|triggers an additional time", ("blink",)),
    "taxes": Theme("Taxes / Cost Reduction", r"costs? \{\d+\} (?:more|less)|opponents can't|opponents cast cost",
                   r"costs? \{\d+\} (?:more|less)|(?:your opponents|each opponent|players) can't|"
                   r"opponents cast cost", ("cost-reducer",)),
    "damage": Theme("Damage / Burn", r"double that damage|deals? double|damage to (?:each|an|target) opponent|"
                    r"source would deal damage", r"double that damage|deals? double|deals? \w+ damage to (?:each|an|"
                    r"target) (?:opponent|player)|damage to any target|source you control would deal damage",
                    ("burn",)),
    "copies": Theme("Copies / Clones", r"\bcop(?:y|ies)\b|activated abilities of creatures",
                    r"becomes? a copy|token that's a copy|enter as a copy|copy target|\bcop(?:y|ies) of",
                    ("copy", "clone")),
    "chosen": Theme("Chosen Creature Type", r"chosen type|choose a creature type",
                    r"chosen type|choose a creature type|changeling|every creature type|all creature types"),
    "cascade": Theme("Cascade / Free Spells", r"\bcascade\b|\bdiscover\b",
                     r"\bcascade\b|\bdiscover\b|without paying (?:its|their) mana costs?"),
    "library": Theme("Top of Library", r"top (?:card )?of your library",
                     r"top (?:card )?of your library|look at the top card of your library any time"),
}

# Staples every Commander deck wants, whatever its theme, ranked by popularity:
# title -> (rules text regex, Scryfall tags, card types left out)
STAPLES = {
    "Ramp": (r"add \{[wubrgc]\}|add (?:one|two|three) mana|mana of any (?:one )?colou?r|search your library for "
             r"(?:a|up to \w+) (?:basic )?lands? cards?|put (?:a|up to \w+) lands? cards? [^.]*onto the battlefield",
             ("ramp", "mana-rock", "mana-dork"), ("Land",)),
    "Card Draw": (r"draws? (?:a|two|three|four|x|that many) cards?", ("draw",), ("Land",)),
    "Removal": (r"(?:destroy|exile) target (?:creature|permanent|artifact|enchantment|nonland permanent|planeswalker)|"
                r"counter target spell|deals? (?:\d+|x) damage to (?:any target|target creature)",
                ("spot-removal", "counterspell"), ("Land",)),
    "Board Wipes": (r"(?:destroy|exile) all (?:other )?(?:creatures|nonland permanents|artifacts|enchantments)|"
                    r"all creatures get -|deals? (?:\d+|x) damage to each creature", ("board-wipe",), ("Land",)),
}

# Card type sections, in the order EDHREC lists them
TYPE_SECTIONS = [("Creature", "Creatures"), ("Instant", "Instants"), ("Sorcery", "Sorceries"),
                 ("Artifact", "Artifacts"), ("Enchantment", "Enchantments"), ("Planeswalker", "Planeswalkers"),
                 ("Battle", "Battles"), ("Land", "Lands")]

HIGH_SYNERGY_SHOWN, STAPLES_SHOWN, TOP_SHOWN, TYPE_SHOWN, LANDS_SHOWN = 20, 12, 30, 30, 30
SHOW_MORE = 30      # cards added by a section's Show More
PRECON_POINTS = 3   # cards from the commander's own precon were designed to go with it
ECHO_POINTS = 4     # sharing the commander's own wording, at most
_RANK_SCALE = 20000  # popularity counts down to about this rank


# Themes

def _plural(word):
    return word[:-1] + "ves" if word.endswith("f") else word + ("es" if word.endswith(("s", "ch", "sh", "x")) else "s")


def tribal_theme(creature_type):
    words = rf"\b(?:{re.escape(creature_type)}|{re.escape(_plural(creature_type))})\b"
    # A commander that only makes tokens of a type ("create a 2/2 Drake creature token")
    # isn't about that type, so those mentions don't suggest it
    return Theme(f"{creature_type} Tribal", words + r"(?![\w ]*creature tokens?)", words)


def theme(key):
    # "tribal:Elf" keys are built on the fly
    return tribal_theme(key.split(":", 1)[1]) if key.startswith("tribal:") else THEMES[key]


def creature_types(card):
    # A creature card's subtypes: "Legendary Creature — Elf Druid" -> ["Elf", "Druid"]
    front = (card["type_line"] or "").split("//")[0]
    if "Creature" not in front or "—" not in front:
        return []
    return [t for t in front.split("—", 1)[1].split()
            if t.isalpha() and t[0].isupper() and t not in _NOT_CREATURE_TYPES]


# Subtypes of other card types that a few odd creatures carry too ("Enchantment Creature — Saga")
_NOT_CREATURE_TYPES = {"Equipment", "Saga", "Aura", "Vehicle", "Class", "Case", "Room", "Food", "Treasure",
                       "Clue", "Background", "Curse", "Shrine", "Cartouche", "Rune", "Fortification", "Blood"}


def known_types(type_lines):
    # Every creature type on at least 3 of these type lines (leaving out one-off joke
    # types), and not the plural of another type ("Elves")
    counts = Counter(t for line in type_lines for t in creature_types({"type_line": line}))
    types = {t for t, n in counts.items() if n >= 3}
    return sorted(types - {_plural(t) for t in types})


def suggest_themes(commanders, known=()):
    """Theme keys that suit the commanders' rules text, best match first. What a
    commander triggers on ("Whenever you cast an instant…") counts twice, keyword
    lines ("Flying, lifelink") don't count, and creature types it mentions (out of
    known) come as tribal themes."""
    # Reminder text isn't the card's own ability (Ghalta's trample reminder mentions
    # planeswalkers), and a god's devotion clause is about being a creature, not a theme
    lines = [line for c in commanders for line in re.sub(r"\([^)]*\)", "", c["oracle_text"] or "").splitlines()
             if ("." in line or ":" in line)  # keyword-only lines have neither
             and "isn't a creature" not in line]
    text = "\n".join(lines)
    for c in commanders:  # its own name ("The Ur-Dragon", "Lord Windgrace") isn't a creature type
        for own in {c["name"], c["name"].split(",")[0]}:
            text = text.replace(own, "CARDNAME")
    text += "\n" + "\n".join(re.findall(r"\b(?:whenever|when|as long as)\b[^,.]*,", text, re.IGNORECASE))
    scores = {key: len(re.findall(t.commander, text, re.IGNORECASE)) for key, t in THEMES.items()}
    # Cascade is a keyword, but one a deck is built around (Maelstrom Wanderer)
    scores["cascade"] += 2 * any(re.search(r"^cascade\b", c["oracle_text"] or "", re.IGNORECASE | re.MULTILINE)
                                 for c in commanders)
    for creature_type in known:
        # Case-sensitive, since types are capitalized: no "Elf" in "itself"
        hits = len(re.findall(tribal_theme(creature_type).commander, text))
        if hits:
            scores[f"tribal:{creature_type}"] = hits + 1  # a named creature type is a strong signal
    return [key for key, points in sorted(scores.items(), key=lambda kv: -kv[1]) if points]


def needed_tags(theme_keys, staples):
    tags = [tag for key in theme_keys for tag in theme(key).tags]
    if staples:
        tags += [tag for _, staple_tags, _ in STAPLES.values() for tag in staple_tags]
    return list(dict.fromkeys(tags))


def identity_of(commanders):
    # The commanders' combined color identity, in WUBRG order ("" for colorless)
    colors = "".join(c["color_identity"] or "" for c in commanders)
    return "".join(c for c in "WUBRG" if c in colors)


# Loading (on a worker thread)

def load(identity, tags, commander_names=(), cards=None, fetch=False, progress=None):
    """(cards, {tag: names}, what's still missing): the cards legal in Commander within
    identity (unless already loaded), the saved names for each Scryfall tag, and under
    "precon" / "precon-decks" the cards and names of the commanders' own precons. With
    fetch (and online), whatever's missing is fetched and saved first; anything that
    can't be fetched just counts as empty."""
    if cards is None:
        rows, _ = db.search_cards(False, format_key="commander", identity=identity, limit=1_000_000)
        cards = [{**row, "text": f"{row['type_line'] or ''}\n{row['oracle_text'] or ''}",
                  "phrases": phrases(row["oracle_text"], row["name"])} for row in rows]
    fetch = fetch and not scryfall.offline
    found, missing = {}, []
    for number, tag in enumerate(tags, start=1):
        names = db.tagged_names(tag, identity)
        if names is None and fetch:
            if progress:
                progress((f"Fetching Scryfall's card tags ({number} of {len(tags)})…", number, len(tags)))
            try:
                names = set(scryfall.tagged_cards(tag, identity))
                db.save_tagged_names(tag, identity, names)
            except requests.RequestException:
                pass
        if names is None:
            missing.append(tag)
        found[tag] = names or set()

    found["precon"], found["precon-decks"] = set(), set()
    for name in commander_names:
        cards_key, decks_key = f"precon:{name}", f"precon-decks:{name}"
        names, decks = db.tagged_names(cards_key, ""), db.tagged_names(decks_key, "")
        if (names is None or decks is None) and fetch:
            if progress:
                progress(("Looking up the commander's precon on MTGJSON…", 0, 1))
            try:
                sets = {row["set_code"] for row in db.local_printings(name=name)}
                decks, names = mtgjson.precon_cards(name, sets)
                db.save_tagged_names(cards_key, "", names)
                db.save_tagged_names(decks_key, "", decks)
            except requests.RequestException:
                pass
        if names is None or decks is None:
            missing.append(cards_key)
        found["precon"] |= names or set()
        found["precon-decks"] |= decks or set()
    return cards, found, missing


# Scoring

def _popularity(card):
    # 1 for the most played card in Commander, falling to 0 around _RANK_SCALE
    rank = card["edhrec_rank"]
    return 0.0 if rank is None else max(0.0, 1 - rank / _RANK_SCALE)


def _front_type(card):
    front = (card["type_line"] or "").split("//")[0]
    return next((t for t, _ in TYPE_SECTIONS if t in front), None)


# Words too common to make two cards alike on their own
_STOPWORDS = {"a", "an", "the", "of", "to", "and", "or", "it", "its", "that", "this", "for", "on", "in", "with",
              "as", "is", "be", "by", "from", "at", "if", "may", "can", "each", "any", "then", "you", "your",
              "gets", "get", "has", "have", "until", "end", "turn", "one", "target"}
_WORDS = re.compile(r"[a-z0-9+/{}'-]+")


def phrases(oracle_text, name=""):
    # A card's rules text as pairs of words ("unspent mana", "leave your"), leaving out
    # reminder text and its own name, for comparing cards with the commander
    text = re.sub(r"\([^)]*\)", "", oracle_text or "").lower()
    for own in {name.lower(), name.split(",")[0].lower()} - {""}:
        text = text.replace(own, "cardname")
    words = _WORDS.findall(text)
    return frozenset(f"{a} {b}" for a, b in zip(words, words[1:]) if not (a in _STOPWORDS and b in _STOPWORDS))


def _echoes(cards, commanders):
    """{card name: 0-1} for how much of the commander's own wording a card shares,
    counting rarer phrases more ("unspent mana" says more than "you control"). This
    finds what fixed themes can't: Kruphix and Upwelling for Omnath, Locus of Mana."""
    card_phrases = [(card["name"], card.get("phrases") or phrases(card["oracle_text"], card["name"]))
                    for card in cards]
    counts = Counter(p for _, found in card_phrases for p in found)
    total = len(cards) or 1
    wanted = set().union(*(phrases(c["oracle_text"], c["name"]) for c in commanders)) if commanders else set()
    # Phrases on at least one other card, and on no more than 1.5% of them
    weights = {p: math.log(total / counts[p]) for p in wanted if 2 <= counts[p] <= total * 0.015}
    names = {c["name"] for c in commanders}
    raw = {name: sum(weights.get(p, 0) for p in found) for name, found in card_phrases if name not in names}
    top = sorted(raw.values(), reverse=True)
    scale = top[min(10, len(top) - 1)] if top and top[0] else 0  # the 10th best counts as a full match
    # A third of that or less is a phrase or two in common, not synergy
    return {name: min(1.0, value / scale) for name, value in raw.items() if value > scale / 3} if scale else {}


def score(cards, theme_keys, tags, commanders=()):
    """The cards with how well each fits the themes and the commander's own wording
    ("score", and "synergy" 0-100), "popularity" (0-1), "type", "staple" (a STAPLES
    title, or None) and "precon" (in the commander's precon; tags["precon"] from
    load()). The slow part of the recommendations, so it's worked out once per choice
    of themes, not per filter."""
    matchers = [(re.compile(t.cards, re.IGNORECASE), [tags.get(tag, set()) for tag in t.tags], t.types)
                for t in map(theme, theme_keys)]
    best = 5 * len(matchers) + ECHO_POINTS  # rules text (3) + a tag (2) for every theme, plus the commander's wording
    precon = tags.get("precon", set())
    echoes = _echoes(cards, commanders)
    staples = [(title, re.compile(pattern, re.IGNORECASE), set().union(*(tags.get(t, set()) for t in staple_tags)),
                left_out) for title, (pattern, staple_tags, left_out) in STAPLES.items()]
    pool = []
    for card in cards:
        points = 0
        for pattern, tag_sets, types in matchers:
            # A theme with no Scryfall tags (tribal, say) counts its rules text for both
            points += (3 if tag_sets else 5) if pattern.search(card["text"]) else 0
            points += 2 if any(card["name"] in names for names in tag_sets) else 0
            points += 1 if any(t in (card["type_line"] or "") for t in types) else 0
        points += PRECON_POINTS if card["name"] in precon else 0
        points += round(ECHO_POINTS * echoes.get(card["name"], 0), 1)
        # Rules text decides which staple a card is (Path to Exile is removal, even though
        # it's tagged ramp); tags only place cards whose text didn't match any
        kind = _front_type(card)
        eligible = [(title, pattern, names) for title, pattern, names, left_out in staples if kind not in left_out]
        staple = (next((title for title, pattern, _ in eligible if pattern.search(card["text"])), None)
                  or next((title for title, _, names in eligible if card["name"] in names), None))
        pool.append({**card, "score": points, "synergy": min(100, round(100 * points / best)),
                     "popularity": _popularity(card), "staple": staple, "type": kind,
                     "precon": card["name"] in precon})
    return pool


_BASIC_TYPES = {"Plains": "W", "Island": "U", "Swamp": "B", "Mountain": "R", "Forest": "G"}


def _off_color_land(card, identity):
    # A land that only finds basic land types outside the commander's colors, like
    # Polluted Delta ("an Island or Swamp card") in a mono-white deck
    colors = {color for basic, color in _BASIC_TYPES.items() if basic in (card["oracle_text"] or "")}
    return card["type"] == "Land" and bool(colors) and not colors & set(identity)


def recommend(commanders, pool, in_deck=(), owned_only=False, max_price=None, staples=True,
              precon_title="From the Precon", more=None):
    """[(section title, rows, how many more there are)], like an EDHREC page: the
    commander's precon, High Synergy Cards, the staples (if staples), Top
    Cards (the most played in these colors), then each card type. pool is from
    score(); each row also gets a "note" (a caption line). more ({title: n}) shows n
    extra cards in a section. Each card shows up once, and the commanders, basic
    lands and in_deck names are left out."""
    skip = {name.lower() for name in in_deck} | {c["name"].lower() for c in commanders}
    identity = identity_of(commanders)
    pool = [card for card in pool
            if card["name"].lower() not in skip and "Basic" not in (card["type_line"] or "")
            and (card["owned"] or not owned_only) and not (max_price and (card["price"] or 0) > max_price)]
    more = more or {}
    used = set()
    sections = []

    def note(row):
        if row["score"]:
            return f"{row['synergy']}% synergy"
        return f"#{row['edhrec_rank']:,} in Commander" if row["edhrec_rank"] else "Staple"

    def add(title, rows, key, limit):
        rows = sorted((r for r in rows if r["name"] not in used), key=key, reverse=True)
        chosen = rows[:limit + more.get(title, 0)]
        used.update(r["name"] for r in chosen)
        sections.append((title, [{**r, "note": note(r)} for r in chosen], len(rows) - len(chosen)))

    def playable(row):
        # Played a lot and fits the themes: the cards people would actually put in the deck
        return row["popularity"] * (1 + 2 * row["synergy"] / 100)

    # The precon first: it was built for this commander, and High Synergy then adds to it
    add(precon_title, [r for r in pool if r["precon"]], lambda r: r["score"] + 2 * r["popularity"], len(pool))
    add("High Synergy Cards", [r for r in pool if r["score"] >= 3], lambda r: (r["score"], r["popularity"]),
        HIGH_SYNERGY_SHOWN)
    if staples:
        for title in STAPLES:
            add(title, [r for r in pool if r["staple"] == title], lambda r: r["popularity"], STAPLES_SHOWN)
    # Popular cards that fit this commander, not just the most played cards in its colors
    add("Top Cards", [r for r in pool if r["type"] != "Land" and r["score"] >= 2], playable, TOP_SHOWN)
    for card_type, title in TYPE_SECTIONS:
        # A card type alone ("it's an artifact") isn't enough to fit; lands all count,
        # so the most played ones in these colors show up too
        rows = [r for r in pool if r["type"] == card_type and (r["score"] >= 2 or card_type == "Land")
                and not _off_color_land(r, identity)]
        add(title, rows, playable, LANDS_SHOWN if card_type == "Land" else TYPE_SHOWN)
    return [section for section in sections if section[1]]
