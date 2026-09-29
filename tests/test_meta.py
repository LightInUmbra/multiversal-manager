import json
from datetime import date

import meta

LISTING = """
<a href="/decklist/modern-league-2026-09-2910983">Modern League</a>
<a href="/decklist/modern-challenge-64-2026-09-2812345678">Modern Challenge 64</a>
<a href="/decklist/duel-commander-league-2026-09-2910931">Duel Commander League</a>
<a href="/decklist/vintage-cube-league-2026-09-2910000">Vintage Cube</a>
<a href="/decklist/limited-league-2026-09-2910001">Limited</a>
<a href="/decklist/modern-league-2026-09-2910983">Modern League (again)</a>
"""


def _entry(name, qty):
    return {"qty": str(qty), "card_attributes": {"card_name": name}}


def _event_page(*deck_lists):
    data = {"decklists": [{"main_deck": [_entry(n, q) for n, q in main], "sideboard_deck": [_entry(n, q) for n, q in side]}
                          for main, side in deck_lists]}
    return f"<script>window.MTGO.decklists.data = {json.dumps(data)};\n</script>"


def test_events_keep_constructed_formats_once():
    assert meta.events(LISTING) == [
        ("modern-league-2026-09-2910983", "modern", date(2026, 9, 29)),
        ("modern-challenge-64-2026-09-2812345678", "modern", date(2026, 9, 28)),
        ("duel-commander-league-2026-09-2910931", "duel", date(2026, 9, 29)),
    ]  # no cube, no limited, no repeats


def test_decks_count_copies_per_pile():
    page = _event_page(([("Lightning Bolt", 4), ("Mountain", 18), ("Lightning Bolt", 0)], [("Smash to Smithereens", 3)]))
    assert meta.decks(page) == [({"Lightning Bolt": 4, "Mountain": 18}, {"Smash to Smithereens": 3})]
    assert meta.decks("<html>no data</html>") == []


BURN = ({"Lightning Bolt": 4, "Goblin Guide": 4, "Lava Spike": 4, "Mountain": 18}, {"Smash to Smithereens": 2})
ZOO = ({"Lightning Bolt": 4, "Wild Nacatl": 4, "Mountain": 4}, {})
TRON = ({"Karn Liberated": 4, "Urza's Tower": 4}, {"Lightning Bolt": 1})


def test_summarize_counts_decks_and_partners():
    data = meta.summarize("modern", [BURN, ZOO, TRON], updated=date(2026, 9, 29))
    assert data["decks"] == 3
    assert data["cards"]["Lightning Bolt"] == [2, 1, 4.0]  # 2 main decks, 1 sideboard, 4 copies each
    assert data["with"]["Lightning Bolt"][0] == ["Mountain", 2]


def test_recommend_played_with_and_top_cards():
    data = meta.summarize("modern", [BURN, BURN, ZOO, TRON])
    played_with, top = meta.recommend(data, ["Lightning Bolt", "Mountain"])
    names = [name for name, _, _ in played_with]
    assert names[:2] == ["Goblin Guide", "Lava Spike"]   # with Bolt in 2 of 3 decks
    assert "Karn Liberated" not in names                 # never played alongside
    assert "Lightning Bolt" not in names                 # already in the deck
    assert top[0][0] in {"Goblin Guide", "Lava Spike"} and top[0][2] == "In 50% of Modern decks"


def test_fetch_gives_up_when_events_keep_failing(monkeypatch):
    listing = "".join(f'<a href="/decklist/modern-league-2026-09-2{n}10983">x</a>' for n in range(8))
    calls = []

    def fake_get(path):
        calls.append(path)
        if path.startswith("/decklists/"):
            return listing
        raise meta.requests.ConnectionError("no answer")

    monkeypatch.setattr(meta, "_get", fake_get)
    try:
        meta.fetch(days=30, today=date(2026, 9, 30), progress=None)
    except RuntimeError as error:
        assert "stopped answering" in str(error)
    else:
        raise AssertionError("fetch kept going")
    assert len([c for c in calls if c.startswith("/decklist/")]) == meta.GIVE_UP
