"""Read-side queries shared by several routes (history, AI inputs)."""
import json
from datetime import datetime, timedelta

from ..util import iso, parse_iso, utcnow


def public_txn(r, wid) -> dict:
    out_dir = r["from_wallet_id"] == wid
    out = {"txn_ref": r["txn_ref"], "type": r["txn_type"], "direction": "DEBIT" if out_dir else "CREDIT",
           "amount_paise": r["amount_paise"], "note": r["note"],
           "category": r["category"] if (out_dir or r["txn_type"] == "TOPUP") else "Received",
           "status": r["status"], "failure_reason": r["failure_reason"], "created_at": r["created_at"],
           "balance_after_paise": r["balance_after_paise"], "source": r["source"],
           "counterparty": {"name": r["cp_name"], "wallet_code": r["cp_code"]} if r["cp_name"] else None}
    if out_dir and r["risk_score"] is not None:                    # risk details are private to the sender
        out["risk"] = {"score": r["risk_score"], "level": r["risk_level"],
                       "reasons": json.loads(r["risk_reasons"] or "[]")}
    return out


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def list_transactions(conn, wid, tz, *, type_=None, direction=None, category=None, status=None, q=None,
                      date_from=None, date_to=None, limit=50, offset=0):
    where = ["(t.from_wallet_id = :wid OR (t.to_wallet_id = :wid AND t.status = 'SUCCESS'))"]
    p = {"wid": wid, "limit": max(1, min(int(limit), 500)), "offset": max(0, int(offset))}
    if type_ in ("TOPUP", "WITHDRAW", "TRANSFER"):
        where.append("t.txn_type = :type"); p["type"] = type_
    if direction == "out":
        where.append("t.from_wallet_id = :wid")
    elif direction == "in":
        where.append("t.to_wallet_id = :wid")
    if category:
        where.append("t.category = :cat"); p["cat"] = category
    if status in ("SUCCESS", "PENDING_OTP", "FAILED", "BLOCKED"):
        where.append("t.status = :status"); p["status"] = status
    if q:
        where.append("(t.note LIKE :q ESCAPE '\\' OR cu.full_name LIKE :q ESCAPE '\\' OR t.txn_ref LIKE :q ESCAPE '\\')")
        p["q"] = _like(q[:50])
    try:
        if date_from:   # local calendar date -> UTC boundary
            p["df"] = iso(datetime.fromisoformat(date_from) - timedelta(minutes=tz)); where.append("t.created_at >= :df")
        if date_to:
            p["dt"] = iso(datetime.fromisoformat(date_to) + timedelta(days=1) - timedelta(minutes=tz)); where.append("t.created_at < :dt")
    except ValueError:
        pass
    base = """FROM transactions t
              LEFT JOIN ledger_entries e ON e.txn_id = t.txn_id AND e.wallet_id = :wid
              LEFT JOIN wallets cw ON cw.wallet_id = CASE WHEN t.from_wallet_id = :wid THEN t.to_wallet_id ELSE t.from_wallet_id END
              LEFT JOIN users cu ON cu.user_id = cw.user_id
              WHERE """ + " AND ".join(where)
    total = conn.execute("SELECT COUNT(*) " + base, p).fetchone()[0]
    rows = conn.execute("SELECT t.*, e.balance_after_paise, cw.wallet_code AS cp_code, cu.full_name AS cp_name " + base +
                        " ORDER BY t.created_at DESC, t.txn_id DESC LIMIT :limit OFFSET :offset", p).fetchall()
    return [public_txn(r, wid) for r in rows], total


def get_transaction(conn, wid, txn_ref):
    rows = conn.execute(
        """SELECT t.*, e.balance_after_paise, cw.wallet_code AS cp_code, cu.full_name AS cp_name
           FROM transactions t
           LEFT JOIN ledger_entries e ON e.txn_id = t.txn_id AND e.wallet_id = :wid
           LEFT JOIN wallets cw ON cw.wallet_id = CASE WHEN t.from_wallet_id = :wid THEN t.to_wallet_id ELSE t.from_wallet_id END
           LEFT JOIN users cu ON cu.user_id = cw.user_id
           WHERE t.txn_ref = :ref AND (t.from_wallet_id = :wid OR (t.to_wallet_id = :wid AND t.status = 'SUCCESS'))""",
        {"wid": wid, "ref": txn_ref}).fetchall()
    return public_txn(rows[0], wid) if rows else None


def spending_rows(conn, wid, days=120) -> list:
    since = iso(utcnow() - timedelta(days=days))
    rows = conn.execute(
        """SELECT t.created_at, t.amount_paise, t.category, t.note, u.full_name AS party
           FROM transactions t JOIN wallets w ON w.wallet_id = t.to_wallet_id JOIN users u ON u.user_id = w.user_id
           WHERE t.from_wallet_id = ? AND t.txn_type = 'TRANSFER' AND t.status = 'SUCCESS' AND t.created_at >= ?
           ORDER BY t.created_at""", (wid, since)).fetchall()
    return [{"ts": parse_iso(r["created_at"]), "amount": r["amount_paise"], "category": r["category"],
             "note": r["note"], "party": r["party"]} for r in rows]


def income_30d(conn, wid) -> int:
    since = iso(utcnow() - timedelta(days=30))
    return conn.execute("SELECT COALESCE(SUM(amount_paise),0) FROM transactions WHERE to_wallet_id = ? "
                        "AND status = 'SUCCESS' AND created_at >= ?", (wid, since)).fetchone()[0]


def flagged_30d(conn, wid) -> int:
    since = iso(utcnow() - timedelta(days=30))
    return conn.execute("SELECT COUNT(*) FROM transactions WHERE from_wallet_id = ? AND created_at >= ? "
                        "AND (risk_level IN ('MEDIUM','HIGH') OR status = 'BLOCKED')", (wid, since)).fetchone()[0]


def risk_overview(conn, wid) -> dict:
    since = iso(utcnow() - timedelta(days=30))
    rows = conn.execute("SELECT COALESCE(risk_level, 'LOW'), COUNT(*) FROM transactions WHERE from_wallet_id = ? "
                        "AND created_at >= ? AND status IN ('SUCCESS','PENDING_OTP','BLOCKED') GROUP BY 1", (wid, since)).fetchall()
    out = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    out.update({r[0]: r[1] for r in rows})
    return out


def contacts(conn, wid, limit=30) -> list:
    rows = conn.execute(
        """SELECT DISTINCT cw.wallet_code, cu.full_name
           FROM (SELECT * FROM transactions WHERE (from_wallet_id = :w OR to_wallet_id = :w) AND status = 'SUCCESS'
                 AND txn_type = 'TRANSFER' ORDER BY txn_id DESC LIMIT 200) t
           JOIN wallets cw ON cw.wallet_id = CASE WHEN t.from_wallet_id = :w THEN t.to_wallet_id ELSE t.from_wallet_id END
           JOIN users cu ON cu.user_id = cw.user_id LIMIT :n""", {"w": wid, "n": limit}).fetchall()
    return [{"name": r["full_name"], "wallet_code": r["wallet_code"]} for r in rows]


def flagged_list(conn, wid, limit=5) -> list:
    rows = conn.execute(
        "SELECT amount_paise, status, risk_score, risk_reasons FROM transactions WHERE from_wallet_id = ? "
        "AND (status IN ('BLOCKED','PENDING_OTP') OR risk_level IN ('MEDIUM','HIGH')) ORDER BY created_at DESC LIMIT ?",
        (wid, limit)).fetchall()
    return [{"amount_paise": r["amount_paise"], "status": r["status"], "risk_score": r["risk_score"],
             "reasons": json.loads(r["risk_reasons"] or "[]")} for r in rows]


def recent_contacts(conn, wid, limit=12) -> list:
    """People and merchants this wallet has paid or received from, newest first."""
    rows = conn.execute(
        """SELECT cw.wallet_code, cu.full_name, cu.account_type, t.created_at, (t.from_wallet_id = :w) AS paid
           FROM transactions t
           JOIN wallets cw ON cw.wallet_id = CASE WHEN t.from_wallet_id = :w THEN t.to_wallet_id ELSE t.from_wallet_id END
           JOIN users cu ON cu.user_id = cw.user_id
           WHERE (t.from_wallet_id = :w OR t.to_wallet_id = :w) AND t.status = 'SUCCESS' AND t.txn_type = 'TRANSFER'
           ORDER BY t.created_at DESC, t.txn_id DESC LIMIT 300""", {"w": wid}).fetchall()
    seen, out = set(), []
    for r in rows:
        if r["wallet_code"] in seen:
            continue
        seen.add(r["wallet_code"])
        out.append({"name": r["full_name"], "wallet_code": r["wallet_code"], "merchant": r["account_type"] == "MERCHANT",
                    "last_at": r["created_at"], "paid": bool(r["paid"])})
        if len(out) >= limit:
            break
    return out


def merchants(conn) -> list:
    rows = conn.execute("SELECT u.full_name, w.wallet_code FROM users u JOIN wallets w ON w.user_id = u.user_id "
                        "WHERE u.account_type = 'MERCHANT' AND u.status = 'active' ORDER BY u.full_name").fetchall()
    return [{"name": r["full_name"], "wallet_code": r["wallet_code"], "merchant": True} for r in rows]


def txn_timeline(conn, wid, ref):
    """Status changes of one payment, written by the database triggers. Receivers only see the final 'paid' step."""
    t = conn.execute("SELECT txn_id, from_wallet_id FROM transactions WHERE txn_ref = ? AND (from_wallet_id = ? "
                     "OR (to_wallet_id = ? AND status = 'SUCCESS'))", (ref, wid, wid)).fetchone()
    if t is None:
        return None
    rows = conn.execute("SELECT new_status, changed_at FROM txn_status_history WHERE txn_id = ? ORDER BY hist_id", (t["txn_id"],)).fetchall()
    if t["from_wallet_id"] != wid:
        rows = [r for r in rows if r["new_status"] == "SUCCESS"]
    return [{"status": r["new_status"], "at": r["changed_at"]} for r in rows]
