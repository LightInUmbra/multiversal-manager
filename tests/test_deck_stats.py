import deck_stats


def _entry(name, quantity=1, section="Main", cmc=None, mana_cost="", type_line="", price=None):
    return {"id": name, "name": name, "quantity": quantity, "section": section, "cmc": cmc,
            "mana_cost": mana_cost, "type_line": type_line, "price": price}


DECK = [
    _entry("Urza, Lord High Artificer", section="Commander", cmc=4, mana_cost="{2}{U}{U}",
           type_line="Legendary Creature — Human Artificer", price=16.33),
    _entry("Sol Ring", cmc=1, mana_cost="{1}", type_line="Artifact", price=2.91),
    _entry("Island", quantity=30, cmc=0, type_line="Basic Land — Island", price=0.34),
    _entry("Ulamog, the Ceaseless Hunger", cmc=10, mana_cost="{10}", type_line="Legendary Creature — Eldrazi"),
    _entry("Kitchen Finks", quantity=2, cmc=3, mana_cost="{1}{G/W}{G/W}", type_line="Creature — Ouphe"),
    _entry("Gut Shot", cmc=1, mana_cost="{R/P}", type_line="Instant"),
    _entry("Counterspell", section="Sideboard", cmc=2, mana_cost="{U}{U}", type_line="Instant", price=4.31),
    _entry("Mystery card", cmc=None),  # not looked up yet
]


def test_mana_curve_counts_spells_only_and_caps_at_seven_plus():
    curve = deck_stats.mana_curve(DECK)
    assert curve == {0: 0, 1: 2, 2: 0, 3: 2, 4: 1, 5: 0, 6: 0, 7: 1}  # no lands, no sideboard


def test_average_mana_value():
    assert deck_stats.average_mana_value(DECK) == (4 + 1 + 10 + 3 * 2 + 1) / 6
    assert deck_stats.average_mana_value([]) is None


def test_color_symbols_count_hybrid_and_phyrexian_for_each_color():
    assert deck_stats.color_symbols(DECK) == {"W": 4, "U": 2, "R": 1, "G": 4}


def test_priciest_first():
    assert [e["name"] for e in deck_stats.priciest(DECK, 2)] == ["Urza, Lord High Artificer", "Counterspell"]
