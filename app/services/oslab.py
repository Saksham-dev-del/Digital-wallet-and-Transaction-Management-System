"""Live OS demonstrations used by the OS Lab tab: deadlock demo, concurrency stress test, system + file info, backups."""
import os
import platform
import random
import sqlite3
import stat
import sys
import tempfile
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ..db import connect, init_db, tx
from ..util import WalletError, iso, utcnow
from .ledger import apply_txn, insert_txn
from .locks import DeadlockVictim, LockManager, LockTimeout

STARTED_AT = time.time()


# ====================================================================== deadlock demo
def deadlock_demo(mode: str = "naive") -> dict:
    """Two transfers want the same two wallets in opposite order.
    naive   -> each takes its 'from' wallet first  -> circular wait -> deadlock -> detector aborts a victim -> retry
    ordered -> both take the lower wallet id first  -> no circular wait -> no deadlock (prevention)"""
    mode = "ordered" if mode == "ordered" else "naive"
    lm = LockManager("demo-locks", default_timeout=5.0)
    t0, events, ev_lock = time.monotonic(), [], threading.Lock()
    summary = {"detected": False, "victim": None, "cycle": None}

    def log_ev(thread, kind, text):
        with ev_lock:
            events.append({"t_ms": int((time.monotonic() - t0) * 1000), "thread": thread, "kind": kind, "text": text})

    def on_deadlock(info):
        summary.update(detected=True, victim=info["victim"], cycle=info["cycle"])
        log_ev("detector", "deadlock", "Deadlock found in the wait-for graph: " + ", ".join(
            f"{c['thread']} waits for {c['waits_for']} held by {c['held_by']}" for c in info["cycle"]))
        log_ev("detector", "recovery", f"Recovery: abort {info['victim']} (fewest locks held = cheapest to roll back)")

    lm.on_deadlock = on_deadlock
    lm.start_detector(0.03)
    barrier = threading.Barrier(2)

    def transfer(name, src, dst):
        order = [src, dst] if mode == "naive" else sorted([src, dst])
        barrier.wait()
        for _attempt in range(3):
            held = []
            try:
                for i, w in enumerate(order):
                    log_ev(name, "request", f"asks for the lock on wallet {w}")
                    lm.acquire(w)
                    held.append(w)
                    log_ev(name, "acquired", f"now holds wallet {w}")
                    if i == 0:
                        time.sleep(0.25)            # checks the balance while holding the first lock
                time.sleep(0.05)
                log_ev(name, "commit", f"transfer wallet {src} -> {dst} committed")
                return
            except DeadlockVictim:
                log_ev(name, "abort", "chosen as the victim: rolls back and gives up its lock")
                order = sorted([src, dst])
            except LockTimeout:
                log_ev(name, "timeout", "gave up waiting (timeout)")
                return
            finally:
                for w in reversed(held):
                    lm.release(w)
                    log_ev(name, "release", f"released wallet {w}")
            time.sleep(0.08)
            log_ev(name, "retry", "retries, this time taking locks in ascending wallet order")

    threads = [threading.Thread(target=transfer, args=("txn-A", 1, 2), name="txn-A"),
               threading.Thread(target=transfer, args=("txn-B", 2, 1), name="txn-B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    lm.stop_detector()
    events.sort(key=lambda e: e["t_ms"])
    outcome = ("Deadlock detected and recovered: the victim retried with ordered locking and both transfers finished."
               if summary["detected"] else
               "No deadlock. Taking locks in ascending wallet order makes a circular wait impossible, so one transfer simply waited for the other.")
    return {"mode": mode, "events": events, "deadlock_detected": summary["detected"], "victim": summary["victim"],
            "cycle": summary["cycle"], "total_ms": events[-1]["t_ms"] if events else 0, "outcome": outcome,
            "lock_stats": dict(lm.stats)}


# ====================================================================== stress test
def stress_test(threads: int = 8, ops: int = 40, wallets: int = 6, ordered: bool = True) -> dict:
    """Many threads move money between a few wallets in a throw-away database.
    Proof of correctness = the total money never changes and every wallet equals the sum of its ledger."""
    threads, ops, wallets = max(2, min(int(threads), 16)), max(1, min(int(ops), 100)), max(2, min(int(wallets), 10))
    start_balance = 10_000_00
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "stress.db")
        init_db(path)
        conn = connect(path)
        ids = []
        for i in range(wallets):
            uid = conn.execute("INSERT INTO users (full_name, email, password_hash) VALUES (?,?,?)",
                               (f"Stress {i}", f"s{i}@test.local", "x")).lastrowid
            wid = conn.execute("INSERT INTO wallets (user_id, wallet_code, balance_paise) VALUES (?,?,0)",
                               (uid, f"s{i}@swallet")).lastrowid
            with tx(conn):
                t = insert_txn(conn, txn_type="TOPUP", amount_paise=start_balance, to_wallet_id=wid, note="seed", category="Top-up")
                apply_txn(conn, t["txn_id"])
            ids.append(wid)
        lm = LockManager("stress-locks", default_timeout=3.0)
        lm.start_detector(0.03)
        counters, clock = Counter(), threading.Lock()

        def bump(name):
            with clock:
                counters[name] += 1

        def worker(seed):
            c, rnd = connect(path), random.Random(seed)
            try:
                for _ in range(ops):
                    a, b = rnd.sample(ids, 2)
                    amt = rnd.randint(1, 400) * 100
                    for _attempt in range(3):
                        try:
                            with lm.hold([a, b], ordered=ordered, timeout=3.0):
                                with tx(c):
                                    t = insert_txn(c, txn_type="TRANSFER", amount_paise=amt, from_wallet_id=a, to_wallet_id=b,
                                                   note="stress", category="Other")
                                    apply_txn(c, t["txn_id"])
                            bump("committed")
                            break
                        except WalletError:
                            bump("declined_insufficient_funds")
                            break
                        except DeadlockVictim:
                            bump("deadlock_victim_retries")
                            time.sleep(0.01)
                        except LockTimeout:
                            bump("lock_timeouts")
                            break
                        except sqlite3.OperationalError:
                            bump("db_busy")
                            break
                    else:
                        bump("gave_up_after_3_deadlocks")
            finally:
                c.close()

        t0 = time.perf_counter()
        pool = [threading.Thread(target=worker, args=(i,), name=f"worker-{i + 1}") for i in range(threads)]
        for t in pool:
            t.start()
        for t in pool:
            t.join(timeout=60)
        elapsed = time.perf_counter() - t0
        lm.stop_detector()
        total_after = conn.execute("SELECT SUM(balance_paise) FROM wallets").fetchone()[0]
        mismatches = conn.execute("SELECT COUNT(*) FROM v_reconciliation WHERE diff_paise <> 0").fetchone()[0]
        entries = conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
        conn.close()
    committed = counters["committed"]
    return {"threads": threads, "ops_per_thread": ops, "wallets": wallets,
            "lock_order": "ascending wallet id (safe)" if ordered else "request order (deadlock-prone)",
            "attempted": threads * ops, "committed": committed, "counters": dict(counters),
            "deadlocks_resolved": lm.stats["deadlocks_resolved"], "elapsed_s": round(elapsed, 3),
            "transfers_per_second": round(committed / elapsed, 1) if elapsed else None,
            "money_before_paise": wallets * start_balance, "money_after_paise": total_after,
            "money_conserved": total_after == wallets * start_balance,
            "ledger_entries": entries, "ledger_consistent": entries == wallets + 2 * committed,
            "reconciliation_mismatches": mismatches, "lock_stats": dict(lm.stats)}


# ====================================================================== system + files
def system_info() -> dict:
    info = {"pid": os.getpid(), "platform": platform.platform(), "python": platform.python_version(),
            "cpu_count": os.cpu_count(), "uptime_s": int(time.time() - STARTED_AT),
            "threads": [{"name": t.name, "daemon": t.daemon} for t in threading.enumerate()]}
    try:
        info["load_average"] = [round(x, 2) for x in os.getloadavg()]
    except (AttributeError, OSError):
        info["load_average"] = None
    try:
        import resource
        ru = resource.getrusage(resource.RUSAGE_SELF)
        info["peak_memory_mb"] = round(ru.ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)
        info["cpu_time_s"] = round(ru.ru_utime + ru.ru_stime, 2)
    except ImportError:
        info["peak_memory_mb"] = info["cpu_time_s"] = None
    try:
        info["open_file_descriptors"] = len(os.listdir("/proc/self/fd"))
    except OSError:
        info["open_file_descriptors"] = None
    return info


def file_facts(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"name": p.name, "exists": False}
    st = p.stat()
    return {"name": p.name, "exists": True, "size_bytes": st.st_size, "permissions": stat.filemode(st.st_mode),
            "inode": st.st_ino, "hard_links": st.st_nlink,
            "modified": iso(datetime.fromtimestamp(st.st_mtime, timezone.utc))}


def data_files(data_dir) -> list:
    d = Path(data_dir)
    return [file_facts(p) for p in sorted(d.iterdir()) if p.is_file()] if d.exists() else []


def create_backup(db_path, backup_dir, keep: int = 10) -> dict:
    """SQLite online-backup API: a consistent snapshot while the app keeps serving requests."""
    folder = Path(backup_dir)
    folder.mkdir(parents=True, exist_ok=True)
    now = utcnow()
    dest = folder / f"wallet-{now.strftime('%Y%m%d-%H%M%S')}-{now.microsecond // 1000:03d}.db"
    src, dst = sqlite3.connect(db_path), sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    check = sqlite3.connect(dest)
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    old = sorted(folder.glob("wallet-*.db"))[:-keep]
    for f in old:
        f.unlink(missing_ok=True)
    return {"name": dest.name, "size_bytes": dest.stat().st_size, "integrity_check": integrity, "pruned": len(old)}


def list_backups(backup_dir) -> list:
    folder = Path(backup_dir)
    return [file_facts(p) for p in sorted(folder.glob("wallet-*.db"), reverse=True)] if folder.exists() else []
