import card_sorting as cs


def _card(id, name, price=None, quantity=1, type_line=None, cmc=None, colors=None, rarity=None, section=None,
          set_name="Alpha", number="1", foil=0, condition="NM"):
    return {"id": id, "name": name, "price": price, "quantity": quantity, "type_line": type_line, "cmc": cmc,
            "colors": colors, "rarity": rarity, "section": section, "set_name": set_name, "set_code": "lea",
            "collector_number": number, "foil": foil, "condition": condition}


CARDS = [_card(1, "Sol Ring", 1.5, 3, "Artifact", 1, "", "uncommon", number="10"),
         _card(2, "Llanowar Elves", 0.3, 1, "Creature — Elf Druid", 1, "G", "common", number="9"),
         _card(3, "Lightning Helix", None, 2, "Instant", 2, "RW", "uncommon"),
         _card(4, "Mystery Card", 5.0)]  # no rules known


def names(rows):
    return [r["name"] for r in rows]


def test_sorts_go_both_ways_with_unknowns_last():
    assert names(cs.sort_rows(CARDS, "Price", True)) == ["Mystery Card", "Sol Ring", "Llanowar Elves", "Lightning Helix"]
    assert names(cs.sort_rows(CARDS, "Price", False))[-1] == "Lightning Helix"  # no price: last either way
    assert names(cs.sort_rows(CARDS, "Name", True)) == ["Sol Ring", "Mystery Card", "Llanowar Elves", "Lightning Helix"]
    assert names(cs.sort_rows(CARDS, "Color", False)) == ["Llanowar Elves", "Lightning Helix", "Sol Ring", "Mystery Card"]
    assert names(cs.sort_rows(CARDS, "Set", False))[2:] == ["Llanowar Elves", "Sol Ring"]  # 1s, then 9, then 10
    assert names(cs.sort_rows(CARDS, "Date added", True))[0] == "Mystery Card"


def test_groups_and_headings():
    view = {"sort": "Name", "descending": False, "group": "Type"}
    groups = cs.arrange(CARDS, view, "collection")
    assert [title for title, _ in groups] == ["Creatures", "Instants", "Artifacts", "Unknown"]
    assert cs.heading("Artifacts", groups[2][1]) == "Artifacts — 3 cards · $4.50"
    assert [t for t, _ in cs.arrange(CARDS, {**view, "group": "Color"}, "collection")] == \
        ["Green", "Multicolor", "Colorless", "Unknown"]
    assert cs.arrange(CARDS, {**view, "group": "Nothing"}, "collection")[0][0] is None


def test_a_deck_keeps_its_sections_apart():
    deck = [_card(1, "Kenrith", section="Commander", type_line="Legendary Creature"),
            _card(2, "Sol Ring", section="Main", type_line="Artifact"),
            _card(3, "Llanowar Elves", section="Main", type_line="Creature"),
            _card(4, "Negate", section="Sideboard", type_line="Instant")]
    view = {"sort": "Name", "descending": False, "group": "Type"}
    assert [t for t, _ in cs.arrange(deck, view, "deck")] == ["Commander", "Creatures", "Artifacts", "Sideboard"]
    assert [t for t, _ in cs.arrange(deck, {**view, "group": "Section"}, "deck")] == ["Commander", "Main Deck",
                                                                                      "Sideboard"]


def test_views_are_remembered_per_list(temp_db):
    assert cs.load("collection", "collection") == cs.default("collection")
    view = cs.picked(cs.default("collection"), "Price")
    assert view["descending"]  # price starts high to low
    cs.save("collection", {**view, "group": "Rarity"})
    assert cs.load("collection", "collection") == {"sort": "Price", "descending": True, "group": "Rarity"}
    cs.save("list:7", {"sort": "Price", "descending": False, "group": "Condition"})  # not a deck grouping
    assert cs.load("list:7", "deck") == cs.default("deck")
