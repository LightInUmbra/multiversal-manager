import os
import sqlite3
from datetime import datetime

import pytest

import backup


def _fill(db):
    owned = db.add_card("Opt", "XLN", 1.0, 2, scryfall_id="opt", market_price=1.0, notes="signed")
    db.watch_cards([{"scryfall_id": sid, "foil": 0, "name": sid, "set_code": "XLN", "set_name": "Ixalan",
                     "collector_number": "1", "rarity": "common", "image_url": "u", "price": 2.0}
                    for sid in ("opt", "tracked", "market")])
    db.track([("tracked", 0)])
    return owned


def test_backup_keeps_your_data_and_drops_downloadable_market_history(temp_db):
    _fill(temp_db)
    path = backup.make_backup("test")
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT notes, quantity FROM collection").fetchall() == [("signed", 2)]
        assert {r[0] for r in conn.execute("SELECT scryfall_id FROM price_history")} == {"opt"}
        # Every watchlist row survives with its tracked flag; refillable columns are blanked
        rows = conn.execute("SELECT scryfall_id, tracked, image_url, price FROM watchlist ORDER BY 1").fetchall()
        assert rows == [("market", 0, None, None), ("opt", 0, None, None), ("tracked", 1, None, None)]

    with_tracked = backup.make_backup("test2", keep_tracked_history=True)
    with sqlite3.connect(with_tracked) as conn:
        assert {r[0] for r in conn.execute("SELECT scryfall_id FROM price_history")} == {"opt", "tracked"}


def test_restore_round_trip_and_rejects_other_files(temp_db, tmp_path):
    owned = _fill(temp_db)
    path = backup.make_backup("before")
    temp_db.remove_card(owned)
    assert temp_db.get_all_cards() == []

    backup.restore(path)
    [row] = temp_db.get_all_cards()
    assert (row["id"], row["notes"]) == (owned, "signed")
    assert temp_db.add_card("Shock", "M19", 0.5, 1) == owned + 1  # ids keep counting up

    junk = tmp_path / "junk.db"
    junk.write_text("not a database")
    with pytest.raises(ValueError):
        backup.restore(junk)
    assert len(temp_db.get_all_cards()) == 2  # untouched


def test_daily_backup_once_a_day_and_pruned(temp_db):
    _fill(temp_db)
    folder = backup.backup_dir()
    folder.mkdir()
    for i in range(12):  # older backups, oldest first
        old = folder / f"collection-2026-01-{i + 1:02d}.db"
        old.write_bytes(b"")
        os.utime(old, (1_700_000_000 + i, 1_700_000_000 + i))

    assert backup.daily_backup() is not None
    assert backup.daily_backup() is None  # already backed up today
    names = [p.name for p in backup.list_backups()]
    assert len(names) == backup.KEEP
    assert names[0].startswith(f"collection-{datetime.now():%Y-%m-%d}")
    assert "collection-2026-01-01.db" not in names  # oldest pruned first


def test_no_database_no_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(backup.db, "DB_NAME", str(tmp_path / "missing.db"))
    assert backup.make_backup() is None
