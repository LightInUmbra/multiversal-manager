import gzip
import io
import json

import database as db
import finance
import scryfall
from classes.card import Card


def _on_day(monkeypatch, day):
    monkeypatch.setattr(db, "_today", lambda: day)


def _card(id="opt", finishes=("nonfoil", "foil"), usd="1.00", usd_foil="3.00", digital=False):
    return Card({"id": id, "name": "Opt", "set": "xln", "set_name": "Ixalan", "collector_number": "65",
                 "rarity": "common", "finishes": list(finishes), "digital": digital,
                 "prices": {"usd": usd, "usd_foil": usd_foil}})


def test_records_cover_each_finish_with_missing_prices_as_none():
    records = finance.watch_records(_card(usd=None))
    assert [(r["foil"], r["price"]) for r in records] == [(False, None), (True, 3.0)]
    assert [r["foil"] for r in finance.watch_records(_card(finishes=["foil"]))] == [True]
    assert [r["foil"] for r in finance.watch_records(_card(), foil=False)] == [False]


def test_watchlist_history_only_stores_changes(temp_db, monkeypatch):
    for day, price in [("2026-09-01", 1.0), ("2026-09-02", 1.0), ("2026-09-03", 2.0)]:
        _on_day(monkeypatch, day)
        temp_db.watch_cards(finance.watch_records(_card(usd=str(price)), foil=False))
    assert temp_db.get_price_history("opt", False) == [("2026-09-01", 1.0), ("2026-09-03", 2.0)]

    # Sparse history still answers "price N days ago"
    [row] = temp_db.get_watchlist(1)
    assert (row["price"], row["past"]) == (2.0, 1.0)
    assert finance.change_for(row) == (1.0, 100.0)
    assert temp_db.get_watchlist(30)[0]["past"] is None


def test_unwatch_and_clear(temp_db):
    temp_db.watch_cards(finance.watch_records(_card()))
    temp_db.unwatch([("opt", True)])
    assert [r["foil"] for r in temp_db.get_watchlist()] == [0]
    temp_db.clear_watchlist()
    assert temp_db.get_watchlist() == []


def test_bulk_file_is_streamed_line_by_line(monkeypatch):
    lines = [json.dumps({"id": "a", "name": "Opt"}), json.dumps({"id": "b", "name": "Shock"}), ""]
    body = gzip.compress("\n".join(lines).encode())

    class Response:
        raw = io.BytesIO(body)
        def raise_for_status(self): pass
        def __enter__(self): return self
        def __exit__(self, *exc): pass

    monkeypatch.setattr(scryfall.requests, "get", lambda *a, **kw: Response())
    seen = []
    cards = list(scryfall.iter_bulk_cards({"jsonl_download_uri": "x", "compressed_size": len(body)},
                                          progress=seen.append))
    assert [c.name for c in cards] == ["Opt", "Shock"]
    assert seen and seen[0][1] == len(body)


def test_track_everything_skips_digital_and_unchanged_files(temp_db, monkeypatch):
    info = {"updated_at": "2026-09-24T09:00:00"}
    monkeypatch.setattr(scryfall, "bulk_info", lambda: info)
    monkeypatch.setattr(scryfall, "iter_bulk_cards",
                        lambda info, progress: iter([_card(), _card(id="arena", digital=True)]))
    assert finance._track_everything(None) == (info["updated_at"], 2)
    assert {r["scryfall_id"] for r in temp_db.get_watchlist()} == {"opt"}
    assert finance._track_everything(info["updated_at"]) is None
