"""
Thin adapter between the app and Magic-Projects' ScryFunctions module.

Printing lookups go through ScryFunctions (and its Card class). The few extra
endpoints this app needs that ScryFunctions doesn't cover yet -- autocomplete,
fuzzy name lookup, batch price refresh, and image downloads -- live here.

Everything in this module does blocking network I/O, so the UI calls it from
background threads (see background.py).
"""

# Imports
import hashlib
import sys
import time
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent

# ScryFunctions does `import classes.card`, so the Magic-Projects root has to be importable
_MAGIC_PROJECTS = BASE_DIR / "external" / "Magic-Projects"
if not (_MAGIC_PROJECTS / "Functions" / "ScryFunctions.py").exists():
    raise ImportError(
        "Magic-Projects submodule is missing. Run: git submodule update --init"
    )
sys.path.insert(0, str(_MAGIC_PROJECTS))

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


def price_for(card, foil):
    return card.price_usd_foil if foil else card.price_usd


def printing_label(card):
    price = card.price_usd or card.price_usd_foil
    price_text = f"${price:.2f}" if price else "no price"
    return f"{card.set_name} ({card.set}) #{card.collector_number} - {price_text}"


def scryfall_page(set_code, collector_number):
    return f"https://scryfall.com/card/{set_code.lower()}/{collector_number}"


# API calls

def autocomplete(partial_name):
    # Up to 20 card names matching what's been typed so far
    data = _get_json("/cards/autocomplete", {"q": partial_name})
    return data["data"] if data else []


def get_printings(name):
    # Every paper printing of a card, newest first. Falls back to a fuzzy
    # lookup so "lightning bolt" or a small typo still finds the card.
    printings = sf.get_all_printings(name)
    if not printings:
        match = _get_json("/cards/named", {"fuzzy": name})
        if match is None:
            return []
        printings = sf.get_all_printings(match["name"]) or [Card(match)]
    return sorted(printings, key=lambda c: c.released_at or "", reverse=True)


def get_cards_by_id(scryfall_ids):
    # {scryfall_id: Card} for every id Scryfall still knows about
    ids = list(dict.fromkeys(scryfall_ids))
    found = {}
    for start in range(0, len(ids), _COLLECTION_BATCH):
        batch = ids[start:start + _COLLECTION_BATCH]
        response = requests.post(
            f"{sf.BASE_URL}/cards/collection",
            json={"identifiers": [{"id": i} for i in batch]},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        time.sleep(_REQUEST_DELAY)
        response.raise_for_status()
        for data in response.json()["data"]:
            found[data["id"]] = Card(data)
    return found


def fetch_image(url):
    # Card image bytes, cached on disk -- Scryfall image URLs are stable per printing
    IMAGE_CACHE_DIR.mkdir(exist_ok=True)
    cache_file = IMAGE_CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".jpg")
    if cache_file.exists():
        return cache_file.read_bytes()

    response = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=TIMEOUT)
    response.raise_for_status()
    cache_file.write_bytes(response.content)
    return response.content
