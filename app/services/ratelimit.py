"""Fixed-window rate limiter (Redis INCR/EXPIRE when available, a dict otherwise)."""
import threading
import time

from ..util import WalletError


class RateLimiter:
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self._counts: dict = {}
        self._lock = threading.Lock()

    def hit(self, scope: str, ident, limit: int, window: int):
        """Returns (allowed, retry_after_seconds, remaining)."""
        now = time.time()
        bucket = int(now // window)
        key = f"rl:{scope}:{ident}:{bucket}"
        retry = int(window - (now % window)) + 1
        count = 0
        if self.redis is not None:
            try:
                pipe = self.redis.pipeline()
                pipe.incr(key)
                pipe.expire(key, window + 1)
                count = pipe.execute()[0]
            except Exception:
                count = 0  # fail open
        else:
            with self._lock:
                if len(self._counts) > 5000:
                    self._counts = {k: v for k, v in self._counts.items() if v[1] > now}
                count = self._counts.get(key, (0, 0))[0] + 1
                self._counts[key] = (count, (bucket + 1) * window)
        return count <= limit, retry, max(0, limit - count)

    def enforce(self, scope: str, ident, limit: int, window: int = 60) -> None:
        allowed, retry, remaining = self.hit(scope, ident, limit, window)
        if not allowed:
            raise WalletError(f"Too many requests. Try again in {retry} seconds.", "rate_limited", 429,
                              retry_after=retry)
        return remaining
