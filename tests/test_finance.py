import gzip
import io
import json
from datetime import date

import database as db
import finance
import mtgjson
import scryfall


def _on_day(monkeypatch, day):
    monkeypatch.setattr(db, "_today", lambda: day)


def _card(id="opt", finishes=("nonfoil", "foil"), usd="1.00", usd_foil="3.00", usd_etched=None, digital=False):
    return {"id": id, "name": "Opt", "set": "xln", "set_name": "Ixalan", "collector_number": "65",
            "rarity": "common", "finishes": list(finishes), "digital": digital,
            "prices": {"usd": usd, "usd_foil": usd_foil, "usd_etched": usd_etched}}


def test_records_cover_each_finish_including_etched():
    records = finance.watch_records(_card(finishes=["nonfoil", "foil", "etched"], usd=None, usd_etched="9.50"))
    assert [(r["foil"], r["price"]) for r in records] == [(0, None), (1, 3.0), (2, 9.5)]
    assert [r["foil"] for r in finance.watch_records(_card(finishes=["foil"]))] == [1]


def test_watchlist_history_only_stores_changes(temp_db, monkeypatch):
    for day, price in [("2026-09-01", "1.0"), ("2026-09-02", "1.0"), ("2026-09-03", "2.0")]:
        _on_day(monkeypatch, day)
        temp_db.watch_cards(finance.watch_records(_card(finishes=["nonfoil"], usd=price)))
    assert temp_db.get_price_history("opt", 0) == [("2026-09-01", 1.0), ("2026-09-03", 2.0)]

    # Sparse history still answers "price N days ago"
    [row] = temp_db.get_watchlist(1)
    assert (row["price"], row["past"]) == (2.0, 1.0)
    assert finance.change_for(row) == (1.0, 100.0)
    assert temp_db.get_watchlist(30)[0]["past"] is None


def test_tracking_survives_refreshes(temp_db):
    temp_db.watch_cards(finance.watch_records(_card()))
    assert temp_db.get_watchlist(tracked_only=True) == []
    temp_db.track([("opt", 1)])
    temp_db.watch_cards(finance.watch_records(_card(usd_foil="4.00")))  # next day's bulk refresh
    assert [(r["foil"], r["price"]) for r in temp_db.get_watchlist(tracked_only=True)] == [(1, 4.0)]
    temp_db.untrack_all()
    assert temp_db.get_watchlist(tracked_only=True) == []


def test_backfill_keeps_existing_days(temp_db, monkeypatch):
    _on_day(monkeypatch, "2026-09-03")
    temp_db.watch_cards(finance.watch_records(_card(finishes=["nonfoil"], usd="5.00")))
    temp_db.add_price_history([("opt", 0, "2026-09-01", 4.0), ("opt", 0, "2026-09-03", 9.0)], batch=1)
    assert temp_db.get_price_history("opt", 0) == [("2026-09-01", 4.0), ("2026-09-03", 5.0)]


def test_backfill_due_weekly():
    today = date(2026, 9, 25)
    assert finance.backfill_due(None, today)
    assert not finance.backfill_due("2026-09-20", today)
    assert finance.backfill_due("2026-09-18", today)


class _Chunked(io.StringIO):
    def read(self, size=-1):
        return super().read(3)  # forces entries to straddle reads


def test_mtgjson_prices_stream_entry_by_entry():
    doc = ('{"meta": {"date": "x"}, "data": {"a": {"paper": {"tcgplayer": {"retail": {'
           '"normal": {"2026-01-02": 2.0, "2026-01-01": 1.0, "2026-01-03": 2.0}, "etched": {"2026-01-01": 7.0}},'
           ' "buylist": {"normal": {"2026-01-01": 0.5}}}, "cardkingdom": {"retail": {"foil": {"2026-01-01": 3.0}}}}},'
           ' "b": {}, "unmapped": {"paper": {"tcgplayer": {"retail": {"normal": {"2026-01-01": 1.0}}}}}}}')
    entries = mtgjson.iter_data_entries(_Chunked(doc))
    assert list(mtgjson.history_points(entries, {"a": "sf-a", "b": "sf-b"})) == [
        ("sf-a", 0, "2026-01-01", 1.0), ("sf-a", 0, "2026-01-02", 2.0), ("sf-a", 2, "2026-01-01", 7.0)]


def test_scryfall_bulk_file_is_streamed_line_by_line(monkeypatch):
    body = gzip.compress("\n".join([json.dumps({"id": "a"}), json.dumps({"id": "b"}), ""]).encode())

    class Response:
        raw = io.BytesIO(body)
        def raise_for_status(self): pass
        def __enter__(self): return self
        def __exit__(self, *exc): pass

    monkeypatch.setattr(scryfall.requests, "get", lambda *a, **kw: Response())
    seen = []
    cards = list(scryfall.iter_bulk_data({"jsonl_download_uri": "x", "compressed_size": len(body)},
                                         progress=seen.append))
    assert [c["id"] for c in cards] == ["a", "b"]
    assert seen and seen[0][1] == len(body)


def test_update_market_skips_digital_and_steps_not_due(temp_db, monkeypatch):
    info = {"updated_at": "2026-09-24T09:00:00"}
    monkeypatch.setattr(scryfall, "bulk_info", lambda: info)
    monkeypatch.setattr(scryfall, "iter_bulk_data",
                        lambda info, progress: iter([_card(), _card(id="arena", digital=True)]))
    monkeypatch.setattr(mtgjson, "price_history", lambda progress: iter([("opt", 0, "2026-08-01", 0.5)]))
    today = date.today().isoformat()
    assert finance.update_market(None, None) == {"bulk": info["updated_at"], "backfill": today}
    assert {r["scryfall_id"] for r in temp_db.get_watchlist()} == {"opt"}
    assert temp_db.get_price_history("opt", 0)[0] == ("2026-08-01", 0.5)
    assert finance.update_market(info["updated_at"], today) == {}
