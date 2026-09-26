"""
Price history backfill from MTGJSON (mtgjson.com), which keeps the last 90 days of
TCGplayer prices for every printing. Scryfall only has today's price, so this is
what gives the Finance window history from the first day. Also the decklists of
Commander precons, for the deck builder's recommendations.

Blocking network I/O -- call from a background thread.
"""

# Imports
import csv
import gzip
import json
import lzma
import re

import requests

import scryfall
from scryfall import HEADERS, TIMEOUT

BASE_URL = "https://mtgjson.com/api/v5"
PRICES_URL = f"{BASE_URL}/AllPrices.json.xz"                # ~47 MB, 90 days from every store
IDENTIFIERS_URL = f"{BASE_URL}/csv/cardIdentifiers.csv.gz"  # ~16 MB, MTGJSON uuid -> Scryfall id

# MTGJSON finish -> the foil code stored with prices (0 non-foil, 1 foil, 2 etched)
FINISHES = {"normal": 0, "foil": 1, "etched": 2}

_CHUNK = 1 << 20
_KEY = re.compile(r'\s*,?\s*"([^"]*)"\s*:\s*')
_END = re.compile(r"\s*}")


def _stream(url):
    response = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=TIMEOUT, stream=True)
    response.raise_for_status()
    return response


def _get(path):
    response = requests.get(f"{BASE_URL}/{path}", headers={"User-Agent": HEADERS["User-Agent"]}, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()["data"]


# MTGJSON sealed categories -> (readable name, group for filtering)
SEALED_CATEGORIES = {
    "booster_box": ("Booster Box", "Booster Boxes"), "booster_pack": ("Booster Pack", "Booster Packs"),
    "bundle": ("Bundle", "Bundles"), "deck": ("Deck", "Decks"), "deck_box": ("Deck Box", "Decks"),
    "multiple_decks": ("Decks", "Decks"), "box_set": ("Box Set", "Box Sets & Secret Lairs"),
    "limited_aid_tool": ("Kit", "Kits"), "kit": ("Kit", "Kits"), "booster_case": ("Booster Case", "Cases"),
    "bundle_case": ("Bundle Case", "Cases"), "limited_aid_case": ("Kit Case", "Cases"), "case": ("Case", "Cases"),
}
_SUBTYPE_NAMES = {"mtgo_redemption": "MTGO Redemption", "fat_pack": "Fat Pack", "six_card": "Six-Card"}


def product_type(category, subtype):
    """A readable product type from MTGJSON's category and subtype, as a store would
    list it: ("booster_box", "collector") -> "Collector Booster Box",
    ("limited_aid_tool", "prerelease_kit") -> "Prerelease Kit",
    ("bundle_case", "gift_bundle") -> "Gift Bundle Case"."""
    base = SEALED_CATEGORIES.get(category, ("Other", ""))[0]
    if subtype in (None, "", "default", "unknown", "other"):
        return base
    extra = _SUBTYPE_NAMES.get(subtype, subtype.replace("_", " ").title())
    if base == "Other":
        return extra
    first = base.split()[0]  # "Gift Bundle" + "Bundle Case" share "Bundle"
    return extra + base[len(first):] if extra.endswith(first) else f"{extra} {base}"


def sealed_group(category):
    return SEALED_CATEGORIES.get(category, ("", "Other"))[1]


def sealed_catalog():
    # Every sealed product MTGJSON lists, as rows for db.replace_sealed_catalog
    scryfall._require_online()
    return [{"uuid": product["uuid"], "name": product["name"], "set_code": s["code"], "set_name": s["name"],
             "product_type": product_type(product.get("category"), product.get("subtype")),
             "category": sealed_group(product.get("category")), "released": s.get("releaseDate")}
            for s in _get("SetList.json") for product in s.get("sealedProduct") or []]


def precon_cards(name, set_codes):
    """(deck names, card names) of the Commander precons with the card `name` in them,
    looked for among the precons of the sets it was printed in (set_codes)."""
    scryfall._require_online()
    codes = {code.upper() for code in set_codes}
    decks, cards = set(), set()
    for deck in _get("DeckList.json"):
        if deck["type"] != "Commander Deck" or deck["code"].upper() not in codes:
            continue
        data = _get(f"decks/{deck['fileName']}.json")
        names = {card["name"] for board in ("commander", "mainBoard") for card in data.get(board) or []}
        if name in names:
            decks.add(deck["name"])
            cards |= names
    return decks, cards


def _scryfall_ids():
    # {MTGJSON uuid: Scryfall id}
    with _stream(IDENTIFIERS_URL) as response:
        with gzip.open(response.raw, "rt", encoding="utf-8", newline="") as f:
            return {row["uuid"]: row["scryfallId"] for row in csv.DictReader(f) if row["scryfallId"]}


def iter_data_entries(text):
    """Yields (key, value) for each entry of the top-level "data" object of a JSON
    document read from the file-like `text`, one entry at a time. AllPrices is over
    a gigabyte of JSON, far too much to json.load at once."""
    decoder = json.JSONDecoder()
    buffer, pos = "", 0

    def more():
        nonlocal buffer, pos
        chunk = text.read(_CHUNK)
        if not chunk:
            raise ValueError("MTGJSON price file ended early")
        buffer, pos = buffer[pos:] + chunk, 0

    while buffer.find('"data":') < 0:
        more()
    pos = buffer.index("{", buffer.find('"data":')) + 1  # ponytail: assumes "meta" has no "data" key
    while True:
        key = _KEY.match(buffer, pos)
        if key is None:
            if _END.match(buffer, pos):
                return
            more()
            continue
        try:
            value, end = decoder.raw_decode(buffer, key.end())
        except json.JSONDecodeError:  # the entry continues in the next chunk
            more()
            continue
        yield key.group(1), value
        pos = end


def history_points(entries, scryfall_ids):
    # (scryfall_id, foil code, day, price) from AllPrices entries: TCGplayer retail in USD,
    # the same source as Scryfall's prices. Unchanged days are dropped -- history is sparse.
    for uuid, prices in entries:
        scryfall_id = scryfall_ids.get(uuid)
        if not scryfall_id:
            continue
        retail = ((prices.get("paper") or {}).get("tcgplayer") or {}).get("retail") or {}
        for finish, days in retail.items():
            if finish not in FINISHES:
                continue
            previous = None
            for day, price in sorted(days.items()):
                if price and price != previous:
                    yield scryfall_id, FINISHES[finish], day, round(price, 2)
                previous = price


def price_history(progress=None):
    # Every printing's last 90 days of prices, as history_points tuples.
    # progress((done, total)) gets compressed bytes read every so often.
    scryfall_ids = _scryfall_ids()
    with _stream(PRICES_URL) as response:
        total = int(response.headers.get("Content-Length") or 0)
        with lzma.open(response.raw, "rt", encoding="utf-8") as text:
            for count, point in enumerate(history_points(iter_data_entries(text), scryfall_ids)):
                if progress and count % 50000 == 0:
                    progress((response.raw.tell(), total))
                yield point
