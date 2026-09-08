"""
db.py
-----
Handles the SQLite database connection and schema initialization.

DBMS concept demonstrated: centralized connection management,
schema creation via raw SQL (DDL), and enabling foreign key
constraints (referential integrity).
"""

import sqlite3
import os

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database")
DB_PATH = os.path.join(DB_DIR, "wallet_system.db")
SCHEMA_PATH = os.path.join(DB_DIR, "schema.sql")


def get_connection():
    """
    Returns a new SQLite connection with foreign key support enabled.
    check_same_thread=False is required because our OS/concurrency
    demo (Module 3) accesses the DB from multiple threads.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Creates all tables from schema.sql if they do not already exist.
    Safe to call every time the app starts.
    """
    os.makedirs(DB_DIR, exist_ok=True)
    conn = get_connection()
    with open(SCHEMA_PATH, "r") as f:
        schema = f.read()
    conn.executescript(schema)
    conn.commit()
    conn.close()
    print(f"[DB] Database ready at: {DB_PATH}")


if __name__ == "__main__":
    init_db()
