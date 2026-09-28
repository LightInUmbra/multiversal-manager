"""
How prices moved over a period: per entry and for the whole collection. Qt-free, so the
phone app and the website use it too; trends.py builds the desktop's windows on it.
"""
# Imports
from dataclasses import dataclass


@dataclass
class Change:
    past: float    # price at the start of the period
    now: float     # current price
    quantity: int

    @property
    def each(self):
        return self.now - self.past

    @property
    def total(self):
        return self.each * self.quantity

    @property
    def percent(self):
        return self.each / self.past * 100 if self.past else None


def compute_changes(rows, past_prices):
    """{card_id: Change} for entries with a price at the start of the period.
    Only market movement counts -- cards added or removed don't show as gains or losses."""
    changes = {}
    for row in rows:
        past = past_prices.get(row["id"])
        if past:  # no history that old, or no price back then
            changes[row["id"]] = Change(past, row["price"], row["quantity"])
    return changes


def collection_change(changes):
    # (total $ change, % change) across every entry with history, or None
    if not changes:
        return None
    past_value = sum(c.past * c.quantity for c in changes.values())
    total = sum(c.total for c in changes.values())
    return total, (total / past_value * 100 if past_value else None)


def format_change(amount, percent=None):
    sign = "+" if amount > 0.004 else "−" if amount < -0.004 else "±"
    text = f"{sign}${abs(amount):,.2f}"
    if percent is not None:
        text += f" ({'+' if percent >= 0 else '−'}{abs(percent):.1f}%)"
    return text
