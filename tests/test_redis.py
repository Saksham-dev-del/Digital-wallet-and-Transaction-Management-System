"""Runs only when a Redis server is reachable on localhost:6379 (database 15 is used and flushed)."""
import threading

import pytest

redis = pytest.importorskip("redis")

from app.services.cache import RedisCache
from app.services.locks import LockManager, LockTimeout, RedisLock, WalletLocks
from app.services.ratelimit import RateLimiter
from tests.conftest import Api, build_app


@pytest.fixture()
def r():
    client = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True, socket_connect_timeout=0.3)
    try:
        client.ping()
    except Exception:
        pytest.skip("no Redis server on localhost:6379")
    client.flushdb()
    yield client
    client.flushdb()


def test_redis_lock_is_exclusive_and_owner_checked(r):
    a, b = RedisLock(r, "k", 5000), RedisLock(r, "k", 5000)
    assert a.acquire(1)
    with pytest.raises(LockTimeout):
        b.acquire(0.1)
    b.release()                                                    # not the owner -> must NOT free the lock
    assert r.get("k") == a.token
    a.release()
    assert r.get("k") is None and b.acquire(1)


def test_wallet_locks_with_redis_serialise_threads(r):
    locks, counter = WalletLocks(LockManager("t"), r), {"v": 0}

    def work():
        for _ in range(40):
            with locks.hold([1, 2]):
                v = counter["v"]
                counter["v"] = v + 1

    ts = [threading.Thread(target=work) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert counter["v"] == 200


def test_cache_and_rate_limit(r):
    c = RedisCache(r, 30)
    assert c.get("x") is None
    c.set("x", 42)
    assert c.get("x") == 42 and c.stats()["hits"] == 1
    c.delete("x")
    assert c.get("x") is None
    rl = RateLimiter(r)
    assert [rl.hit("t", "u", 2, 60)[0] for _ in range(3)] == [True, True, False]


def test_whole_app_on_redis(tmp_path, r):
    app = build_app(tmp_path, USE_REDIS=True, REDIS_URL="redis://localhost:6379/15")
    assert app.extensions["wallet"].redis is not None
    c = app.test_client()
    api = Api(c)
    a, _ = api.register("Asha Rao")
    b, _ = api.register("Bhavesh Kumar")
    api.topup(a, 1000)
    assert api.pay(a, "bhavesh@swallet", 100).status_code == 201
    assert api.balance(a) == 90000 and api.balance(b) == 10000
    assert any(k.startswith("session:") for k in r.scan_iter("session:*"))
    assert c.get("/api/os/overview", headers=a).json["cache"]["kind"] == "redis"
