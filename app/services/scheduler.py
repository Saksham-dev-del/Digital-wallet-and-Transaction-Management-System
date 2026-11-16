"""Payment scheduler - the process-management part of the project.

Producer / consumer pattern:
   dispatcher thread  --(due payments)-->  PriorityQueue  --->  N worker threads  --->  WalletService
* PriorityQueue orders by (priority, arrival order): priority 1 runs before 9, equal priority = FCFS.
* A payment is *claimed* with one atomic UPDATE (ACTIVE -> RUNNING) so it can never run twice.
* Workers are daemon threads that wait on queue.get() (a blocking, semaphore-like wait: no CPU burnt while idle).
"""
import itertools
import logging
import queue
import threading
import time
from collections import Counter

from ..db import connect
from ..util import iso

log = logging.getLogger("wallet.scheduler")


class PaymentScheduler:
    def __init__(self, db_path: str, service, workers: int = 3, poll_seconds: float = 2.0):
        self.db_path, self.service, self.n_workers, self.poll = db_path, service, workers, poll_seconds
        self.queue: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = itertools.count()
        self._stop = threading.Event()
        self._threads: list = []
        self._lock = threading.Lock()
        self.stats = Counter()
        self.per_worker = Counter()
        self._wait_ms: list = []
        self.running = False

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self.running:
            return
        conn = connect(self.db_path)
        try:  # crash recovery: anything left RUNNING by a previous process goes back to ACTIVE
            conn.execute("UPDATE scheduled_payments SET status = 'ACTIVE' WHERE status = 'RUNNING'")
        finally:
            conn.close()
        self._stop.clear()
        self._threads = [threading.Thread(target=self._dispatcher, name="sched-dispatcher", daemon=True)]
        self._threads += [threading.Thread(target=self._worker, name=f"sched-worker-{i + 1}", daemon=True)
                          for i in range(self.n_workers)]
        for t in self._threads:
            t.start()
        self.running = True
        log.info("scheduler started: 1 dispatcher + %d workers", self.n_workers)

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)
        self.running = False

    # ------------------------------------------------------------------ producer
    def enqueue_due(self) -> int:
        conn = connect(self.db_path)
        try:
            due = conn.execute("SELECT sched_id, priority FROM scheduled_payments WHERE status = 'ACTIVE' AND next_run_at <= ? "
                               "ORDER BY priority, next_run_at LIMIT 50", (iso(),)).fetchall()
            claimed = 0
            for r in due:
                cur = conn.execute("UPDATE scheduled_payments SET status = 'RUNNING' WHERE sched_id = ? AND status = 'ACTIVE'",
                                   (r["sched_id"],))
                if cur.rowcount == 1:                     # we won the claim
                    self.queue.put((r["priority"], next(self._seq), time.monotonic(), r["sched_id"]))
                    claimed += 1
            self.stats["enqueued"] += claimed
            return claimed
        finally:
            conn.close()

    def _dispatcher(self) -> None:
        while not self._stop.wait(self.poll):
            try:
                self.enqueue_due()
            except Exception:
                log.exception("dispatcher error")

    # ------------------------------------------------------------------ consumers
    def _run_one(self, conn, item, worker_name) -> None:
        priority, _, enqueued_at, sched_id = item
        waited = (time.monotonic() - enqueued_at) * 1000
        try:
            res = self.service.run_schedule(conn, sched_id)
            with self._lock:
                self.stats["succeeded" if res["ok"] else "failed"] += 1
        except Exception as exc:
            log.exception("scheduled payment %s crashed", sched_id)
            conn.execute("UPDATE scheduled_payments SET status = 'FAILED', last_result = ? WHERE sched_id = ?",
                         (f"crashed: {exc.__class__.__name__}", sched_id))
            with self._lock:
                self.stats["failed"] += 1
        with self._lock:
            self.per_worker[worker_name] += 1
            self._wait_ms = (self._wait_ms + [waited])[-200:]

    def _worker(self) -> None:
        name = threading.current_thread().name
        conn = connect(self.db_path)
        try:
            while not self._stop.is_set():
                try:
                    item = self.queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                try:
                    self._run_one(conn, item, name)
                finally:
                    self.queue.task_done()
        finally:
            conn.close()

    def run_pending_once(self) -> int:
        """Synchronous variant used by tests: claim everything due and process it on the calling thread."""
        n = self.enqueue_due()
        conn = connect(self.db_path)
        try:
            while True:
                try:
                    item = self.queue.get_nowait()
                except queue.Empty:
                    break
                self._run_one(conn, item, "inline")
                self.queue.task_done()
        finally:
            conn.close()
        return n

    def snapshot(self) -> dict:
        with self.queue.mutex:
            waiting = sorted(self.queue.queue)
        with self._lock:
            avg = round(sum(self._wait_ms) / len(self._wait_ms), 1) if self._wait_ms else None
            return {"running": self.running, "workers": self.n_workers, "poll_seconds": self.poll,
                    "queue_length": len(waiting), "queued_ids": [w[3] for w in waiting][:10],
                    "stats": dict(self.stats), "per_worker": dict(self.per_worker), "avg_queue_wait_ms": avg,
                    "policy": "Priority scheduling: 1 = most urgent, first-come-first-served within the same priority"}
