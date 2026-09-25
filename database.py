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
        # Decks, binders and wishlists: named lists of printings, owned or not.
        # section is a deck's board (Main, Sideboard, ...) and "" for other lists.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                created TEXT NOT NULL,
                format TEXT NOT NULL DEFAULT 'casual'
            )
        """)
        if "format" not in {row["name"] for row in conn.execute("PRAGMA table_info(lists)")}:
            conn.execute("ALTER TABLE lists ADD COLUMN format TEXT NOT NULL DEFAULT 'casual'")
        # One row per card (not per printing) from Scryfall's bulk data: rules, types,
        # colors and legality in every format, plus a representative printing for the
        # card list. Joined to everything else by name.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS oracle_cards (
                name TEXT PRIMARY KEY COLLATE NOCASE,
                type_line TEXT,
                mana_cost TEXT,
                cmc REAL,
                colors TEXT,
                color_identity TEXT,
                oracle_text TEXT,
                legalities TEXT,
                scryfall_id TEXT,
                set_code TEXT,
                set_name TEXT,
                collector_number TEXT,
                rarity TEXT,
                image_url TEXT,
                foil INTEGER,
                price REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS list_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                list_id INTEGER NOT NULL,
                section TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL,
                scryfall_id TEXT,
                foil INTEGER NOT NULL DEFAULT 0,
                set_code TEXT,
                set_name TEXT,
                collector_number TEXT,
                image_url TEXT,
                price REAL,
                price_updated TEXT,
                quantity INTEGER NOT NULL
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


# Lists (decks, binders, wishlists)

def create_list(name, kind, format="casual"):
    with _connect() as conn:
        return conn.execute("INSERT INTO lists (name, kind, created, format) VALUES (?, ?, ?, ?)",
                            (name, kind, _now(), format)).lastrowid


def set_list_format(list_id, format):
    with _connect() as conn:
        conn.execute("UPDATE lists SET format = ? WHERE id = ?", (format, list_id))


def rename_list(list_id, name):
    with _connect() as conn:
        conn.execute("UPDATE lists SET name = ? WHERE id = ?", (name, list_id))


def delete_list(list_id):
    with _connect() as conn:
        conn.execute("DELETE FROM list_entries WHERE list_id = ?", (list_id,))
        conn.execute("DELETE FROM lists WHERE id = ?", (list_id,))


def get_lists():
    # Every list with its card count and value, by kind then name
    with _connect() as conn:
        return conn.execute("""
            SELECT l.*, COALESCE(SUM(e.quantity), 0) AS cards,
                   COALESCE(SUM(e.quantity * e.price), 0) AS value
            FROM lists l LEFT JOIN list_entries e ON e.list_id = l.id
            GROUP BY l.id ORDER BY l.kind, l.name COLLATE NOCASE
        """).fetchall()


def add_list_entries(list_id, records, section=""):
    """Adds cards to a list. records are add_card-style dicts (name, set_name, price,
    quantity, scryfall_id, set_code, collector_number, foil, image_url; anything else
    is ignored), optionally with their own "section". The same printing + finish in the
    same section only gets one entry -- adding it again bumps the quantity."""
    stamp = _now()
    with _connect() as conn:
        for r in records:
            entry_section = r.get("section", section)
            existing = conn.execute("""
                SELECT id FROM list_entries
                WHERE list_id = ? AND section = ? AND scryfall_id IS ? AND foil = ? AND name = ?
            """, (list_id, entry_section, r.get("scryfall_id"), int(r.get("foil", False)), r["name"])).fetchone()
            if existing:
                conn.execute("UPDATE list_entries SET quantity = quantity + ? WHERE id = ?",
                             (r["quantity"], existing["id"]))
                continue
            conn.execute("""
                INSERT INTO list_entries (list_id, section, name, scryfall_id, foil, set_code, set_name,
                                          collector_number, image_url, price, price_updated, quantity)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (list_id, entry_section, r["name"], r.get("scryfall_id"), int(r.get("foil", False)),
                  r.get("set_code"), r.get("set_name"), r.get("collector_number"), r.get("image_url"),
                  r.get("price"), stamp if r.get("scryfall_id") else None, r["quantity"]))


def get_list_entries(list_id):
    # A list's entries plus each card's rules, types, colors and legality (None until
    # the card database has been downloaded)
    with _connect() as conn:
        return conn.execute("""
            SELECT e.*, o.type_line, o.mana_cost, o.cmc, o.colors, o.color_identity, o.oracle_text,
                   o.legalities
            FROM list_entries e LEFT JOIN oracle_cards o ON o.name = e.name
            WHERE e.list_id = ? ORDER BY e.name COLLATE NOCASE
        """, (list_id,)).fetchall()


def update_list_entry(entry_id, **fields):
    # fields: quantity and/or section
    with _connect() as conn:
        for column in ("quantity", "section"):
            if column in fields:
                conn.execute(f"UPDATE list_entries SET {column} = ? WHERE id = ?", (fields[column], entry_id))


def remove_list_entries(entry_ids):
    with _connect() as conn:
        conn.executemany("DELETE FROM list_entries WHERE id = ?", [(i,) for i in entry_ids])


def update_list_prices(prices):
    # prices: iterable of (entry_id, current Scryfall price)
    stamp = _now()
    with _connect() as conn:
        conn.executemany("UPDATE list_entries SET price = ?, price_updated = ? WHERE id = ?",
                         [(price, stamp, entry_id) for entry_id, price in prices])


def owned_by_name():
    # {lowercased card name: copies in the collection, any printing}
    with _connect() as conn:
        return {row[0]: row[1] for row in conn.execute(
            "SELECT LOWER(name), SUM(quantity) FROM collection GROUP BY LOWER(name)")}


# Card database (rules, types and legality of every card, from Scryfall's bulk data)

_ORACLE_COLUMNS = ["name", "type_line", "mana_cost", "cmc", "colors", "color_identity", "oracle_text",
                   "legalities", "scryfall_id", "set_code", "set_name", "collector_number", "rarity",
                   "image_url", "foil", "price"]


def replace_oracle_cards(records):
    # records: dicts with _ORACLE_COLUMNS. Replaces the whole card database in one go.
    with _connect() as conn:
        conn.execute("DELETE FROM oracle_cards")
        conn.executemany(
            f"INSERT OR REPLACE INTO oracle_cards ({', '.join(_ORACLE_COLUMNS)}) "
            f"VALUES ({', '.join(':' + c for c in _ORACLE_COLUMNS)})", records)


def has_card_database():
    with _connect() as conn:
        return conn.execute("SELECT EXISTS (SELECT 1 FROM oracle_cards)").fetchone()[0] == 1


def card_info(name):
    with _connect() as conn:
        return conn.execute("SELECT * FROM oracle_cards WHERE name = ?", (name,)).fetchone()


def printings_of(name):
    # Every printing and finish of a card, with how many of each you own (needs the card database)
    with _connect() as conn:
        return conn.execute("""
            SELECT w.scryfall_id, w.foil, w.name, w.set_code, w.set_name, w.collector_number, w.rarity,
                   w.image_url, w.price,
                   COALESCE((SELECT SUM(c.quantity) FROM collection c
                             WHERE c.scryfall_id = w.scryfall_id AND c.foil = w.foil), 0) AS owned
            FROM watchlist w WHERE w.name = ? COLLATE NOCASE
            ORDER BY w.set_name COLLATE NOCASE, w.collector_number, w.foil
        """, (name,)).fetchall()


# Card list sort orders -> ORDER BY (fixed strings, never user text)
CARD_SORTS = {
    "Name": "name COLLATE NOCASE",
    "Mana value": "cmc IS NULL, cmc, name COLLATE NOCASE",
    "Price (high to low)": "price IS NULL, price DESC, name COLLATE NOCASE",
    "Owned (most first)": "owned DESC, name COLLATE NOCASE",
}


def search_cards(owned_only, text="", card_type="", colors="", format_key=None, identity=None, limit=300,
                 sort="Name"):
    """Cards for the deck builder's card list, by name: (rows, total matches).
    owned_only lists the collection (one row per printing + finish you own); otherwise
    every card in the card database (one row per card, using a representative
    printing). Every row has an `owned` count. text matches name, type or rules text;
    colors is a string of W/U/B/R/G/C (a card matches if it has any of them, C meaning
    colorless); format_key keeps cards legal in that format; identity (a string of
    colors) keeps cards within a commander's color identity."""
    if owned_only:
        base = """
            SELECT c.name, c.scryfall_id, c.foil, c.set_code, c.set_name, c.collector_number, c.image_url,
                   MAX(c.price) AS price, SUM(c.quantity) AS owned, o.type_line, o.mana_cost, o.cmc, o.colors,
                   o.color_identity, o.oracle_text, o.legalities
            FROM collection c LEFT JOIN oracle_cards o ON o.name = c.name
            GROUP BY c.scryfall_id, c.foil, c.name
        """
    else:
        base = """
            SELECT o.name, o.scryfall_id, o.foil, o.set_code, o.set_name, o.collector_number, o.image_url,
                   o.price, COALESCE(own.copies, 0) AS owned, o.type_line, o.mana_cost, o.cmc, o.colors,
                   o.color_identity, o.oracle_text, o.legalities
            FROM oracle_cards o LEFT JOIN (
                SELECT name, SUM(quantity) AS copies FROM collection GROUP BY name COLLATE NOCASE
            ) own ON own.name = o.name
        """
    where, params = [], []
    if text.strip():
        like = f"%{text.strip()}%"
        where.append("(name LIKE ? OR type_line LIKE ? OR oracle_text LIKE ?)")
        params += [like, like, like]
    if card_type:
        where.append("type_line LIKE ?")
        params.append(f"%{card_type}%")
    if colors:
        wanted = [f"colors LIKE '%{c}%'" for c in "WUBRG" if c in colors]
        if "C" in colors:
            wanted.append("colors = ''")
        where.append(f"({' OR '.join(wanted)})")
    if format_key and format_key != "casual":
        where.append("json_extract(legalities, ?) IN ('legal', 'restricted')")
        params.append(f"$.{format_key}")
    if identity is not None:
        where += [f"color_identity NOT LIKE '%{c}%'" for c in "WUBRG" if c not in identity]
    filters = f"WHERE {' AND '.join(where)}" if where else ""
    with _connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM ({base}) {filters}", params).fetchone()[0]
        rows = conn.execute(f"SELECT * FROM ({base}) {filters} ORDER BY {CARD_SORTS[sort]} LIMIT ?",
                            params + [limit]).fetchall()
        return rows, total


def remove_card(card_id):
    # Deletes by id specifically, not by name -- this is exactly why the
    # id column exists, so two identical-looking cards don't get confused
    with _connect() as conn:
        conn.execute("DELETE FROM collection WHERE id = ?", (card_id,))
