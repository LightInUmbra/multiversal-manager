"""
Rules calculators: answers worked out from the Comprehensive Rules for the kinds of
question that follow fixed rules, reading each creature's abilities from its Oracle text
(or from the question: "a 2/2 with flying"). Every answer lists the rules it used.

Combat: who can block whom, and what happens in each combat damage step.
Commander Brackets: which brackets the cards named fit (see brackets.py).
No Qt here, so the same logic can move to the website and mobile app.
"""
import re
from dataclasses import dataclass, field

import brackets

COLORS = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
KEYWORDS = {"first strike", "double strike", "deathtouch", "trample", "lifelink", "indestructible", "infect",
            "wither", "flying", "reach", "menace", "vigilance", "defender", "shadow", "horsemanship", "fear",
            "intimidate", "skulk", "haste", "hexproof", "shroud", "flash"}
# How a question may name them ("a first striker", "a flier", "trampling")
_KEYWORD_WORDS = re.compile(
    r"\b(first[- ]strik(?:e|er|ing)|double[- ]strik(?:e|er|ing)|deathtouch|trampl(?:e|er|ing)|lifelink|"
    r"indestructible|infect|wither|fl(?:ying|ier|yer)|reach|menace|vigilance|defender|shadow|horsemanship|fear|"
    r"intimidate|skulk|haste|hexproof|shroud|flash)\b")
_COLOR_WORDS = re.compile(r"\b(white|blue|black|red|green|artifact)\b")


def _keyword(word):
    word = word.replace("-", " ")
    for stem, keyword in (("first strik", "first strike"), ("double strik", "double strike"), ("trampl", "trample"),
                          ("fl", "flying")):
        if word.startswith(stem):
            return keyword
    return word


@dataclass(eq=False)
class Creature:
    name: str
    power: int = None                   # None when unknown ("*", or not given)
    toughness: int = None
    colors: frozenset = frozenset()     # "white", "blue"…
    type_line: str = "Creature"
    keywords: set = field(default_factory=set)
    protection: set = field(default_factory=set)   # "white", "everything", "creatures", "demons"…
    unblockable: bool = False
    cant_block: bool = False
    blocks_only_fliers: bool = False
    # During combat
    damage: int = 0
    counters: int = 0                   # -1/-1 counters from wither and infect
    deathtouched: bool = False
    gone: bool = False

    def has(self, keyword):
        return keyword in self.keywords

    def protected_from(self, source):
        # The quality this creature has protection from that the source has, if any
        types = set(re.findall(r"[a-z]+", source.type_line.lower()))
        for quality in sorted(self.protection):
            if (quality in ("everything", "creatures") or quality in source.colors
                    or (quality == "multicolored" and len(source.colors) > 1)
                    or (quality == "monocolored" and len(source.colors) == 1)
                    or (quality == "colorless" and not source.colors)
                    or quality.rstrip("s") in types):
                return quality
        return None


def _qualities(text):
    # "white and from blue" -> {"white", "blue"}; "each color" -> the five colors
    found = set()
    for quality in re.split(r",? and from |, from ", text.strip()):
        quality = quality.strip()
        found |= set(COLORS.values()) if quality in ("each color", "all colors") else {quality}
    return found


def _number(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def creature_from_card(name, card, other_keywords=()):
    """A Creature for a card: card is a row from the card database (type_line, colors,
    oracle_text, power, toughness). Its keywords come from its keyword lines ("Flying,
    vigilance"), not from abilities it gives others ("creatures you control have flying").
    other_keywords: every keyword ability's name, so lines like "Ward {2}" are recognized."""
    text = (card["oracle_text"] or "").split("\n\n")[0]      # the front face
    creature = Creature(name, _number(card["power"]), _number(card["toughness"]),
                        frozenset(COLORS[c] for c in (card["colors"] or "") if c in COLORS),
                        card["type_line"] or "Creature")
    subjects = {"this creature", "this permanent", name.lower(), name.split(",")[0].lower()}
    for line in text.split("\n"):
        line = re.sub(r"\s*\([^)]*\)", "", line).strip().rstrip(".").lower()
        parts = [p.strip() for p in re.split(r"[,;]\s*(?!and from|from)", line) if p.strip()]
        if parts and all(p in KEYWORDS or p.startswith("protection from")
                         or any(p == k or p.startswith(k + " ") for k in other_keywords) for p in parts):
            for part in parts:
                if part.startswith("protection from"):
                    creature.protection |= _qualities(part[len("protection from "):])
                elif part in KEYWORDS:
                    creature.keywords.add(part)
            continue
        match = re.fullmatch(r"(.+?) (can't be blocked|can't block|can't attack or block|"
                             r"can block only creatures with flying)", line)
        if match and match.group(1) in subjects:
            restriction = match.group(2)
            creature.unblockable |= restriction == "can't be blocked"
            creature.cant_block |= restriction in ("can't block", "can't attack or block")
            creature.blocks_only_fliers |= restriction.startswith("can block only")
    return creature


@dataclass
class Worked:
    """An answer worked out from the rules"""
    verdict: str
    steps: list          # what happens, in order
    rules: list          # the rules it used, in order
    assumes: str = "It assumes nothing else changes things: no tricks, other permanents or effects."


class _Rules(list):
    def use(self, *refs):
        self.extend(r for r in refs if r not in self)


# Commander Brackets

_BRACKET_QUESTION = re.compile(r"\bbrackets?\b|game[- ]changers?|\bcedh\b", re.IGNORECASE)
_GAME_CHANGER_QUESTION = re.compile(r"game[- ]changers?", re.IGNORECASE)
_BRACKETS_NOTE = ("Brackets are Wizards' optional Commander guidelines, not Comprehensive Rules. This looks at "
                  "each card on its own; two-card combos show up in the deck builder.")


def answer_brackets(question, cards):
    """Which Commander brackets the named cards fit ({name: card database row}), or None
    if the question isn't about brackets or names no cards"""
    if not cards or not _BRACKET_QUESTION.search(question):
        return None
    steps, lowest = [], []
    for name, card in cards.items():
        if brackets.is_mass_land_denial(card):
            steps.append(f"{name} is mass land denial: only in Brackets 4 and 5.")
            lowest.append(4)
        elif brackets.is_game_changer(card):
            steps.append(f"{name} is a Game Changer: none in Brackets 1 and 2, up to three in Bracket 3, "
                         "any number in Brackets 4 and 5.")
            lowest.append(3)
        elif brackets.is_extra_turn(card):
            steps.append(f"{name} gives an extra turn: none in Bracket 1; a few are fine in Brackets 2 and 3 "
                         "as long as they aren't chained or looped.")
            lowest.append(2)
        else:
            steps.append(f"{name} isn't a Game Changer, mass land denial or an extra-turn card, so on its own "
                         "it fits every bracket.")
            lowest.append(1)
    changers = [name for name, card in cards.items() if brackets.is_game_changer(card)]
    if _GAME_CHANGER_QUESTION.search(question):
        verdict = (("Yes" if changers else "No") if len(cards) == 1 else
                   f"{len(changers)} of {len(cards)} are Game Changers" + (f": {', '.join(changers)}" if changers else ""))
    else:
        verdict = f"Bracket {max(lowest)} and up" if max(lowest) > 1 else "Every bracket"
    return Worked(verdict, steps, [], _BRACKETS_NOTE)


# Blocking

def block_check(blocker, attacker):
    """Whether blocker can block attacker on its own terms: (can, why, [rules])"""
    b, a = blocker.name, attacker.name
    if blocker.cant_block:
        return False, f"{b} can't block.", ["509.1b"]
    if attacker.unblockable:
        return False, f"{a} can't be blocked.", ["509.1b"]
    quality = attacker.protected_from(blocker)
    if quality:
        return False, f"{a} has protection from {quality}, and {b} has that quality.", ["702.16f"]
    if attacker.has("flying") and not (blocker.has("flying") or blocker.has("reach")):
        return False, f"{a} has flying, and {b} has neither flying nor reach.", ["702.9b"]
    if blocker.blocks_only_fliers and not attacker.has("flying"):
        return False, f"{b} can block only creatures with flying.", ["509.1b"]
    if attacker.has("shadow") != blocker.has("shadow"):
        return False, (f"{a} has shadow and {b} doesn't." if attacker.has("shadow")
                       else f"{b} has shadow, so it can only block creatures with shadow."), ["702.28b"]
    if attacker.has("horsemanship") and not blocker.has("horsemanship"):
        return False, f"{a} has horsemanship and {b} doesn't.", ["702.31b"]
    is_artifact = "artifact" in blocker.type_line.lower()
    if attacker.has("fear") and not (is_artifact or "black" in blocker.colors):
        return False, f"{a} has fear, and {b} is neither black nor an artifact.", ["702.36b"]
    if attacker.has("intimidate") and not (is_artifact or blocker.colors & attacker.colors):
        return False, f"{a} has intimidate, and {b} is neither an artifact nor shares a color with it.", ["702.13b"]
    if (attacker.has("skulk") and None not in (blocker.power, attacker.power)
            and blocker.power > attacker.power):
        return False, f"{a} has skulk, and {b} has greater power.", ["702.118b"]
    if attacker.has("flying"):
        how = "flying" if blocker.has("flying") else "reach"
        return True, f"{a} has flying, but {b} has {how}.", ["702.9b"]
    return True, f"Nothing stops {b} from blocking {a}.", ["509.1a"]


def blocks_check(attacker, blockers):
    """Whether these creatures can block attacker together: (can, [reasons], [rules])"""
    rules, reasons, can = _Rules(), [], True
    for blocker in blockers:
        ok, why, refs = block_check(blocker, attacker)
        can &= ok
        reasons.append(why)
        rules.use(*refs)
    if can and attacker.has("menace") and len(blockers) < 2:
        can = False
        reasons.append(f"{attacker.name} has menace, so it can't be blocked except by two or more creatures.")
        rules.use("702.111b")
    return can, reasons, rules


# Combat damage

def _lethal(target, source):
    # Damage that counts as lethal when assigning source's damage (702.19b, 702.2c)
    if source.has("deathtouch"):
        return 1
    return max(target.toughness - target.counters - target.damage, 0)


def _assign(attacker, blockers, rules):
    # The attacker's combat damage this step: [(creature, or None for the player, amount)].
    # It divides its damage to destroy as many blockers as it can (510.1c)
    power = attacker.power
    if not blockers:
        return [(None, power)]
    alive = [b for b in blockers if not b.gone]
    if not alive:
        if attacker.has("trample"):
            rules.use("702.19d")
            return [(None, power)]
        rules.use("510.1c")
        return []
    assigned, left = [], power
    for blocker in sorted(alive, key=lambda b: _lethal(b, attacker)):
        amount = min(left, _lethal(blocker, attacker))
        if amount:
            assigned.append([blocker, amount])
            left -= amount
    if left:
        if attacker.has("trample"):
            rules.use("702.19b")
            assigned.append([None, left])
        elif assigned:
            assigned[-1][1] += left
        else:
            assigned.append([alive[0], left])
    return [tuple(a) for a in assigned]


def _deal(source, target, amount, player, result, steps, rules):
    if amount <= 0:
        return
    name = target.name if target else player
    quality = target.protected_from(source) if target else None
    if quality:
        steps.append(f"{source.name}'s {amount} damage to {name} is prevented (protection from {quality}).")
        rules.use("702.16e")
        return
    if target is None:
        if source.has("infect"):
            result["poison"] += amount
            steps.append(f"{source.name} deals {amount} damage to {name}: {amount} poison counters.")
            rules.use("702.90b")
        else:
            result["player damage"] += amount
            steps.append(f"{source.name} deals {amount} damage to {name}.")
    elif source.has("infect") or source.has("wither"):
        target.counters += amount
        steps.append(f"{source.name} deals {amount} damage to {name}: {amount} -1/-1 counters.")
        rules.use("120.3d")
    else:
        target.damage += amount
        steps.append(f"{source.name} deals {amount} damage to {name}.")
    if target is not None and source.has("deathtouch"):
        target.deathtouched = True
        rules.use("702.2b")
    if source.has("lifelink"):
        result["life"][source.name] = result["life"].get(source.name, 0) + amount
        rules.use("702.15b")


def _check_deaths(creatures, steps, rules):
    # State-based actions after combat damage
    for creature in creatures:
        if creature.gone:
            continue
        toughness = creature.toughness - creature.counters
        if toughness <= 0:
            creature.gone = True
            steps.append(f"{creature.name} has 0 toughness and is put into the graveyard"
                         + (" (indestructible doesn't stop that)." if creature.has("indestructible") else "."))
            rules.use("704.5f")
        elif creature.damage >= toughness or creature.deathtouched:
            why = "lethal damage" if creature.damage >= toughness else "damage from a creature with deathtouch"
            if creature.has("indestructible"):
                steps.append(f"{creature.name} has {why} but is indestructible, so it survives.")
                rules.use("702.12b")
            else:
                creature.gone = True
                steps.append(f"{creature.name} is destroyed ({why}).")
                rules.use("704.5g" if why == "lethal damage" else "704.5h")


def combat(attacker, blockers, player="the defending player"):
    """What happens when attacker is blocked by blockers (none: unblocked), step by step.
    Every creature needs a known power and toughness. Returns (steps, result, rules)."""
    rules, steps = _Rules(["510.1a"]), []
    result = {"player damage": 0, "poison": 0, "life": {}}
    everyone = [attacker] + blockers
    first = [c for c in everyone if c.has("first strike") or c.has("double strike")]
    if first:
        rules.use("702.7b" if any(c.has("first strike") for c in first) else "702.4b")
        phases = [("First-strike combat damage step", lambda c: c in first),
                  ("Regular combat damage step", lambda c: c not in first or c.has("double strike"))]
    else:
        phases = [("Combat damage step", lambda c: True)]
    for title, deals in phases:
        steps.append(f"<b>{title}</b>")
        dealing = []
        if not attacker.gone and deals(attacker):
            dealing += [(attacker, target, amount) for target, amount in _assign(attacker, blockers, rules)]
        if not attacker.gone:
            dealing += [(b, attacker, b.power) for b in blockers if not b.gone and deals(b)]
        if not any(amount > 0 for _, _, amount in dealing):
            steps.append("No combat damage is dealt.")
        rules.use("510.2")
        # All of the step's combat damage is dealt at the same time, then creatures are checked
        for source, target, amount in dealing:
            _deal(source, target, amount, player, result, steps, rules)
        _check_deaths(everyone, steps, rules)
    return steps, result, rules


def _summary(attacker, blockers, result, player):
    parts = [f"{c.name} {'dies' if c.gone else 'survives'}" for c in [attacker] + blockers]
    if result["player damage"]:
        parts.append(f"{player} {'take' if player == 'you' else 'takes'} {result['player damage']} damage")
    if result["poison"]:
        parts.append(f"{player} {'get' if player == 'you' else 'gets'} {result['poison']} poison counters")
    for name, life in result["life"].items():
        parts.append(f"{name}'s controller gains {life} life")
    text = "; ".join(parts)
    return text[0].upper() + text[1:]


# Reading a combat question

_ROLE_NOUN = r"(?:creature|attacker|blocker|fl[iy]er|trampler|(?:first|double)[- ]striker|token)"
_PT = re.compile(rf"(?<![\w/+-])(\d+)/(\d+)(?![\w/])(?:\s+{_ROLE_NOUN}\b)?")
_GENERIC = re.compile(rf"\b{_ROLE_NOUN}\b(?!s)")
_WITH = re.compile(r"\s*(?:with|that has|that have|which has|who has|has|having)\b")
_PHRASE_END = re.compile(r"\b(?:attacks?|attacking|attacked|blocks?|blocking|blocked|is|are|and (?:a|an|my|your|their"
                         r"|the)|then|deals?|can|gets?)\b|[.?!;]")
_LIST = r"@\d+(?:(?:\s*,\s*|\s*,?\s+and\s+)(?:[\w']+\s+){0,2}?@\d+)*"
_SKIP = r"(?:[\w']+\s+){0,2}?"


def _mentions(question, cards):
    """The creatures a question talks about: [(start, end, Creature)] in order. cards is
    {name: Creature} for the cards it names; "a 2/2 with flying" and "a creature with
    reach" become creatures of their own."""
    text = question.lower()
    spans = []
    for name, creature in cards.items():
        for match in re.finditer(rf"(?<![\w']){re.escape(name.lower())}(?!\w|'(?!s\b))", text):
            spans.append((match.start(), match.end(), creature))

    def taken(start, end, among):
        return any(start < e and end > s for s, e, *_ in among)

    generic = [(m.start(), m.end(), m) for m in _PT.finditer(text) if not taken(m.start(), m.end(), spans)]
    generic += [(m.start(), m.end(), None) for m in _GENERIC.finditer(text)
                if not taken(m.start(), m.end(), spans) and not taken(m.start(), m.end(), generic)]
    generic.sort(key=lambda g: g[0])
    starts = sorted([s for s, _, _ in spans] + [s for s, _, _ in generic] + [len(text)])
    for start, end, pt in generic:
        following = text[end:next(s for s in starts if s > start)]
        described = ""
        if lead := _WITH.match(following):
            ending = _PHRASE_END.search(following, lead.end())
            described = following[:ending.start() if ending else len(following)]
        # Words describing it before it: "a white flying 2/2", after its "a", "my" or "the"
        leading = re.search(r".*\b(?:a|an|my|your|their|his|her|the|another|opponent's)\s+([^.?!;,]*)$",
                            text[max(0, start - 40):start])
        before = leading.group(1) if leading else ""
        words = f"{before} {text[start:end]} {described}"
        keywords = {_keyword(w) for w in _KEYWORD_WORDS.findall(words)}
        name = (f"the {pt.group(1)}/{pt.group(2)}" if pt else
                "the creature" + (f" with {' and '.join(sorted(keywords))}" if keywords else ""))
        creature = Creature(name, int(pt.group(1)) if pt else None, int(pt.group(2)) if pt else None)
        creature.keywords = keywords
        found = set(_COLOR_WORDS.findall(words))
        creature.colors = frozenset(found - {"artifact"})
        if "artifact" in found:
            creature.type_line = "Artifact Creature"
        creature.protection = set(re.findall(r"protection from (\w+)", described))
        # The description is part of the mention: "@1 is unblocked", not "@1 with lifelink is unblocked"
        spans.append((start, end + len(described.rstrip()), creature))
    return sorted(spans, key=lambda s: s[0])


def _roles(question, mentions):
    """(attacker, [blockers], asks whether it can block?) from the question's wording, or None"""
    text, creatures = question.lower(), []
    for _, _, creature in mentions:
        if creature not in creatures:
            creatures.append(creature)
    for start, end, creature in reversed(mentions):
        text = text[:start] + f"@{creatures.index(creature)}" + text[end:]

    def pick(found):
        return [creatures[int(i)] for i in re.findall(r"@(\d+)", found or "")]

    def take(pattern):
        # Finds a phrase and blanks it out, so later patterns don't read it again
        nonlocal text
        match = re.search(pattern, text)
        if match:
            text = text[:match.start()] + " " * (match.end() - match.start()) + text[match.end():]
        return match

    attacker, blockers, asking = None, [], False
    if match := take(rf"\bcan(?:'t| not)?\s+{_SKIP}({_LIST})\s+{_SKIP}block\s+{_SKIP}(@\d+|it|him|her|them)"):
        blockers, asking = pick(match.group(1)), True
        attacker = (pick(match.group(2)) or [None])[0]
    elif match := take(rf"\bcan(?:'t| not)?\s+{_SKIP}(@\d+)\s+be\s+blocked\s+by\s+{_SKIP}({_LIST})"):
        attacker, blockers, asking = pick(match.group(1))[0], pick(match.group(2)), True
    if match := take(rf"(@\d+)\s+(?:is|gets|was|got|becomes)\s+(?:double[- ])?blocked\s+by\s+{_SKIP}({_LIST})"):
        attacker, blockers = pick(match.group(1))[0], blockers or pick(match.group(2))
    if match := take(rf"\b(?:is|gets|was|got)\s+(?:double[- ])?blocked\s+by\s+{_SKIP}({_LIST})"):
        blockers = blockers or pick(match.group(1))
    if match := take(rf"\b(?:double[- ])?block(?:s|ed|ing)?\s+{_SKIP}(@\d+)\s+with\s+{_SKIP}({_LIST})"):
        attacker, blockers = attacker or pick(match.group(1))[0], blockers or pick(match.group(2))
    if match := take(rf"\b(?:double[- ])?block(?:s|ed|ing)?\s+(?:it\s+|them\s+)?with\s+{_SKIP}({_LIST})"):
        blockers = blockers or pick(match.group(1))
    if match := take(rf"({_LIST})\s+(?:[\w']+\s+)?(?:double[- ])?(?:blocks?|blocking)\b\s*{_SKIP}(@\d+)?"):
        blockers = blockers or pick(match.group(1))
        attacker = attacker or (pick(match.group(2)) or [None])[0]
    if match := (take(r"(@\d+)\s+(?:[\w']+\s+)?(?:attacks|attacking|attacked|attack|is unblocked|isn't blocked)\b")
                 or take(rf"\battack(?:s|ed|ing)?\s+with\s+{_SKIP}(@\d+)")):
        attacker = attacker or pick(match.group(1))[0]
    if attacker is None and blockers:
        others = [c for c in creatures if c not in blockers]
        attacker = others[0] if len(others) == 1 else None
    if attacker is None or attacker in blockers:
        return None
    return attacker, blockers, asking


def answer_combat(question, cards):
    """A worked-out answer to a combat question, or None if it isn't one this can work
    out. cards: {name: Creature} for the cards the question names."""
    roles = _roles(question, _mentions(question, cards))
    if not roles:
        return None
    attacker, blockers, asking = roles
    lower = question.lower()
    unblocked = re.search(r"\bunblocked\b|\b(?:isn't|is not|not|wasn't|isn't being) blocked\b|\bno blockers?\b",
                          lower)
    if not blockers and not unblocked:
        return None
    player = "you" if re.search(r"\b(?:attacks?|attacking) (?:me|you)\b", lower) else "the defending player"
    rules = _Rules()
    if blockers:
        can, reasons, used = blocks_check(attacker, blockers)
        rules.use(*used)
        if asking or not can:
            verdict = "Yes" if can else "No"
            if not can and not asking:
                who = " and ".join(b.name for b in blockers)
                verdict = f"No, {who} can't block {attacker.name}"
            reasons = [r[0].upper() + r[1:] for r in reasons]
            return Worked(verdict, reasons, list(rules), "It reads each creature's own keywords and abilities; "
                          "effects from other cards, and tapped creatures, aren't included.")
    if None in (attacker.power, attacker.toughness) or any(None in (b.power, b.toughness) for b in blockers):
        return None
    before = [f"{c.name}: {c.power}/{c.toughness}" + (f", {', '.join(sorted(c.keywords))}" if c.keywords else "")
              for c in [attacker] + blockers]
    steps, result, used = combat(attacker, blockers, player)
    steps = [s[0].upper() + s[1:] for s in steps]
    rules.use(*used)
    return Worked(_summary(attacker, blockers, result, player), before + steps, list(rules))


# Timing: can I cast, play or activate this now?

_CAN = re.compile(r"\bcan(?:'t| not)? (?:i|you|we|my opponents?|an opponent|the opponent|opponents|they|he|she|"
                  r"a player|players|someone|anyone)\b")
_BY_OPPONENT = re.compile(r"\bcan(?:'t| not)? (?:my opponents?|an opponent|the opponent|opponents|they|he|she)\b")
_PART_OF_TURN = r"(?:turn|(?:first |second |precombat |postcombat )?main phase|upkeep|draw step|end step|combat)\b"
_THEIR_TURN = re.compile(r"\b(?:(?:my |an |the )?opponents?'?s?|their|his|her|someone else's|another player's) "
                         rf"{_PART_OF_TURN}|\bnot my turn\b")
_MY_TURN = re.compile(rf"\b(?:my|your) (?:own )?{_PART_OF_TURN}")
_STEPS = [("untap", r"\buntap step\b"), ("upkeep", r"\bupkeep\b"), ("draw", r"\bdraw step\b"),
          ("main", r"\bmain phase\b"),
          ("combat", r"\b(?:beginning of combat|declare attackers|declare blockers|combat damage step|during combat|"
                     r"in combat|after (?:blockers|attackers) (?:are|were) declared)\b"),
          ("end", r"\b(?:end step|end of (?:the |my |your |their |his |her )?turn)\b"),
          ("cleanup", r"\bcleanup\b")]
_STACK = re.compile(r"\bin response\b|\brespond(?:ing)? to\b|\bon the stack\b|\bbefore (?:it|that|\S+) resolves\b|"
                    r"\bwhile (?:it|that|\S+) (?:is )?resolving\b")
_SPEED = re.compile(r"\b(?:instant|sorcery)[- ]speed\b|\bany ?time\b|\bwhenever I want\b|\bat any point\b")
_JUST_ENTERED = re.compile(r"\bthe (?:same )?turn (?:it|they|he|she|that it) (?:came|comes|come|enters?|entered|was "
                           r"cast|were cast|is cast|was played|came into play|comes into play|came out|comes out)\b|"
                           r"\bsummoning[- ]sick|\bthe turn i (?:cast|play(?:ed)?) (?:it|them)\b")
_TYPE_WORDS = re.compile(r"\b(instant|sorcery|sorceries|creature|artifact|enchantment|aura|equipment|planeswalker|"
                         r"land|battle|plains|island|swamp|mountain|forest)s?\b")
_TYPE_OF = {"sorceries": "sorcery", "aura": "enchantment", "equipment": "artifact", "plains": "land", "island": "land",
            "swamp": "land", "mountain": "land", "forest": "land"}
_ELSEWHERE = re.compile(r"\bfrom (?:my |your |their |the |a )?(?:graveyard|exile|library|top of)")
_CAST_RULE = {"sorcery": "307.1", "creature": "302.1", "artifact": "301.1", "enchantment": "303.1",
              "planeswalker": "306.1", "battle": "310.1", "instant": "304.1", "land": "305.1"}


@dataclass
class _Situation:
    own_turn: bool = None      # the player asking about it, or None if the question doesn't say
    step: str = None           # "upkeep", "main", "combat"… or None
    stack: bool = None         # something on the stack?
    split_second: str = None   # the spell with split second on the stack, if any
    instant_speed: bool = False  # asks about doing it "at instant speed"


def _situation(lower, cards):
    by_opponent = bool(_BY_OPPONENT.search(lower))
    turn = "theirs" if _THEIR_TURN.search(lower) else "mine" if _MY_TURN.search(lower) else None
    situation = _Situation(None if turn is None else (turn == "mine") != by_opponent)
    situation.step = next((step for step, pattern in _STEPS if re.search(pattern, lower)), None)
    situation.stack = True if _STACK.search(lower) else None
    situation.instant_speed = bool(re.search(r"\binstant[- ]speed\b|\bany ?time\b", lower))
    for name, card in cards.items():
        if "split second" in (card["oracle_text"] or "").lower() and re.search(
                rf"{re.escape(name.lower())}\W+(?:\w+\W+){{0,3}}(?:is )?on the stack|(?:respon\w+|while) (?:to )?"
                rf"(?:\w+\W+){{0,2}}{re.escape(name.lower())}", lower):
            situation.split_second = name
    if "split second" in lower and not situation.split_second:
        situation.split_second = "a spell with split second"
    return situation


def _when(situation, speed, what, rules):
    """(verdict, [reasons]) for doing what (e.g. "cast Wrath of God") at speed "instant",
    "sorcery", "land", "mana" or "special" in this situation"""
    s = situation
    if s.step == "untap":
        rules.use("502.4")
        return "No", [f"No player gets priority during the untap step, so you can't {what} then."]
    if s.step == "cleanup":
        rules.use("514.3")
        return "No", [f"Normally no player gets priority during the cleanup step, so you can't {what} then."]
    if s.split_second and speed not in ("mana", "special", "land"):
        rules.use("702.61a")
        return "No", [f"While {s.split_second} (split second) is on the stack, players can't cast spells or activate "
                      "abilities other than mana abilities."]
    if s.split_second:
        rules.use("702.61b")
    if speed in ("instant", "mana", "special"):
        how = {"instant": "any time you have priority", "mana": "any time you have priority, and even in the middle "
               "of casting a spell or paying a cost", "special": "any time you have priority"}[speed]
        return "Yes", [f"You can {what} {how}."]
    sorcery_speed = f"You can only {what} during your own main phase while the stack is empty (sorcery speed)."
    main = None if s.step is None else s.step == "main"
    needs = [("it's your turn", "it isn't your turn", s.own_turn),
             ("it's your main phase", "it isn't your main phase", main),
             ("the stack is empty", "the stack isn't empty", None if s.stack is None else not s.stack)]
    broken = [problem for _, problem, ok in needs if ok is False]
    if broken:
        return "No", [f"{sorcery_speed} Here {' and '.join(broken)}."]
    if s.instant_speed:
        return "No", [f"{sorcery_speed} It doesn't have flash."]
    unknown = [need for need, _, ok in needs if ok is None]
    if len(unknown) == len(needs):
        return "Only during your main phase, when the stack is empty", [sorcery_speed]
    if unknown:
        return f"Yes, if {' and '.join(unknown)}", [sorcery_speed]
    return "Yes", [f"It's your main phase and the stack is empty, so you can {what}."]


def _abilities(card):
    """Each activated ability of a card: (cost, text, speed, [restrictions]). speed is
    "instant", "sorcery" (loyalty, equip, "activate only as a sorcery") or "mana"."""
    found = []
    for line in (card["oracle_text"] or "").split("\n\n")[0].split("\n"):
        line = re.sub(r"\s*\([^)]*\)", "", line).strip()
        if line.lower().startswith("equip"):
            found.append((line, line, "sorcery", ["equip: sorcery speed"]))
            continue
        cost, colon, effect = line.partition(": ")
        if not colon or len(cost) > 80 or cost.lower().startswith(("when", "whenever", "at ", "as ", "if ")):
            continue
        restrictions = re.findall(r"Activate (?:only |this ability only )?([^.]+)", effect)
        if re.fullmatch(r"[+−-]?(?:\d+|X)", cost):
            speed = "sorcery"
            restrictions.append("loyalty ability: once per turn, sorcery speed")
        elif any("as a sorcery" in r for r in restrictions):
            speed = "sorcery"
        elif effect.startswith("Add ") and "target" not in effect:
            speed = "mana"
        else:
            speed = "instant"
        found.append((cost, line, speed, restrictions))
    return found


def _first_after(lower, start, cards):
    # The card (name) or card type word the question is about, the first after start
    best = None
    for name in cards:
        for form in {name, name.split(" // ")[0]}:      # "Brazen Borrower" for Brazen Borrower // Petty Theft
            found = lower.find(form.lower(), start)
            if found >= 0 and (best is None or found < best[0]):
                best = (found, name)
    word = _TYPE_WORDS.search(lower, start)
    if word and (best is None or word.start() < best[0]):
        return None, _TYPE_OF.get(word.group(1), word.group(1))
    return (best[1], None) if best else (None, None)


def _is_flash(name, card, cards, lower):
    # Whether a card can be cast any time you could cast an instant, and why
    text = (card["oracle_text"] or "") if card else ""
    if card and "flash" in creature_from_card(name, card).keywords:
        return f"{name.split(' // ')[0]} has flash."
    if re.search(r"\b(?:with|has|gets|gains|given) flash\b|\bflash (?:it|them) in\b", lower):
        return "It has flash."
    if "as though it had flash" in text.lower():
        sentence = next(s for s in re.split(r"(?<=\.)\s+", text) if "as though it had flash" in s.lower())
        return f"{name} says: “{sentence.strip()}”"
    type_line = (card["type_line"] or "").lower() if card else ""
    for other, other_card in cards.items():
        match = re.search(r"[^.]*\bcast ([a-z ]*?)spells as though they had flash[^.]*\.?", (other_card["oracle_text"]
                                                                                         or "").lower())
        if other != name and match and all(w.rstrip("s") in type_line or w in ("", "noncreature") for w in
                                           match.group(1).split()):
            return f"{other} lets you: “{match.group(0).strip().capitalize()}”"
    return None


def answer_timing(question, cards):
    """A worked-out answer to "can I cast / play / activate this now?", or None if the
    question isn't about when something can be done. cards: {name: card database row}
    for the cards it names (any card type)."""
    worked = _answer_timing(question, cards)
    if worked and _BY_OPPONENT.search(question.lower()) and not re.search(r"\brespond\b", question.lower()):
        # Asked about an opponent: "they", not "you"
        for mine, theirs in (("You can", "They can"), ("you can", "they can"), ("your own", "their own"),
                             ("your turn", "their turn"), ("your main phase", "their main phase"),
                             ("you've", "they've"), ("your most recent", "their most recent")):
            worked.steps = [s.replace(mine, theirs) for s in worked.steps]
            worked.verdict = worked.verdict.replace(mine, theirs)
    return worked


def _answer_timing(question, cards):
    lower = question.lower()
    can = _CAN.search(lower)
    if not can or _ELSEWHERE.search(lower):
        return None
    rules = _Rules()
    rest = lower[can.end():]

    # Cast while another spell resolves (cascade, discover): the timing rules don't apply
    if re.match(r"\s*cast\b", rest) and re.search(r"\b(?:cascade|discover|cascading)\b", lower):
        rules.use("608.2g", "702.85a")
        return Worked("Yes", ["A spell you cast while another spell or ability is resolving (like cascade) ignores the "
                              "normal timing rules, so even a sorcery can be cast then, on any player's turn."],
                      list(rules), "")
    # "In response to" something that doesn't use the stack
    if re.search(r"\bin response to (?:\w+\s+){0,3}play(?:s|ing)? (?:a |the |their |his |her )?land\b", lower):
        rules.use("305.1", "116.2a")
        return Worked("No", ["Playing a land is a special action: the land goes straight onto the battlefield without "
                             "using the stack, so there's no moment to respond to it. You can act after it's "
                             "played."], list(rules), "")

    # Responding to something that doesn't use the stack
    if respond := re.match(r"\s*respond (?:to )?(.*)", rest):
        inner = respond.group(1)
        if re.search(r"\bplay(?:s|ing)? (?:a |the |their |my |his |her )?land\b|\bland drop\b", inner):
            rules.use("305.1", "116.2a")
            return Worked("No", ["Playing a land is a special action: it doesn't use the stack, so there's nothing "
                                 "to respond to."], list(rules), "")
        if re.search(r"face[- ]up|\bunmorph|\bmorph\b|\bmanifest|\bdisguise|\bcloak", inner):
            rules.use("116.2b", "702.37e")
            return Worked("No", ["Turning a face-down creature face up is a special action: it doesn't use the "
                                 "stack, so there's nothing to respond to. Players can respond to anything that "
                                 "triggers when it's turned face up."], list(rules), "")
        if re.search(r"\bfor mana\b|\bmana abilit", inner):
            rules.use("605.3b")
            return Worked("No", ["Mana abilities don't use the stack; they resolve immediately."], list(rules), "")
        return None

    situation = _situation(lower, cards)
    verb = re.match(r"\s*(?:(?:still|only|ever|just|now)\s+)?(cast|play|flash|activate|use|tap|equip|attack|block)\b",
                    rest)
    if not verb:
        return None
    verb_word, after = verb.group(1), can.end() + verb.end()
    name, type_word = _first_after(lower, after, cards)
    card = cards.get(name) if name else None
    what_name = name.split(" // ")[0] if name else (f"a{'n' if (type_word or 'x')[0] in 'aeiou' else ''} {type_word}" if type_word else "it")

    # Summoning sickness: attacking or {T} abilities the turn a creature arrives
    if _JUST_ENTERED.search(lower) and verb_word in ("attack", "tap", "activate", "use"):
        haste = ((card and "haste" in creature_from_card(name, card).keywords)
                 or re.search(r"\b(?:has|with|gets|gains|given) haste\b", lower))
        if verb_word == "attack":
            rules.use("302.6", "508.1a")
            if haste:
                rules.use("702.10b")
                return Worked("Yes", [f"{what_name} has haste, so it can attack the turn it comes under your "
                                      "control."], list(rules), "")
            return Worked("No", ["A creature can't attack unless you've controlled it continuously since your most "
                                 "recent turn began (“summoning sickness”), unless it has haste."],
                          list(rules), "")
        tapping = verb_word == "tap" or not card or any("{T}" in cost or "{Q}" in cost
                                                        for cost, *_ in _abilities(card))
        rules.use("302.6")
        if not tapping:
            return Worked("Yes", ["Summoning sickness only stops attacking and abilities with {T} or {Q} in their "
                                  "cost; this ability has neither."], list(rules), "")
        if haste:
            rules.use("702.10c")
            return Worked("Yes", ["It has haste, so it can use {T} abilities right away."], list(rules), "")
        return Worked("No", [f"Abilities with {{T}} or {{Q}} in the cost can't be activated unless you've controlled "
                             f"the creature continuously since your most recent turn began (“summoning "
                             f"sickness”), unless it has haste. Abilities without {{T}} are fine."],
                      list(rules), "")

    # The rest is only answered when the question is about timing
    if not (situation.own_turn is not None or situation.step or situation.stack or situation.split_second
            or _SPEED.search(lower)):
        return None
    rules.use("117.1a")

    if verb_word in ("activate", "use", "equip", "tap") or type_word == "planeswalker" and verb_word != "cast":
        rules.remove("117.1a")
        abilities = _abilities(card) if card else []
        if verb_word == "equip" or type_word == "equipment":
            abilities = [("Equip", "Equip", "sorcery", ["equip: sorcery speed"])]
        elif type_word == "planeswalker" or "loyalty" in lower:
            abilities = [("+1", "a loyalty ability", "sorcery", ["loyalty ability: once per turn, sorcery speed"])]
        elif "mana abilit" in lower or re.search(r"\bfor mana\b", lower):
            abilities = [a for a in abilities if a[2] == "mana"] or [("{T}", "a mana ability", "mana", [])]
        if not abilities:
            return None
        verdicts, steps = set(), []
        for cost, text, speed, restrictions in abilities:
            rules.use({"sorcery": "602.5d", "mana": "605.3a", "instant": "117.1b"}[speed])
            if any("loyalty" in r for r in restrictions):
                rules.use("606.3")
            if any(r.startswith("equip") for r in restrictions):
                rules.use("702.6a")
            verdict, reasons = _when(situation, speed, "activate it", rules)
            extra = [r for r in restrictions if not r.startswith(("as a sorcery", "equip", "loyalty"))]
            if any("during your turn" in r for r in extra) and situation.own_turn is False:
                verdict, reasons = "No", ["It can only be activated during your turn."]
            verdicts.add(verdict)
            steps.append(f"“{text}”: {' '.join(reasons)}"
                         + (f" It also says: activate only {'; '.join(extra)}." if extra else ""))
        verdict = verdicts.pop() if len(verdicts) == 1 else "It depends on the ability"
        return Worked(verdict, steps, list(rules), "It reads the card's own text; other cards' effects aren't "
                      "included.")

    if verb_word in ("attack", "block"):
        return None
    # The front face: Brazen Borrower is a creature with flash, not its Petty Theft adventure
    types = (card["type_line"] or "").lower().split("//")[0] if card else (type_word or "")
    if not types:
        return None
    if re.search(r"\bland\b", types) and verb_word == "play":
        rules.remove("117.1a")
        rules.use("305.1", "305.2")
        verdict, reasons = _when(situation, "sorcery", f"play {what_name}", rules)
        return Worked(verdict, reasons + ["You can normally play only one land each turn, and playing it is a "
                                          "special action (it doesn't use the stack)."], list(rules), "")
    kind = next((t for t in ("instant", "sorcery", "creature", "artifact", "enchantment", "planeswalker", "battle")
                 if t in types), None)
    if kind is None:
        return None
    flash = None if kind == "instant" else _is_flash(name, card, cards, lower)
    if kind == "instant" or flash:
        rules.use(_CAST_RULE["instant"] if kind == "instant" else "702.8a")
        verdict, reasons = _when(situation, "instant", f"cast {what_name}", rules)
        return Worked(verdict, ([flash] if flash else []) + reasons, list(rules), "")
    rules.use(_CAST_RULE[kind])
    verdict, reasons = _when(situation, "sorcery", f"cast {what_name}", rules)
    return Worked(verdict, reasons, list(rules), "Unless something gives it flash.")


# State checks: does it die, does a player lose? (state-based actions, rule 704)

_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10}
_COUNT = r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)"
_ABOUT_STATE = re.compile(r"\b(?:die|dies|died|survive|survives|live|lives|destroyed|graveyard|lose|loses|lost|win|"
                          r"wins|what happens|still alive|end up|left|stay|stays|legend rule|keep)\b")
_STATE_NOTE = "It assumes nothing else changes things: no other effects or replacement effects."


def _count(word):
    return int(word) if word.isdigit() else _NUMBER_WORDS[word]


def _player_state(lower, cards=None):
    # A player losing: life, poison, commander damage, drawing from an empty library
    rules = _Rules()
    for name, card in (cards or {}).items():
        text = card["oracle_text"] or ""
        if "can't lose the game" in text.lower() and re.search(r"\b(?:lose|loses|lost)\b", lower):
            sentence = next(s for s in re.split(r"(?<=\.)\s+", text) if "can't lose the game" in s.lower())
            rules.use("101.2", "704.5a")
            return Worked(f"No, not while {name.split(',')[0]} is on the battlefield",
                          [f"{name} says: “{sentence.strip()}”",
                           "When a rule says something happens and an effect says it can't, the “can't” "
                           "wins. Its controller loses as soon as it leaves, if they're still at 0 or less life."],
                          list(rules), "")
    if match := (re.search(r"(\d+)\s+(?:combat\s+)?(?:commander damage|damage from (?:\w+\s+){0,2}?commanders?)", lower)
                 or re.search(r"commanders? (?:has |have )?(?:deals?|dealt) (?:\w+\s+){0,3}?(\d+)(?: combat)? damage",
                              lower)):
        rules.use("903.10a", "704.6c")
        if re.search(r"\bdifferent commanders\b|\btwo commanders\b|\bcombined\b|\bin total from\b", lower):
            return Worked("No", ["Only combat damage from the same commander counts: a player loses after 21 or "
                                 "more from one commander."], list(rules), _STATE_NOTE)
        if "noncombat" in lower:
            return Worked("No", ["Only combat damage counts toward commander damage."], list(rules), _STATE_NOTE)
        amount = int(match.group(1))
        return Worked("Yes, that player loses" if amount >= 21 else "No",
                      [f"{amount} combat damage from the same commander is "
                       + ("21 or more, so that player loses the game the next time state-based actions are checked."
                          if amount >= 21 else "less than 21, so they haven't lost to commander damage.")],
                      list(rules), _STATE_NOTE)
    if match := re.search(r"(\d+)\s+poison", lower):
        rules.use("704.5c")
        amount = int(match.group(1))
        return Worked("Yes, that player loses" if amount >= 10 else "No",
                      [f"A player with ten or more poison counters loses the game; {amount} is "
                       f"{'enough' if amount >= 10 else 'not enough'}, whatever their life total."],
                      list(rules), _STATE_NOTE)
    empty = r"(?:empty library|library is empty|no cards (?:left )?in (?:my|their|his|her|your|the) library)"
    if re.search(rf"\bdraw\w*\b.*{empty}|{empty}.*\bdraw", lower):
        rules.use("704.5b", "117.5")
        return Worked("Yes, that player loses", ["A player who tried to draw from an empty library loses the next "
                                                 "time state-based actions are checked, before anyone gets "
                                                 "priority."], list(rules), _STATE_NOTE)
    if re.search(r"\b(?:mill\w*|exile\w*)\b.*\b(?:last card|whole library|entire library)\b", lower):
        rules.use("704.5b")
        return Worked("No, not until they'd have to draw", ["Having no cards in your library isn't a loss by itself: "
                                                        "you lose when you'd draw from an empty library."],
                      list(rules), _STATE_NOTE)
    life = re.search(r"(?:at|to|is|of|with|has|have|on)\s+(-?\d+)\s+life\b|life total (?:is|of|becomes|goes to|drops "
                     r"to|at|reaches)\s+(-?\d+)", lower)
    negative = re.search(r"\bnegative life\b|\bbelow (?:0|zero) life\b|\bzero life\b", lower)
    if life or negative:
        amount = int(next(g for g in life.groups() if g is not None)) if life else 0
        rules.use("704.5a")
        steps = []
        # Life lost and gained at the same time (combat damage and lifelink): only the result is checked
        lost = sum(int(next(g for g in m.groups() if g)) for m in re.finditer(
            r"\b(?:i'?m|i am|i was|i get|i'm being|i take|i took|i'll take|i'd take)\s+(?:dealt\s+)?(\d+)\s+"
            r"(?:combat\s+)?damage|\b(?:i )?lose (\d+) life", lower))
        gained = sum(int(a) for a in re.findall(r"\bgain (\d+) life", lower))
        if "lifelink" in lower:
            gained += sum(int(a) for a in re.findall(r"lifelink[^.]*?\bdeals? (\d+)", lower))
            rules.use("120.3f")
        if lost or gained:
            start, amount = amount, amount - lost + gained
            steps.append(f"They start at {start} life, gain {gained} and lose {lost} at the same time: {amount} life.")
            if "combat" in lower:
                rules.use("510.2")
        if amount > 0:
            steps.append(f"A player loses at 0 or less life; {amount} is above that.")
            return Worked("No", steps, list(rules), _STATE_NOTE)
        steps.append("A player with 0 or less life loses the game the next time state-based actions are checked.")
        if re.search(r"\brespon\w*|\bgain\w* life\b|\bbefore\b|\bin time\b", lower):
            rules.use("117.5")
            steps.append("State-based actions are checked before any player gets priority, so nobody can respond "
                         "(for example, by gaining life) once a player is at 0.")
        return Worked("Yes, that player loses", steps, list(rules), _STATE_NOTE)
    return None


def _legend_rule(lower, cards):
    if not re.search(r"\b(?:two|second|another|both|copy|copies|clone|same name|legend rule)\b", lower):
        return None
    rules = _Rules(["704.5j"])
    legendary = [n for n, c in cards.items() if "legendary" in (c["type_line"] or "").lower()]
    if not legendary and "legend" not in lower:
        return None
    if not legendary and cards and "legendary" not in lower:
        names = " and ".join(n.split(" // ")[0] for n in cards)
        return Worked("No", [f"{names} isn't legendary, so the legend rule doesn't apply."], list(rules), "")
    if re.search(r"\bdifferent names?\b", lower):
        return Worked("No", ["The legend rule only applies to legendary permanents with the same name."],
                      list(rules), "")
    if re.search(r"\b(?:each|both) control|\bmy opponent (?:also )?(?:controls?|has)\b|\b(?:an|the) opponent "
                 r"(?:controls?|has)\b|\bone each\b", lower):
        return Worked("No", ["The legend rule only applies when one player controls two or more legendary "
                             "permanents with the same name. Each player can have their own."], list(rules), "")
    rules.use("700.4")
    return Worked("You keep one; the other goes to the graveyard",
                  ["When you control two or more legendary permanents with the same name, you choose one to keep and "
                   "the rest are put into their owners' graveyards.",
                   "That isn't destroying or sacrificing them, so indestructible doesn't help. A creature put into the "
                   "graveyard this way does die, so “dies” abilities trigger."], list(rules), "")


def _planeswalker_state(lower, cards):
    walker = next((n for n, c in cards.items() if "planeswalker" in (c["type_line"] or "").lower()), None)
    if not walker and "planeswalker" not in lower:
        return None
    start = re.search(r"(?:with|has|at|of|on)\s+(\d+)\s+loyalty", lower)
    loyalty = int(start.group(1)) if start else _number(cards[walker]["loyalty"]) if walker else None
    if loyalty is None:
        return None
    rules, steps = _Rules(), [f"It starts with {loyalty} loyalty."]
    for amount in re.findall(r"(\d+)\s+(?:combat\s+)?damage", lower):
        loyalty -= int(amount)
        steps.append(f"{amount} damage removes {amount} loyalty counters: {loyalty} left.")
        rules.use("120.3c")
    for sign, amount in re.findall(r"(?:uses?|activates?|activated|using) (?:its |a |the |her |his )?([+−-])(\d+)",
                                   lower):
        loyalty += int(amount) if sign == "+" else -int(amount)
        steps.append(f"Its {sign}{amount} ability {'adds' if sign == '+' else 'removes'} {amount} loyalty as a cost: "
                     f"{loyalty} left.")
        rules.use("606.4")
    for amount in re.findall(r"remov\w* (\d+) loyalty", lower):
        loyalty -= int(amount)
        steps.append(f"Removing {amount} loyalty counters leaves {loyalty}.")
    if len(steps) == 1:
        return None
    rules.use("704.5i")
    if loyalty <= 0:
        steps.append("A planeswalker with 0 loyalty is put into its owner's graveyard.")
        return Worked("It goes to the graveyard", steps, list(rules), _STATE_NOTE)
    steps.append("It still has loyalty, so it stays.")
    return Worked(f"It stays, with {loyalty} loyalty", steps, list(rules), _STATE_NOTE)


def _fate(lower, dies, who):
    # "Yes, it survives" to "does it survive?", "No, it survives" to "does it die?"
    if re.search(r"\b(?:survive|survives|live|lives|stay|stays|still alive)\b", lower):
        return f"Yes, {who} survives" if not dies else f"No, {who} dies"
    if re.search(r"\b(?:die|dies|died|destroyed|graveyard)\b", lower):
        return f"Yes, {who} dies" if dies else f"No, {who} survives"
    text = f"{who} {'dies' if dies else 'survives'}"
    return text[0].upper() + text[1:]


def _creature_state(lower, cards):
    name, card = next(((n, c) for n, c in cards.items() if "creature" in (c["type_line"] or "").lower()),
                      (None, None))
    base = re.search(r"(?<![\w/+-])(\d+)/(\d+)(?![\w/])", lower)
    power, toughness = ((_number(card["power"]), _number(card["toughness"])) if card else
                        (int(base.group(1)), int(base.group(2))) if base else (None, None))
    rules, steps = _Rules(), []
    plus = minus = 0
    for count, sign in re.findall(rf"{_COUNT}\s+([+-])1/[+-]1 counters?", lower):
        if sign == "+":
            plus += _count(count)
        else:
            minus += _count(count)
    if re.search(r"\b(?:infect|wither)\b", lower):
        for amount in re.findall(r"(\d+)\s+(?:combat\s+)?damage", lower):
            minus += int(amount)
            steps.append(f"{amount} damage from a source with infect or wither is dealt as {amount} -1/-1 counters.")
            rules.use("120.3d")
        damage = 0
    else:
        damage = sum(int(a) for a in re.findall(r"(\d+)\s+(?:combat\s+)?damage", lower))
    if plus and minus:
        removed = min(plus, minus)
        plus, minus = plus - removed, minus - removed
        rules.use("704.5q")
        left = (f"{plus} +1/+1 counter{'s' * (plus != 1)}" if plus else
                f"{minus} -1/-1 counter{'s' * (minus != 1)}" if minus else "no counters")
        steps.append(f"+1/+1 and -1/-1 counters cancel out in pairs ({removed} of each are removed), leaving {left}.")
        if toughness is None:
            return Worked(left[0].upper() + left[1:], steps, list(rules), _STATE_NOTE)
    # Only "does it die / survive?"; "what are its power and toughness?" is a layers question
    if toughness is None or not re.search(r"\b(?:die|dies|died|destroyed|graveyard|survive|survives|live|lives|"
                                          r"still alive)\b", lower):
        return None
    who = name.split(" // ")[0] if name else "It"
    subject = who if name else "it"
    steps.insert(0, f"{who} starts as a {power}/{toughness}.")
    changes = [(int(p), int(t)) for p, t in re.findall(r"(?<![\w/])([+-]\d+)/([+-]\d+)(?!\s*counters?)", lower)]
    temporary = sum(t for _, t in changes) if "until end of turn" in lower else 0
    power += sum(p for p, _ in changes) + plus - minus
    toughness += sum(t for _, t in changes) + plus - minus
    if changes or plus or minus:
        rules.use("613.4c")
        steps.append(f"With its counters and effects it's a {power}/{toughness}.")
    indestructible = "indestructible" in lower or (card and "indestructible" in creature_from_card(name, card).keywords)
    deathtouch = damage and re.search(r"\bdeathtouch\b", lower)
    if re.search(r"\blethal damage\b", lower) and not damage:
        damage = max(toughness, 1)
    if damage:
        steps.append(f"It has {damage} damage marked on it.")
    if toughness <= 0:
        rules.use("704.5f")
        steps.append("A creature with 0 or less toughness is put into its owner's graveyard"
                     + (" (indestructible doesn't stop that, because it isn't destroyed)." if indestructible else "."))
        return Worked(_fate(lower, True, subject), steps, list(rules), _STATE_NOTE)
    lethal = damage >= toughness or deathtouch
    if lethal:
        rules.use("704.5g" if damage >= toughness else "704.5h")
        if indestructible:
            rules.use("702.12b")
            steps.append("That's lethal damage, but it's indestructible, so it isn't destroyed.")
            return Worked(_fate(lower, False, subject), steps, list(rules), _STATE_NOTE)
        steps.append("That's lethal damage" if damage >= toughness else "Damage from a source with deathtouch is "
                     "enough")
        steps[-1] += ", so it's destroyed the next time state-based actions are checked."
        return Worked(_fate(lower, True, subject), steps, list(rules), _STATE_NOTE)
    if temporary and re.search(r"\b(?:end of (?:the )?turn|cleanup|wears? off|end step|next turn)\b",
                               lower.replace("until end of turn", "")):
        rules.use("514.2")
        steps.append("In the cleanup step, damage is removed at the same time as “until end of turn” effects "
                     "end, so the damage never meets the lower toughness.")
        if toughness - temporary <= 0:
            rules.use("704.5f")
            steps.append("Without the effect its toughness is 0 or less, so it's put into the graveyard then.")
            return Worked(_fate(lower, True, subject) + ", when the effect ends", steps, list(rules), _STATE_NOTE)
        return Worked(_fate(lower, False, subject), steps, list(rules), _STATE_NOTE)
    if damage or changes or plus or minus:
        rules.use("704.5g")
        steps.append(f"{damage} damage is less than its toughness of {toughness}, so it survives.")
        return Worked(_fate(lower, False, subject), steps, list(rules), _STATE_NOTE)
    return None


def answer_state(question, cards):
    """A worked-out answer to "does it die / does that player lose / what's left?", or
    None. cards: {name: card database row} for the cards it names."""
    lower = question.lower()
    if not _ABOUT_STATE.search(lower):
        return None
    player_loses = re.search(r"\b(?:i|you|they|he|she|opponent|player)s? (?:lose|loses|lost)\b", lower)
    if player_loses and not _player_state(lower, cards):
        commander = next((n for n, c in cards.items() if re.search(r"legendary (?:\w+ )*creature",
                                                                    (c["type_line"] or "").lower())), None)
        damage = re.search(r"(\d+)\s+(?:combat\s+)?damage from", lower)
        if commander and damage:
            worked = _player_state(lower.replace(commander.lower(), "the same commander"), cards)
            if worked:
                worked.verdict += f", if {commander.split(',')[0]} is their commander"
                return worked
    if player_loses:
        return _player_state(lower, cards)
    return (_player_state(lower, cards) or _legend_rule(lower, cards) or _planeswalker_state(lower, cards)
            or _creature_state(lower, cards))


# Tokens: how many, and which, after every replacement effect (rule 616)

_AMOUNTS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
            "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20}
_CREATE = re.compile(rf"\bcreate ({'|'.join(_AMOUNTS)}|\d+) (tapped )?(.+?) tokens?\b", re.I)
_WOULD_CREATE = r"if (?:an effect would create one or more (creature )?tokens|one or more (creature )?tokens would be created)"
_MULTIPLY = re.compile(_WOULD_CREATE + r"(?P<yours> under your control)?, (?:it creates )?"
                                       r"(?P<times>twice|three times|four times) that many", re.I)
_PLUS_THAT_MANY = re.compile(_WOULD_CREATE + r"[^,]*, those tokens plus that many (?P<what>.+?) tokens? are "
                                             r"created instead", re.I)
_TIMES = {"twice": 2, "three times": 3, "four times": 4}
_TIMES_WORDS = {count: word for word, count in _TIMES.items()}
_ACTION = re.compile(r"\b(?:cast|casts|casting|activate|activates|activated|resolve|resolves|play|plays|use|uses)\b")


def _name_at(lower, name):
    # Where a card is named in a question, however it's typed ("kaya geist hunter's"), or -1
    words = re.split(r"[\s,]+", name.split(" // ")[0].lower())
    found = re.search(r"(?<!\w)" + r",?\s+".join(re.escape(w).replace("'", "'?") for w in words) + r"(?!\w)", lower)
    return found.start() if found else -1


def _cost(line):
    # A loyalty or activated ability's cost ("-2", "{T}"), or None for other lines
    found = re.match(r"^([+−-]?(?:\d+|X)|[^\"“:]*\{[^}]*\}[^\"“:]*):", line)
    return found.group(1).replace("−", "-") if found else None


def _token_effects(cards, lower, source):
    """The replacement effects on creating tokens from the cards on the battlefield:
    [(card, kind, value, creature only, rule text)] with kind "times" (value 2, 3…) or
    "plus" (value: the tokens added, as many as the tokens being created). An activated
    ability's effect (Kaya's −2) counts when the question gives its cost."""
    effects = []
    for name, card in cards.items():
        # An instant or sorcery isn't on the battlefield; a permanent making tokens is (Elspeth doubles her own +1)
        if name == source and re.search(r"\b(?:instant|sorcery)\b", (card["type_line"] or "").lower()):
            continue
        for line in (card["oracle_text"] or "").split("\n\n")[0].split("\n"):
            cost = _cost(line)
            if cost and cost not in lower.replace("−", "-"):
                continue
            short = name.split(",")[0].split(" // ")[0]
            if found := _MULTIPLY.search(line):
                creature_only = bool(found.group(1) or found.group(2))
                effects.append((short, "times", _TIMES[found.group("times").lower()], creature_only, line))
            elif found := _PLUS_THAT_MANY.search(line):
                effects.append((short, "plus", found.group("what"), False, line))
    return effects


def _apply(groups, effects, steps):
    # groups: {token description: [count, is creature]}; each effect applies once, in this order
    for name, kind, value, creature_only, _ in effects:
        if kind == "plus":
            total = sum(count for count, _ in groups.values())
            key = f"{value} token"
            groups.setdefault(key, [0, "creature" in value.lower()])[0] += total
            steps.append(f"{name}: plus that many {value} tokens (+{total:,}).")
        else:
            for count_and_kind in groups.values():
                if count_and_kind[1] or not creature_only:
                    count_and_kind[0] *= value
            what = "creature tokens" if creature_only else "tokens"
            steps.append(f"{name}: {_TIMES_WORDS.get(value, f'{value} times')} that many {what} "
                         f"({sum(c for c, _ in groups.values()):,}).")
    return groups


def _event(description, count, effects):
    # One token-making event through every effect: (groups, steps), in the order that makes the most
    order = sorted(effects, key=lambda e: e[1] != "plus")         # additions first: then they're multiplied too
    steps = []
    groups = _apply({description: [count, "creature" in description.lower()]}, order, steps)
    reverse = _apply({description: [count, "creature" in description.lower()]},
                     sorted(effects, key=lambda e: e[1] == "plus"), [])
    total, other = sum(c for c, _ in groups.values()), sum(c for c, _ in reverse.values())
    if total != other:
        steps.append(f"You choose the order the effects apply in. This order gives the most; applying the "
                     f"additions last would give {other:,}.")
    return groups, steps


def _describe(groups):
    parts = [f"{count:,} {what}{'s' if count != 1 else ''}" for what, (count, _) in groups.items() if count]
    return " and ".join(parts) if len(parts) < 3 else ", ".join(parts[:-1]) + " and " + parts[-1]


def answer_tokens(question, cards):
    """How many tokens a spell or ability makes, and which, through every replacement
    effect on the battlefield (Doubling Season, Chatterfang…); or None. cards: {name: card
    database row} for the cards the question names."""
    lower = question.lower()
    if "token" not in lower or not re.search(r"\bhow many\b|\bwhat tokens\b|\bwhich tokens\b|\bend up\b", lower):
        return None
    # The card making the tokens: named after "cast", "activate"…, with a "create … token" of its own
    positions = sorted((position, name) for name in cards if (position := _name_at(lower, name)) >= 0)
    actions = [m.start() for m in _ACTION.finditer(lower)]
    source, made = None, None
    for position, name in sorted(positions, key=lambda p: not any(a < p[0] for a in actions)):
        for line in (cards[name]["oracle_text"] or "").split("\n\n")[0].split("\n"):
            cost = _cost(line)
            if "would" in line or (cost and cost not in lower.replace("−", "-")):
                continue
            if found := _CREATE.search(line):
                source, made = name, found
                break
        if source:
            break
    if not source:
        return None
    count = int(made.group(1)) if made.group(1).isdigit() else _AMOUNTS[made.group(1).lower()]
    description = (made.group(2) or "") + made.group(3) + " token"
    effects = _token_effects(cards, lower, source)
    rules = _Rules(["111.1", "614.1a", "616.1"])
    groups, steps = _event(description, count, effects)
    short = source.split(",")[0].split(" // ")[0]
    steps.insert(0, f"{short} creates {count:,} {description}{'s' if count != 1 else ''}. Each replacement effect "
                    "applies once, in the order you choose:")
    total = sum(c for c, _ in groups.values())
    verdict = f"{total:,} tokens: {_describe(groups)}"

    # Tokens made later this turn by triggers (Ocelot Pride at your end step)
    for name, card in cards.items():
        text = card["oracle_text"] or ""
        trigger = re.search(r"At the beginning of your end step, if you gained life this turn, create (a|an|one) "
                            r"(.+?) token\.( Then if you have the city's blessing, for each token you control that "
                            r"entered this turn, create a token that's a copy of it)?", text)
        if not trigger:
            continue
        rules.use("603.4")
        who = name.split(",")[0]
        if not re.search(r"\bgain(?:ed|s)? (?:\d+ |some )?life\b|\blifelink\b.*\b(?:dealt|deals|attack)", lower):
            steps.append(f"{who} makes more at your end step, but only if you gained life this turn, and the question "
                         "doesn't say you did.")
        cat, _ = _event(trigger.group(2) + " token", 1, effects)
        more = sum(c for c, _ in cat.values())
        line = f"If you gained life this turn, at your end step {who} creates {_describe(cat)} ({more:,})"
        if trigger.group(3):
            rules.use("702.131b")
            entered = total + more
            copies, _ = _event("creature token copy", entered, effects)   # copies of creature tokens are creature tokens
            more += sum(c for c, _ in copies.values())
            line += (f", then (you have the city's blessing: you control ten or more permanents) a copy of each "
                     f"of the {entered:,} tokens that entered this turn, through the same effects: "
                     f"{sum(c for c, _ in copies.values()):,} more")
        steps.append(line + f". That would make {total + more:,} tokens made this turn in all.")
    return Worked(verdict, steps, list(rules), "It counts the replacement effects of the cards you name; any "
                  "others you control would change the count.")
