import json

from flask import Blueprint, g, jsonify

from ..ai.fraud import training_contexts
from ..deps import auth_required, get_db, svc
from ..util import WalletError, iso, utcnow
from datetime import timedelta

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


@bp.get("/overview")
@auth_required(admin=True)
def overview():
    conn = get_db()
    since = iso(utcnow() - timedelta(hours=24))
    q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
    statuses = {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM transactions GROUP BY status")}
    return jsonify({"ok": True,
                    "users": q("SELECT COUNT(*) FROM users WHERE account_type = 'PERSONAL'"),
                    "merchants": q("SELECT COUNT(*) FROM users WHERE account_type = 'MERCHANT'"),
                    "money_in_wallets_paise": q("SELECT COALESCE(SUM(balance_paise),0) FROM wallets"),
                    "volume_24h_paise": q("SELECT COALESCE(SUM(amount_paise),0) FROM transactions WHERE status = 'SUCCESS' "
                                          "AND txn_type = 'TRANSFER' AND created_at >= ?", since),
                    "txn_24h": q("SELECT COUNT(*) FROM transactions WHERE created_at >= ?", since),
                    "status_counts": statuses,
                    "open_alerts": q("SELECT COUNT(*) FROM fraud_alerts WHERE review_status = 'OPEN'")})


@bp.get("/alerts")
@auth_required(admin=True)
def alerts():
    rows = get_db().execute(
        """SELECT a.*, t.txn_ref, t.amount_paise, t.note, t.created_at AS txn_at, su.full_name AS sender, su.email AS sender_email,
                  ru.full_name AS recipient
           FROM fraud_alerts a JOIN transactions t ON t.txn_id = a.txn_id
           JOIN wallets sw ON sw.wallet_id = t.from_wallet_id JOIN users su ON su.user_id = sw.user_id
           LEFT JOIN wallets rw ON rw.wallet_id = t.to_wallet_id LEFT JOIN users ru ON ru.user_id = rw.user_id
           ORDER BY a.review_status = 'OPEN' DESC, a.created_at DESC LIMIT 50""").fetchall()
    return jsonify({"ok": True, "alerts": [{
        "alert_id": r["alert_id"], "txn_ref": r["txn_ref"], "amount_paise": r["amount_paise"], "note": r["note"],
        "sender": r["sender"], "sender_email": r["sender_email"], "recipient": r["recipient"], "risk_score": r["risk_score"],
        "reasons": json.loads(r["reasons"]), "review_status": r["review_status"], "created_at": r["created_at"]} for r in rows]})


@bp.post("/alerts/<int:alert_id>/<action>")
@auth_required(admin=True)
def resolve(alert_id, action):
    if action not in ("approve", "reject"):
        raise WalletError("Use approve or reject.", "bad_action")
    res = svc().wallet.resolve_alert(get_db(), g.user, alert_id, action == "approve")
    return jsonify({"ok": True, **res})


@bp.get("/users")
@auth_required(admin=True)
def users():
    rows = get_db().execute(
        "SELECT u.user_id, u.full_name, u.email, u.role, u.status, u.account_type, u.created_at, w.wallet_code, w.balance_paise "
        "FROM users u JOIN wallets w ON w.user_id = u.user_id WHERE u.account_type = 'PERSONAL' ORDER BY u.user_id").fetchall()
    return jsonify({"ok": True, "users": [dict(r) for r in rows]})


@bp.post("/users/<int:user_id>/<action>")
@auth_required(admin=True)
def set_status(user_id, action):
    if action not in ("freeze", "unfreeze"):
        raise WalletError("Use freeze or unfreeze.", "bad_action")
    cur = get_db().execute("UPDATE users SET status = ? WHERE user_id = ? AND role <> 'admin'",
                           ("frozen" if action == "freeze" else "active", user_id))
    if cur.rowcount != 1:
        raise WalletError("User not found, or admins can't be frozen.", "not_found", 404)
    svc().audit.append(f"user.{action}", g.user["user_id"], {"user": user_id})
    return jsonify({"ok": True})


@bp.get("/reconcile")
@auth_required(admin=True)
def reconcile():
    conn = get_db()
    bad = conn.execute("SELECT * FROM v_reconciliation WHERE diff_paise <> 0").fetchall()
    return jsonify({"ok": True, "wallets_checked": conn.execute("SELECT COUNT(*) FROM wallets").fetchone()[0],
                    "mismatches": [dict(r) for r in bad], "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
                    "explanation": "Every wallet's stored balance must equal the sum of its ledger entries (credits - debits)."})


@bp.post("/ai/retrain")
@auth_required(admin=True)
def retrain():
    s = svc()
    info = s.fraud.train(training_contexts(get_db(), s.cfg["OTP_THRESHOLD_PAISE"], s.cfg["TZ_OFFSET_MINUTES"]))
    s.audit.append("ai.retrained", g.user["user_id"], {"real_rows": info["trained_on"]["real"]})
    return jsonify({"ok": True, **info})
