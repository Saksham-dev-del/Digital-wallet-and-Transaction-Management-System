"""
auth.py
-------
Basic user registration and login.

NOTE (pending work): passwords are hashed with SHA-256 + a static
salt for demo purposes. A production system should use bcrypt/argon2
with a per-user random salt. This is intentionally left as a
TODO for the next phase of the project (see README -> Pending Work).
"""

import hashlib
from db import get_connection

STATIC_SALT = "dwpt_pbl_salt"  # TODO: replace with per-user random salt (pending work)


def hash_password(password: str) -> str:
    return hashlib.sha256((password + STATIC_SALT).encode()).hexdigest()


def register_user(username: str, password: str, full_name: str, email: str):
    """
    Creates a new user AND their wallet in a single DB transaction.
    If wallet creation fails, the user insert is rolled back
    (ACID - Atomicity).
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN")
        cur.execute(
            "INSERT INTO users (username, password_hash, full_name, email) VALUES (?, ?, ?, ?)",
            (username, hash_password(password), full_name, email),
        )
        user_id = cur.lastrowid
        cur.execute(
            "INSERT INTO wallets (user_id, balance) VALUES (?, 0.0)",
            (user_id,),
        )
        conn.commit()
        print(f"[AUTH] User '{username}' registered successfully with a new wallet.")
        return user_id
    except Exception as e:
        conn.rollback()
        print(f"[AUTH] Registration failed, rolled back. Reason: {e}")
        return None
    finally:
        conn.close()


def login_user(username: str, password: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
    conn.close()

    if user is None:
        print("[AUTH] No such user.")
        return None
    if user["password_hash"] != hash_password(password):
        print("[AUTH] Incorrect password.")
        return None

    print(f"[AUTH] Welcome back, {user['full_name']}!")
    return dict(user)
