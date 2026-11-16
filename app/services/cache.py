"""Balance cache (cache-aside).

OS / memory-management concept: a fixed number of 'frames' (capacity). When the cache is full the
Least-Recently-Used entry is evicted - the same idea as LRU page replacement.
If Redis is running it is used instead (it has its own eviction + TTL).
"""
import json
import logging
import threading
import time
from collections import OrderedDict

log = logging.getLogger("wallet.cache")


class LRUCache:
    kind = "in-process LRU"

    def __init__(self, capacity: int = 256, ttl: int = 30):
        self.capacity, self.ttl = capacity, ttl
        self._data: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = self.evictions = 0

    def get(self, key):
        with self._lock:
            item = self._data.get(key)
            if item is None or item[1] < time.monotonic():
                if item is not None:
                    del self._data[key]
                self.misses += 1
                return None
            self._data.move_to_end(key)          # most recently used goes to the back
            self.hits += 1
            return item[0]

    def set(self, key, value, ttl: int | None = None) -> None:
        with self._lock:
            self._data[key] = (value, time.monotonic() + (ttl or self.ttl))
            self._data.move_to_end(key)
            while len(self._data) > self.capacity:
                self._data.popitem(last=False)   # evict the least recently used
                self.evictions += 1

    def delete(self, key) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            return {"kind": self.kind, "capacity": self.capacity, "size": len(self._data), "hits": self.hits,
                    "misses": self.misses, "evictions": self.evictions,
                    "hit_ratio": round(self.hits / total, 3) if total else None,
                    "keys_lru_to_mru": list(self._data.keys())[:20]}


class RedisCache:
    kind = "redis"

    def __init__(self, client, ttl: int = 30, prefix: str = "wallet:cache:"):
        self.client, self.ttl, self.prefix = client, ttl, prefix
        self.hits = self.misses = 0

    def get(self, key):
        try:
            raw = self.client.get(self.prefix + key)
        except Exception:
            raw = None
        if raw is None:
            self.misses += 1
            return None
        self.hits += 1
        return json.loads(raw)

    def set(self, key, value, ttl: int | None = None) -> None:
        try:
            self.client.set(self.prefix + key, json.dumps(value), ex=ttl or self.ttl)
        except Exception as exc:
            log.warning("redis cache set failed (%s)", exc.__class__.__name__)

    def delete(self, key) -> None:
        try:
            self.client.delete(self.prefix + key)
        except Exception as exc:
            log.warning("redis cache delete failed (%s)", exc.__class__.__name__)

    def clear(self) -> None:
        try:
            for k in self.client.scan_iter(self.prefix + "*"):
                self.client.delete(k)
        except Exception:
            pass

    def stats(self) -> dict:
        total = self.hits + self.misses
        size = None
        try:
            size = sum(1 for _ in self.client.scan_iter(self.prefix + "*"))
        except Exception:
            pass
        return {"kind": self.kind, "ttl": self.ttl, "size": size, "hits": self.hits, "misses": self.misses,
                "hit_ratio": round(self.hits / total, 3) if total else None}


def make_cache(redis_client, capacity: int, ttl: int):
    return RedisCache(redis_client, ttl) if redis_client is not None else LRUCache(capacity, ttl)
