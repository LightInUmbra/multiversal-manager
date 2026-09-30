from datetime import date

import market


def _printing(id, name="Opt", finishes=("nonfoil", "foil"), usd="2.00", usd_foil="5.00", digital=False):
    return {"id": id, "name": name, "set": "xln", "set_name": "Ixalan", "collector_number": "65", "rarity": "common",
            "finishes": list(finishes), "digital": digital, "prices": {"usd": usd, "usd_foil": usd_foil}}


def test_sampled_takes_the_latest_price_on_or_before_each_day():
    points = [("2026-09-01", 1.0), ("2026-09-10", 2.0)]
    assert market.sampled(points, ["2026-08-31", "2026-09-01", "2026-09-05", "2026-09-30"]) == [None, 1.0, 1.0, 2.0]


def test_build_and_read_back():
    today = date(2026, 9, 30)
    history = [("a", 0, "2026-08-31", 1.0), ("a", 0, "2026-09-23", 1.5),   # nonfoil: 30 and 7 days back
               ("a", 1, "2026-09-29", 4.0),                                 # foil: only yesterday
               ("gone", 0, "2026-09-29", 9.0)]                              # a printing Scryfall no longer has
    summary = market.build(today, [_printing("a"), _printing("b", usd=None, usd_foil=None),
                                   _printing("d", digital=True)], history)
    assert [(c[0], c[5]) for c in summary["cards"]] == [("a", 0), ("a", 1)]  # no price, digital: left out
    week = {row["foil"]: row for row in market.rows(summary, 7)}
    assert (week[0]["price"], week[0]["past"], week[0]["rarity"], week[0]["set_name"]) == (2.0, 1.5, "Common", "Ixalan")
    assert week[1]["past"] is None  # no foil price a week ago
    assert market.rows(summary, 30)[0]["past"] == 1.0
    assert market.rows(summary, 1)[1]["past"] == 4.0
    assert market.history(summary, week[0]["index"])[-3:] == [("2026-09-27", 1.5), ("2026-09-29", 1.5),
                                                              ("2026-09-30", 2.0)]


def test_period_changes_and_the_phones_cached_copy(tmp_path, monkeypatch):
    summary = market.build(date(2026, 9, 30), [_printing("a", finishes=("nonfoil",))],
                           [("a", 0, "2026-08-31", 1.0), ("a", 0, "2026-09-23", 1.5)])
    changes = {label: (then, change) for label, then, change in market.period_changes(summary, 0)}
    assert changes["7 days"] == (1.5, (0.5, 0.5 / 1.5 * 100))
    assert changes["90 days"] == (None, None)  # no price that far back

    cache = tmp_path / "market.json.gz"
    market.write(summary, cache)
    monkeypatch.setattr(market.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("downloaded")))
    assert market.download(cache=cache)["built"] == "2026-09-30"  # fresh enough: no download


def test_shown_filters_and_sorts_like_the_desktop():
    def entry(name, price, past):
        row = {"name": name, "set_name": "Set", "set_code": "set", "price": price, "past": past,
               "collector_number": "1", "foil": 0, "rarity": "Rare"}
        return row, market.change_for(row)

    entries = [entry("Up", 4.0, 2.0), entry("Down", 1.0, 2.0), entry("Penny", 0.1, 0.05), entry("New", 3.0, None)]

    def names(shown):
        return [row["name"] for row, _ in shown]

    assert names(market.shown(entries, "", 0.5, market.SHOW_SPIKES, market.PERCENT_COL, True)) == ["Up"]
    assert names(market.shown(entries, "", 0.0, market.SHOW_DROPS, market.PERCENT_COL, False)) == ["Down"]
    assert names(market.shown(entries, "", 0.0, market.SHOW_ALL, market.PRICE_COL, True)) == ["Up", "New", "Down",
                                                                                              "Penny"]
    assert names(market.shown(entries, "pen", 0.0, market.SHOW_ALL, market.NAME_COL, False)) == ["Penny"]
