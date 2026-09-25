"""
Thin adapter between the app and Magic-Projects' ScryFunctions module.

Printing lookups go through ScryFunctions (and its Card class). The few extra
endpoints this app needs that ScryFunctions doesn't cover yet -- autocomplete,
fuzzy name lookup, batch price refresh, and image downloads -- live here.

Everything in this module does blocking network I/O, so the UI calls it from
background threads (see background.py).

In offline mode (File → Work Offline) nothing here touches the internet: lookups
answer from the downloaded card list instead, and downloads raise OfflineError.
"""

# Imports
import gzip
import hashlib
import json
import sys
import time
from pathlib import Path

import requests

import database

BASE_DIR = Path(__file__).resolve().parent

# ScryFunctions does `import classes.card`, so the Magic-Projects root has to be importable
_MAGIC_PROJECTS = BASE_DIR / "external" / "Magic-Projects"
if not (_MAGIC_PROJECTS / "Functions" / "ScryFunctions.py").exists():
    raise ImportError(
        "Magic-Projects submodule is missing. Run: git submodule update --init"
    )
# Appended (not prepended) so this project's own modules always win over same-named
# ones in Magic-Projects (it has its own main.py, for example)
sys.path.append(str(_MAGIC_PROJECTS))

from Functions import ScryFunctions as sf  # noqa: E402
from classes.card import Card  # noqa: E402

# Constants
IMAGE_CACHE_DIR = BASE_DIR / "image_cache"
TIMEOUT = 15

# Scryfall asks for an accurate User-Agent identifying the app
HEADERS = {
    "User-Agent": "MultiversalManager/1.0",
    "Accept": "application/json",
}

# Scryfall asks for 50-100ms between API requests
_REQUEST_DELAY = 0.1

# /cards/collection accepts at most 75 identifiers per request
_COLLECTION_BATCH = 75


# Set from the File → Work Offline setting
offline = False


class OfflineError(Exception):
    pass


def _require_online():
    if offline:
        raise OfflineError("Offline mode is on (File → Work Offline), so nothing is downloaded.")


# Helpers

def _get_json(path, params=None):
    response = requests.get(f"{sf.BASE_URL}{path}", params=params, headers=HEADERS, timeout=TIMEOUT)
    time.sleep(_REQUEST_DELAY)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def image_url_for(card):
    # Double-faced cards have no top-level image_uris -- the images live on each face.
    # Always the full "normal" card image (never art_crop) so the artist credit and
    # copyright line stay visible.
    if card.image_normal:
        return card.image_normal
    for face in card.card_faces:
        url = face.get("image_uris", {}).get("normal")
        if url:
            return url
    return None


# Finishes, stored as the `foil` code everywhere: code -> (Scryfall's name, label)
FINISHES = {0: ("nonfoil", "Non-foil"), 1: ("foil", "Foil"), 2: ("etched", "Etched")}


def finish_label(code):
    # "" for non-foil, since that's the default, else "Foil" / "Etched"
    return FINISHES[int(code)][1] if code else ""


def finish_codes(card):
    # The finish codes a printing exists in
    return [code for code, (name, _) in FINISHES.items() if name in card.finishes]


def price_for(card, foil):
    # foil: a finish code (True/False work too, as foil/non-foil)
    return (card.price_usd, card.price_usd_foil, card.price_usd_etched)[int(foil)]


def printing_label(card):
    price = card.price_usd or card.price_usd_foil or card.price_usd_etched
    price_text = f"${price:.2f}" if price else "no price"
    return f"{card.set_name} ({card.set}) #{card.collector_number} - {price_text}"


def card_record(card, foil, quantity, price=None):
    # Keyword arguments for database.add_card, built from a Scryfall printing
    return {
        "name": card.name,
        "set_name": card.set_name,
        "price": price_for(card, foil) if price is None else price,
        "quantity": quantity,
        "scryfall_id": card.id,
        "set_code": card.set,
        "collector_number": card.collector_number,
        "foil": foil,
        "rarity": card.rarity,
        "artist": card.artist,
        "image_url": image_url_for(card),
        # Scryfall's own price, kept for price history even when `price` is overridden
        "market_price": price_for(card, foil),
    }


def scryfall_page(set_code, collector_number):
    return f"https://scryfall.com/card/{set_code.lower()}/{collector_number}"


# Offline lookups, from the downloaded card list (database.local_printings)

_PRICE_KEYS = {0: "usd", 1: "usd_foil", 2: "usd_etched"}


def _local_cards(**query):
    # Cards shaped like Scryfall's, one per printing, newest first
    cards = {}
    for row in database.local_printings(**query):
        data = cards.setdefault(row["scryfall_id"], {
            "id": row["scryfall_id"], "name": row["name"], "set": row["set_code"],
            "set_name": row["set_name"], "collector_number": row["collector_number"],
            "rarity": row["rarity"], "artist": row["artist"], "released_at": row["released_at"],
            "image_uris": {"normal": row["image_url"]}, "finishes": [], "prices": {},
        })
        data["finishes"].append(FINISHES[row["foil"]][0])
        data["prices"][_PRICE_KEYS[row["foil"]]] = row["price"]
    return [Card(data) for data in cards.values()]


# Scryfall identifier fields -> local_printings arguments
_LOCAL_FIELDS = {"id": "scryfall_id", "set": "set_code", "collector_number": "collector_number", "name": "name"}


def _local_collection(identifiers):
    # get_collection, offline: the newest matching printing for each identifier
    cards = []
    for identifier in identifiers:
        found = _local_cards(**{_LOCAL_FIELDS[key]: value for key, value in identifier.items()})
        cards.extend(found[:1])
    return cards


# API calls

def autocomplete(partial_name):
    # Up to 20 card names matching what's been typed so far
    if offline:
        return database.card_names(partial_name)
    data = _get_json("/cards/autocomplete", {"q": partial_name})
    return data["data"] if data else []


def get_printings(name):
    # Every paper printing of a card, newest first. Falls back to a fuzzy
    # lookup so "lightning bolt" or a small typo still finds the card.
    if offline:
        return _local_cards(name=name)
    printings = sf.get_all_printings(name)
    if not printings:
        match = _get_json("/cards/named", {"fuzzy": name})
        if match is None:
            return []
        printings = sf.get_all_printings(match["name"]) or [Card(match)]
    return sorted(printings, key=lambda c: c.released_at or "", reverse=True)


def get_collection(identifiers):
    # Looks up many cards at once. identifiers are dicts in any of Scryfall's forms:
    # {"id"}, {"set", "collector_number"}, {"name", "set"} or {"name"}.
    # Returns the Cards found; identifiers with no match are simply absent.
    if offline:
        return _local_collection(identifiers)
    cards = []
    for start in range(0, len(identifiers), _COLLECTION_BATCH):
        response = requests.post(
            f"{sf.BASE_URL}/cards/collection",
            json={"identifiers": identifiers[start:start + _COLLECTION_BATCH]},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        time.sleep(_REQUEST_DELAY)
        response.raise_for_status()
        cards.extend(Card(data) for data in response.json()["data"])
    return cards


def get_cards_by_id(scryfall_ids):
    # {scryfall_id: Card} for every id Scryfall still knows about
    ids = list(dict.fromkeys(scryfall_ids))
    return {card.id: card for card in get_collection([{"id": i} for i in ids])}


def fetch_prices(rows):
    # rows: list of (row_id, scryfall_id, foil). Returns ([(row_id, current price)], missing count).
    # Offline, saved prices are kept rather than restamped as fresh from old card data.
    _require_online()
    cards =get_cards_by_id([scryfall_id for _, scryfall_id, _ in rows])
    updates, missing = [], 0
    for row_id, scryfall_id, foil in rows:
        card = cards.get(scryfall_id)
        if card is None:
            missing += 1
            continue
        updates.append((row_id, price_for(card, foil)))
    return updates, missing


def fuzzy_card(name):
    # Scryfall's best guess for a misspelled or alternate card name, or None
    if offline:
        return None
    data =_get_json("/cards/named", {"fuzzy": name})
    return Card(data) if data else None


def get_set_codes():
    # {lowercased set name: set code}, for files that only give the set's full name
    if offline:
        return database.set_codes()
    data =_get_json("/sets")
    return {s["name"].lower(): s["code"] for s in data["data"]} if data else {}


def bulk_info(kind="default-cards"):
    # Metadata for one of Scryfall's daily bulk files: updated_at, jsonl_download_uri,
    # compressed_size. default-cards is every printing (English, or its only language).
    # The first step of every card data / price history update, so it guards them all.
    _require_online()
    return_get_json(f"/bulk-data/{kind}")


def iter_bulk_data(info, progress=None):
    # Streams a bulk file one raw card dict at a time -- it's gzipped JSON lines, so the
    # whole ~500 MB of card data never sits in memory. Raw dicts rather than Cards, since
    # Card has no etched price. progress((done, total)) gets compressed bytes read now and then.
    with requests.get(info["jsonl_download_uri"], headers={"User-Agent": HEADERS["User-Agent"]},
                      timeout=TIMEOUT, stream=True) as response:
        response.raise_for_status()
        with gzip.open(response.raw, "rt", encoding="utf-8") as lines:
            for count, line in enumerate(lines):
                if line.strip():
                    yield json.loads(line)
                if progress and count % 5000 == 0:
                    progress((response.raw.tell(), info["compressed_size"]))


def fetch_image(url):
    # Card image bytes, cached on disk -- Scryfall image URLs are stable per printing
    IMAGE_CACHE_DIR.mkdir(exist_ok=True)
    cache_file = IMAGE_CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".jpg")
    if cache_file.exists():
        return cache_file.read_bytes()

    _require_online()
    response = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=TIMEOUT)
    response.raise_for_status()
    cache_file.write_bytes(response.content)
    return response.content
