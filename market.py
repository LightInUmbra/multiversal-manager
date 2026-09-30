"""
The market summary behind the website's Finance page. The desktop's Finance window keeps
every printing's prices in its own database, from Scryfall's bulk data (~500 MB) and
MTGJSON's 90 days of history (~1 GB unpacked), far too much for a browser on every visit.
So .github/workflows/market.yml builds this once a day, on GitHub's side: every paper
printing's price today and at a few days over the last 90, a few MB, published on the
market-data branch. The website downloads it once per visit.

    python market.py market.json.gz      (build it; the workflow does this)
"""

# Imports
import gzip
import itertools
import json
import os
import sys
from datetime import date, timedelta

import requests

import scryfall

# MM_MARKET_URL points the website at another copy, e.g. one built locally, for testing
URL = os.environ.get("MM_MARKET_URL",
                     "https://raw.githubusercontent.com/LightInUmbra/multiversal-manager/market-data/market.json.gz")
# Days before the build whose prices are kept: enough for each period's change and a small chart
OFFSETS = [90, 75, 60, 45, 30, 21, 14, 7, 3, 1]
# The Finance window's periods (trends.PERIODS), up to the 90 days MTGJSON keeps
PERIODS = [("24 hours", 1), ("7 days", 7), ("30 days", 30), ("90 days", 90)]
DEFAULT_PERIOD = "7 days"


def watch_records(data):
    # Watchlist records for a raw Scryfall card dict, one per finish it's printed in
    prices = data.get("prices") or {}
    card = scryfall.Card(data)
    return [{
        "scryfall_id": card.id,
        "foil": code,
        "name": card.name,
        "set_code": card.set,
        "set_name": card.set_name,
        "collector_number": card.collector_number,
        "rarity": card.rarity,
        "image_url": scryfall.image_url_for(card),
        "price": float(prices[key]) if prices.get(key) else None,
        "artist": card.artist,
        "released_at": card.released_at,
    } for finish, (code, key) in scryfall.PRICE_KEYS.items() if finish in card.finishes]


def change_for(row):
    # (each, percent) since the period's start, or None without a price then and now
    if not row["past"] or not row["price"]:
        return None
    each = row["price"] - row["past"]
    return each, each / row["past"] * 100


# The Finance table, on the desktop (finance.py) and the website: what's listed and in what order

COLUMNS = ["Card", "Set", "#", "Finish", "Rarity", "Price", "Change", "Change %"]
(NAME_COL, SET_COL, NUMBER_COL, FINISH_COL, RARITY_COL, PRICE_COL, CHANGE_COL,
 PERCENT_COL) = range(len(COLUMNS))
SHOW_SPIKES, SHOW_DROPS, SHOW_ALL = "Biggest spikes", "Biggest drops", "Everything"
FINISH_LABELS = {0: "", 1: "Foil", 2: "Etched"}


def accepts(entry, text, min_price, show):
    # Whether a (row, change_for(row)) entry is listed; text is lowercased
    row, change = entry
    if (row["price"] or 0.0) < min_price:
        return False
    if show == SHOW_SPIKES and (change is None or change[0] <= 0.004):
        return False
    if show == SHOW_DROPS and (change is None or change[0] >= -0.004):
        return False
    return not text or text in f"{row['name']} {row['set_name']} {row['set_code']}".lower()


def sort_key(entry, column):
    row, change = entry
    if column >= CHANGE_COL:
        return change[column - CHANGE_COL] if change else 0.0
    if column == PRICE_COL:
        return row["price"] or 0.0
    if column == NUMBER_COL:
        number = row["collector_number"] or ""
        return (int(number) if number.isdigit() else 0, number)
    if column == FINISH_COL:
        return row["foil"]
    return (row[["name", "set_name", "", "", "rarity"][column]] or "").casefold()


def shown(entries, text, min_price, show, column, descending):
    # The entries listed, sorted: plain sorted() with a key, fast even for every printing
    return sorted((e for e in entries if accepts(e, text, min_price, show)),
                  key=lambda e: sort_key(e, column), reverse=descending)


# Building (the daily workflow)

def sampled(points, days):
    """The price on each of days (ISO dates, oldest first) from one printing's sparse history
    [(day, price)], sorted: the latest price recorded on or before it, or None before any"""
    values, index, price = [], 0, None
    for day in days:
        while index < len(points) and points[index][0] <= day:
            price = points[index][1]
            index += 1
        values.append(price)
    return values


def build(today=None, printings=None, history=None):
    """The summary as a dict. printings: raw Scryfall card dicts (default: today's bulk file);
    history: (scryfall_id, foil, day, price) grouped by printing and finish, days in order
    (default: MTGJSON's 90 days)"""
    today = today or date.today()
    days = [(today - timedelta(days=n)).isoformat() for n in OFFSETS]
    if printings is None:
        printings = scryfall.iter_bulk_data(scryfall.bulk_info())
    if history is None:
        import mtgjson  # needs lzma, which the website's Python lacks; only building uses it
        history = mtgjson.price_history()
    names, sets, rows = {}, {}, {}
    for data in printings:
        if data.get("digital"):
            continue
        for record in watch_records(data):
            if record["price"] is None:
                continue
            sets[record["set_code"]] = record["set_name"]
            name = names.setdefault(record["name"], len(names))
            rows[(record["scryfall_id"], record["foil"])] = [
                record["scryfall_id"], name, record["set_code"], record["collector_number"],
                (record["rarity"] or "")[:1], record["foil"], round(record["price"] * 100), [0] * len(OFFSETS)]
    for (scryfall_id, foil), points in itertools.groupby(history, key=lambda p: (p[0], p[1])):
        row = rows.get((scryfall_id, foil))
        if row is not None:
            row[7] = [round(p * 100) if p else 0 for p in sampled([(day, price) for _, _, day, price in points], days)]
    return {"built": today.isoformat(), "offsets": OFFSETS, "sets": sets, "names": list(names),
            "cards": list(rows.values())}


def write(summary, path):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(summary, f, separators=(",", ":"))


# Reading (the website)

RARITIES = {"c": "Common", "u": "Uncommon", "r": "Rare", "m": "Mythic", "s": "Special", "b": "Bonus"}


def download(url=URL):
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    return json.loads(gzip.decompress(response.content))


def rows(summary, days):
    """The Finance window's rows (as db.get_watchlist gives them) for a period of days: each
    printing's price today and its price that many days ago as "past". "index" is for history()."""
    column = summary["offsets"].index(days)
    names, sets = summary["names"], summary["sets"]
    return [{"index": index, "scryfall_id": card_id, "name": names[name], "set_code": set_code,
             "set_name": sets.get(set_code, ""), "collector_number": number, "rarity": RARITIES.get(rarity, ""),
             "foil": foil, "price": price / 100, "past": past[column] / 100 or None}
            for index, (card_id, name, set_code, number, rarity, foil, price, past) in enumerate(summary["cards"])]


def history(summary, index):
    # [(day, price)] for a row's printing (rows()' "index"): its kept days, then today
    built = date.fromisoformat(summary["built"])
    *_, price, past = summary["cards"][index]
    return ([((built - timedelta(days=n)).isoformat(), p / 100) for n, p in zip(summary["offsets"], past) if p]
            + [(summary["built"], price / 100)])


def image_url(scryfall_id):
    # Scryfall's image of a printing, from its id alone (the summary leaves the URLs out)
    return f"https://cards.scryfall.io/normal/front/{scryfall_id[0]}/{scryfall_id[1]}/{scryfall_id}.jpg"


if __name__ == "__main__":
    summary = build()
    write(summary, sys.argv[1] if len(sys.argv) > 1 else "market.json.gz")
    print(f"{len(summary['cards']):,} printings, {len(summary['names']):,} cards, {len(summary['sets']):,} sets")
