"""
The desktop's Sort / direction / Group controls (card_sorting.py does the sorting): above the
collection, a deck or list in the Deck Builder, and the sealed product table.
"""

# Imports
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QComboBox, QHBoxLayout, QLabel, QTableWidgetItem, QToolButton, QWidget

import background
import card_sorting

GROUP_ROLE = Qt.ItemDataRole.UserRole + 20  # a group's title, on its heading row's first cell


class SortBar(QWidget):
    """changed fires when the view changes; key is where the view is remembered (set_key
    switches it, e.g. to another list). extra_sorts: sorts beyond card_sorting's, such as the
    collection's own columns (they're picked by clicking the column's header)."""

    changed = Signal()

    def __init__(self, kind, key, extra_sorts=(), parent=None):
        super().__init__(parent)
        self.kind, self.key, self.extra_sorts = kind, key, list(extra_sorts)
        self.view = card_sorting.load(key, kind, self.extra_sorts)
        self._fetching = False
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(card_sorting.sorts_for(kind) + self.extra_sorts)
        self.sort_combo.setToolTip("Sort the cards (clicking a column header does too)")
        self.direction = QToolButton()
        self.direction.setToolTip("Flip the order")
        self.group_combo = QComboBox()
        self.group_combo.addItems(card_sorting.GROUPS[kind])
        self.group_combo.setToolTip("Put the cards in groups, each with its count and value; click a group to fold it")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for widget in (QLabel("Sort:"), self.sort_combo, self.direction, QLabel("Group:"), self.group_combo):
            layout.addWidget(widget)
        # A deck's or list's View: List, Text, Grid or Stacks
        layout.addSpacing(12)
        self.view_label = QLabel("View:")
        layout.addWidget(self.view_label)
        self.display_buttons = QButtonGroup(self)
        for display in card_sorting.DISPLAYS:
            button = QToolButton(text=display, checkable=True, autoRaise=True)
            button.setToolTip(f"Show the cards as {display.lower()}")
            button.clicked.connect(lambda _, d=display: self._set({**self.view, "display": d}))
            self.display_buttons.addButton(button)
            layout.addWidget(button)
        self._show()
        self.sort_combo.currentTextChanged.connect(lambda sort: self.pick(sort) if sort != self.view["sort"] else None)
        self.direction.clicked.connect(lambda: self._set({**self.view, "descending": not self.view["descending"]}))
        self.group_combo.currentTextChanged.connect(lambda group: self._set({**self.view, "group": group}))

    def set_key(self, key, kind=None):
        # Another list's view (kind: when it's another kind of list, e.g. a binder after a deck)
        if kind and kind != self.kind:
            self.kind = kind
            for combo, items in ((self.sort_combo, card_sorting.sorts_for(kind) + self.extra_sorts),
                                 (self.group_combo, card_sorting.GROUPS[kind])):
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(items)
                combo.blockSignals(False)
        self.key = key
        self.view = card_sorting.load(key, self.kind, self.extra_sorts)
        self._show()

    def pick(self, sort):
        # A sort chosen here or by a column header: the same one again flips the order
        self._set(card_sorting.picked(self.view, sort))

    def _set(self, view):
        if view != self.view:
            self.view = view
            card_sorting.save(self.key, view)
            self._show()
            self.changed.emit()

    def _show(self):
        for combo, value in ((self.sort_combo, self.view["sort"]), (self.group_combo, self.view["group"])):
            combo.blockSignals(True)
            combo.setCurrentText(value)
            combo.blockSignals(False)
        shown = self.kind in card_sorting.DISPLAY_KINDS
        self.view_label.setVisible(shown)
        for button in self.display_buttons.buttons():
            button.setVisible(shown)
            button.setChecked(button.text() == self.view["display"])
        ascending, descending = card_sorting.direction_labels(self.view["sort"])
        self.direction.setText(f"↓ {descending}" if self.view["descending"] else f"↑ {ascending}")

    def arrange(self, rows, extra_keys=None, look_up_rules=False):
        """card_sorting.arrange for this view. look_up_rules: rows lack card rules (the
        collection's), so they're added, and any the card database lacks are fetched from
        Scryfall in the background, firing changed once they're in."""
        if look_up_rules and card_sorting.needs_rules(self.view):
            rows, missing = card_sorting.with_rules(rows)
            if missing and not self._fetching:
                self._fetching = True
                background.run(card_sorting.fetch_rules, missing, on_success=self._fetched,
                               on_error=lambda message: setattr(self, "_fetching", False))
        return card_sorting.arrange(rows, self.view, self.kind, extra_keys)

    def _fetched(self, found):
        self._fetching = False
        if found:
            self.changed.emit()


# Groups in a QTableWidget (the collection and sealed tables): a heading row above each group,
# spanning the table, that folds the group away when clicked

def table_lines(groups):
    """The table's rows for card_sorting.arrange's groups: (title, its rows) for a heading,
    (None, row) for a row of its own"""
    lines = []
    for title, members in groups:
        if title is not None:
            lines.append((title, members))
        lines += [(None, row) for row in members]
    return lines


def set_heading(table, row_index, title, members, folded, noun="card"):
    text = card_sorting.heading(title, members, noun)
    item = QTableWidgetItem(("▸ " if title in folded else "▾ ") + text)
    item.setData(GROUP_ROLE, title)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
    font = item.font()
    font.setBold(True)
    item.setFont(font)
    item.setToolTip("Click to fold or unfold this group")
    table.setItem(row_index, 0, item)
    table.setSpan(row_index, 0, 1, table.columnCount())


def toggle_heading(table, row_index, folded):
    """Folds or unfolds the group whose heading was clicked (folded: the set of folded titles).
    False when the row isn't a heading."""
    item = table.item(row_index, 0)
    title = item.data(GROUP_ROLE) if item else None
    if title is None:
        return False
    folded ^= {title}
    item.setText(("▸ " if title in folded else "▾ ") + item.text()[2:])
    return True


def hide_rows(table, id_role, matches, folded):
    """Hides the rows the filter doesn't match (matches(row id) says) and the folded groups'
    rows, and the heading of a group with nothing matching"""
    headings, folded_now = [], False  # [heading row, rows matching] for each group
    for row_index in range(table.rowCount()):
        item = table.item(row_index, 0)
        if item.data(GROUP_ROLE) is not None:
            headings.append([row_index, 0])
            folded_now = item.data(GROUP_ROLE) in folded
            continue
        shown = matches(item.data(id_role))
        if shown and headings:
            headings[-1][1] += 1
        table.setRowHidden(row_index, not shown or folded_now)
    for row_index, matching in headings:
        table.setRowHidden(row_index, matching == 0)


def show_sort_indicator(table, column_sorts, view):
    # The arrow on the header of the column the view sorts by (none if it's not a column)
    table.horizontalHeader().setSortIndicator(
        next((c for c, sort in column_sorts.items() if sort == view["sort"]), -1),
        Qt.SortOrder.DescendingOrder if view["descending"] else Qt.SortOrder.AscendingOrder)
