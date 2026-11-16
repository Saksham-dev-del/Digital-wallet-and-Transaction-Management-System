import csv
import io

from flask import Blueprint, Response, g, jsonify, request

from ..deps import auth_required, body, get_db, svc
from ..services import queries
from ..services.ledger import run_idempotent
from ..services.trace import Trace
from datetime import timedelta

from ..util import WalletError, clean_note, iso, parse_iso, to_paise, utcnow

bp = Blueprint("wallet", __name__, url_prefix="/api")
HTTP = {"SUCCESS": 201, "PENDING_OTP": 202, "BLOCKED": 403, "FAILED": 409}


def _pay_limit() -> int:
    s = svc()
    return s.limiter.enforce("pay", g.user["user_id"], s.cfg["RATE_PAY_PER_MIN"], 60)


def _respond(res, status, replay=False):
    out = jsonify({"ok": res.get("status") in ("SUCCESS", "PENDING_OTP"), **res})
    out.status_code = status
    if replay:
        out.headers["Idempotent-Replay"] = "true"
    return out


def _money_move(endpoint, kind, payload, **kwargs):
    s, conn = svc(), get_db()
    trace = Trace()
    trace.add("API", "Rate limit checked", f"{_pay_limit()} more requests allowed this minute")
    key = request.headers.get("Idempotency-Key")

    def run():
        trace.add("API", "Idempotency key stored" if key else "No idempotency key sent",
                  f"key {key[:8]}...: a retry replays this answer" if key else "a network retry could pay twice")
        res = s.wallet.submit(conn, g.user, kind=kind, trace=trace, **kwargs)
        return res, HTTP.get(res["status"], 200)

    res, status, replay = run_idempotent(conn, g.user["user_id"], key, endpoint, payload, run)
    return _respond(res, status, replay)


@bp.get("/wallet")
@auth_required()
def wallet_summary():
    return jsonify({"ok": True, **svc().wallet.summary(get_db(), g.user)})


@bp.post("/wallet/topup")
@auth_required()
def topup():
    data = body()
    amount = to_paise(data.get("amount"))
    return _money_move("topup", "TOPUP", {"amount": amount}, amount_paise=amount)


@bp.post("/wallet/withdraw")
@auth_required()
def withdraw():
    data = body()
    amount = to_paise(data.get("amount"))
    return _money_move("withdraw", "WITHDRAW", {"amount": amount}, amount_paise=amount)


@bp.post("/wallet/transfer/preview")
@auth_required()
def preview():
    s, data = svc(), body()
    s.limiter.enforce("preview", g.user["user_id"], 40, 60)
    amount = to_paise(data.get("amount"))
    kind = "WITHDRAW" if data.get("kind") == "WITHDRAW" else "TRANSFER"
    return jsonify({"ok": True, **s.wallet.preview(get_db(), g.user, data.get("to"), amount, data.get("note", ""), kind)})


@bp.post("/wallet/transfer")
@auth_required()
def transfer():
    data = body()
    amount, to = to_paise(data.get("amount")), str(data.get("to", "")).strip()
    note, category = clean_note(data.get("note")), data.get("category") or None
    payload = {"to": to.lower(), "amount": amount, "note": note, "category": category}
    return _money_move("transfer", "TRANSFER", payload, amount_paise=amount, to_ident=to, note=note, category=category)


@bp.post("/wallet/transfer/confirm")
@auth_required()
def confirm():
    s, data = svc(), body()
    _pay_limit()
    res = s.wallet.confirm_otp(get_db(), g.user, str(data.get("txn_ref", "")), str(data.get("otp", "")))
    return _respond(res, HTTP.get(res["status"], 200))


@bp.get("/recipients/lookup")
@auth_required()
def lookup():
    s = svc()
    s.limiter.enforce("lookup", g.user["user_id"], s.cfg["RATE_LOOKUP_PER_MIN"], 60)
    r = s.wallet.find_recipient(get_db(), request.args.get("q", ""))
    if r["user_id"] == g.user["user_id"]:
        raise WalletError("That's your own wallet.", "self_transfer")
    return jsonify({"ok": True, "name": r["full_name"], "wallet_code": r["wallet_code"],
                    "merchant": r["account_type"] == "MERCHANT"})


def _filters():
    a = request.args
    return dict(type_=a.get("type"), direction=a.get("direction"), category=a.get("category"), status=a.get("status"),
                q=a.get("q"), date_from=a.get("from"), date_to=a.get("to"))


@bp.get("/transactions")
@auth_required()
def transactions():
    conn, s = get_db(), svc()
    w = s.wallet.wallet_of(conn, g.user["user_id"])
    rows, total = queries.list_transactions(conn, w["wallet_id"], s.cfg["TZ_OFFSET_MINUTES"], limit=request.args.get("limit", 50),
                                            offset=request.args.get("offset", 0), **_filters())
    return jsonify({"ok": True, "transactions": rows, "total": total})


def _csv_safe(v):
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v        # stop spreadsheet formula injection


@bp.get("/transactions/export.csv")
@auth_required()
def export_csv():
    conn, s = get_db(), svc()
    w = s.wallet.wallet_of(conn, g.user["user_id"])
    rows, _ = queries.list_transactions(conn, w["wallet_id"], s.cfg["TZ_OFFSET_MINUTES"], limit=500, **_filters())
    buf = io.StringIO()
    out = csv.writer(buf)
    out.writerow(["Date (UTC)", "Reference", "Type", "Direction", "Amount (INR)", "Balance after (INR)", "Category",
                  "Counterparty", "Note", "Status"])
    for t in rows:
        out.writerow([t["created_at"], t["txn_ref"], t["type"], t["direction"], f"{t['amount_paise'] / 100:.2f}",
                      "" if t["balance_after_paise"] is None else f"{t['balance_after_paise'] / 100:.2f}", t["category"],
                      _csv_safe((t["counterparty"] or {}).get("name")), _csv_safe(t["note"]), t["status"]])
    s.audit.append("statement.exported", g.user["user_id"], {"rows": len(rows)})
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=wallet-statement.csv"})


@bp.get("/recipients/recent")
@auth_required()
def recent_people():
    conn = get_db()
    w = svc().wallet.wallet_of(conn, g.user["user_id"])
    return jsonify({"ok": True, "contacts": queries.recent_contacts(conn, w["wallet_id"])})


@bp.get("/merchants")
@auth_required()
def merchant_list():
    return jsonify({"ok": True, "merchants": queries.merchants(get_db())})


@bp.get("/transactions/<ref>/timeline")
@auth_required()
def timeline(ref):
    conn = get_db()
    w = svc().wallet.wallet_of(conn, g.user["user_id"])
    steps = queries.txn_timeline(conn, w["wallet_id"], ref)
    if steps is None:
        raise WalletError("Transaction not found.", "txn_not_found", 404)
    return jsonify({"ok": True, "timeline": steps})


@bp.get("/transactions/<ref>")
@auth_required()
def one(ref):
    conn = get_db()
    w = svc().wallet.wallet_of(conn, g.user["user_id"])
    t = queries.get_transaction(conn, w["wallet_id"], ref)
    if t is None:
        raise WalletError("Transaction not found.", "txn_not_found", 404)
    return jsonify({"ok": True, "transaction": t})


@bp.patch("/transactions/<ref>/category")
@auth_required()
def recategorize(ref):
    s, conn, data = svc(), get_db(), body()
    cat = str(data.get("category", ""))
    if cat not in s.categorizer.counts:
        raise WalletError("Choose one of the listed categories.", "bad_category")
    w = s.wallet.wallet_of(conn, g.user["user_id"])
    t = conn.execute("SELECT t.txn_id, t.note, u.full_name FROM transactions t JOIN wallets cw ON cw.wallet_id = t.to_wallet_id "
                     "JOIN users u ON u.user_id = cw.user_id WHERE t.txn_ref = ? AND t.from_wallet_id = ? AND t.txn_type = 'TRANSFER'",
                     (ref, w["wallet_id"])).fetchone()
    if t is None:
        raise WalletError("You can only re-categorise payments you sent.", "txn_not_found", 404)
    conn.execute("UPDATE transactions SET category = ? WHERE txn_id = ?", (cat, t["txn_id"]))
    text = f"{t['note']} {t['full_name']}".strip()
    conn.execute("INSERT INTO category_feedback (user_id, text, category) VALUES (?,?,?)", (g.user["user_id"], text, cat))
    s.categorizer.learn(text, cat)                                  # the AI learns from the correction immediately
    return jsonify({"ok": True, "category": cat, "learned_from": text})


@bp.get("/categories")
def categories():
    from ..ai.categorizer import CATEGORIES
    return jsonify({"ok": True, "categories": CATEGORIES})


# ---------------------------------------------------------------- scheduled payments
@bp.get("/scheduled")
@auth_required()
def scheduled_list():
    rows = get_db().execute(
        "SELECT s.*, u.full_name, w.wallet_code FROM scheduled_payments s JOIN wallets w ON w.wallet_id = s.to_wallet_id "
        "JOIN users u ON u.user_id = w.user_id WHERE s.user_id = ? ORDER BY s.status = 'CANCELLED', s.next_run_at LIMIT 100",
        (g.user["user_id"],)).fetchall()
    return jsonify({"ok": True, "scheduled": [{
        "sched_id": r["sched_id"], "to_name": r["full_name"], "to_code": r["wallet_code"], "amount_paise": r["amount_paise"],
        "note": r["note"], "category": r["category"], "priority": r["priority"], "frequency": r["frequency"],
        "next_run_at": r["next_run_at"], "status": r["status"], "last_result": r["last_result"], "run_count": r["run_count"]}
        for r in rows]})


@bp.post("/scheduled")
@auth_required()
def scheduled_create():
    s, conn, data = svc(), get_db(), body()
    _pay_limit()
    amount = to_paise(data.get("amount"))
    if data.get("in_seconds") not in (None, ""):
        try:
            when = iso(utcnow().replace(microsecond=0) + timedelta(seconds=max(5, min(int(data["in_seconds"]), 86400 * 30))))
        except (TypeError, ValueError):
            raise WalletError("in_seconds must be a number.", "bad_time")
    else:
        try:
            when = iso(parse_iso(str(data.get("run_at", ""))))
        except ValueError:
            raise WalletError("Pick a date and time for the payment.", "bad_time")
    try:
        priority = max(1, min(int(data.get("priority", 5)), 9))
    except (TypeError, ValueError):
        priority = 5
    res = s.wallet.create_schedule(conn, g.user, to_ident=str(data.get("to", "")), amount_paise=amount, note=data.get("note", ""),
                                   category=data.get("category"), frequency=str(data.get("frequency", "ONCE")).upper(),
                                   run_at=when, priority=priority)
    return jsonify({"ok": True, **res, "next_run_at": when}), 201


@bp.delete("/scheduled/<int:sched_id>")
@auth_required()
def scheduled_cancel(sched_id):
    cur = get_db().execute("UPDATE scheduled_payments SET status = 'CANCELLED' WHERE sched_id = ? AND user_id = ? "
                           "AND status = 'ACTIVE'", (sched_id, g.user["user_id"]))
    if cur.rowcount != 1:
        raise WalletError("That scheduled payment can't be cancelled (it may have already run).", "not_cancellable", 409)
    return jsonify({"ok": True})
