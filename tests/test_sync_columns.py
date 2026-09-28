import sqlite3

import database as db


def _row(table, row_id):
    with db._connect() as conn:
        return conn.execute(f"SELECT uid, updated_at FROM {table} WHERE id = ?", (row_id,)).fetchone()


def _set_stamp(table, row_id, stamp):
    with db._connect() as conn:
        conn.execute(f"UPDATE {table} SET updated_at = ? WHERE id = ?", (stamp, row_id))


def test_existing_rows_get_uids_on_upgrade(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE collection (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
                 "set_name TEXT NOT NULL, price REAL NOT NULL, quantity INTEGER NOT NULL)")
    conn.executemany("INSERT INTO collection (name, set_name, price, quantity) VALUES (?, 'C21', 1, 1)",
                     [("Sol Ring",), ("Arcane Signet",)])
    conn.commit()
    conn.close()

    monkeypatch.setattr(db, "DB_NAME", str(path))
    db.create_table()
    db.create_table()

    uids = {r["uid"] for r in db.get_all_cards()}
    assert len(uids) == 2 and None not in uids
    assert all(r["updated_at"] for r in db.get_all_cards())


def test_edits_stamp_but_price_refreshes_dont(temp_db):
    card = temp_db.add_card("Sol Ring", "Commander 2021", 1.0, 1, scryfall_id="abc")
    uid, _ = _row("collection", card)
    assert len(uid) == 32

    _set_stamp("collection", card, "2000-01-01T00:00:00.000Z")
    temp_db.update_prices([(card, 2.0)])
    assert _row("collection", card)["updated_at"] == "2000-01-01T00:00:00.000Z"

    temp_db.update_quantity(card, 3)
    assert _row("collection", card)["updated_at"] > "2000"
    assert _row("collection", card)["uid"] == uid


def test_sync_can_write_its_own_stamp(temp_db):
    # Rows arriving from another device keep their uid and updated_at
    with db._connect() as conn:
        card = conn.execute("INSERT INTO collection (name, set_name, price, quantity, uid, updated_at) "
                            "VALUES ('Sol Ring', 'C21', 1, 1, 'remote', '2001-01-01T00:00:00.000Z')").lastrowid
        conn.execute("UPDATE collection SET quantity = 5, updated_at = '2002-01-01T00:00:00.000Z' WHERE id = ?",
                     (card,))
    assert tuple(_row("collection", card)) == ("remote", "2002-01-01T00:00:00.000Z")


def test_deletes_leave_tombstones(temp_db):
    deck = temp_db.create_list("Atraxa", "deck", "commander")
    temp_db.add_list_entries(deck, [{"name": "Sol Ring", "set_name": "C21", "price": 1.0, "quantity": 1}])
    deck_uid = _row("lists", deck)["uid"]

    temp_db.delete_list(deck)

    with db._connect() as conn:
        tombs = {(r["tbl"], r["uid"]) for r in conn.execute("SELECT * FROM sync_tombstones")}
    assert ("lists", deck_uid) in tombs
    assert sum(t == "list_entries" for t, _ in tombs) == 1


def test_tracking_is_stamped(temp_db):
    record = {"scryfall_id": "abc", "foil": 0, "name": "Sol Ring", "set_code": "c21", "set_name": "C21",
              "collector_number": "1", "rarity": "uncommon", "image_url": None, "price": 1.0}
    temp_db.watch_cards([record])

    def tracked_at():
        with db._connect() as conn:
            return conn.execute("SELECT tracked_at FROM watchlist").fetchone()[0]

    assert tracked_at() is None
    temp_db.watch_cards([record])  # a refresh isn't a change
    assert tracked_at() is None
    temp_db.track([("abc", 0)])
    assert tracked_at()
