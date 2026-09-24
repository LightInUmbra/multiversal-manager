import pytest

import trends


def _row(id, price, quantity=1):
    return {"id": id, "price": price, "quantity": quantity}


def test_changes_only_for_entries_with_past_prices():
    rows = [_row(1, 12.0, 2), _row(2, 5.0), _row(3, 1.0)]
    changes = trends.compute_changes(rows, {1: 10.0, 3: 0.0})
    assert set(changes) == {1}  # no history for 2; a $0 past price has no meaningful %
    change = changes[1]
    assert (change.each, change.total, change.percent) == (2.0, 4.0, 20.0)


def test_collection_change_is_weighted_by_quantity():
    changes = trends.compute_changes([_row(1, 12.0, 2), _row(2, 4.0, 1)], {1: 10.0, 2: 5.0})
    total, percent = trends.collection_change(changes)
    assert total == 3.0  # +4 on two copies, -1 on one
    assert percent == pytest.approx(3.0 / 25.0 * 100)
    assert trends.collection_change({}) is None


def test_format_change():
    assert trends.format_change(1.2, 15.0) == "+$1.20 (+15.0%)"
    assert trends.format_change(-0.5, -2.5) == "−$0.50 (−2.5%)"
    assert trends.format_change(0.0, 0.0) == "±$0.00 (+0.0%)"
    assert trends.format_change(1234.5) == "+$1,234.50"
