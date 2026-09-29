import pytest

import deck_links
import importer


def _card(name, qty, categories, edition="tsp", number="227", modifier="Normal"):
    return {"quantity": qty, "categories": categories, "modifier": modifier,
            "card": {"oracleCard": {"name": name}, "edition": {"editioncode": edition}, "collectorNumber": number}}


def test_archidekt_keeps_printings_and_sections():
    data = {"name": "Fungus", "categories": [{"name": "Considering", "includedInDeck": False}],
            "cards": [_card("Thelon of Havenwood", 1, ["Commander"]),
                      _card("Mana Crypt", 1, ["Ramp"], "mps", "16", "Foil"),
                      _card("Pithing Needle", 2, ["Sideboard"], "sok", "158"),
                      _card("Doubling Season", 1, ["Considering"], "rav", "155")]}
    name, text = deck_links.archidekt_text(data)
    assert name == "Fungus"
    rows, errors = importer.parse_text(text)
    assert not errors
    found = {(r.name, r.section, r.set_code.upper(), r.collector_number, r.foil) for r in rows}
    assert ("Thelon of Havenwood", "Commander", "TSP", "227", 0) in found
    assert ("Mana Crypt", "Main", "MPS", "16", 1) in found
    assert ("Pithing Needle", "Sideboard", "SOK", "158", 0) in found
    assert ("Doubling Season", "Maybeboard", "RAV", "155", 0) in found   # its category isn't in the deck


def test_goldfish_blank_line_starts_the_sideboard():
    _, text = deck_links.goldfish_text("4 Lightning Bolt\r\n20 Mountain\r\n\r\n2 Smash to Smithereens\r\n")
    rows, _ = importer.parse_text(text)
    assert [(r.name, r.section) for r in rows] == [("Lightning Bolt", "Main"), ("Mountain", "Main"),
                                                   ("Smash to Smithereens", "Sideboard")]


def test_links_are_recognized_or_explained():
    assert deck_links.source("https://archidekt.com/decks/123/my_deck")[1] == "https://archidekt.com/api/decks/123/"
    assert deck_links.source("https://www.mtggoldfish.com/deck/6520000#paper")[1] == \
        "https://www.mtggoldfish.com/deck/download/6520000"
    with pytest.raises(deck_links.LinkError, match="Moxfield"):
        deck_links.source("https://moxfield.com/decks/abc")
    with pytest.raises(deck_links.LinkError, match="Archidekt and MTGGoldfish"):
        deck_links.source("https://example.com/deck")
    assert deck_links.is_link("  https://archidekt.com/decks/1  ")
    assert not deck_links.is_link("4 Lightning Bolt")
