"""
concurrency.py
--------------
OS Module: Mutual Exclusion — two layers.

LAYER 1 - threading.Lock (in-process):
Concept: In a real payment system, multiple requests (threads/processes)
can try to update the SAME wallet's balance at the same time. Without
synchronization this causes a "race condition" - e.g. two withdrawals
of 500 each on a wallet with 700 balance could BOTH read balance=700,
both think it's sufficient, and both succeed, leaving balance = -300.
LockManager keeps one Lock object per wallet_id so operations on
DIFFERENT wallets can still run in parallel - only operations on the
SAME wallet are serialized. This only protects a single Python
process, though.

LAYER 2 - RedisLock (distributed):
If this app were ever run as multiple processes/servers behind a load
balancer (a very normal production setup), an in-process
threading.Lock is USELESS - process A's lock knows nothing about
process B. Redis gives every process a shared place to coordinate:
  - acquire: SET key value NX PX <ttl>   (atomic "only if not already set")
  - release: a Lua script that only deletes the key if it still holds
    OUR unique token (so process A can never accidentally release a
    lock that process B currently owns)
This is the same idea as a Banker's-Algorithm-style resource lock,
just implemented with Redis's atomic commands instead of shared
memory. transaction.py uses BOTH layers together: the threading.Lock
first (cheap, fast path for the common single-process case), then
the RedisLock (correct even if you scale to multiple app instances).

PENDING WORK (not implemented yet, see README):
- Deadlock avoidance for transfer() when two transfers happen in
  opposite directions simultaneously (needs global lock ordering or
  Banker's Algorithm).
- Semaphore-based limiting of max concurrent DB connections.
"""

import threading
import time
import uuid

from cache import get_redis, redis_available


class LockManager:
    def __init__(self):
        self._locks = {}
        self._locks_guard = threading.Lock()  # protects the _locks dict itself

    def get_lock(self, wallet_id: int) -> threading.Lock:
        with self._locks_guard:
            if wallet_id not in self._locks:
                self._locks[wallet_id] = threading.Lock()
            return self._locks[wallet_id]


# Single shared instance used across the whole application
lock_manager = LockManager()


# Lua script for a SAFE unlock: only delete the key if its value still
# matches the token we set when we acquired it. Without this, a slow
# process could delete a lock that a different process now owns.
_UNLOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class RedisLock:
    """
    A distributed mutex for one wallet_id, backed by Redis.
    Falls back to a no-op if Redis is unreachable, so the app still
    runs (protected only by the in-process threading.Lock in that
    case) - see README for why this fallback is a deliberate
    trade-off for a student project rather than a hard dependency.
    """

    def __init__(self, wallet_id: int, ttl_ms: int = 5000, wait_timeout_s: float = 5.0):
        self.key = f"lock:wallet:{wallet_id}"
        self.token = str(uuid.uuid4())
        self.ttl_ms = ttl_ms
        self.wait_timeout_s = wait_timeout_s
        self._acquired = False
        self._redis_ok = redis_available()

    def __enter__(self):
        if not self._redis_ok:
            print("[REDIS] Not reachable - skipping distributed lock "
                  "(in-process lock still applies).")
            return self

        r = get_redis()
        deadline = time.time() + self.wait_timeout_s
        while time.time() < deadline:
            if r.set(self.key, self.token, nx=True, px=self.ttl_ms):
                self._acquired = True
                return self
            time.sleep(0.05)
        raise TimeoutError(f"Could not acquire distributed lock for {self.key}")

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._acquired:
            r = get_redis()
            r.eval(_UNLOCK_SCRIPT, 1, self.key, self.token)


# ---------------------------------------------------------------------
# Demo: race condition WITHOUT proper locking, vs SAFE version WITH it.
# Run this file directly to see the difference printed to console.
# ---------------------------------------------------------------------
if __name__ == "__main__":
    import time
    from db import init_db, get_connection
    import auth
    import transaction

    init_db()

    # Set up a fresh demo user/wallet
    conn = get_connection()
    conn.execute("DELETE FROM users WHERE username = 'demo_concurrency_user'")
    conn.commit()
    conn.close()

    user_id = auth.register_user(
        "demo_concurrency_user", "pass123", "Demo User", "demo_conc@example.com"
    )
    from wallet import get_wallet_by_user_id, get_balance
    wallet = get_wallet_by_user_id(user_id)
    wallet_id = wallet["wallet_id"]
    transaction.deposit(wallet_id, 1000)

    print("\n--- Starting 5 concurrent withdrawals of 300 each (balance=1000) ---")
    print("Wallet can only truly afford 3 of these 5 withdrawals.\n")

    def try_withdraw():
        try:
            transaction.withdraw(wallet_id, 300)
        except Exception as e:
            print(f"[THREAD {threading.current_thread().name}] Withdraw rejected: {e}")

    threads = [threading.Thread(target=try_withdraw, name=f"T{i+1}") for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final_balance = get_balance(wallet_id)
    print(f"\n[RESULT] Final balance = {final_balance} "
          f"(should be 100 if locking worked correctly: 1000 - 3*300 = 100)")

