import threading
import time

from app.services.audit import AuditLog
from app.services.cache import LRUCache
from app.services.locks import DeadlockVictim, LockManager, LockTimeout
from app.services.oslab import deadlock_demo, stress_test


def test_ordered_locking_never_deadlocks():
    lm = LockManager("t", 5)
    done = []

    def worker(a, b):
        for _ in range(50):
            with lm.hold([a, b], ordered=True):
                pass
        done.append(1)

    ts = [threading.Thread(target=worker, args=(1, 2)), threading.Thread(target=worker, args=(2, 1))]
    [t.start() for t in ts]
    [t.join(10) for t in ts]
    assert len(done) == 2 and lm.stats["timeouts"] == 0


def test_detector_breaks_a_real_deadlock():
    lm = LockManager("t", 5)
    lm.start_detector(0.02)
    out = {}

    def w(name, first, second):
        try:
            lm.acquire(first)
            time.sleep(0.15)
            lm.acquire(second)
            out[name] = "ok"
            lm.release(second)
            lm.release(first)
        except DeadlockVictim:
            out[name] = "victim"
            lm.release(first)

    ts = [threading.Thread(target=w, args=("A", 1, 2), name="A"), threading.Thread(target=w, args=("B", 2, 1), name="B")]
    [t.start() for t in ts]
    [t.join(10) for t in ts]
    lm.stop_detector()
    assert sorted(out.values()) == ["ok", "victim"] and lm.stats["deadlocks_resolved"] == 1


def test_lock_timeout():
    lm = LockManager("t", 0.1)
    lm.acquire("x")
    err = []

    def other_thread():
        try:
            lm.acquire("x", 0.1)
        except LockTimeout:
            err.append("timeout")

    t = threading.Thread(target=other_thread)
    t.start()
    t.join()
    assert err == ["timeout"] and lm.stats["timeouts"] == 1


def test_lru_evicts_least_recently_used():
    c = LRUCache(2, 30)
    c.set("a", 1); c.set("b", 2); c.get("a"); c.set("c", 3)
    assert c.get("b") is None and c.get("a") == 1 and c.get("c") == 3 and c.stats()["evictions"] == 1


def test_deadlock_demo_modes():
    naive, ordered = deadlock_demo("naive"), deadlock_demo("ordered")
    assert naive["deadlock_detected"] and naive["victim"] and any(e["kind"] == "commit" for e in naive["events"])
    assert sum(e["kind"] == "commit" for e in naive["events"]) == 2
    assert not ordered["deadlock_detected"] and sum(e["kind"] == "commit" for e in ordered["events"]) == 2


def test_stress_test_conserves_money():
    safe = stress_test(8, 25, 5, True)
    assert safe["money_conserved"] and safe["ledger_consistent"] and safe["reconciliation_mismatches"] == 0
    assert safe["committed"] == safe["attempted"] and safe["deadlocks_resolved"] == 0
    unsafe = stress_test(6, 15, 3, False)
    assert unsafe["money_conserved"] and unsafe["ledger_consistent"] and unsafe["reconciliation_mismatches"] == 0


def test_audit_chain_detects_tampering(tmp_path):
    log = AuditLog(str(tmp_path / "a.log"))
    for i in range(6):
        log.append("evt", 1, {"amount_paise": 100 * i})
    assert log.verify()["ok"] and log.verify()["entries"] == 6
    assert AuditLog(str(tmp_path / "a.log")).append("more")["seq"] == 7          # chain continues after a restart
    assert log.tamper_demo()["caught"] and log.verify()["ok"]                     # the real file is untouched
    lines = (tmp_path / "a.log").read_text().splitlines()
    (tmp_path / "a.log").write_text("\n".join(lines[:2] + lines[3:]) + "\n")      # delete one line
    assert not AuditLog.verify_file(tmp_path / "a.log")["ok"]


def test_backup_and_os_api(seeded):
    c = seeded.test_client()
    admin = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@wallet.test", "password": "Admin@123"}).json["token"]}
    user = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "aarav@wallet.test", "password": "Demo@1234"}).json["token"]}
    b = c.post("/api/os/backup", headers=admin).json
    assert b["integrity_check"] == "ok" and c.get("/api/os/files", headers=admin).json["backups"]
    assert c.post("/api/os/backup", headers=user).status_code == 403
    ov = c.get("/api/os/overview", headers=user).json
    assert ov["system"]["pid"] and ov["cache"]["kind"] and "locks" in ov
    paging = c.post("/api/os/paging", json={"refs": "7 0 1 2 0 3 0 4", "frames": 3}, headers=user).json
    assert set(paging["results"]) == {"FIFO", "LRU", "OPT"}
    assert c.post("/api/os/cpu", json={"jobs": [], "policy": "RR"}, headers=user).status_code == 400
