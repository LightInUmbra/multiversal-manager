# Imports
import sys
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QDialog,
    QLineEdit, QDoubleSpinBox, QSpinBox, QDialogButtonBox
)
from PySide6.QtCore import Qt
import database as db

def get_add_card_input():
    # QDialog is a separate popup window/modal window
    dialog = QDialog()
    dialog.setWindowTitle("Add Card")

    # QFormLayout is purpose-built for "label: input" rows, stacked vertically --
    # addRow() takes a label and a widget, and lines them up automatically
    form_layout = QFormLayout()

    name_input = QLineEdit()
    set_input = QLineEdit()

    # QDoubleSpinBox/QSpinBox are numeric-only inputs
    price_input = QDoubleSpinBox()
    price_input.setPrefix("$")
    price_input.setMaximum(100000.00)  # a reasonable ceiling for a card price
    price_input.setDecimals(2)

    quantity_input = QSpinBox()
    quantity_input.setMinimum(1)
    quantity_input.setMaximum(999)

    form_layout.addRow("Name:", name_input)
    form_layout.addRow("Set:", set_input)
    form_layout.addRow("Price:", price_input)
    form_layout.addRow("Quantity:", quantity_input)

    # QDialogButtonBox gives you standard OK/Cancel buttons already wired
    # to the dialog's built-in accept()/reject() behavior
    button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    button_box.accepted.connect(dialog.accept)
    button_box.rejected.connect(dialog.reject)

    # An outer layout holds the form on top and the OK/Cancel buttons below
    outer_layout = QVBoxLayout()
    outer_layout.addLayout(form_layout)
    outer_layout.addWidget(button_box)
    dialog.setLayout(outer_layout)

    # dialog.exec() shows the dialog AND blocks execution right here until
    # the user closes it -- unlike window.show(), which returns immediately.
    # It returns QDialog.DialogCode.Accepted or .Rejected depending on which
    # button was clicked.
    result = dialog.exec()

    if result == QDialog.DialogCode.Accepted:
        return (name_input.text(), set_input.text(), price_input.value(), quantity_input.value())
    else:
        return None  # user clicked Cancel or closed the dialog

def populate_table():
    rows = db.get_all_cards()
    table.setRowCount(len(rows))

    for row_index, (card_id, name, set_name, price, quantity) in enumerate(rows):
        name_item = QTableWidgetItem(name)
        name_item.setData(Qt.ItemDataRole.UserRole, card_id)

        table.setItem(row_index, 0, name_item)
        table.setItem(row_index, 1, QTableWidgetItem(set_name))
        table.setItem(row_index, 2, QTableWidgetItem(f"${price:.2f}"))
        table.setItem(row_index, 3, QTableWidgetItem(str(quantity)))


# Action functions

def on_add_card_clicked():
    card_data = get_add_card_input()

    # If the user cancelled, card_data is None -- nothing should happen
    if card_data is None:
        return

    name, set_name, price, quantity = card_data

    # Basic guard: don't insert a completely blank name
    if not name.strip():
        print("Card name cannot be blank.")
        return

    db.add_card(name, set_name, price, quantity)
    populate_table()

def on_remove_selected_clicked():
    selected_row = table.currentRow()
    if selected_row == -1:
        print("No row selected.")
        return

    name_item = table.item(selected_row, 0)
    card_id = name_item.data(Qt.ItemDataRole.UserRole)

    db.remove_card(card_id)
    populate_table()


# App setup

app = QApplication(sys.argv)
db.create_table()

window = QWidget()
window.setWindowTitle("Multiversal Manager")
window.resize(1280, 720)

outer_layout = QVBoxLayout()

table = QTableWidget()
table.setColumnCount(4)
table.setHorizontalHeaderLabels(["Name", "Set", "Price", "Quantity"])

button_layout = QHBoxLayout()
add_button = QPushButton("Add Card")
remove_button = QPushButton("Remove Selected")
button_layout.addWidget(add_button)
button_layout.addWidget(remove_button)

add_button.clicked.connect(on_add_card_clicked)
remove_button.clicked.connect(on_remove_selected_clicked)

outer_layout.addWidget(table)
outer_layout.addLayout(button_layout)
window.setLayout(outer_layout)

populate_table()

window.show()
sys.exit(app.exec())