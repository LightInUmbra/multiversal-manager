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


def _card(name, type_line, cmc, cost, quantity=1, section="Main", price=None):
    return _entry(name, quantity, section, cmc, cost, type_line, price)


def test_stats_count_the_deck_and_leave_out_the_sideboard():
    entries = [_card("Lightning Bolt", "Instant", 1, "{R}", 4, price=1.5),
               _card("Goblin Guide", "Creature — Goblin Scout", 1, "{R}", 4, price=3.0),
               _card("Fireball", "Sorcery", 1, "{X}{R}", 2),
               _card("Mountain", "Basic Land — Mountain", 0, "", 10),
               _card("Smash to Smithereens", "Instant", 2, "{1}{R}", 3, section="Sideboard", price=0.25)]
    st = deck_stats.stats(entries)
    assert st["curve"][1] == 10 and st["curve"][2] == 0      # sideboard and lands left out
    assert st["average"] == 1.0
    assert st["colors"] == {"R": 10}
    assert list(st["types"]) == ["Land", "Instant", "Creature", "Sorcery"]   # most first
    assert (st["lands"], st["size"]) == (10, 20)
    assert [e["name"] for e in st["priciest"]] == ["Goblin Guide", "Lightning Bolt", "Smash to Smithereens"]


def test_binders_count_every_card_and_empty_lists_have_no_stats():
    binder = [_card("Sol Ring", "Artifact", 1, "{1}", section="")]
    assert deck_stats.stats(binder, is_deck=False)["size"] == 1
    assert deck_stats.stats(binder) is None          # as a deck, nothing's in the main deck
    assert deck_stats.stats([]) is None


def test_the_desktop_draws_the_stats_as_html():
    import lists
    page = lists.stats_html(deck_stats.stats([_card("Lightning Bolt", "Instant", 1, "{R}", 4, price=1.5),
                                              _card("Mountain", "Basic Land — Mountain", 0, "", 6)]))
    assert "Mana curve" in page and "Average mana value 1.00" in page and "Red" in page
    assert "Instants" in page and "6 lands of 10 cards (60%)" in page and "$1.50" in page
