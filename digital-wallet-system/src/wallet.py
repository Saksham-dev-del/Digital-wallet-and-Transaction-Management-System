"""
wallet.py
---------
Simple wallet lookups. Balance modifications themselves live in
transaction.py, because every balance change must go through the
transaction ledger (that's the whole point of the DBMS module).

Redis caching (cache-aside pattern):
get_balance() is called very often (every dashboard refresh) but
changes relatively rarely. Instead of hitting SQLite every time:
  1. Check Redis for wallet:balance:<id>.
  2. If present (cache hit) -> return it, skip the DB entirely.
  3. If absent (cache miss) -> read from SQLite, then store it in
     Redis with a short TTL so it self-heals even if an invalidation
     is ever missed.
Whenever transaction.py changes a balance, it calls
invalidate_balance_cache() so the next read is forced back to
SQLite (the source of truth) and the cache gets refreshed.
"""

from db import get_connection
from cache import get_redis, redis_available

BALANCE_CACHE_TTL_SECONDS = 30
BALANCE_CACHE_PREFIX = "wallet:balance:"


def get_wallet_by_user_id(user_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_balance(wallet_id: int) -> float:
    cache_key = BALANCE_CACHE_PREFIX + str(wallet_id)

    if redis_available():
        cached = get_redis().get(cache_key)
        if cached is not None:
            return float(cached)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM wallets WHERE wallet_id = ?", (wallet_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise ValueError(f"Wallet {wallet_id} does not exist.")

    balance = row["balance"]
    if redis_available():
        get_redis().setex(cache_key, BALANCE_CACHE_TTL_SECONDS, str(balance))
    return balance


def invalidate_balance_cache(wallet_id: int):
    if redis_available():
        get_redis().delete(BALANCE_CACHE_PREFIX + str(wallet_id))
