"""Optional Redis. If it is not installed / not running the project silently uses in-memory fallbacks."""
import logging

log = logging.getLogger("wallet.redis")


def connect_redis(url: str, enabled: bool = True):
    if not enabled:
        return None
    try:
        import redis

        client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=2)
        client.ping()
        log.info("Redis connected (%s): sessions, locks, cache and rate limits will use it", url)
        return client
    except Exception as exc:  # ImportError, ConnectionError, ...
        log.warning("Redis not available (%s) - using in-memory fallbacks", exc.__class__.__name__)
        return None
