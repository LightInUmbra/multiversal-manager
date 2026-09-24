import database as db


def _on_day(monkeypatch, day):
    monkeypatch.setattr(db, "_today", lambda: day)


def test_prices_are_recorded_once_per_day_per_finish(temp_db, monkeypatch):
    _on_day(monkeypatch, "2026-09-01")
    card_id = temp_db.add_card("Opt", "XLN", 0.10, 1, scryfall_id="opt", market_price=0.10)
    temp_db.update_prices([(card_id, 0.12)])  # same day: latest wins
    temp_db.add_card("Opt", "XLN", 0.50, 1, scryfall_id="opt", foil=True, market_price=0.50)
    _on_day(monkeypatch, "2026-09-02")
    temp_db.update_prices([(card_id, 0.20)])

    assert temp_db.get_price_history("opt", False) == [("2026-09-01", 0.12), ("2026-09-02", 0.20)]
    assert temp_db.get_price_history("opt", True) == [("2026-09-01", 0.50)]


def test_overridden_price_is_not_recorded_as_market_price(temp_db, monkeypatch):
    _on_day(monkeypatch, "2026-09-01")
    temp_db.add_card("Opt", "XLN", 99.0, 1, scryfall_id="opt", market_price=0.10)
    assert temp_db.get_price_history("opt", False) == [("2026-09-01", 0.10)]


def test_manual_cards_have_no_history(temp_db):
    temp_db.add_card("Proxy", "Custom", 5.0, 1, market_price=5.0)
    assert temp_db.get_past_prices(None) == {}


def test_past_prices_use_latest_point_on_or_before_cutoff(temp_db, monkeypatch):
    _on_day(monkeypatch, "2026-09-01")
    card_id = temp_db.add_card("Opt", "XLN", 1.0, 1, scryfall_id="opt", market_price=1.0)
    _on_day(monkeypatch, "2026-09-05")
    temp_db.update_prices([(card_id, 2.0)])
    _on_day(monkeypatch, "2026-09-10")
    temp_db.update_prices([(card_id, 3.0)])

    assert temp_db.get_past_prices(0) == {card_id: 3.0}
    assert temp_db.get_past_prices(4) == {card_id: 2.0}   # cutoff 09-06 -> the 09-05 price
    assert temp_db.get_past_prices(9) == {card_id: 1.0}   # cutoff 09-01
    assert temp_db.get_past_prices(30) == {}              # no history that old
    assert temp_db.get_past_prices(None) == {card_id: 1.0}


def test_history_survives_removing_and_readding(temp_db, monkeypatch):
    _on_day(monkeypatch, "2026-09-01")
    card_id = temp_db.add_card("Opt", "XLN", 1.0, 1, scryfall_id="opt", market_price=1.0)
    temp_db.remove_card(card_id)
    _on_day(monkeypatch, "2026-09-08")
    new_id = temp_db.add_card("Opt", "XLN", 1.5, 1, scryfall_id="opt", market_price=1.5)
    assert temp_db.get_past_prices(7) == {new_id: 1.0}


def test_value_snapshots(temp_db, monkeypatch):
    _on_day(monkeypatch, "2026-09-01")
    temp_db.record_value_snapshot()
    temp_db.add_card("Opt", "XLN", 2.0, 3, scryfall_id="opt")
    temp_db.record_value_snapshot()  # same day: latest wins
    _on_day(monkeypatch, "2026-09-02")
    temp_db.record_value_snapshot()
    assert temp_db.get_value_history() == [("2026-09-01", 6.0, 3), ("2026-09-02", 6.0, 3)]


def test_existing_prices_seed_history_on_upgrade(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE collection (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                    set_name TEXT NOT NULL, price REAL NOT NULL, quantity INTEGER NOT NULL,
                    scryfall_id TEXT, foil INTEGER NOT NULL DEFAULT 0, price_updated TEXT)""")
    conn.execute("INSERT INTO collection (name, set_name, price, quantity, scryfall_id, price_updated) "
                 "VALUES ('Opt', 'XLN', 0.25, 1, 'opt', '2026-08-15T12:00:00+00:00')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_NAME", str(path))
    db.create_table()
    history = db.get_price_history("opt", False)
    assert len(history) == 1 and history[0][1] == 0.25
