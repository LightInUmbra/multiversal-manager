# Imports
import sqlite3 as sql

# Constants
DB_NAME = "collection.db"

# Functions
def create_table():
    with sql.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS collection (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                set_name TEXT NOT NULL,
                price REAL NOT NULL,
                quantity INTEGER NOT NULL
            )
        """)
        conn.commit()


def add_card(name, set_name, price, quantity):
    with sql.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO collection (name, set_name, price, quantity)
            VALUES (?, ?, ?, ?)
        """, (name, set_name, price, quantity))
        conn.commit()

def get_all_cards():
    # Returns every row as a list of tuples: (id, name, set_name, price, quantity)
    with sql.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, set_name, price, quantity FROM collection")
        return cursor.fetchall()

def remove_card(card_id):
    # Deletes by id specifically, not by name -- this is exactly why the
    # id column exists, so two identical-looking cards don't get confused
    with sql.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM collection WHERE id = ?", (card_id,))
        conn.commit()