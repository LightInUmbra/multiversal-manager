"""
What's played in constructed formats, from the decklists Wizards publishes for MTGO events
(League 5-0 decks, Challenge top decks) at mtgo.com/decklists. A weekly GitHub Action
(.github/workflows/meta.yml) runs build() and publishes one small JSON per format on the
repo's meta-data branch; every app reads them from there (load()) for "decks with your cards
also play…" recommendations (recommend()).

    python meta.py build <folder> [days]

Needs only requests, so the Action doesn't install the app.
"""

# Imports
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import requests

# MTGO's event name prefix -> the app's format key (formats.FORMATS)
FORMATS = {"duel-commander": "duel", "standard": "standard", "pioneer": "pioneer", "modern": "modern",
           "legacy": "legacy", "vintage": "vintage", "pauper": "pauper", "premodern": "premodern"}
SITE = "https://www.mtgo.com"
HEADERS = {"User-Agent": "MultiversalManager/1.0 (github.com/LightInUmbra/multiversal-manager)"}
# Where the apps read the published files (raw.githubusercontent.com allows browsers to fetch)
META_URL = "https://raw.githubusercontent.com/LightInUmbra/multiversal-manager/meta-data/{format}.json"
DAYS = 30        # how far back the decklists go
PARTNERS = 40    # cards kept per card as "played with"
# Seconds between requests. mtgo.com stops answering for a while after a quick burst, and the
# weekly Action has time to spare (a month of events takes roughly 20-40 minutes)
DELAY = 1.5
TIMEOUT = 20
TRIES = 3
_EVENT = re.compile(r'href="/decklist/([a-z0-9-]+?-(\d{4}-\d{2}-\d{2})\d+)"')
_DATA = re.compile(r"window\.MTGO\.decklists\.data\s*=\s*(\{.*?\});\s*\n", re.S)


# Reading mtgo.com

def events(html):
    """[(slug, format key, date)] for every constructed event on a listing page (cubes and
    other formats left out)."""
    found = []
    for slug, day in _EVENT.findall(html):
        if "cube" in slug:
            continue
        prefix = next((p for p in FORMATS if slug.startswith(p + "-")), None)
        if prefix:
            found.append((slug, FORMATS[prefix], date.fromisoformat(day)))
    return list(dict.fromkeys(found))


def decks(html):
    """Each decklist on an event page as ({card: copies} main deck, {card: copies} sideboard)."""
    match = _DATA.search(html)
    if not match:
        return []
    out = []
    for deck in json.loads(match.group(1)).get("decklists", []):
        piles = []
        for key in ("main_deck", "sideboard_deck"):
            pile = Counter()
            for entry in deck.get(key) or []:
                pile[entry["card_attributes"]["card_name"]] += int(entry["qty"])
            piles.append(dict(pile))
        out.append(tuple(piles))
    return out


def _get(path):
    # When mtgo.com stops answering, waiting a while (longer each time) usually brings it back
    for attempt in range(1, TRIES + 1):
        try:
            response = requests.get(SITE + path, headers=HEADERS, timeout=TIMEOUT)
            time.sleep(DELAY)
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            if attempt == TRIES:
                raise
            time.sleep(30 * attempt)


def fetch(days=DAYS, today=None, progress=print):
    """{format key: [deck, ...]} for the last `days` days of MTGO events."""
    today = today or date.today()
    since = today - timedelta(days=days)
    months = sorted({(since.year, since.month), (today.year, today.month)})
    listed = []
    for year, month in months:
        listed += events(_get(f"/decklists/{year}/{month:02d}"))
    listed = [e for e in dict.fromkeys(listed) if e[2] >= since]
    found = defaultdict(list)
    for number, (slug, format_key, _) in enumerate(listed, start=1):
        if progress and number % 25 == 0:
            progress(f"{number} of {len(listed)} events")
        try:
            found[format_key] += decks(_get(f"/decklist/{slug}"))
        except requests.RequestException as error:
            if progress:
                progress(f"Skipped {slug}: {error}")
    return found


# The published summary

def summarize(format_key, format_decks, updated=None, days=DAYS):
    """The file for one format: how many decks, each card's [main decks, sideboards, copies
    per main deck], and the cards played most with it in main decks ([card, decks together])."""
    cards = defaultdict(lambda: [0, 0, 0])
    together = defaultdict(Counter)
    for main, side in format_decks:
        for name, copies in main.items():
            cards[name][0] += 1
            cards[name][2] += copies
        for name in side:
            cards[name][1] += 1
        names = sorted(main)
        for name in names:
            together[name].update(other for other in names if other != name)
    return {
        "format": format_key, "updated": (updated or date.today()).isoformat(), "days": days, "decks": len(format_decks),
        "cards": {name: [m, s, round(c / m, 2) if m else 0] for name, (m, s, c) in cards.items()},
        "with": {name: [[other, n] for other, n in partners.most_common(PARTNERS)] for name, partners in together.items()},
    }


def build(folder, days=DAYS):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for format_key, format_decks in fetch(days).items():
        if not format_decks:
            print(f"{format_key}: no decks, so no file (the apps fall back to their own picks)")
            continue
        data = summarize(format_key, format_decks, days=days)
        (folder / f"{format_key}.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        print(f"{format_key}: {data['decks']} decks, {len(data['cards'])} cards")


# Using it

_loaded = {}


def load(format_key):
    """A format's published summary, or None when there isn't one (no MTGO events, not built
    yet, offline). MM_META_DIR points at a local folder instead, for testing."""
    if format_key not in set(FORMATS.values()):
        return None
    if format_key not in _loaded:
        local = os.environ.get("MM_META_DIR")
        try:
            if local:
                path = Path(local) / f"{format_key}.json"
                _loaded[format_key] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            else:
                response = requests.get(META_URL.format(format=format_key), headers=HEADERS, timeout=TIMEOUT)
                _loaded[format_key] = response.json() if response.status_code == 200 else None
        except (requests.RequestException, ValueError, OSError):
            return None  # try again next time
    return _loaded[format_key]


def recommend(data, deck_names):
    """(played with, top cards): [(card, score, note)] best first, leaving out the deck's cards.
    Played with: how often decks with the deck's cards play each card (the chance, averaged over
    the deck's cards the meta knows). Top cards: the share of all decks playing each card."""
    cards, total = data["cards"], data["decks"] or 1
    mine = [name for name in dict.fromkeys(deck_names) if name in cards and cards[name][0]]
    have = set(deck_names)
    chance = Counter()
    for name in mine:
        for other, n in data["with"].get(name, []):
            chance[other] += n / cards[name][0]
    played_with = [(name, value / len(mine), f"In {round(100 * value / len(mine))}% of decks with your cards")
                   for name, value in chance.most_common() if name not in have]
    top = sorted(((name, m / total, f"In {round(100 * m / total)}% of {data['format'].title()} decks")
                  for name, (m, _, _) in cards.items() if m and name not in have), key=lambda t: -t[1])
    return played_with, top


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "build":
        build(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else DAYS)
    else:
        sys.exit(__doc__)
