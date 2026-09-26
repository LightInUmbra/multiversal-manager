import scryfall
from scryfall import Card


def _card(**overrides):
    data = {
        "id": "abc", "name": "Sol Ring", "set": "c21", "set_name": "Commander 2021",
        "collector_number": "263", "prices": {"usd": "1.50", "usd_foil": None},
        "image_uris": {"normal": "https://img/normal.jpg", "art_crop": "https://img/crop.jpg"},
    }
    data.update(overrides)
    # Scryfall omits keys rather than sending null (e.g. no top-level image_uris on DFCs)
    return Card({k: v for k, v in data.items() if v is not None})


def test_image_url_uses_full_card_not_art_crop():
    assert scryfall.image_url_for(_card()) == "https://img/normal.jpg"


def test_image_url_for_double_faced_card_uses_front_face():
    card = _card(image_uris=None, card_faces=[
        {"image_uris": {"normal": "https://img/front.jpg"}},
        {"image_uris": {"normal": "https://img/back.jpg"}},
    ])
    assert scryfall.image_url_for(card) == "https://img/front.jpg"


def test_image_url_missing():
    card = _card(image_uris={})
    assert scryfall.image_url_for(card) is None


def test_price_for_finish():
    card = _card(prices={"usd": "1.50", "usd_foil": "4.00"})
    assert scryfall.price_for(card, foil=False) == 1.5
    assert scryfall.price_for(card, foil=True) == 4.0

    etched = _card(prices={"usd": None, "usd_foil": None, "usd_etched": "9.25"}, finishes=["etched"])
    assert scryfall.price_for(etched, 2) == 9.25
    assert scryfall.finish_codes(etched) == [2]
    assert scryfall.finish_label(2) == "Etched" and scryfall.finish_label(0) == ""


def test_printing_label():
    assert scryfall.printing_label(_card()) == "Commander 2021 (C21) #263 - $1.50"
    assert scryfall.printing_label(_card(prices={})).endswith("no price")


def test_scryfall_page():
    assert scryfall.scryfall_page("C21", "263") == "https://scryfall.com/card/c21/263"


def test_offline_mode_answers_from_the_downloaded_card_list(temp_db, monkeypatch):
    import pytest

    def printing(sid, foil, name, code, set_name, released, price):
        return {"scryfall_id": sid, "foil": foil, "name": name, "set_code": code, "set_name": set_name,
                "collector_number": "1", "rarity": "rare", "image_url": f"https://img/{sid}.jpg",
                "price": price, "artist": "Artist", "released_at": released}
    temp_db.watch_cards([
        printing("old", 0, "Fire // Ice", "apc", "Apocalypse", "2001-06-04", 1.00),
        printing("new", 0, "Fire // Ice", "dmr", "Dominaria Remastered", "2023-01-13", 0.50),
        printing("new", 1, "Fire // Ice", "dmr", "Dominaria Remastered", "2023-01-13", 2.00),
    ])
    monkeypatch.setattr(scryfall, "offline", True)

    new, old = scryfall.get_printings("fire")                        # front face, newest first
    assert (new.id, new.finishes, new.price_usd_foil, new.artist) == ("new", ["nonfoil", "foil"], 2.0, "Artist")
    assert old.image_normal == "https://img/old.jpg"
    assert [c.id for c in scryfall._local_collection([{"set": "APC", "collector_number": "1"},
                                                      {"name": "Fire // Ice"}, {"name": "Nope"}])] == ["old", "new"]
    assert temp_db.set_codes()["apocalypse"] == "apc"
    with pytest.raises(scryfall.OfflineError):
        scryfall.bulk_info()                                         # guards every card data download
    with pytest.raises(scryfall.OfflineError):
        scryfall.fetch_prices([(1, "new", 0)])


def test_online_lookups_still_reach_scryfall(monkeypatch):
    calls = []
    monkeypatch.setattr(scryfall, "_get_json", lambda path, params=None: calls.append(path) or {"data": []})
    scryfall.bulk_info()
    assert scryfall.tagged_cards("ramp", "G") == []
    assert calls == ["/bulk-data/default-cards", "/cards/search"]
