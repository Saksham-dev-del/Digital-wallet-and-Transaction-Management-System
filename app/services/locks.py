"""Lock manager - the Operating-Systems heart of the project.

Concepts demonstrated
  * mutual exclusion    : one lock per wallet, so two payments never edit the same balance together
  * deadlock prevention : locks are always taken in ascending wallet_id order -> no circular wait is possible
  * deadlock detection  : a wait-for graph (thread -> thread that owns the lock it wants) + cycle search
  * deadlock recovery   : pick a victim, abort it (DeadlockVictim), it releases its locks and retries
  * distributed lock    : optional Redis lock (SET NX PX + token-checked release) for multi-process servers
"""
import logging
import threading
import time
import uuid
from collections import Counter
from contextlib import contextmanager

log = logging.getLogger("wallet.locks")


class LockTimeout(Exception):
    pass


class DeadlockVictim(Exception):
    pass


class LockManager:
    POLL = 0.02

    def __init__(self, name: str = "wallet-locks", default_timeout: float = 10.0):
        self.name = name
        self.default_timeout = default_timeout
        self._guard = threading.Lock()
        self._locks: dict = {}       # resource -> threading.Lock
        self._holder: dict = {}      # resource -> thread id that owns it
        self._held: dict = {}        # thread id -> [resources in acquisition order]
        self._waiting: dict = {}     # thread id -> resource it is blocked on
        self._names: dict = {}       # thread id -> readable name
        self._victims: set = set()
        self.stats = Counter()
        self.on_deadlock = None      # optional callback(info_dict)
        self._detector = None
        self._detector_stop = threading.Event()

    # ------------------------------------------------------------------ acquire / release
    def acquire(self, resource, timeout: float | None = None) -> None:
        me = threading.get_ident()
        deadline = time.monotonic() + (self.default_timeout if timeout is None else timeout)
        with self._guard:
            lock = self._locks.setdefault(resource, threading.Lock())
            self._names[me] = threading.current_thread().name
            if self._holder.get(resource) == me:
                raise RuntimeError(f"thread already holds lock {resource!r} (locks are not re-entrant)")
        if lock.acquire(blocking=False):
            self._record_acquired(me, resource)
            return
        self.stats["contended"] += 1
        with self._guard:
            self._waiting[me] = resource
        try:
            while True:
                if lock.acquire(timeout=self.POLL):
                    break
                with self._guard:
                    is_victim = me in self._victims
                    self._victims.discard(me)
                if is_victim:
                    self.stats["victims"] += 1
                    raise DeadlockVictim(f"{self._names[me]} was aborted to break a deadlock (waiting for {resource!r})")
                if time.monotonic() >= deadline:
                    self.stats["timeouts"] += 1
                    raise LockTimeout(f"timed out waiting for lock {resource!r}")
        finally:
            with self._guard:
                self._waiting.pop(me, None)
        self._record_acquired(me, resource)

    def _record_acquired(self, me, resource) -> None:
        with self._guard:
            self._holder[resource] = me
            self._held.setdefault(me, []).append(resource)
            self.stats["acquired"] += 1

    def release(self, resource) -> None:
        me = threading.get_ident()
        with self._guard:
            if self._holder.get(resource) != me:
                raise RuntimeError(f"thread does not hold lock {resource!r}")
            del self._holder[resource]
            held = self._held.get(me, [])
            held.remove(resource)
            if not held:
                self._held.pop(me, None)
            lock = self._locks[resource]
        lock.release()

    @contextmanager
    def hold(self, resources, ordered: bool = True, timeout: float | None = None):
        """Take several locks. ordered=True sorts them first (deadlock prevention)."""
        items = sorted(set(resources)) if ordered else list(dict.fromkeys(resources))
        got = []
        try:
            for r in items:
                self.acquire(r, timeout)
                got.append(r)
            yield items
        finally:
            for r in reversed(got):
                self.release(r)

    # ------------------------------------------------------------------ deadlock detection
    def wait_for_graph(self) -> dict:
        """{waiting thread: thread that holds the lock it wants}"""
        with self._guard:
            return {w: self._holder[r] for w, r in self._waiting.items()
                    if r in self._holder and self._holder[r] != w}

    def find_cycle(self):
        graph = self.wait_for_graph()
        for start in graph:
            path, node = [], start
            while node in graph and node not in path:
                path.append(node)
                node = graph[node]
            if node in path:
                return path[path.index(node):]
        return None

    def _describe(self, cycle) -> list:
        with self._guard:
            return [{"thread": self._names.get(t, str(t)),
                     "waits_for": f"wallet {self._waiting.get(t)}",
                     "held_by": self._names.get(self._holder.get(self._waiting.get(t)), "?")} for t in cycle]

    def break_deadlock(self, cycle):
        """Recovery: abort the cheapest victim (fewest locks held; ties -> newest thread)."""
        with self._guard:
            if any(t in self._victims for t in cycle):
                return None  # a victim was already chosen for this cycle
            victim = min(cycle, key=lambda t: (len(self._held.get(t, [])), -t))
            self._victims.add(victim)
            self.stats["deadlocks_resolved"] += 1
            return self._names.get(victim, str(victim))

    def start_detector(self, interval: float = 0.05) -> None:
        if self._detector and self._detector.is_alive():
            return
        self._detector_stop.clear()

        def loop():
            while not self._detector_stop.wait(interval):
                cycle = self.find_cycle()
                if not cycle:
                    continue
                info = {"cycle": self._describe(cycle)}
                victim = self.break_deadlock(cycle)
                if victim:
                    info["victim"] = victim
                    log.info("deadlock detected %s -> victim %s", info["cycle"], victim)
                    if self.on_deadlock:
                        try:
                            self.on_deadlock(info)
                        except Exception:  # never let a callback kill the detector
                            log.exception("on_deadlock callback failed")

        self._detector = threading.Thread(target=loop, name=f"{self.name}-detector", daemon=True)
        self._detector.start()

    def stop_detector(self) -> None:
        self._detector_stop.set()
        if self._detector:
            self._detector.join(timeout=1)

    def snapshot(self) -> dict:
        with self._guard:
            return {
                "name": self.name,
                "locks_known": len(self._locks),
                "held": [{"resource": r, "holder": self._names.get(t, str(t))} for r, t in self._holder.items()],
                "waiting": [{"thread": self._names.get(t, str(t)), "resource": r} for t, r in self._waiting.items()],
                "stats": dict(self.stats),
            }


# ---------------------------------------------------------------------- distributed lock (Redis)
class RedisLock:
    _RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"

    def __init__(self, client, key: str, ttl_ms: int = 15000):
        self.client, self.key, self.ttl_ms = client, key, ttl_ms
        self.token = uuid.uuid4().hex

    def acquire(self, timeout: float = 10.0) -> bool:
        """True = lock taken. False = Redis failed (we fail open: the local lock + DB lock still protect us)."""
        deadline = time.monotonic() + timeout
        try:
            while not self.client.set(self.key, self.token, nx=True, px=self.ttl_ms):
                if time.monotonic() >= deadline:
                    raise LockTimeout(f"timed out waiting for redis lock {self.key}")
                time.sleep(0.01)
            return True
        except LockTimeout:
            raise
        except Exception as exc:
            log.warning("redis lock unavailable (%s) - continuing with local locks only", exc.__class__.__name__)
            return False

    def release(self) -> None:
        try:
            self.client.eval(self._RELEASE, 1, self.key, self.token)  # only the owner (same token) can delete
        except Exception as exc:
            log.warning("redis lock release failed (%s)", exc.__class__.__name__)


class WalletLocks:
    """What the payment code uses: local thread locks (always) + Redis locks (when Redis is running)."""

    def __init__(self, local: LockManager, redis_client=None, ttl_ms: int = 15000):
        self.local, self.redis, self.ttl_ms = local, redis_client, ttl_ms

    @property
    def mode(self) -> str:
        return "threading.Lock + RedisLock" if self.redis is not None else "threading.Lock"

    @contextmanager
    def hold(self, wallet_ids, timeout: float = 10.0):
        ordered = sorted(set(wallet_ids))
        with self.local.hold(ordered, ordered=True, timeout=timeout):
            taken = []
            try:
                if self.redis is not None:
                    for wid in ordered:
                        lock = RedisLock(self.redis, f"wallet:lock:{wid}", self.ttl_ms)
                        if lock.acquire(timeout):
                            taken.append(lock)
                yield ordered
            finally:
                for lock in reversed(taken):
                    lock.release()
