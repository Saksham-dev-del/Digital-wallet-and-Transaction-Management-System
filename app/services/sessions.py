"""Login sessions. SQLite is the source of truth; Redis (when running) is a fast lookup in front of it."""
import logging
from datetime import timedelta

from ..security import hash_token, new_token
from ..util import iso, parse_iso, utcnow

log = logging.getLogger("wallet.sessions")


class SessionStore:
    def __init__(self, ttl_seconds: int, redis_client=None):
        self.ttl, self.redis = ttl_seconds, redis_client

    def create(self, conn, user_id, ip="", user_agent="") -> str:
        token = new_token()
        digest = hash_token(token)                       # only the hash is stored - a DB leak does not leak sessions
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (iso(),))
        conn.execute("INSERT INTO sessions (token_hash, user_id, expires_at, ip, user_agent) VALUES (?,?,?,?,?)",
                     (digest, user_id, iso(utcnow() + timedelta(seconds=self.ttl)), ip[:64], user_agent[:200]))
        self._redis_set(digest, user_id)
        return token

    def resolve(self, conn, token: str):
        if not token:
            return None
        digest = hash_token(token)
        if self.redis is not None:
            try:
                uid = self.redis.get(f"session:{digest}")
                if uid:
                    return int(uid)
            except Exception:
                pass
        row = conn.execute("SELECT user_id, expires_at FROM sessions WHERE token_hash = ?", (digest,)).fetchone()
        if row is None or parse_iso(row["expires_at"]) < utcnow():
            return None
        self._redis_set(digest, row["user_id"])
        return row["user_id"]

    def revoke(self, conn, token: str) -> None:
        digest = hash_token(token)
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (digest,))
        if self.redis is not None:
            try:
                self.redis.delete(f"session:{digest}")
            except Exception:
                pass

    def _redis_set(self, digest, user_id) -> None:
        if self.redis is not None:
            try:
                self.redis.set(f"session:{digest}", user_id, ex=self.ttl)
            except Exception as exc:
                log.warning("redis session write failed (%s)", exc.__class__.__name__)
