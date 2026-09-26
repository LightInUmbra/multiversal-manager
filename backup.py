"""
Automatic backups of the collection database: one a day when the app starts, plus
Back Up Now and Restore from the File menu. Backups live in backups/ next to
collection.db, and the newest KEEP are kept.

A backup holds everything that can't be downloaded again: the collection, its value
history, the price history of owned cards (and of cards tracked in a Start Empty
Finance list), and which printings Finance tracks. The rest of the market price
history is left out -- it's hundreds of MB, and Scryfall and MTGJSON supply it again.
"""

# Imports
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import database as db

KEEP = 10

# Market data a backup leaves out: price history is filtered to rows matching these
# (`t` is the live row), and watchlist columns the next Finance update refills are blanked
_OWNED = "EXISTS (SELECT 1 FROM live.collection c WHERE c.scryfall_id = t.scryfall_id AND c.foil = t.foil)"
_TRACKED = ("EXISTS (SELECT 1 FROM live.watchlist w "
            "WHERE w.scryfall_id = t.scryfall_id AND w.foil = t.foil AND w.tracked)")
_BLANKED = {"watchlist": {"set_name", "rarity", "image_url", "price", "price_updated"}}
# Tables backed up empty: entirely re-downloaded with the card database
_REDOWNLOADED = {"oracle_cards", "sealed_catalog", "card_rulings"}


def backup_dir():
    return Path(db.DB_NAME).parent / "backups"


def list_backups():
    # Newest first
    return sorted(backup_dir().glob("collection-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)


def make_backup(name=None, keep_tracked_history=False):
    """Writes a backup and returns its path (None if there's no database yet). name
    defaults to the current date and time. keep_tracked_history also keeps the full
    price history of every tracked printing: small for a hand-picked Finance list,
    but not when every card is tracked."""
    live = Path(db.DB_NAME)
    if not live.exists():
        return None
    folder = backup_dir()
    folder.mkdir(exist_ok=True)
    dest = folder / f"collection-{name or datetime.now().strftime('%Y-%m-%d_%H%M%S')}.db"
    tmp = dest.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)

    with closing(sqlite3.connect(tmp)) as conn:
        conn.execute("ATTACH DATABASE ? AS live", (str(live),))
        tables = conn.execute(
            "SELECT name, sql FROM live.sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        history_filter = f"WHERE {_OWNED}" + (f" OR {_TRACKED}" if keep_tracked_history else "")
        with conn:
            for table, sql in tables:
                conn.execute(sql)
                if table in _REDOWNLOADED:
                    continue
                columns =[row[1] for row in conn.execute(f"PRAGMA live.table_info({table})")]
                blanked = _BLANKED.get(table, set())
                select = ", ".join("NULL" if c in blanked else c for c in columns)
                where = history_filter if table == "price_history" else ""
                conn.execute(f"INSERT INTO main.{table} SELECT {select} FROM live.{table} t {where}")
        conn.execute("DETACH DATABASE live")
    tmp.replace(dest)  # only a finished backup ever gets the .db name
    return dest


def daily_backup(keep_tracked_history=False):
    # Today's backup, unless there already is one. Returns its path, or None if skipped.
    today = datetime.now().strftime("%Y-%m-%d")
    if any(p.name.startswith(f"collection-{today}") for p in list_backups()):
        return None
    path = make_backup(today, keep_tracked_history)
    prune()
    return path


def prune(keep=KEEP):
    for old in list_backups()[keep:]:
        old.unlink()


def restore(path):
    """Replaces the live database with a backup. Raises ValueError if the file isn't a
    Multiversal Manager backup. Afterwards, Finance should re-download market data."""
    try:
        with closing(sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)) as src:
            src.execute("SELECT id, name, quantity FROM collection LIMIT 1").fetchall()
            with closing(sqlite3.connect(db.DB_NAME)) as dest:
                src.backup(dest)
    except sqlite3.DatabaseError as error:
        raise ValueError(f"{Path(path).name} isn't a Multiversal Manager backup ({error}).") from None
    db.create_table()  # upgrades backups made by older versions
