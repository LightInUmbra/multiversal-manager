import importer
import import_review_dialog as review
from scryfall import Card


def _card(id, name, set_code="xln", number="1"):
    return Card({"id": id, "name": name, "set": set_code, "set_name": "Set",
                 "collector_number": number, "prices": {"usd": "1.00", "usd_foil": "2.00"}})


def _result(text, cards, fallback=False):
    rows, _ = importer.parse_text(text)
    result = importer.ImportResult()
    for row in rows:
        card = cards.get(row.name)
        if card is None:
            result.unmatched.append(row)
        else:
            result.matched.append((row, card))
            if fallback:
                result.approximate.append((row, card))
    return result


def test_name_only_rows_need_review_and_come_first():
    result = _result("1 Opt (XLN) 65\n1 Sol Ring\n1 Fake Card",
                     {"Opt": _card("o", "Opt"), "Sol Ring": _card("s", "Sol Ring")})
    entries = review.build_entries(result)
    assert [(e.row.name, e.state) for e in entries] == [
        ("Sol Ring", review.UNSPECIFIED),
        ("Fake Card", review.NOT_FOUND),
        ("Opt", review.EXACT),
    ]
    assert entries[1].include is False


def test_fallback_matches_need_review():
    result = _result("1 Opt (XLN) 999", {"Opt": _card("o", "Opt")}, fallback=True)
    (entry,) = review.build_entries(result)
    assert entry.state == review.FELL_BACK


def test_entry_record_keeps_foil_and_price_override():
    entry = review.ReviewEntry(importer.ImportRow(1, 3, "Opt"), _card("o", "Opt"),
                               review.CHOSEN, foil=True, price=None, quantity=3)
    assert entry.record()["price"] == 2.0
    entry.price = 5.0
    assert (entry.record()["price"], entry.record()["quantity"], entry.record()["foil"]) == (5.0, 3, True)


def test_the_website_parses_a_files_text():
    # The browser gives the file's contents, not a path
    rows, _ = importer.parse("Name,Quantity\nOpt,2\n", "cards.csv")
    assert [(r.name, r.quantity) for r in rows] == [("Opt", 2)]
    rows, _ = importer.parse("4 Lightning Bolt\n", "deck.txt")
    assert [(r.name, r.quantity) for r in rows] == [("Lightning Bolt", 4)]


def test_summary_counts_what_needs_review_and_what_imports():
    result = _result("2 Opt (XLN) 65\n1 Sol Ring\n1 Fake Card",
                     {"Opt": _card("o", "Opt"), "Sol Ring": _card("s", "Sol Ring")})
    entries = importer.build_entries(result)
    text, button = importer.review_summary(entries)
    assert "1 need a printing chosen" in text and "1 couldn't be found" in text and button == "Import 3 Cards"
    entries[0].include = False  # Sol Ring
    assert importer.review_summary(entries)[1] == "Import 2 Cards"


def test_choosing_a_printing():
    exact = importer.ReviewEntry(importer.ImportRow(1, 1, "Opt"), _card("o", "Opt"), importer.EXACT)
    importer.choose_printing(exact, exact.card, 0, 1.0, 1.0)
    assert exact.state == importer.EXACT and exact.price is None  # same printing, Scryfall's price
    other = _card("o2", "Opt", number="2")
    importer.choose_printing(exact, other, 1, 3.5, 2.0)
    assert (exact.state, exact.card, exact.foil, exact.price) == (importer.CHOSEN, other, 1, 3.5)
