# Imports
import sqlite3 as sql
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
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


def _today():
    # Local calendar day; history keeps one price per printing + finish per day
    return date.today().isoformat()


def _record_price(conn, scryfall_id, foil, price):
    # Scryfall's market price for a printing + finish on a given day (latest wins)
    if scryfall_id and price is not None:
        conn.execute("""
            INSERT INTO price_history (scryfall_id, foil, day, price) VALUES (?, ?, ?, ?)
            ON CONFLICT (scryfall_id, foil, day) DO UPDATE SET price = excluded.price
        """, (scryfall_id, int(foil), _today(), price))


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

        # Price history is kept per printing + finish rather than per collection row,
        # so it survives rows being edited, merged, removed and re-added
        conn.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                scryfall_id TEXT NOT NULL,
                foil INTEGER NOT NULL,
                day TEXT NOT NULL,
                price REAL NOT NULL,
                PRIMARY KEY (scryfall_id, foil, day)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS value_history (
                day TEXT PRIMARY KEY,
                value REAL NOT NULL,
                cards INTEGER NOT NULL
            )
        """)
        # Seed history from prices saved before history existed, dated when they were fetched
        conn.execute("""
            INSERT OR IGNORE INTO price_history (scryfall_id, foil, day, price)
            SELECT scryfall_id, foil, DATE(price_updated, 'localtime'), price FROM collection
            WHERE scryfall_id IS NOT NULL AND price_updated IS NOT NULL
        """)
        # Printings followed in the Finance window, whether owned or not. Their prices
        # go into the same price_history as the collection's.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                scryfall_id TEXT NOT NULL,
                foil INTEGER NOT NULL,
                name TEXT NOT NULL,
                set_code TEXT,
                set_name TEXT,
                collector_number TEXT,
                rarity TEXT,
                image_url TEXT,
                price REAL,
                price_updated TEXT,
                PRIMARY KEY (scryfall_id, foil)
            )
        """)


def _add(conn, name, set_name, price, quantity, *, scryfall_id=None, set_code=None,
         collector_number=None, foil=False, rarity=None, artist=None, image_url=None,
         market_price=None):
    # The same printing + finish only gets one row -- adding it again bumps the quantity
    # (and refreshes the price) instead of creating a duplicate. Returns the row id.
    # market_price is Scryfall's price, recorded to history even if `price` was overridden.
    _record_price(conn, scryfall_id, foil, market_price)
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


def add_card(name, set_name, price, quantity, **details):
    with _connect() as conn:
        return _add(conn, name, set_name, price, quantity, **details)


def add_cards(cards):
    # Bulk version of add_card for imports: cards is a list of add_card keyword
    # dicts, all written in one transaction. Returns the row ids.
    with _connect() as conn:
        return [_add(conn, **card) for card in cards]


def update_card(card_id, name, set_name, price, quantity, *, scryfall_id=None, set_code=None,
                collector_number=None, foil=False, rarity=None, artist=None, image_url=None,
                market_price=None):
    # Rewrites an entry (e.g. after changing its printing). If that makes it the same
    # printing + finish as another entry, the two are merged. Returns the surviving id.
    with _connect() as conn:
        _record_price(conn, scryfall_id, foil, market_price)
        if scryfall_id:
            other = conn.execute(
                "SELECT id FROM collection WHERE scryfall_id = ? AND foil = ? AND id != ?",
                (scryfall_id, int(foil), card_id),
            ).fetchone()
            if other:
                conn.execute(
                    "UPDATE collection SET quantity = quantity + ?, price = ?, price_updated = ? WHERE id = ?",
                    (quantity, price, _now(), other["id"]),
                )
                conn.execute("DELETE FROM collection WHERE id = ?", (card_id,))
                return other["id"]

        conn.execute("""
            UPDATE collection SET name = ?, set_name = ?, price = ?, quantity = ?, scryfall_id = ?,
                set_code = ?, collector_number = ?, foil = ?, rarity = ?, artist = ?, image_url = ?,
                price_updated = ?
            WHERE id = ?
        """, (name, set_name, price, quantity, scryfall_id, set_code, collector_number, int(foil),
              rarity, artist, image_url, _now() if scryfall_id else None, card_id))
        return card_id


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
    # prices: iterable of (card_id, new Scryfall price). Also recorded to price history.
    stamp = _now()
    with _connect() as conn:
        for card_id, price in prices:
            conn.execute("UPDATE collection SET price = ?, price_updated = ? WHERE id = ?",
                         (price, stamp, card_id))
            row = conn.execute("SELECT scryfall_id, foil FROM collection WHERE id = ?", (card_id,)).fetchone()
            if row:
                _record_price(conn, row["scryfall_id"], row["foil"], price)


# History

def record_value_snapshot():
    # Today's total collection value (latest wins), for the value-over-time chart
    with _connect() as conn:
        conn.execute("""
            INSERT INTO value_history (day, value, cards)
            SELECT ?, COALESCE(SUM(price * quantity), 0), COALESCE(SUM(quantity), 0) FROM collection
            WHERE true
            ON CONFLICT (day) DO UPDATE SET value = excluded.value, cards = excluded.cards
        """, (_today(),))


def get_value_history():
    # [(day, value, cards)] oldest first
    with _connect() as conn:
        return [tuple(r) for r in conn.execute("SELECT day, value, cards FROM value_history ORDER BY day")]


def get_price_history(scryfall_id, foil):
    # [(day, price)] oldest first
    with _connect() as conn:
        return [tuple(r) for r in conn.execute(
            "SELECT day, price FROM price_history WHERE scryfall_id = ? AND foil = ? ORDER BY day",
            (scryfall_id, int(foil)),
        )]


def _past_lookup(days):
    # SQL tail (and params) picking a price_history row `h` as of `days` days ago
    if days is None:
        return "ORDER BY h.day ASC LIMIT 1", ()
    cutoff = date.fromisoformat(_today()) - timedelta(days=days)
    return "AND h.day <= ? ORDER BY h.day DESC LIMIT 1", (cutoff.isoformat(),)


def get_past_prices(days=None):
    """{card_id: price} -- each Scryfall-linked entry's price `days` days ago (the
    latest recorded on or before that day), or its earliest recorded price when
    days is None. Entries with no history that old are left out."""
    lookup, params = _past_lookup(days)
    with _connect() as conn:
        rows = conn.execute(f"""
            SELECT c.id, (
                SELECT h.price FROM price_history h
                WHERE h.scryfall_id = c.scryfall_id AND h.foil = c.foil {lookup}
            ) AS past
            FROM collection c WHERE c.scryfall_id IS NOT NULL
        """, params).fetchall()
        return {row["id"]: row["past"] for row in rows if row["past"] is not None}


# Watchlist (Finance window)

def watch_cards(records):
    """Adds printings to the watchlist or refreshes the ones already there. records are
    dicts with scryfall_id, foil, name, set_code, set_name, collector_number, rarity,
    image_url and price (None when Scryfall has none). Returns how many were written."""
    stamp, today = _now(), _today()
    with _connect() as conn:
        for r in records:
            conn.execute("""
                INSERT INTO watchlist (scryfall_id, foil, name, set_code, set_name, collector_number,
                                       rarity, image_url, price, price_updated)
                VALUES (:scryfall_id, :foil, :name, :set_code, :set_name, :collector_number,
                        :rarity, :image_url, :price, :stamp)
                ON CONFLICT (scryfall_id, foil) DO UPDATE SET name = excluded.name,
                    set_code = excluded.set_code, set_name = excluded.set_name,
                    collector_number = excluded.collector_number, rarity = excluded.rarity,
                    image_url = excluded.image_url, price = excluded.price,
                    price_updated = excluded.price_updated
            """, {**r, "foil": int(r["foil"]), "stamp": stamp})
            # Only store a point when the price moved: tracking every card means ~150k
            # printings a day, and "latest on or before a day" lookups work on sparse history
            if r["price"]:
                conn.execute("""
                    INSERT INTO price_history (scryfall_id, foil, day, price)
                    SELECT ?, ?, ?, ? WHERE ? IS NOT (
                        SELECT price FROM price_history WHERE scryfall_id = ? AND foil = ?
                        ORDER BY day DESC LIMIT 1)
                    ON CONFLICT (scryfall_id, foil, day) DO UPDATE SET price = excluded.price
                """, (r["scryfall_id"], int(r["foil"]), today, r["price"], r["price"],
                      r["scryfall_id"], int(r["foil"])))
        return len(records)


def get_watchlist(days=None):
    # Every watched printing plus its price `days` days ago as "past" (None if no history
    # that old), with the same lookup rules as get_past_prices
    lookup, params = _past_lookup(days)
    with _connect() as conn:
        return conn.execute(f"""
            SELECT w.*, (
                SELECT h.price FROM price_history h
                WHERE h.scryfall_id = w.scryfall_id AND h.foil = w.foil {lookup}
            ) AS past
            FROM watchlist w ORDER BY w.name COLLATE NOCASE
        """, params).fetchall()


def unwatch(keys):
    # keys: iterable of (scryfall_id, foil)
    with _connect() as conn:
        conn.executemany("DELETE FROM watchlist WHERE scryfall_id = ? AND foil = ?",
                         [(sid, int(foil)) for sid, foil in keys])


def clear_watchlist():
    with _connect() as conn:
        conn.execute("DELETE FROM watchlist")


def remove_card(card_id):
    # Deletes by id specifically, not by name -- this is exactly why the
    # id column exists, so two identical-looking cards don't get confused
    with _connect() as conn:
        conn.execute("DELETE FROM collection WHERE id = ?", (card_id,))
