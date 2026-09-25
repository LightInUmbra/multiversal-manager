import importer
import lists


def _entry(id, name, quantity, price=1.0, section="Main", set_code="", number="", foil=0):
    return {"id": id, "name": name, "quantity": quantity, "price": price, "section": section,
            "set_code": set_code, "collector_number": number, "foil": foil}


def test_owned_copies_are_shared_out_across_printings():
    entries = [_entry(1, "Lightning Bolt", 3), _entry(2, "Lightning Bolt", 2, price=5.0), _entry(3, "Opt", 4)]
    have = lists.completion(entries, {"lightning bolt": 4})
    assert have == {1: 3, 2: 1, 3: 0}
    cards, value, owned, missing, cost = lists.summary(entries, have)
    assert (cards, value, owned, missing, cost) == (9, 17.0, 4, 5, 5.0 + 4.0)


def test_deck_sections_survive_export_and_import():
    entries = [_entry(1, "Atraxa, Praetors' Voice", 1, section="Commander", set_code="2XM", number="190"),
               _entry(2, "Sol Ring", 1, set_code="C21", number="263", foil=1),
               _entry(3, "Duress", 2, section="Sideboard")]
    text = lists.deck_text(entries)
    assert text.splitlines()[:2] == ["Commander", "1 Atraxa, Praetors' Voice (2XM) 190"]
    rows, errors = importer.parse_text(text)
    assert not errors
    assert [(r.name, r.section, r.foil, r.set_code) for r in rows] == [
        ("Atraxa, Praetors' Voice", "Commander", False, "2xm"),
        ("Sol Ring", "Main", True, "c21"),
        ("Duress", "Sideboard", False, ""),
    ]


def test_text_sections_from_other_tools():
    rows, _ = importer.parse_text("About\nName My Deck\n\nDeck\n4 Opt\nSB: 2 Duress\n\nSideboard\n1 Negate\n")
    assert [(r.name, r.section) for r in rows] == [("Opt", "Main"), ("Duress", "Sideboard"), ("Negate", "Sideboard")]


def _oracle(name, type_line, colors, identity, legal_in, set_code="XLN"):
    import json
    return {"name": name, "type_line": type_line, "mana_cost": "{U}", "cmc": 1, "colors": colors,
            "color_identity": identity, "oracle_text": f"{name} text",
            "legalities": json.dumps({f: "legal" for f in legal_in}), "scryfall_id": name.lower(),
            "set_code": set_code, "set_name": "Set", "collector_number": "1", "rarity": "common",
            "image_url": None, "foil": 0, "price": 1.0}


def test_card_search_owned_and_explore(temp_db):
    temp_db.replace_oracle_cards([
        _oracle("Opt", "Instant", "U", "U", ["standard", "modern"]),
        _oracle("Lightning Bolt", "Instant", "R", "R", ["modern"]),
        _oracle("Llanowar Elves", "Creature — Elf Druid", "G", "G", ["standard", "modern"]),
        _oracle("Sol Ring", "Artifact", "", "", ["commander"]),
    ])
    temp_db.add_card("Opt", "Ixalan", 0.25, 3, scryfall_id="opt")

    def names(**filters):
        rows, total = temp_db.search_cards(filters.pop("owned_only", False), **filters)
        return [r["name"] for r in rows]

    assert names() == ["Lightning Bolt", "Llanowar Elves", "Opt", "Sol Ring"]
    assert names(owned_only=True) == ["Opt"]
    assert names(text="elf") == ["Llanowar Elves"]                # type line matches too
    assert names(card_type="Instant") == ["Lightning Bolt", "Opt"]
    assert names(colors="RG") == ["Lightning Bolt", "Llanowar Elves"]
    assert names(colors="C") == ["Sol Ring"]
    assert names(format_key="standard") == ["Llanowar Elves", "Opt"]
    assert names(identity="U") == ["Opt", "Sol Ring"]             # within a mono-blue commander's colors
    rows, total = temp_db.search_cards(False, limit=2)
    assert (len(rows), total) == (2, 4)
    assert temp_db.card_names("l") == ["Lightning Bolt", "Llanowar Elves", "Sol Ring"]  # prefix matches first
    [opt] = [r for r in temp_db.search_cards(False, text="opt")[0]]
    assert opt["owned"] == 3

    deck = temp_db.create_list("Tempo", "deck", "modern")
    temp_db.add_list_entries(deck, [{"name": "Opt", "quantity": 4}], section="Main")
    [entry] = temp_db.get_list_entries(deck)
    assert (entry["type_line"], entry["color_identity"]) == ("Instant", "U")  # card info joined by name
    assert temp_db.get_lists()[0]["format"] == "modern"


def test_card_database_from_bulk_data():
    import finance
    card = finance.oracle_record({
        "id": "delver", "name": "Delver of Secrets // Insectile Aberration", "layout": "transform",
        "type_line": "Creature — Human Wizard // Creature — Human Insect", "cmc": 1, "color_identity": ["U"],
        "legalities": {"modern": "legal"}, "finishes": ["nonfoil", "foil"], "prices": {"usd": "0.10"},
        "set": "isd", "set_name": "Innistrad", "collector_number": "51", "rarity": "common",
        "card_faces": [{"mana_cost": "{U}", "colors": ["U"], "oracle_text": "Front."},
                       {"mana_cost": "", "colors": ["U"], "oracle_text": "Flying"}],
    })
    assert (card["mana_cost"], card["colors"], card["color_identity"], card["price"]) == ("{U}", "U", "U", 0.10)
    assert card["oracle_text"] == "Front.\n\nFlying"
    assert finance.oracle_record({"id": "t", "name": "Goblin", "layout": "token"}) is None


def test_printings_grouped_with_finishes_and_owned(temp_db):
    from card_browser import group_printings
    temp_db.watch_cards([
        {"scryfall_id": sid, "foil": foil, "name": "Opt", "set_code": code, "set_name": name,
         "collector_number": "1", "rarity": "common", "image_url": None, "price": price}
        for sid, foil, code, name, price in [("a", 0, "XLN", "Ixalan", 0.25), ("a", 1, "XLN", "Ixalan", 1.50),
                                             ("b", 0, "DOM", "Dominaria", 0.10)]])
    temp_db.add_card("Opt", "Ixalan", 1.50, 2, scryfall_id="a", foil=True)
    printings = group_printings(temp_db.printings_of("opt"))
    assert [(p["set_code"], p["finishes"], p["owned"], p["price"]) for p in printings] == [
        ("DOM", [(0, 0.10, 0)], 0, 0.10),
        ("XLN", [(0, 0.25, 0), (1, 1.50, 2)], 2, 0.25),
    ]


def test_list_storage(temp_db):
    deck = temp_db.create_list("Izzet", "deck")
    wishlist = temp_db.create_list("Wants", "wishlist")
    opt = {"name": "Opt", "set_name": "Ixalan", "set_code": "XLN", "collector_number": "65",
           "scryfall_id": "opt", "foil": False, "price": 0.25, "quantity": 2, "condition": "LP"}
    temp_db.add_list_entries(deck, [opt, opt], section="Main")          # same printing: merged
    temp_db.add_list_entries(deck, [{**opt, "section": "Sideboard"}])  # other section: separate
    temp_db.add_list_entries(wishlist, [opt])
    entries = temp_db.get_list_entries(deck)
    assert sorted((e["section"], e["quantity"]) for e in entries) == [("Main", 4), ("Sideboard", 2)]

    temp_db.update_list_entry(entries[0]["id"], quantity=1, section="Maybeboard")
    temp_db.update_list_prices([(entries[0]["id"], 0.30)])
    [changed] = [e for e in temp_db.get_list_entries(deck) if e["id"] == entries[0]["id"]]
    assert (changed["quantity"], changed["section"], changed["price"]) == (1, "Maybeboard", 0.30)

    summary = {row["name"]: (row["kind"], row["cards"]) for row in temp_db.get_lists()}
    assert summary == {"Izzet": ("deck", 3), "Wants": ("wishlist", 2)}
    temp_db.delete_list(deck)
    assert [row["name"] for row in temp_db.get_lists()] == ["Wants"]
    assert temp_db.get_list_entries(deck) == []

    temp_db.add_card("Opt", "Ixalan", 0.25, 3, scryfall_id="opt")
    temp_db.add_card("OPT", "Other", 0.25, 1)
    assert temp_db.owned_by_name() == {"opt": 4}
