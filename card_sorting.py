"""
Sorting and grouping cards the same way in the desktop app, the website and the phone: the
collection, decks, binders and wishlists, and sealed product. Qt-free.

A view is a dict {"sort": ..., "descending": bool, "group": ...}. Each list remembers its own
on the device (load/save). Rows are sqlite3.Rows or dicts. Mana value, Color and Type need the
card's rules (type_line, cmc, colors): deck entries come with them, the collection gets them
from with_rules(), and fetch_rules() looks up the ones the card database lacks.
"""

# Imports
import json

import copy_details
import database as db
import formats
import price_changes
import scryfall
from importer import SECTIONS

KINDS = ("collection", "deck", "list", "sealed")  # "list": a binder or wishlist
SORTS = ["Name", "Price", "Quantity", "Mana value", "Color", "Type", "Rarity", "Set", "Date added"]
SEALED_SORTS = ["Name", "Price", "Quantity", "Set", "Date added"]
GROUPS = {"collection": ["Nothing", "Type", "Color", "Mana value", "Rarity", "Set", "Finish", "Condition"],
          # A deck's sections always stay apart; the grouping splits the main deck
          "deck": ["Section", "Type", "Color", "Mana value", "Rarity", "Set"],
          "list": ["Nothing", "Type", "Color", "Mana value", "Rarity", "Set", "Finish"],
          "sealed": ["Nothing", "Set", "Product type"]}
NEEDS_RULES = {"Mana value", "Color", "Type"}
# Sorts that start biggest (or newest) first when picked
DESCENDING_FIRST = {"Price", "Quantity", "Date added", "Total", "Change", "Paid", "Gain / Loss"}  # desktop columns too

SECTION_TITLES = {"Commander": "Commander", "Companion": "Companion", "Main": "Main Deck",
                  "Sideboard": "Sideboard", "Maybeboard": "Maybeboard"}
COLOR_NAMES = {"W": "White", "U": "Blue", "B": "Black", "R": "Red", "G": "Green"}
COLOR_ORDER = ["White", "Blue", "Black", "Red", "Green", "Multicolor", "Colorless"]
RARITIES = ["common", "uncommon", "rare", "mythic", "special", "bonus"]
UNKNOWN = "Unknown"  # a card whose rules or details aren't known


def sorts_for(kind):
    return SEALED_SORTS if kind == "sealed" else SORTS


def default(kind):
    return {"sort": "Name", "descending": False, "group": GROUPS[kind][0]}


def direction_labels(sort):
    # (ascending, descending) as the controls say them
    if sort in ("Price", "Quantity", "Mana value"):
        return "Low to high", "High to low"
    if sort == "Date added":
        return "Oldest first", "Newest first"
    return "A to Z", "Z to A"


def picked(view, sort):
    # The view after picking a sort: the same sort flips direction, another starts its natural way
    if sort == view["sort"]:
        return {**view, "descending": not view["descending"]}
    return {**view, "sort": sort, "descending": sort in DESCENDING_FIRST}


def label(view):
    # A short summary for a button: "Price ↓ · Type"
    arrow = "↓" if view["descending"] else "↑"
    group = view["group"]
    return f"{view['sort']} {arrow}" + ("" if group in ("Nothing", "Section") else f" · {group}")


# Remembering each list's view (in the card database's local settings, so per device)

def load(key, kind, extra_sorts=()):
    # extra_sorts: sorts a list offers beyond sorts_for(kind) (the desktop collection's columns)
    with db._connect() as conn:
        row = conn.execute("SELECT value FROM sync_state WHERE key = ?", (f"view:{key}",)).fetchone()
    view = default(kind)
    try:
        view.update(json.loads(row[0]) if row else {})
    except (TypeError, ValueError):
        pass
    if view["sort"] not in sorts_for(kind) + list(extra_sorts) or view["group"] not in GROUPS[kind]:
        return default(kind)
    return view


def save(key, view):
    with db._connect() as conn:
        conn.execute("INSERT OR REPLACE INTO sync_state (key, value) VALUES (?, ?)", (f"view:{key}", json.dumps(view)))


# Card rules for the collection (its rows only know the printing)

def needs_rules(view):
    return view["sort"] in NEEDS_RULES or view["group"] in NEEDS_RULES


def with_rules(rows):
    """(rows as dicts with type_line, cmc and colors added, names the card database lacks)"""
    rules = db.card_rules({row["name"] for row in rows})
    blank = {"type_line": None, "cmc": None, "colors": None}
    merged = [{**dict(row), **rules.get(row["name"], blank)} for row in rows]
    return merged, sorted({row["name"] for row in rows} - set(rules))


_tried = set()  # names looked up already this run, so a card Scryfall doesn't know isn't asked again


def fetch_rules(names):
    """Looks up these cards' rules on Scryfall and keeps them (network: call off the UI thread).
    Returns how many were found."""
    names = [n for n in names if n not in _tried]
    _tried.update(names)
    records = scryfall.fetch_card_data(names) if names else []
    if records:
        db.add_oracle_cards(records)
    return len(records)


# Sorting and grouping

def _get(row, key):
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _type(row):
    line = _get(row, "type_line")
    if line is None:
        return None
    front = line.split("//")[0]
    return next((t for t in formats.CARD_TYPES if t in front), "Other")


def _color(row):
    colors = _get(row, "colors")
    if colors is None:
        return None
    return "Colorless" if not colors else "Multicolor" if len(colors) > 1 else COLOR_NAMES.get(colors, "Colorless")


def _rarity(row):
    rarity = (_get(row, "rarity") or "").lower()
    return rarity if rarity in RARITIES else None


def _number(row):
    # A collector number in number order: "9" before "10", "12a" after "12"
    number = _get(row, "collector_number") or ""
    digits = "".join(c for c in number if c.isdigit())
    return int(digits) if digits else 0, number


def _price(row):
    price = _get(row, "price")
    return price if price is not None else _get(row, "value")  # sealed product has a value


SORT_KEYS = {
    "Name": lambda r: (r["name"] or "").lower(),
    "Price": _price,
    "Quantity": lambda r: _get(r, "quantity"),
    "Mana value": lambda r: _get(r, "cmc"),
    "Color": lambda r: None if _color(r) is None else (COLOR_ORDER.index(_color(r)), _get(r, "colors")),
    "Type": lambda r: None if _type(r) is None else (formats.CARD_TYPES + ["Other"]).index(_type(r)),
    "Rarity": lambda r: None if _rarity(r) is None else RARITIES.index(_rarity(r)),
    "Set": lambda r: ((_get(r, "set_name") or "").lower(), _number(r)) if _get(r, "set_name") else None,
    "Date added": lambda r: _get(r, "id"),
}


# The sealed tables' own sorts, by their columns (the desktop's and the website's)
SEALED_COLUMN_KEYS = {"Product type": lambda r: (r["product_type"] or "").lower() or None,
                      "Paid": lambda r: r["paid"], "Total": lambda r: (r["value"] or 0) * r["quantity"],
                      "Gain / Loss": price_changes.sealed_gain, "Notes": lambda r: (r["notes"] or "").lower() or None}


def sort_rows(rows, sort, descending, extra_sorts=None):
    """rows in order: by name first, then by the sort (either way), with rows the sort knows
    nothing about (no price, no rules) always last. extra_sorts: {name: key} beyond SORT_KEYS
    (the desktop's own columns)."""
    key = {**SORT_KEYS, **(extra_sorts or {})}[sort]
    by_name = sorted(rows, key=SORT_KEYS["Name"])
    known = [r for r in by_name if key(r) is not None]
    return sorted(known, key=key, reverse=descending) + [r for r in by_name if key(r) is None]


def _type_title(card_type):
    return {"Sorcery": "Sorceries", "Other": "Other"}.get(card_type, card_type + "s")


def _group_of(row, group):
    """(order, title) of the group a row falls in"""
    if group == "Type":
        kind = _type(row)
        return ((formats.CARD_TYPES + ["Other"]).index(kind), _type_title(kind)) if kind else (99, UNKNOWN)
    if group == "Color":
        color = _color(row)
        return (COLOR_ORDER.index(color), color) if color else (99, UNKNOWN)
    if group == "Mana value":
        cmc = _get(row, "cmc")
        if cmc is None:
            return 99, UNKNOWN
        value = min(int(cmc), 7)
        return value, f"Mana value {value}{'+' if value == 7 else ''}"
    if group == "Rarity":
        rarity = _rarity(row)
        return (RARITIES.index(rarity), rarity.capitalize()) if rarity else (99, UNKNOWN)
    if group == "Set":
        name, code = _get(row, "set_name"), _get(row, "set_code")
        if not name:
            return "~", "No set"
        return name.lower(), f"{name} ({code.upper()})" if code else name
    if group == "Finish":
        code = int(_get(row, "foil") or 0)
        return code, scryfall.FINISHES[code][1]
    if group == "Condition":
        condition = _get(row, "condition")
        order = list(copy_details.CONDITIONS)
        return (order.index(condition), copy_details.CONDITIONS[condition]) if condition in order else (99, UNKNOWN)
    if group == "Product type":
        kind = _get(row, "product_type")
        return (kind.lower(), kind) if kind else ("~", "Other")
    return 0, ""


def _grouped(rows, group):
    groups = {}
    for row in rows:
        groups.setdefault(_group_of(row, group), []).append(row)
    return [(title, members) for (_, title), members in sorted(groups.items(), key=lambda item: item[0][0])]


def arrange(rows, view, kind, extra_sorts=None):
    """[(group title, rows in order)]: one untitled group (title None) when grouped by nothing.
    A deck keeps its Commander and Companion first and Sideboard and Maybeboard last as their
    own groups; the grouping splits the main deck (or leaves it whole, grouped by section)."""
    ordered = sort_rows(rows, view["sort"], view["descending"], extra_sorts)
    group = view["group"]
    if kind == "deck":
        sections = SECTIONS + sorted({_get(r, "section") or "" for r in ordered} - set(SECTIONS))
        result = []
        for section in sections:
            members = [r for r in ordered if (_get(r, "section") or "") == section]
            if section == "Main" and group != "Section":
                result += _grouped(members, group)
            elif members or section == "Main":
                result.append((SECTION_TITLES.get(section, section or "Cards"), members))
        return result
    if group == "Nothing":
        return [(None, ordered)] if ordered else []
    return _grouped(ordered, group)


def totals(rows):
    # (copies, value) of a group
    return (sum(_get(r, "quantity") or 0 for r in rows),
            sum((_price(r) or 0) * (_get(r, "quantity") or 0) for r in rows))


def heading(title, rows, noun="card"):
    # A group's heading line: "Creatures — 32 cards · $145.20" (noun: "item" for sealed product)
    copies, value = totals(rows)
    return f"{title} — {copies} {noun}{'s' if copies != 1 else ''}" + (f" · ${value:,.2f}" if value else "")
