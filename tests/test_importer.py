import importer
from scryfall import Card


def _card(id, name, set_code, number, usd="1.00", usd_foil="3.00"):
    return Card({"id": id, "name": name, "set": set_code, "set_name": set_code.upper() + " Set",
                 "collector_number": number, "prices": {"usd": usd, "usd_foil": usd_foil}})


# Parsing

def test_parses_this_apps_own_export():
    text = ("name,set_code,set_name,collector_number,foil,quantity,price,rarity,artist,scryfall_id\n"
            "Sol Ring,C21,Commander 2021,263,1,2,1.5,uncommon,Mike Bierek,ABC-123\n")
    (row,), errors = importer.parse_csv(text)
    assert errors == []
    assert (row.name, row.set_code, row.collector_number, row.foil, row.quantity, row.scryfall_id) == \
        ("Sol Ring", "c21", "263", True, 2, "abc-123")


def test_parses_moxfield_export():
    text = ('"Count","Tradelist Count","Name","Edition","Condition","Language","Foil","Tags",'
            '"Last Modified","Collector Number","Alter","Proxy","Purchase Price"\n'
            '"4","0","Lightning Bolt","m10","Near Mint","English","foil","","2024-01-01","146","False","False",""\n')
    (row,), _ = importer.parse_csv(text)
    assert (row.quantity, row.name, row.set_code, row.collector_number, row.foil) == \
        (4, "Lightning Bolt", "m10", "146", True)


def test_parses_manabox_export():
    text = ("Name,Set code,Set name,Collector number,Foil,Rarity,Quantity,ManaBox ID,Scryfall ID,"
            "Purchase price,Misprint,Altered,Condition,Language,Purchase price currency\n"
            "Sol Ring,C21,Commander 2021,263,normal,uncommon,3,1,abc,0.5,false,false,near_mint,en,USD\n")
    (row,), _ = importer.parse_csv(text)
    assert (row.quantity, row.set_code, row.foil, row.scryfall_id) == (3, "c21", False, "abc")


def test_parses_deckbox_export_with_full_set_names():
    text = ("Count,Tradelist Count,Name,Edition,Card Number,Condition,Language,Foil,Signed\n"
            "2,0,Counterspell,Commander 2021,82,Near Mint,English,,\n")
    (row,), _ = importer.parse_csv(text)
    assert (row.quantity, row.set_code, row.set_name, row.collector_number) == \
        (2, "", "Commander 2021", "82")


def test_semicolon_csv_and_bad_rows():
    text = "Quantity;Card Name\n2;Opt\nlots;Island\n0;Skipped\n;\n"
    rows, errors = importer.parse_csv(text)
    assert [(r.quantity, r.name) for r in rows] == [(2, "Opt")]
    assert len(errors) == 1 and "Line 3" in errors[0]


def test_csv_without_name_column_is_rejected():
    rows, errors = importer.parse_csv("foo,bar\n1,2\n")
    assert rows == [] and errors


def test_parses_text_lists():
    text = """Deck
4 Lightning Bolt
1x Sol Ring (C21) 263 *F*
Counterspell [MH2]
// a comment

Sideboard:
2 Delver of Secrets
"""
    rows, errors = importer.parse_text(text)
    assert errors == []
    assert [(r.quantity, r.name, r.set_code, r.collector_number, r.foil) for r in rows] == [
        (4, "Lightning Bolt", "", "", False),
        (1, "Sol Ring", "c21", "263", True),
        (1, "Counterspell", "mh2", "", False),
        (2, "Delver of Secrets", "", "", False),
    ]


def test_csv_detection_without_extension(tmp_path):
    path = tmp_path / "list.txt"
    path.write_text("Name,Quantity\nOpt,2\n", encoding="utf-8")
    rows, _ = importer.parse_file(str(path))
    assert [(r.name, r.quantity) for r in rows] == [("Opt", 2)]


# Matching

class FakeScryfall:
    def __init__(self, cards):
        self.cards = cards
        self.calls = []

    def lookup(self, identifiers):
        self.calls.append(identifiers)
        found = []
        for ident in identifiers:
            for card in self.cards:
                if "id" in ident and card.id == ident["id"]:
                    found.append(card)
                elif "collector_number" in ident and (card.set.lower(), card.collector_number) == (ident["set"], ident["collector_number"]):
                    found.append(card)
                elif "name" in ident and card.name.lower().startswith(ident["name"].lower()) and \
                        ("set" not in ident or card.set.lower() == ident["set"]):
                    found.append(card)
                else:
                    continue
                break
        return found


def test_exact_match_by_set_and_number():
    fake = FakeScryfall([_card("1", "Sol Ring", "c21", "263")])
    rows, _ = importer.parse_text("2 Sol Ring (C21) 263")
    result = importer.resolve(rows, lookup=fake.lookup)
    assert [card.id for _, card in result.matched] == ["1"]
    assert result.approximate == [] and result.unmatched == []


def test_bad_collector_number_falls_back_and_is_flagged():
    fake = FakeScryfall([_card("1", "Sol Ring", "c21", "263")])
    rows, _ = importer.parse_text("1 Sol Ring (C21) 999")
    result = importer.resolve(rows, lookup=fake.lookup)
    assert [card.id for _, card in result.matched] == ["1"]
    assert len(result.approximate) == 1
    assert len(fake.calls) == 2


def test_name_only_rows_are_not_flagged_and_dfc_front_face_matches():
    fake = FakeScryfall([_card("d", "Delver of Secrets // Insectile Aberration", "isd", "51")])
    rows, _ = importer.parse_text("4 Delver of Secrets")
    result = importer.resolve(rows, lookup=fake.lookup)
    assert len(result.matched) == 1 and result.approximate == []


def test_unknown_card_is_unmatched():
    fake = FakeScryfall([])
    rows, _ = importer.parse_text("1 Not A Real Card (XYZ) 1")
    result = importer.resolve(rows, lookup=fake.lookup)
    assert [r.name for r in result.unmatched] == ["Not A Real Card"]
    assert len(fake.calls) == 3  # set+number, name+set, name


def test_duplicate_rows_share_one_lookup():
    fake = FakeScryfall([_card("1", "Opt", "xln", "65")])
    rows, _ = importer.parse_text("1 Opt\n2 Opt")
    result = importer.resolve(rows, lookup=fake.lookup)
    assert len(result.matched) == 2
    assert fake.calls == [[{"name": "Opt"}]]


def test_set_names_are_mapped_to_codes():
    fake = FakeScryfall([_card("c", "Counterspell", "c21", "82")])
    rows, _ = importer.parse_csv("Count,Name,Edition,Card Number\n1,Counterspell,Commander 2021,82\n")
    result = importer.resolve(rows, lookup=fake.lookup, set_codes=lambda: {"commander 2021": "c21"})
    assert len(result.matched) == 1 and result.approximate == []


def test_accents_and_curly_quotes_still_match():
    fake = FakeScryfall([_card("v", "Lim-Dûl’s Vault", "all", "90")])
    fake.lookup = lambda idents: [fake.cards[0]]
    rows, _ = importer.parse_text("1 Lim-Dul's Vault")
    assert len(importer.resolve(rows, lookup=fake.lookup).matched) == 1


def test_card_records_use_finish_price():
    fake = FakeScryfall([_card("1", "Opt", "xln", "65", usd="0.10", usd_foil="0.50")])
    rows, _ = importer.parse_text("3 Opt *F*")
    (record,) = importer.card_records(importer.resolve(rows, lookup=fake.lookup))
    assert (record["quantity"], record["foil"], record["price"], record["scryfall_id"]) == (3, True, 0.5, "1")


def test_split_cards_are_looked_up_by_front_face():
    fake = FakeScryfall([_card("f", "Fire // Ice", "mh2", "290")])
    rows, _ = importer.parse_text("1 Fire // Ice\n1 Fire/Ice")
    result = importer.resolve(rows, lookup=fake.lookup)
    assert len(result.matched) == 2
    assert fake.calls == [[{"name": "Fire"}]]


def test_set_and_number_pointing_at_another_card_falls_back_to_name():
    fake = FakeScryfall([_card("e", "Environmental Sciences", "stx", "1"),
                         _card("w", "Wear // Tear", "stx", "167")])
    rows, _ = importer.parse_text("1 Wear // Tear (STX) 1")
    result = importer.resolve(rows, lookup=fake.lookup)
    assert [card.id for _, card in result.matched] == ["w"]
    assert len(result.approximate) == 1
