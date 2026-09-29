import interactions as ix


def _card(name, type_line, text):
    return {"name": name, "type_line": type_line, "oracle_text": text}


RHYS = _card("Rhys the Redeemed", "Legendary Creature — Elf Warrior",
             "{2}{G/W}, {T}: Create a 1/1 green and white Elf Warrior creature token.\n"
             "{4}{G/W}{G/W}, {T}: For each creature token you control, create a token that's a copy of that creature.")
SCALES = _card("Hardened Scales", "Enchantment", "If one or more +1/+1 counters would be put on a creature you "
               "control, that many plus one +1/+1 counters are put on it instead.")
ARTIST = _card("Blood Artist", "Creature — Vampire", "Whenever Blood Artist or another creature dies, target player "
               "loses 1 life and you gain 1 life.")
ALTAR = _card("Ashnod's Altar", "Artifact", "Sacrifice a creature: Add {C}{C}.")


def test_roles_come_from_type_line_and_rules_text():
    assert ix.roles_of(RHYS) == ({"tokens"}, {"tokens"})
    # A replacement effect only pays off: Hardened Scales puts no counters out by itself
    assert ix.roles_of(SCALES) == ({"enchantments"}, {"counters"})
    assert ix.roles_of(ARTIST) == ({"lifegain"}, {"deaths"})
    assert ix.roles_of(ALTAR) == ({"artifacts", "deaths"}, set())
    # Reminder text isn't the card's own
    assert ix.roles_of(_card("Sidisi's Faithful", "Creature — Naga Wizard",
                             "Exploit (When this creature enters, you may sacrifice a creature.)")) == (set(), set())


def test_ruling_links_leave_out_words_sets_subtypes_and_examples():
    cards = ["Mindlock Orb", "Arcbound Ravager", "Consider", "Ramunap Excavator", "Excavator", "Shapeshifter",
             "Stifle", "Sylvan Bounty", "Aether Revolt"]
    rulings = {
        "Mindlock Orb": ["If Arcbound Ravager's ability is activated, you can't search your library."],
        "Arcbound Ravager": ["You may consider it; consider it again; consider waiting. Consider it done."],
        "Ramunap Excavator": ["Ramunap Excavator doesn't allow you to activate abilities of land cards."],
        "Sylvan Bounty": ["Effects that interact with activated abilities (such as Stifle) interact with it.",
                          "A Shapeshifter token copies it. Aether Revolt had it."],
    }
    links = ix.ruling_links(cards, rulings, set_names=["Aether Revolt"], subtypes=["Shapeshifter"])
    assert set(links) == {("Mindlock Orb", "Arcbound Ravager")}


def test_ruling_links_leave_out_stock_examples_named_by_many_cards():
    count = ix.MAX_REFERENCES + 1
    cards = ["Doubling Season"] + [f"Card {n}" for n in range(count)]
    rulings = {f"Card {n}": ["If you control Doubling Season, you get twice as many."] for n in range(count)}
    assert ix.ruling_links(cards, rulings) == {}


def test_ruling_themes_are_the_ones_only_the_rulings_match():
    import synergy
    cards = {c["name"]: c for c in (RHYS, ALTAR, _card("Clever Copy", "Instant", "Copy target spell you control."))}
    rulings = {"Clever Copy": ["If the copied spell creates tokens, the copy creates tokens too."],
               "Rhys the Redeemed": ["The copies are tokens, so they're created, not cast."],  # its own text says so
               "Ashnod's Altar": ["Mana abilities don't use the stack. Sacrificing an Elf or Wolves works too. "
                                  "In a Two-Headed Giant game, or with The Lord of the Rings, it's the same. "
                                  "Choose a type, such as Fungus or Archer. Wizards of the Coast says so; see Wizards.com."]}
    assert ix.ruling_themes(cards, rulings, synergy.THEMES) == {"Clever Copy": ["tokens"]}
    # Creature types the rulings name (by their plural too), as tribal theme keys; Rhys's rulings add nothing
    found = ix.ruling_themes(cards, rulings, synergy.THEMES, ["Elf", "Wolf", "Giant", "Lord", "Fungus", "Archer",
                                                              "Wizard"], synergy.tribal_theme)
    assert found["Ashnod's Altar"] == ["tribal:Elf", "tribal:Wolf"]
    assert "Rhys the Redeemed" not in found


def test_rulings_copied_onto_many_cards_are_left_out():
    boilerplate = "Prepared creatures create a copy of their prepare spell."
    rulings = {f"Card {n}": [boilerplate] for n in range(ix.BOILERPLATE)}
    rulings["Card 0"] = [boilerplate, "Card 0's own ruling."]
    assert ix.own_rulings(rulings) == {"Card 0": ["Card 0's own ruling."]}


def test_interactions_say_why_and_find_partners():
    data = {"roles": {"Rhys the Redeemed": [["tokens"], ["tokens"], 1], "Anointed Procession": [[], ["tokens"], 4],
                      "Raise the Alarm": [["spells", "tokens"], [], 2], "Blood Artist": [["lifegain"], ["deaths"], 2]},
            "rulings": [["Mindlock Orb", "Arcbound Ravager", "A ruling."]]}
    engine = ix.Interactions(data)
    assert engine.reasons("Raise the Alarm", "Anointed Procession") == [(1.0, "makes tokens for Anointed Procession")]
    assert engine.reasons("Anointed Procession", "Raise the Alarm") == [(1.0, "pays off the tokens Raise the Alarm makes")]
    assert engine.reasons("Arcbound Ravager", "Mindlock Orb")[0] == (ix.RULING_WEIGHT, "a ruling covers it with Mindlock Orb")
    assert engine.reasons("Blood Artist", "Raise the Alarm") == []
    assert set(engine.partners("Anointed Procession")) == {"Rhys the Redeemed", "Raise the Alarm"}
    # A card newer than the data pairs up by its own text
    assert engine.reasons(RHYS | {"name": "New Token Maker"}, "Anointed Procession")
    # Examples: sharing the most, then the most focused, then the cheapest
    assert engine.summary("Anointed Procession") == [
        "Pays off tokens: 2 cards provide it, like Rhys the Redeemed, Raise the Alarm"]
    assert engine.summary("Mindlock Orb") == ["Arcbound Ravager: a ruling covers them together"]
