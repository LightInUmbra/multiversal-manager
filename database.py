# Imports
import sqlite3 as sql
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# Constants
# Stored next to this file (not the current working directory) so the app finds
# the same collection no matter where it's launched from
DB_NAME = str(Path(__file__).resolve().parent / "collection.db")

# Columns added after the original (id, name, set_name, price, quantity) schema.
# create_table() adds any that are missing, so older collection.db files upgrade in place.
_EXTRA_COLUMNS = {
    "scryfall_id": "TEXT",
    "set_code": "TEXT",
    "collector_number": "TEXT",
    "foil": "INTEGER NOT NULL DEFAULT 0",
    "rarity": "TEXT",
    "artist": "TEXT",
    "image_url": "TEXT",
    "price_updated": "TEXT",
}


@contextmanager
def _connect():
    # sqlite3's own context manager commits/rolls back but never closes the
    # connection, so wrap it to do both
    conn = sql.connect(DB_NAME)
    # Rows come back as sqlite3.Row, so callers can use row["name"] instead of tuple indexes
    conn.row_factory = sql.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Functions
def create_table():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS collection (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                set_name TEXT NOT NULL,
                price REAL NOT NULL,
                quantity INTEGER NOT NULL
            )
        """)
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(collection)")}
        for column, definition in _EXTRA_COLUMNS.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE collection ADD COLUMN {column} {definition}")


def add_card(name, set_name, price, quantity, *, scryfall_id=None, set_code=None,
             collector_number=None, foil=False, rarity=None, artist=None, image_url=None):
    # The same printing + finish only gets one row -- adding it again bumps the quantity
    # (and refreshes the price) instead of creating a duplicate. Returns the row id.
    with _connect() as conn:
        if scryfall_id:
            existing = conn.execute(
                "SELECT id FROM collection WHERE scryfall_id = ? AND foil = ?",
                (scryfall_id, int(foil)),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE collection SET quantity = quantity + ?, price = ?, price_updated = ? WHERE id = ?",
                    (quantity, price, _now(), existing["id"]),
                )
                return existing["id"]

        cursor = conn.execute("""
            INSERT INTO collection (name, set_name, price, quantity, scryfall_id, set_code,
                                    collector_number, foil, rarity, artist, image_url, price_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, set_name, price, quantity, scryfall_id, set_code, collector_number,
              int(foil), rarity, artist, image_url, _now() if scryfall_id else None))
        return cursor.lastrowid


def get_all_cards():
    # Returns every row as a sqlite3.Row (index by column name)
    with _connect() as conn:
        return conn.execute("SELECT * FROM collection ORDER BY name COLLATE NOCASE").fetchall()


def get_summary():
    # (unique rows, total card count, total value)
    with _connect() as conn:
        row = conn.execute("""
            SELECT COUNT(*), COALESCE(SUM(quantity), 0), COALESCE(SUM(price * quantity), 0)
            FROM collection
        """).fetchone()
        return row[0], row[1], row[2]


def update_quantity(card_id, quantity):
    with _connect() as conn:
        conn.execute("UPDATE collection SET quantity = ? WHERE id = ?", (quantity, card_id))


def update_prices(prices):
    # prices: iterable of (card_id, new_price)
    stamp = _now()
    with _connect() as conn:
        conn.executemany(
            "UPDATE collection SET price = ?, price_updated = ? WHERE id = ?",
            [(price, stamp, card_id) for card_id, price in prices],
        )


def remove_card(card_id):
    # Deletes by id specifically, not by name -- this is exactly why the
    # id column exists, so two identical-looking cards don't get confused
    with _connect() as conn:
        conn.execute("DELETE FROM collection WHERE id = ?", (card_id,))
