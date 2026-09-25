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
    # Per entry: the same printing + finish in another condition or language is its own entry
    "condition": "TEXT NOT NULL DEFAULT 'NM'",
    "language": "TEXT NOT NULL DEFAULT 'en'",
    "notes": "TEXT NOT NULL DEFAULT ''",
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
        # Every paper printing and finish, for the Finance window (owned or not), with
        # `tracked` marking the ones listed there. Prices go into the same
        # price_history as the collection's; foil there is 0 non-foil, 1 foil, 2 etched.
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
                tracked INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (scryfall_id, foil)
            )
        """)
        if "tracked" not in {row["name"] for row in conn.execute("PRAGMA table_info(watchlist)")}:
            # Before the full card list, the watchlist held only what was tracked
            conn.execute("ALTER TABLE watchlist ADD COLUMN tracked INTEGER NOT NULL DEFAULT 0")
            conn.execute("UPDATE watchlist SET tracked = 1")


def merge_notes(existing, new):
    # Notes of two entries being combined, without repeating a note that's already there
    existing, new = (existing or "").strip(), (new or "").strip()
    if not new or new in existing:
        return existing
    return f"{existing}\n{new}" if existing else new


def _same_copies(conn, scryfall_id, foil, condition, language, exclude_id=None):
    # The entry already holding this printing + finish + condition + language, if any
    return conn.execute("""
        SELECT id, notes FROM collection
        WHERE scryfall_id = ? AND foil = ? AND condition = ? AND language = ? AND id IS NOT ?
    """, (scryfall_id, int(foil), condition, language, exclude_id)).fetchone()


def _add(conn, name, set_name, price, quantity, *, scryfall_id=None, set_code=None,
         collector_number=None, foil=False, rarity=None, artist=None, image_url=None,
         market_price=None, condition="NM", language="en", notes=""):
    # The same printing, finish, condition and language only gets one row -- adding it
    # again bumps the quantity (and refreshes the price) instead of creating a duplicate.
    # Returns the row id. market_price is Scryfall's price, recorded to history even if
    # `price` was overridden.
    _record_price(conn, scryfall_id, foil, market_price)
    if scryfall_id:
        existing = _same_copies(conn, scryfall_id, foil, condition, language)
        if existing:
            conn.execute(
                "UPDATE collection SET quantity = quantity + ?, price = ?, price_updated = ?, notes = ? "
                "WHERE id = ?",
                (quantity, price, _now(), merge_notes(existing["notes"], notes), existing["id"]),
            )
            return existing["id"]

    cursor = conn.execute("""
        INSERT INTO collection (name, set_name, price, quantity, scryfall_id, set_code,
                                collector_number, foil, rarity, artist, image_url, price_updated,
                                condition, language, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, set_name, price, quantity, scryfall_id, set_code, collector_number,
          int(foil), rarity, artist, image_url, _now() if scryfall_id else None,
          condition, language, (notes or "").strip()))
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
                market_price=None, condition="NM", language="en", notes=""):
    # Rewrites an entry (e.g. after changing its printing or condition). If that makes it
    # the same printing, finish, condition and language as another entry, the two are
    # merged, notes included. Returns the surviving id.
    with _connect() as conn:
        _record_price(conn, scryfall_id, foil, market_price)
        if scryfall_id:
            other = _same_copies(conn, scryfall_id, foil, condition, language, exclude_id=card_id)
            if other:
                conn.execute(
                    "UPDATE collection SET quantity = quantity + ?, price = ?, price_updated = ?, notes = ? "
                    "WHERE id = ?",
                    (quantity, price, _now(), merge_notes(other["notes"], notes), other["id"]),
                )
                conn.execute("DELETE FROM collection WHERE id = ?", (card_id,))
                return other["id"]

        conn.execute("""
            UPDATE collection SET name = ?, set_name = ?, price = ?, quantity = ?, scryfall_id = ?,
                set_code = ?, collector_number = ?, foil = ?, rarity = ?, artist = ?, image_url = ?,
                price_updated = ?, condition = ?, language = ?, notes = ?
            WHERE id = ?
        """, (name, set_name, price, quantity, scryfall_id, set_code, collector_number, int(foil),
              rarity, artist, image_url, _now() if scryfall_id else None, condition, language,
              (notes or "").strip(), card_id))
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

def watch_cards(records, track_new=False):
    """Adds printings to the watchlist or refreshes the ones already there (keeping
    whether they're tracked; new ones are tracked if track_new). records are dicts with
    scryfall_id, foil, name, set_code, set_name, collector_number, rarity, image_url and
    price (None when Scryfall has none). Returns how many were written."""
    stamp, today = _now(), _today()
    with _connect() as conn:
        for r in records:
            conn.execute("""
                INSERT INTO watchlist (scryfall_id, foil, name, set_code, set_name, collector_number,
                                       rarity, image_url, price, price_updated, tracked)
                VALUES (:scryfall_id, :foil, :name, :set_code, :set_name, :collector_number,
                        :rarity, :image_url, :price, :stamp, :tracked)
                ON CONFLICT (scryfall_id, foil) DO UPDATE SET name = excluded.name,
                    set_code = excluded.set_code, set_name = excluded.set_name,
                    collector_number = excluded.collector_number, rarity = excluded.rarity,
                    image_url = excluded.image_url, price = excluded.price,
                    price_updated = excluded.price_updated
            """, {**r, "foil": int(r["foil"]), "stamp": stamp, "tracked": int(track_new)})
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


def get_watchlist(days=None, tracked_only=False):
    # Watched printings plus each one's price `days` days ago as "past" (None if no
    # history that old), with the same lookup rules as get_past_prices
    lookup, params = _past_lookup(days)
    with _connect() as conn:
        return conn.execute(f"""
            SELECT w.*, (
                SELECT h.price FROM price_history h
                WHERE h.scryfall_id = w.scryfall_id AND h.foil = w.foil {lookup}
            ) AS past
            FROM watchlist w {"WHERE w.tracked" if tracked_only else ""}
            ORDER BY w.name COLLATE NOCASE
        """, params).fetchall()


def track(keys, tracked=True):
    # keys: iterable of (scryfall_id, foil). Untracking keeps the printing's price history.
    with _connect() as conn:
        conn.executemany("UPDATE watchlist SET tracked = ? WHERE scryfall_id = ? AND foil = ?",
                         [(int(tracked), sid, int(foil)) for sid, foil in keys])


def untrack(keys):
    track(keys, tracked=False)


def track_all(tracked=True):
    with _connect() as conn:
        conn.execute("UPDATE watchlist SET tracked = ?", (int(tracked),))


def untrack_all():
    track_all(tracked=False)


def add_price_history(points, batch=100_000):
    """Stores past prices, e.g. from MTGJSON: points is an iterable of (scryfall_id,
    foil, day, price). Days that already have a price keep it. Written in batches, so
    the collection window isn't locked out of the database for the whole import.
    Returns how many points were read."""
    count, rows = 0, []
    for point in points:
        rows.append(point)
        count += 1
        if len(rows) >= batch:
            _insert_history(rows)
            rows = []
    _insert_history(rows)
    return count


def _insert_history(rows):
    with _connect() as conn:
        conn.executemany("INSERT OR IGNORE INTO price_history (scryfall_id, foil, day, price) "
                         "VALUES (?, ?, ?, ?)", rows)


def remove_card(card_id):
    # Deletes by id specifically, not by name -- this is exactly why the
    # id column exists, so two identical-looking cards don't get confused
    with _connect() as conn:
        conn.execute("DELETE FROM collection WHERE id = ?", (card_id,))
