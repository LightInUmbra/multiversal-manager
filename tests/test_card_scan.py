import card_scan

NAMES = card_scan.Names(["Sol Ring", "Solemn Simulacrum", "Llanowar Elves", "Lightning Bolt", "Kaya, Geist Hunter",
                         "Delver of Secrets // Insectile Aberration", "Thassa's Oracle", "Arcane Signet",
                         "Emeritus of Truce // Swords to Plowshares", "Swords to Plowshares"])


def _lines(*texts):
    # Text read off a photo, top to bottom
    return [{"text": t, "top": 40 * i} for i, t in enumerate(texts)]


def test_a_modern_card_gives_its_name_set_and_number():
    lines = _lines("Sol Ring 1", "Artifact", "{T}: Add {C}{C}.", "Illus. Mike Bierek", "0263 R", "C21 • EN")
    assert card_scan.identify(lines, NAMES) == ("Sol Ring", "C21", "263")


def test_misread_letters_and_symbols_still_match():
    assert NAMES.match("Llanowar Eives") == "Llanowar Elves"
    assert NAMES.match("Kaya, Geist Hunter 1WB") == "Kaya, Geist Hunter"
    assert NAMES.match("Thassa’s Oracle") == "Thassa's Oracle"
    assert NAMES.match("Sol Rng") == "Sol Ring"
    assert NAMES.match("Instant") is None


def test_either_face_of_a_two_faced_card_but_a_card_of_its_own_first():
    assert card_scan.identify(_lines("Delver of Secrets U", "Creature — Human Wizard"), NAMES)[0] == \
        "Delver of Secrets // Insectile Aberration"
    assert NAMES.match("Insectile Aberration") == "Delver of Secrets // Insectile Aberration"
    assert NAMES.match("Swords to Plowshare") == "Swords to Plowshares"


def test_old_cards_and_unreadable_photos():
    # Older cards print "263/281 R" and no set code line
    assert card_scan.identify(_lines("Lightning Bolt", "Instant", "Deals 3 damage.", "144/306 C"), NAMES) == \
        ("Lightning Bolt", None, "144")
    assert card_scan.identify(_lines("a blurry", "photo of", "a table"), NAMES) == (None, None, None)
    assert card_scan.identify([], NAMES) == (None, None, None)


def test_the_title_wins_over_names_in_the_rules_text():
    lines = _lines("Arcane Signet", "Artifact", "Search for a Sol Ring", "0092 C", "M3C • EN")
    assert card_scan.identify(lines, NAMES) == ("Arcane Signet", "M3C", "92")
