"""
A deck's numbers, Qt-free so every app shares them: which copies you own, totals, the
plain-text list, and the Stats tab's mana curve, colors and priciest cards.
lists.py (desktop), mobile/decks.py (phone) and mobile/web_decks.py (website) use it.
"""
# Imports
import re
from collections import Counter

import formats
from formats import MAIN_SECTIONS
from importer import SECTIONS

CURVE_TOP = 7  # the curve's last column is this mana value and up ("7+")
COLOR_ORDER = "WUBRGC"


def completion(entries, owned):
    """{entry id: copies you have} for a list's entries (in display order), given
    owned_by_name(). Owned copies are shared out in order, so two printings of the
    same card on one list don't both count the same copies."""
    remaining = dict(owned)
    have = {}
    for entry in entries:
        key = entry["name"].lower()
        have[entry["id"]] = min(entry["quantity"], remaining.get(key, 0))
        remaining[key] = remaining.get(key, 0) - have[entry["id"]]
    return have


def summary(entries, have):
    # (cards, value, cards you have, cards missing, cost of the missing ones)
    cards = sum(e["quantity"] for e in entries)
    value = sum(e["quantity"] * (e["price"] or 0) for e in entries)
    owned = sum(have.values())
    cost = sum((e["quantity"] - have[e["id"]]) * (e["price"] or 0) for e in entries)
    return cards, value, owned, cards - owned, cost


def deck_text(entries):
    # A plain-text deck list, grouped by section, that this app and most others can import
    blocks = []
    for section in SECTIONS:
        lines = [f"{e['quantity']} {e['name']}"
                 + (f" ({e['set_code']}) {e['collector_number']}" if e["set_code"] else "")
                 + {0: "", 1: " *F*", 2: " *E*"}[e["foil"]]
                 for e in entries if (e["section"] or "Main") == section]
        if lines:
            blocks.append("\n".join(["Deck" if section == "Main" else section] + lines))
    return "\n\n".join(blocks) + "\n"


def counted(entries):
    # The cards that make up the deck: main deck and command zone
    return [e for e in entries if e["section"] in MAIN_SECTIONS]


def _is_land(entry):
    return "Land" in (entry["type_line"] or "").split("//")[0]


def mana_curve(entries):
    """{mana value: copies} for the deck's spells (lands left out), 0 to CURVE_TOP, the
    last one counting everything at CURVE_TOP or more. Cards not looked up yet don't count."""
    curve = dict.fromkeys(range(CURVE_TOP + 1), 0)
    for e in counted(entries):
        if e["cmc"] is not None and not _is_land(e):
            curve[min(int(e["cmc"]), CURVE_TOP)] += e["quantity"]
    return curve


def average_mana_value(entries):
    # The spells' average mana value, or None with no spells
    spells = [e for e in counted(entries) if e["cmc"] is not None and not _is_land(e)]
    copies = sum(e["quantity"] for e in spells)
    return sum(e["cmc"] * e["quantity"] for e in spells) / copies if copies else None


_SYMBOL = re.compile(r"\{([^}]+)\}")


def color_symbols(entries):
    """{color: mana symbols} in the deck's mana costs, W U B R G and C (colorless), in that
    order. Hybrid and Phyrexian symbols count for each color in them; generic mana doesn't."""
    counts = Counter()
    for e in counted(entries):
        for symbol in _SYMBOL.findall(e["mana_cost"] or ""):
            for color in set(symbol.split("/")) & set(COLOR_ORDER):
                counts[color] += e["quantity"]
    return {c: counts[c] for c in COLOR_ORDER if counts[c]}


def priciest(entries, n=5):
    # The n most valuable entries by price per copy, priciest first
    return sorted((e for e in entries if e["price"]), key=lambda e: -e["price"])[:n]


def stats(entries, is_deck=True):
    """Everything the Stats tab shows, for every app to draw its own way, or None with no
    cards: curve, average (mana value, or None), colors (mana symbols), types ({type:
    copies}, most first), lands, size, priciest. A deck counts its main deck and command
    zone; a binder or wishlist every card."""
    cards = counted(entries) if is_deck else [{**dict(e), "section": "Main"} for e in entries]
    if not cards:
        return None
    types = formats.type_counts(cards)
    return {"curve": mana_curve(cards), "average": average_mana_value(cards), "colors": color_symbols(cards),
            "types": dict(sorted(types.items(), key=lambda kv: -kv[1])), "lands": types.get("Land", 0),
            "size": sum(e["quantity"] for e in cards), "priciest": priciest(entries)}
