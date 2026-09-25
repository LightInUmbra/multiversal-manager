import sqlite3

import copy_details
import database as db
import importer


def test_conditions_and_languages_from_other_tools():
    for text, code in [("Near Mint", "NM"), ("near_mint", "NM"), ("Mint", "NM"), ("lightly played", "LP"),
                       ("EX", "LP"), ("Moderately Played", "MP"), ("HP", "HP"), ("Damaged", "DMG"),
                       ("Poor", "DMG"), ("", "NM"), ("???", "NM")]:
        assert copy_details.parse_condition(text) == code, text
    for text, code in [("English", "en"), ("JP", "ja"), ("Japanese", "ja"), ("zh-CN", "zhs"),
                       ("Chinese Traditional", "zht"), ("pt-BR", "pt"), ("", "en"), ("Klingon", "en")]:
        assert copy_details.parse_language(text) == code, text


def test_different_condition_or_language_is_a_separate_entry(temp_db):
    nm = temp_db.add_card("Opt", "XLN", 1.0, 2, scryfall_id="opt")
    assert temp_db.add_card("Opt", "XLN", 1.0, 1, scryfall_id="opt") == nm  # same copies: merged
    lp = temp_db.add_card("Opt", "XLN", 1.0, 1, scryfall_id="opt", condition="LP")
    ja = temp_db.add_card("Opt", "XLN", 1.0, 1, scryfall_id="opt", language="ja")
    assert len({nm, lp, ja}) == 3
    quantities = {row["id"]: row["quantity"] for row in temp_db.get_all_cards()}
    assert quantities == {nm: 3, lp: 1, ja: 1}


def test_notes_are_kept_when_entries_merge(temp_db):
    first = temp_db.add_card("Opt", "XLN", 1.0, 1, scryfall_id="opt", notes="signed")
    temp_db.add_card("Opt", "XLN", 1.0, 1, scryfall_id="opt", notes="signed")  # no duplicate note
    temp_db.add_card("Opt", "XLN", 1.0, 1, scryfall_id="opt", notes="red binder")
    other = temp_db.add_card("Opt", "XLN", 1.0, 1, scryfall_id="opt", condition="LP", notes="altered")
    # Editing the LP copy to NM folds it into the first entry
    assert temp_db.update_card(other, "Opt", "XLN", 1.0, 1, scryfall_id="opt", notes="altered") == first
    [row] = temp_db.get_all_cards()
    assert (row["quantity"], row["notes"]) == (4, "signed\nred binder\naltered")


def test_existing_collections_upgrade_as_near_mint_english(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE collection (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
                 "set_name TEXT NOT NULL, price REAL NOT NULL, quantity INTEGER NOT NULL)")
    conn.execute("INSERT INTO collection (name, set_name, price, quantity) VALUES ('Opt', 'XLN', 1.0, 1)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_NAME", str(path))
    db.create_table()
    [row] = db.get_all_cards()
    assert (row["condition"], row["language"], row["notes"]) == ("NM", "en", "")


def test_csv_import_reads_condition_language_and_notes():
    rows, errors = importer.parse_csv(
        "Count,Name,Edition,Condition,Language,Notes\n"
        "1,Opt,XLN,Lightly Played,Japanese,from a trade\n"
        "2,Shock,M19,,,\n")
    assert not errors
    assert [r.details() for r in rows] == [
        {"condition": "LP", "language": "ja", "notes": "from a trade"},
        {"condition": "NM", "language": "en", "notes": ""},
    ]
