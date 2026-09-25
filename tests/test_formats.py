import json

import formats


def _card(id, name, quantity, section="Main", legal="legal", type_line="Instant", identity="R", text=""):
    legalities = json.dumps({key: legal for key in formats.FORMATS})
    return {"id": id, "name": name, "quantity": quantity, "section": section, "legalities": legalities,
            "type_line": type_line, "color_identity": identity, "oracle_text": text}


def _deck(size, more=()):
    return [_card(1, "Lightning Bolt", 4),
            _card(2, "Mountain", size - 4, type_line="Basic Land — Mountain", identity="")] + list(more)


def test_legal_standard_deck_has_no_problems():
    assert formats.validate(_deck(60), "standard") == ([], {})
    assert formats.type_counts(_deck(60)) == {"Instant": 4, "Land": 56}


def test_deck_size_sideboard_and_copies():
    problems, statuses = formats.validate(
        _deck(50, [_card(3, "Shock", 5), _card(4, "Duress", 16, section="Sideboard"),
                   _card(5, "Opt", 30, section="Maybeboard")]), "modern")
    assert any("at least 60" in p for p in problems)
    assert any("at most 15" in p for p in problems)
    # Sideboard copies count toward the limit; Maybeboard copies don't
    assert statuses == {3: "Too many (5, max 4)", 4: "Too many (16, max 4)"}


def test_banned_restricted_and_not_legal():
    deck = _deck(60, [_card(3, "Oko", 1, legal="banned"), _card(4, "Ancestral Recall", 2, legal="restricted"),
                      _card(5, "Brainstorm", 1, legal="not_legal")])
    _, statuses = formats.validate(deck, "vintage")
    assert statuses == {3: "Banned", 4: "Restricted (1 copy)", 5: "Not legal"}


def test_special_copy_limits():
    fmt = formats.FORMATS["modern"]
    rats = _card(1, "Relentless Rats", 20, text="A deck can have any number of cards named Relentless Rats.")
    dwarves = _card(2, "Seven Dwarves", 7, text="A deck can have up to seven cards named Seven Dwarves.")
    assert formats.copy_limit(rats, fmt) is None
    assert formats.copy_limit(dwarves, fmt) == 7
    assert formats.copy_limit(_card(3, "Snow-Covered Island", 1, type_line="Basic Snow Land — Island"), fmt) is None


def test_commander_size_singleton_and_color_identity():
    deck = [_card(1, "Krenko, Mob Boss", 1, section="Commander", type_line="Legendary Creature — Goblin"),
            _card(2, "Mountain", 96, type_line="Basic Land — Mountain", identity=""),
            _card(3, "Sol Ring", 2, type_line="Artifact", identity=""),
            _card(4, "Counterspell", 1, identity="U")]
    problems, statuses = formats.validate(deck, "commander")
    assert not any("exactly 100" in p for p in problems)  # 1 + 96 + 2 + 1, commander included
    assert statuses == {3: "Too many (2, max 1)", 4: "Outside color identity"}

    no_commander, _ = formats.validate([_card(2, "Mountain", 100, type_line="Basic Land", identity="")],
                                       "commander")
    assert any("Choose a commander" in p for p in no_commander)
    wrong_size, _ = formats.validate(deck[:2], "commander")
    assert any("exactly 100" in p for p in wrong_size)
    in_standard, _ = formats.validate(deck, "standard")
    assert any("has no commander" in p for p in in_standard)

    walker = _card(1, "Oko, Thief of Crowns", 1, section="Commander", type_line="Legendary Planeswalker — Oko")
    assert formats.validate([walker], "commander")[1] == {1: "Can't be a commander"}
    assert 1 not in formats.validate([walker], "brawl")[1]
    assert formats.can_be_commander({**walker, "type_line": "Legendary Enchantment — Background"}, "commander")


def test_unknown_legality_and_casual():
    deck = _deck(60, [{**_card(3, "Homebrew", 1), "legalities": None}])
    problems, statuses = formats.validate(deck, "standard")
    assert statuses == {} and any("unknown for 1 card" in p for p in problems)
    assert formats.validate(_deck(5), "casual") == ([], {})
