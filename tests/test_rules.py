import rules

CR = """Magic: The Gathering Comprehensive Rules

These rules are effective as of September 25, 2026.

Contents

1. Game Concepts
100. General
7. Additional Rules
702. Keyword Abilities
Glossary
Credits

1. Game Concepts

100. General

100.1. These Magic rules apply to any Magic game with two or more players.

100.1a A two-player game is a game that begins with only two players.
Example: A game that begins with two players is still a two-player game even if one leaves. See rule 800.4a.

7. Additional Rules

702. Keyword Abilities

702.9. Flying

702.9a Flying is an evasion ability.

702.85. Cascade

702.85a Cascade is a triggered ability that functions only while the spell with cascade is on the stack.

Glossary

Absorb
A keyword ability that prevents damage. See rule 702.64, "Absorb."

Cascade
A keyword ability. See rule 702.85, "Cascade."

Credits

Lead Designer: someone
"""


def test_comprehensive_rules_parse_into_sections_rules_and_glossary():
    cr = rules.parse_cr(CR)
    assert cr.effective == "These rules are effective as of September 25, 2026."
    assert [(s.number, s.title) for s in cr.sections] == [("1", "Game Concepts"), ("7", "Additional Rules")]
    rule = cr.rule("100.1a")
    assert rule.text == "A two-player game is a game that begins with only two players."
    assert rule.examples[0].startswith("Example: A game that begins")   # examples stay with their rule
    assert [r.id for r in cr.chapter("702").rules] == ["702.9", "702.9a", "702.85", "702.85a"]
    assert cr.glossary == [("Absorb", 'A keyword ability that prevents damage. See rule 702.64, "Absorb."'),
                           ("Cascade", 'A keyword ability. See rule 702.85, "Cascade."')]
    assert cr.keywords() == {"flying": "702.9", "cascade": "702.85"}


def test_keyword_rules_for_a_card():
    keywords = {"flying": "702.9", "cascade": "702.85", "trample": "702.19", "scry": "701.22",
                "destroy": "701.8", "proliferate": "701.34"}
    text = "Flying\nCascade (When you cast this spell, exile cards… trample in reminder text doesn't count.)\n" \
           "When this enters, destroy target artifact. Scry 2, then proliferate."
    assert rules.keyword_rules(text, keywords) == [("scry", "701.22"), ("proliferate", "701.34"),
                                                   ("flying", "702.9"), ("cascade", "702.85")]


def test_tournament_documents_split_at_their_numbered_headings():
    raw = """Magic: The Gathering Tournament Rules
Contents
1. Tournament Fundamentals ..................................... 5
1.1 Tournament Types ............................................ 5
Introduction text that explains the document.
1. Tournament Fundamentals
1.1 Tournament Types
Sanctioned tournaments are rated or casual. Rated tournaments
count toward rankings.
Page 5
1.2 Publishing Tournament Information
Organizers must announce the date.
"""
    parts = rules.parse_numbered(raw)
    assert [(p.heading, p.title) for p in parts] == [
        ("", "Introduction"), ("1", "Tournament Fundamentals"), ("1.1", "Tournament Types"),
        ("1.2", "Publishing Tournament Information")]
    assert parts[2].text == "Sanctioned tournaments are rated or casual. Rated tournaments count toward rankings.\n"


def test_newest_tournament_documents_are_picked_from_the_pages():
    pages = ('<a href="https://media.wizards.com/ContentResources/WPN/MTG_MTR_2026_Feb27_EN.pdf">'
             '"\\u002FMTG_IPG_2024Sep23_EN.pdf" "MTG_IPG_2023Nov20_EN.pdf" MTG_JAR_2024Aug2_EN.pdf')
    assert rules.latest_wpn_files(pages) == {"mtr": "MTG_MTR_2026_Feb27_EN.pdf", "ipg": "MTG_IPG_2024Sep23_EN.pdf",
                                             "jar": "MTG_JAR_2024Aug2_EN.pdf"}


def test_web_pages_become_readable_text():
    page = ("<html><nav>Menu</nav><main><h2>Deck Construction</h2><p>Decks are 100 cards.</p>"
            "<ul><li>One commander</li><li>Singleton</li></ul><script>x()</script></main></html>")
    assert rules.html_to_text(page) == "Deck Construction\nDecks are 100 cards.\n• One commander\n• Singleton"


def test_card_rulings_are_found_by_card_name(temp_db):
    temp_db.replace_oracle_cards([{"name": "Imotekh the Stormlord", "oracle_id": "imo", "type_line": "Creature",
                                   "mana_cost": "", "cmc": 5, "colors": "B", "color_identity": "B",
                                   "oracle_text": "", "legalities": "{}", "scryfall_id": "x", "set_code": "40K",
                                   "set_name": "Warhammer 40,000", "collector_number": "1", "rarity": "mythic",
                                   "image_url": None, "foil": 0, "price": 1.0}])
    temp_db.replace_rulings([{"oracle_id": "imo", "source": "wotc", "published_at": "2022-10-07",
                              "comment": "Imotekh's ability triggers once however many artifacts leave."},
                             {"oracle_id": "other", "source": "wotc", "published_at": "2020-01-01", "comment": "x"}])
    [ruling] = temp_db.card_rulings("imotekh the stormlord")
    assert ruling["comment"].startswith("Imotekh's ability triggers once")
    assert temp_db.has_rulings()


def test_numbered_lists_inside_a_section_are_not_headings():
    raw = """Contents
3.1 Tiebreakers ........................ 15
3.2 Format Categories .................. 15
4. Communication ....................... 21
3.1 Tiebreakers
Players are ranked by:
1. Match points
4. Opponents' game-win percentage
3.2 Format Categories
Constructed and Limited.
4. Communication
Players must communicate clearly.
"""
    assert [p.heading for p in rules.parse_numbered(raw) if p.heading] == ["3.1", "3.2", "4"]


def test_rules_terms_two_cards_share():
    glossary = [("Artifact", "A card type. See rule 301, \"Artifacts.\""), ("Graveyard", "A zone. See rule 404."),
                ("Card", "See rule 108."), ("Token", "See rule 111.")]
    imotekh = "Whenever one or more artifact cards leave your graveyard, create two artifact creature tokens."
    lattice = "All permanents are artifacts in addition to their other types. (Reminder about graveyard.)"
    assert [(term, count) for term, _, count in rules.shared_terms([imotekh, lattice], glossary)] == [("Artifact", 2)]


def test_card_names_are_matched_as_names_not_everyday_words():
    names = ["Turn // Burn", "Turn to Frog", "Clone", "Exile", "Iron Maiden", "Iron", "Fire // Ice"]
    question = "If I turn my Clone into a frog with Turn to Frog in response, does exile matter? Fire // Ice too."
    assert rules.mentioned_cards(question, names, rules_terms=["Exile"]) == ["Turn to Frog", "Fire // Ice", "Clone"]
    assert rules.mentioned_cards("Iron Maiden and Exile", names, rules_terms=["Exile"]) == ["Iron Maiden"]


def test_find_rules_brings_keywords_and_cards_first():
    cr = rules.parse_cr(CR)
    passages = rules.find_rules("Does cascade trigger when I cast it?", cr,
                                cards=[("Bloodbraid Elf", "Cascade\nHaste", ["Cascade triggers on cast."])])
    refs = [p.ref for p in passages]
    assert refs[:4] == ["Bloodbraid Elf", "Bloodbraid Elf ruling 1", "702.85", "702.85a"]
    assert "[RULE 702.85a]" in rules.prompt_context(passages)


def test_rules_library_is_complete_and_findable():
    library = rules.load_library()
    assert len(library["concepts"]) >= 10 and len(library["interactions"]) >= 40
    for guide in library["concepts"]:
        assert guide["title"] and guide["summary"] and guide["rules"]
    for entry in library["interactions"]:
        assert entry["question"] and entry["answer"] and entry["explanation"] and entry["topic"]
        assert all(rules.RULE_ID.fullmatch(ref) for ref in entry["rules"]), entry["rules"]
        # Every verified question finds itself first
        assert rules.similar_interactions(entry["question"], library)[0][1] is entry
    [(score, best), *_] = rules.similar_interactions(
        "what happens when you attack with a creature with first strike and you have a creature in hand with "
        "ninjutsu?", library)
    assert best["answer"] == "Yes" and "510.4" in best["rules"]
    assert rules.similar_interactions("what is the best way to cook pasta", library) == []
    assert "APNAP order" in [g["title"] for g in rules.guides_for("in what order do triggers resolve in a 4 player "
                                                                  "game?", library)]
