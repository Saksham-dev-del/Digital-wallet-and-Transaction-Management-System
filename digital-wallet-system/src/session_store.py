"""
session_store.py
-----------------
Login session tokens, stored in Redis with an expiry.

Why this matters (fixes a real gap from the earlier version):
previously the frontend just remembered the logged-in user's info in
localStorage and sent whatever wallet_id it liked with every request
- the backend trusted it blindly. Now:

  1. login() creates a random token and stores
     token -> {user_id, wallet_id, full_name, username} in Redis
     with a TTL (session expires after SESSION_TTL_SECONDS).
  2. Every protected API call must send that token in an
     "Authorization: Bearer <token>" header.
  3. The backend looks up the token in Redis to find out WHICH
     wallet the caller is actually allowed to act on - it no longer
     trusts a wallet_id supplied in the request body for the
     "my own wallet" operations (deposit/withdraw/history/balance).

This is a session store, not a login system - auth.py still owns
password verification. This module just tracks "who is currently
logged in, as which token, until when".
"""

import secrets
import json
from cache import get_redis

SESSION_TTL_SECONDS = 60 * 60 * 24  # 24 hours
SESSION_KEY_PREFIX = "session:"


def create_session(user: dict) -> str:
    token = secrets.token_hex(32)
    r = get_redis()
    r.setex(
        SESSION_KEY_PREFIX + token,
        SESSION_TTL_SECONDS,
        json.dumps(user),
    )
    return token


def get_session(token: str):
    if not token:
        return None
    r = get_redis()
    raw = r.get(SESSION_KEY_PREFIX + token)
    if raw is None:
        return None
    return json.loads(raw)


def destroy_session(token: str):
    if not token:
        return
    r = get_redis()
    r.delete(SESSION_KEY_PREFIX + token)


def extract_token(auth_header: str) -> str:
    """Pulls the token out of an 'Authorization: Bearer <token>' header."""
    if not auth_header or not auth_header.startswith("Bearer "):
        return ""
    return auth_header[len("Bearer "):].strip()
