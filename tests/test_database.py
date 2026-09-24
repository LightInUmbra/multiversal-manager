import sqlite3

import database as db


def test_upgrades_legacy_schema_in_place(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE collection (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, set_name TEXT NOT NULL,
            price REAL NOT NULL, quantity INTEGER NOT NULL
        )
    """)
    conn.execute("INSERT INTO collection (name, set_name, price, quantity) VALUES ('Sol Ring', 'C21', 1.5, 2)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(db, "DB_NAME", str(path))
    db.create_table()
    db.create_table()  # running twice must be harmless

    (row,) = db.get_all_cards()
    assert row["name"] == "Sol Ring"
    assert row["quantity"] == 2
    assert row["scryfall_id"] is None
    assert row["foil"] == 0


def test_same_printing_and_finish_merges_quantity(temp_db):
    first = temp_db.add_card("Sol Ring", "Commander 2021", 1.0, 1, scryfall_id="abc")
    second = temp_db.add_card("Sol Ring", "Commander 2021", 1.25, 3, scryfall_id="abc")

    assert first == second
    (row,) = temp_db.get_all_cards()
    assert row["quantity"] == 4
    assert row["price"] == 1.25


def test_foil_is_tracked_separately(temp_db):
    temp_db.add_card("Sol Ring", "Commander 2021", 1.0, 1, scryfall_id="abc", foil=False)
    temp_db.add_card("Sol Ring", "Commander 2021", 5.0, 1, scryfall_id="abc", foil=True)
    assert len(temp_db.get_all_cards()) == 2


def test_manual_rows_without_scryfall_id_never_merge(temp_db):
    temp_db.add_card("Proxy", "Custom", 0.0, 1)
    temp_db.add_card("Proxy", "Custom", 0.0, 1)
    assert len(temp_db.get_all_cards()) == 2


def test_summary_totals(temp_db):
    assert temp_db.get_summary() == (0, 0, 0)
    temp_db.add_card("A", "S", 2.50, 2, scryfall_id="a")
    temp_db.add_card("B", "S", 10.00, 1, scryfall_id="b")
    unique, count, value = temp_db.get_summary()
    assert (unique, count) == (2, 3)
    assert value == 15.0


def test_update_quantity_prices_and_remove(temp_db):
    card_id = temp_db.add_card("A", "S", 2.0, 1, scryfall_id="a")
    temp_db.update_quantity(card_id, 5)
    temp_db.update_prices([(card_id, 3.0)])
    (row,) = temp_db.get_all_cards()
    assert (row["quantity"], row["price"]) == (5, 3.0)
    assert row["price_updated"] is not None

    temp_db.remove_card(card_id)
    assert temp_db.get_all_cards() == []
