import sqlite3
import threading

import pytest

from app.db import connect
from tests.conftest import Api, build_app


def users(api):
    a, ua = api.register("Asha Rao")
    b, ub = api.register("Bhavesh Kumar")
    return a, ua, b, ub


def test_register_login_me_and_errors(client, api):
    h, user = api.register("Asha Rao")
    assert user["wallet_code"] == "asha@swallet"
    assert client.get("/api/auth/me", headers=h).json["user"]["email"] == "asha.rao@t.test"
    assert client.get("/api/wallet").status_code == 401
    r = client.post("/api/auth/register", json={"full_name": "Asha Rao", "email": "asha.rao@t.test", "password": "Passw0rd1"})
    assert r.status_code == 409
    assert client.post("/api/auth/register", json={"full_name": "X Y", "email": "x@y.test", "password": "short"}).status_code == 400
    assert client.post("/api/auth/login", json={"email": "asha.rao@t.test", "password": "nope"}).status_code == 401
    ok = client.post("/api/auth/login", json={"email": "asha.rao@t.test", "password": "Passw0rd1"})
    assert ok.status_code == 200
    h2 = {"Authorization": "Bearer " + ok.json["token"]}
    assert client.post("/api/auth/logout", headers=h2).status_code == 200
    assert client.get("/api/wallet", headers=h2).status_code == 401           # token revoked


@pytest.mark.parametrize("bad", [0, -5, "abc", "10.123", "", None, "1e999"])
def test_amount_validation(client, api, bad):
    h, _ = api.register("Asha Rao")
    assert client.post("/api/wallet/topup", json={"amount": bad}, headers=h).status_code == 400


def test_transfer_is_double_entry_and_reconciles(client, api, app):
    a, _, b, _ = users(api)
    api.topup(a, 1000)
    r = api.pay(a, "bhavesh@swallet", 250.50, "chai")
    assert r.status_code == 201 and r.json["balance_paise"] == 74950
    assert api.balance(b) == 25050
    conn = connect(app.config["DB_PATH"])
    assert conn.execute("SELECT COUNT(*) FROM v_reconciliation WHERE diff_paise <> 0").fetchone()[0] == 0
    assert conn.execute("SELECT SUM(CASE direction WHEN 'CREDIT' THEN amount_paise ELSE -amount_paise END) "
                        "FROM ledger_entries WHERE txn_id = (SELECT MAX(txn_id) FROM transactions)").fetchone()[0] == 0
    assert app.extensions["wallet"].audit.verify()["ok"]


def test_insufficient_funds_is_recorded_as_failed(client, api):
    a, _, b, _ = users(api)
    api.topup(a, 100)
    r = api.pay(a, "bhavesh@swallet", 500)
    assert r.status_code == 409 and r.json["status"] == "FAILED"
    assert api.balance(a) == 10000 and api.balance(b) == 0
    hist = client.get("/api/transactions", headers=a).json["transactions"]
    assert hist[0]["status"] == "FAILED"
    assert client.get("/api/transactions", headers=b).json["total"] == 0       # recipient never sees failed attempts


def test_recipient_rules(client, api):
    a, ua, _, _ = users(api)
    api.topup(a, 500)
    assert api.pay(a, ua["wallet_code"], 10).status_code == 400                 # self transfer
    assert api.pay(a, "nobody@swallet", 10).status_code == 404


def test_otp_flow(client, api, app):
    a, _, b, _ = users(api)
    api.topup(a, 20000)
    r = api.pay(a, "bhavesh@swallet", 6000)
    assert r.status_code == 202 and r.json["status"] == "PENDING_OTP"
    ref, otp = r.json["txn_ref"], r.json["demo_otp"]
    assert api.balance(a) == 2000000                                              # nothing moved yet
    wrong = client.post("/api/wallet/transfer/confirm", json={"txn_ref": ref, "otp": "000000" if otp != "000000" else "111111"}, headers=a)
    assert wrong.status_code == 400 and wrong.json["attempts_left"] == 2          # a wrong OTP is not an expired login
    good = client.post("/api/wallet/transfer/confirm", json={"txn_ref": ref, "otp": otp}, headers=a)
    assert good.status_code == 201 and api.balance(a) == 1400000 and api.balance(b) == 600000
    again = client.post("/api/wallet/transfer/confirm", json={"txn_ref": ref, "otp": otp}, headers=a)
    assert again.json["already_processed"] and api.balance(a) == 1400000          # no double payment


def test_otp_lockout_and_expiry(client, api, app):
    a, _, _, _ = users(api)
    api.topup(a, 20000)
    ref = api.pay(a, "bhavesh@swallet", 6000).json["txn_ref"]
    for _ in range(2):
        client.post("/api/wallet/transfer/confirm", json={"txn_ref": ref, "otp": "12"}, headers=a)
    last = client.post("/api/wallet/transfer/confirm", json={"txn_ref": ref, "otp": "12"}, headers=a)
    assert last.status_code == 429 and last.json["code"] == "otp_locked"
    ref2 = api.pay(a, "bhavesh@swallet", 6000).json["txn_ref"]
    conn = connect(app.config["DB_PATH"])
    conn.execute("UPDATE otp_challenges SET expires_at = '2000-01-01T00:00:00.000Z'")
    assert client.post("/api/wallet/transfer/confirm", json={"txn_ref": ref2, "otp": "000000"}, headers=a).status_code == 410
    assert api.balance(a) == 2000000


def test_idempotency_key(client, api):
    a, _, b, _ = users(api)
    api.topup(a, 1000)
    first = api.pay(a, "bhavesh@swallet", 100, "lunch", key="k-1")
    second = api.pay(a, "bhavesh@swallet", 100, "lunch", key="k-1")
    assert first.status_code == 201 and second.status_code == 201
    assert first.json["txn_ref"] == second.json["txn_ref"] and second.headers["Idempotent-Replay"] == "true"
    assert api.balance(a) == 90000                                                # paid once, not twice
    assert api.pay(a, "bhavesh@swallet", 200, "lunch", key="k-1").status_code == 422   # same key, different body


def test_concurrent_same_idempotency_key_pays_once(app, api):
    a, _, _, _ = users(api)
    api.topup(a, 1000)
    codes = []

    def go():
        codes.append(Api(app.test_client()).pay(a, "bhavesh@swallet", 100, key="race").status_code)

    ts = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert api.balance(a) == 90000, codes


def test_daily_limit(client, api, app):
    a, _, _, _ = users(api)
    api.topup(a, 20000)
    connect(app.config["DB_PATH"]).execute("UPDATE wallets SET daily_limit_paise = 100000")
    assert api.pay(a, "bhavesh@swallet", 800).status_code == 201
    r = api.pay(a, "bhavesh@swallet", 300)
    assert r.status_code == 409 and "Daily limit" in r.json["message"]


def test_rate_limit(tmp_path):
    app = build_app(tmp_path, RATE_PAY_PER_MIN=3)
    c = app.test_client()
    api = Api(c)
    a, _ = api.register("Asha Rao")
    api.register("Bhavesh Kumar")
    api.topup(a, 1000)
    codes = [api.pay(a, "bhavesh@swallet", 1).status_code for _ in range(4)]
    assert codes[:2] == [201, 201] and codes[3] == 429


def test_ledger_is_append_only(app, api):
    a, _, _, _ = users(api)
    api.topup(a, 100)
    conn = connect(app.config["DB_PATH"])
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE ledger_entries SET amount_paise = 1")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM ledger_entries")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE wallets SET balance_paise = -1")                     # CHECK constraint


def test_frozen_user_cannot_pay(client, api, app):
    a, ua, _, _ = users(api)
    api.topup(a, 500)
    connect(app.config["DB_PATH"]).execute("UPDATE users SET status = 'frozen' WHERE user_id = ?", (ua["user_id"],))
    assert api.pay(a, "bhavesh@swallet", 10).status_code == 403


def test_blocked_payment_admin_review(client, api, app):
    cfg = app.config
    admin_h = {"Authorization": "Bearer " + client.post("/api/auth/register", json={"full_name": "Boss Admin", "email": "boss@t.test", "password": "Passw0rd1"}).json["token"]}
    connect(cfg["DB_PATH"]).execute("UPDATE users SET role = 'admin' WHERE email = 'boss@t.test'")
    a, _, b, _ = users(api)
    api.topup(a, 500)
    api.topup(a, 500)                                                              # Rs 1000 balance
    r = api.pay(a, "bhavesh@swallet", 990)                                         # drains the wallet to a brand-new account
    # force a HIGH decision regardless of ML randomness
    svc = app.extensions["wallet"]
    svc.fraud.high = 1
    r = api.pay(a, "bhavesh@swallet", 5)
    assert r.status_code == 403 and r.json["status"] == "BLOCKED" and r.json["risk"]["reasons"] is not None
    svc.fraud.high = 70
    alerts = client.get("/api/admin/alerts", headers=admin_h).json["alerts"]
    assert alerts and alerts[0]["review_status"] == "OPEN"
    before = api.balance(b)
    ok = client.post(f"/api/admin/alerts/{alerts[0]['alert_id']}/approve", headers=admin_h)
    assert ok.status_code in (200, 201) and api.balance(b) == before + 500
    assert client.get("/api/admin/reconcile", headers=admin_h).json["mismatches"] == []
    assert client.get("/api/admin/alerts", headers=a).status_code == 403          # normal users can't


def test_category_learning_and_csv(client, api):
    a, _, _, _ = users(api)
    api.topup(a, 1000)
    ref = api.pay(a, "bhavesh@swallet", 50, "=cmd|' /C calc'!A0").json["txn_ref"]
    assert client.patch(f"/api/transactions/{ref}/category", json={"category": "Education"}, headers=a).status_code == 200
    csv = client.get("/api/transactions/export.csv", headers=a).data.decode()
    assert "'=cmd" in csv and "\n=cmd" not in csv                                  # formula injection neutralised
    found = client.get("/api/transactions?q=cmd&direction=out", headers=a).json
    assert found["total"] == 1 and found["transactions"][0]["category"] == "Education"


def test_scheduled_payment_runs_once(client, api, app):
    a, _, b, _ = users(api)
    api.topup(a, 1000)
    r = client.post("/api/scheduled", json={"to": "bhavesh@swallet", "amount": 100, "note": "tuition", "in_seconds": 5, "priority": 2}, headers=a)
    assert r.status_code == 201
    conn = connect(app.config["DB_PATH"])
    conn.execute("UPDATE scheduled_payments SET next_run_at = '2000-01-01T00:00:00.000Z'")
    sched = app.extensions["wallet"].scheduler
    assert sched.run_pending_once() == 1 and sched.run_pending_once() == 0         # claimed exactly once
    assert api.balance(b) == 10000
    assert client.get("/api/scheduled", headers=a).json["scheduled"][0]["status"] == "DONE"
    big = client.post("/api/scheduled", json={"to": "bhavesh@swallet", "amount": 9000, "in_seconds": 60}, headers=a)
    assert big.status_code == 400                                                  # OTP-size payments can't be automated


def test_concurrent_opposite_transfers_conserve_money(app, api):
    a, _, b, _ = users(api)
    api.topup(a, 5000)
    api.topup(b, 5000)

    def go(h, to):
        c = Api(app.test_client())
        for _ in range(15):
            c.pay(h, to, 7)

    ts = [threading.Thread(target=go, args=(a, "bhavesh@swallet")), threading.Thread(target=go, args=(b, "asha@swallet")),
          threading.Thread(target=go, args=(a, "bhavesh@swallet")), threading.Thread(target=go, args=(b, "asha@swallet"))]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert api.balance(a) + api.balance(b) == 1_000_000
    conn = connect(app.config["DB_PATH"])
    assert conn.execute("SELECT COUNT(*) FROM v_reconciliation WHERE diff_paise <> 0").fetchone()[0] == 0
    assert app.extensions["wallet"].local_locks.find_cycle() is None


def test_receiver_does_not_see_pending_or_risk(client, api):
    a, _, b, _ = users(api)
    api.topup(a, 20000)
    api.pay(a, "bhavesh@swallet", 6000)                                            # stays PENDING_OTP
    assert client.get("/api/transactions", headers=b).json["total"] == 0
    out = client.get("/api/transactions", headers=a).json["transactions"][0]
    assert out["status"] == "PENDING_OTP" and "risk" in out


def test_payment_trace_and_contacts(client, api):
    a, _, b, _ = users(api)
    api.topup(a, 1000)
    r = api.pay(a, "bhavesh@swallet", 100, "chai", key="trace-1")
    steps = r.json["trace"]
    assert {"API", "AI", "OS", "DBMS", "CACHE", "FILE"} <= {s["layer"] for s in steps}
    titles = [s["title"] for s in steps]
    assert titles.index("BEGIN IMMEDIATE") < titles.index("COMMIT") < titles.index("Wallet locks released")
    assert api.pay(a, "bhavesh@swallet", 100, "chai", key="trace-1").json["trace"] == steps      # a replay returns the stored answer
    contacts = client.get("/api/recipients/recent", headers=a).json["contacts"]
    assert contacts[0]["wallet_code"] == "bhavesh@swallet" and contacts[0]["paid"] and not contacts[0]["merchant"]
    assert client.get("/api/recipients/recent", headers=b).json["contacts"][0]["wallet_code"] == "asha@swallet"
    ref = r.json["txn_ref"]
    assert [x["status"] for x in client.get(f"/api/transactions/{ref}/timeline", headers=a).json["timeline"]] == ["PENDING", "SUCCESS"]
    assert [x["status"] for x in client.get(f"/api/transactions/{ref}/timeline", headers=b).json["timeline"]] == ["SUCCESS"]
    assert client.get("/api/transactions/NOPE/timeline", headers=a).status_code == 404


def test_trace_for_otp_and_held_payments(client, api, app):
    a, _, _, _ = users(api)
    api.topup(a, 20000)
    pending = api.pay(a, "bhavesh@swallet", 6000)
    assert any(s["title"] == "OTP required" for s in pending.json["trace"])
    done = client.post("/api/wallet/transfer/confirm", json={"txn_ref": pending.json["txn_ref"], "otp": pending.json["demo_otp"]}, headers=a)
    titles = [s["title"] for s in done.json["trace"]]
    assert titles[0] == "OTP verified" and "COMMIT" in titles
    app.extensions["wallet"].fraud.high = 1
    held = api.pay(a, "bhavesh@swallet", 5)
    app.extensions["wallet"].fraud.high = 70
    assert held.status_code == 403 and any(s["title"] == "Payment held for review" for s in held.json["trace"])


def test_merchant_directory(seeded):
    c = seeded.test_client()
    h = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "aarav@wallet.test", "password": "Demo@1234"}).json["token"]}
    names = [m["name"] for m in c.get("/api/merchants", headers=h).json["merchants"]]
    assert "Swiggy" in names and "Aarav Sharma" not in names                  # only merchants are listed publicly
    recent = c.get("/api/recipients/recent", headers=h).json["contacts"]
    assert any(x["merchant"] for x in recent) and any(not x["merchant"] for x in recent)
    ref = c.get("/api/transactions?limit=1", headers=h).json["transactions"][0]["txn_ref"]
    tl = c.get(f"/api/transactions/{ref}/timeline", headers=h).json["timeline"]
    assert tl and tl[-1]["status"] == "SUCCESS" and tl[-1]["at"][:4] == "2026"
