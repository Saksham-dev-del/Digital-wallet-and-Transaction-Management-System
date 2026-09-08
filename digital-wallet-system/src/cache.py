"""
cache.py
--------
Central Redis connection used for two purposes across the app:
  1. session_store.py  -> login session tokens
  2. wallet.py          -> cached wallet balances (cache-aside pattern)
  3. concurrency.py     -> distributed lock (SET NX PX)

Redis is used here as an in-memory data store that sits IN FRONT OF
the SQLite database (which remains the single source of truth).
If Redis is ever unreachable, the app should still work correctly
against SQLite directly - Redis only makes it faster/safer, it must
never be the only place data lives.
"""

import redis

REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0

_client = None


def get_redis():
    """
    Returns a shared Redis client (lazily created).
    decode_responses=True so we get plain Python strs back instead
    of bytes.
    """
    global _client
    if _client is None:
        _client = redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True
        )
    return _client


def redis_available() -> bool:
    """Quick health check - used so the app can degrade gracefully."""
    try:
        get_redis().ping()
        return True
    except Exception:
        return False
