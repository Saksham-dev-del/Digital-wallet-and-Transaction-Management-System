"""SQLite connection helpers.

DBMS concepts: ACID transactions (BEGIN IMMEDIATE ... COMMIT / ROLLBACK), WAL journal mode
(readers never block the single writer), foreign keys, busy-timeout (a waiting writer sleeps
instead of failing).
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=15, isolation_level=None)  # None = we control BEGIN/COMMIT ourselves
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def init_db(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    finally:
        conn.close()


@contextmanager
def tx(conn: sqlite3.Connection):
    """One ACID transaction. BEGIN IMMEDIATE takes the write lock up-front, so two money movements
    can never interleave their read-modify-write steps (serializable behaviour)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        try:
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
