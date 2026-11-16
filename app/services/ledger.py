"""Money movement and payment rules.

Two layers:
  1. low-level primitives (insert_txn / apply_txn) - no policy, just correct bookkeeping inside a transaction.
     The web flow, the scheduler, the demo-data seeder and the stress test all share them.
  2. WalletService - the business rules: limits, AI risk check, OTP step-up, idempotency, locking, caching.

Concurrency recipe for every money movement (OS + DBMS working together):
     take wallet locks in ascending id order      -> no deadlock
     BEGIN IMMEDIATE                              -> one writer at a time inside SQLite
     re-validate balance / limits INSIDE the lock -> no check-then-act race
     post debit + credit + mark SUCCESS           -> atomic: all or nothing
     COMMIT, invalidate cache, release locks
"""
import json
import logging
import sqlite3
import time
from datetime import timedelta

from ..ai.fraud import TxnContext
from ..db import tx
from ..security import hash_otp, new_otp, same
from ..util import (WalletError, canonical, clean_note, inr, iso, local_dt, new_txn_ref, parse_iso, sha256, utcnow)
from .trace import Trace

log = logging.getLogger("wallet.ledger")

TERMINAL = ("SUCCESS", "FAILED")


# =====================================================================================
#  1. LOW-LEVEL PRIMITIVES  (call these inside `with tx(conn):`)
# =====================================================================================
def insert_txn(conn, *, txn_type, amount_paise, from_wallet_id=None, to_wallet_id=None, note="", category="Other",
               status="PENDING", source="WEB", risk=None, failure_reason=None, created_at=None) -> dict:
    ref = new_txn_ref()
    cur = conn.execute(
        """INSERT INTO transactions (txn_ref, txn_type, from_wallet_id, to_wallet_id, amount_paise, note, category,
                                     status, failure_reason, risk_score, risk_level, risk_reasons, source, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (ref, txn_type, from_wallet_id, to_wallet_id, amount_paise, note, category, status, failure_reason,
         risk["score"] if risk else None, risk["level"] if risk else None,
         json.dumps(risk["reasons"]) if risk else None, source, created_at or iso()))
    return {"txn_id": cur.lastrowid, "txn_ref": ref}


def _debit(conn, wallet_id, amount, txn_id, ts):
    cur = conn.execute("UPDATE wallets SET balance_paise = balance_paise - ?, version = version + 1 "
                       "WHERE wallet_id = ? AND balance_paise >= ?", (amount, wallet_id, amount))
    if cur.rowcount != 1:
        raise WalletError("Not enough balance for this payment.", "insufficient_funds", 409)
    bal = conn.execute("SELECT balance_paise FROM wallets WHERE wallet_id = ?", (wallet_id,)).fetchone()[0]
    conn.execute("INSERT INTO ledger_entries (txn_id, wallet_id, direction, amount_paise, balance_after_paise, created_at) "
                 "VALUES (?,?,?,?,?,?)", (txn_id, wallet_id, "DEBIT", amount, bal, ts))


def _credit(conn, wallet_id, amount, txn_id, ts, max_balance=None):
    conn.execute("UPDATE wallets SET balance_paise = balance_paise + ?, version = version + 1 WHERE wallet_id = ?",
                 (amount, wallet_id))
    bal = conn.execute("SELECT balance_paise FROM wallets WHERE wallet_id = ?", (wallet_id,)).fetchone()[0]
    if max_balance is not None and bal > max_balance:
        raise WalletError("The receiving wallet would go over its balance limit.", "recipient_limit", 409)
    conn.execute("INSERT INTO ledger_entries (txn_id, wallet_id, direction, amount_paise, balance_after_paise, created_at) "
                 "VALUES (?,?,?,?,?,?)", (txn_id, wallet_id, "CREDIT", amount, bal, ts))


def apply_txn(conn, txn_id, *, ts=None, max_balance=None) -> None:
    """Post the ledger entries for an existing transaction row and mark it SUCCESS."""
    t = conn.execute("SELECT * FROM transactions WHERE txn_id = ?", (txn_id,)).fetchone()
    ts = ts or iso()
    amt = t["amount_paise"]
    if t["txn_type"] == "TOPUP":
        _credit(conn, t["to_wallet_id"], amt, txn_id, ts, max_balance)
    elif t["txn_type"] == "WITHDRAW":
        _debit(conn, t["from_wallet_id"], amt, txn_id, ts)
    else:
        _debit(conn, t["from_wallet_id"], amt, txn_id, ts)
        _credit(conn, t["to_wallet_id"], amt, txn_id, ts, max_balance)
    conn.execute("UPDATE transactions SET status = 'SUCCESS', failure_reason = NULL, completed_at = ? WHERE txn_id = ?",
                 (ts, txn_id))


# =====================================================================================
#  2. IDEMPOTENCY  (safe retries)
# =====================================================================================
def run_idempotent(conn, user_id, key, endpoint, payload, fn):
    """fn() -> (body_dict, http_status). Same key + same payload returns the stored answer instead of paying twice."""
    if not key:
        body, status = fn()
        return body, status, False
    if len(key) > 100:
        raise WalletError("Idempotency-Key is too long (max 100 characters).", "bad_idempotency_key", 400)
    digest = sha256(canonical({"endpoint": endpoint, "payload": payload}))
    for _ in range(2):
        try:
            conn.execute("INSERT INTO idempotency_keys (user_id, idem_key, endpoint, request_hash, state) "
                         "VALUES (?,?,?,?, 'IN_PROGRESS')", (user_id, key, endpoint, digest))
            break
        except sqlite3.IntegrityError:
            row = conn.execute("SELECT * FROM idempotency_keys WHERE user_id = ? AND idem_key = ?",
                               (user_id, key)).fetchone()
            if row is None:
                continue
            if row["request_hash"] != digest:
                raise WalletError("This Idempotency-Key was already used for a different request.", "idempotency_mismatch", 422)
            if row["state"] == "DONE":
                return json.loads(row["response_json"]), row["status_code"], True
            if utcnow() - parse_iso(row["created_at"]) > timedelta(seconds=60):   # crashed request: take over
                conn.execute("DELETE FROM idempotency_keys WHERE user_id = ? AND idem_key = ?", (user_id, key))
                continue
            raise WalletError("The first request with this Idempotency-Key is still running.", "idempotency_in_progress", 409)
    try:
        body, status = fn()
    except Exception:
        conn.execute("DELETE FROM idempotency_keys WHERE user_id = ? AND idem_key = ?", (user_id, key))
        raise
    conn.execute("UPDATE idempotency_keys SET state = 'DONE', status_code = ?, response_json = ? "
                 "WHERE user_id = ? AND idem_key = ?", (status, json.dumps(body), user_id, key))
    return body, status, False


# =====================================================================================
#  3. BUSINESS SERVICE
# =====================================================================================
class WalletService:
    def __init__(self, cfg, locks, cache, audit, fraud, categorizer):
        self.cfg, self.locks, self.cache, self.audit = cfg, locks, cache, audit
        self.fraud, self.categorizer = fraud, categorizer

    # ------------------------------------------------------------------ lookups
    @staticmethod
    def wallet_of(conn, user_id):
        row = conn.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            raise WalletError("Wallet not found.", "no_wallet", 404)
        return row

    @staticmethod
    def find_recipient(conn, ident):
        ident = (ident or "").strip()
        if not ident:
            raise WalletError("Enter who you want to pay: a wallet ID, email or phone number.", "recipient_required")
        row = conn.execute(
            """SELECT w.*, u.full_name, u.status AS user_status, u.account_type FROM wallets w
               JOIN users u ON u.user_id = w.user_id
               WHERE w.wallet_code = ? COLLATE NOCASE OR u.email = ? COLLATE NOCASE OR u.phone = ?""",
            (ident, ident, ident)).fetchone()
        if row is None:
            raise WalletError("No wallet found for that ID, email or phone. Check it and try again.", "recipient_not_found", 404)
        return row

    def balance(self, conn, wallet_id) -> int:
        """Cache-aside read: cache first, database on a miss."""
        key = f"bal:{wallet_id}"
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        bal = conn.execute("SELECT balance_paise FROM wallets WHERE wallet_id = ?", (wallet_id,)).fetchone()[0]
        self.cache.set(key, bal)
        return bal

    def _invalidate(self, *wallet_ids):
        for w in wallet_ids:
            if w:
                self.cache.delete(f"bal:{w}")

    def spent_24h(self, conn, wallet_id) -> int:
        since = iso(utcnow() - timedelta(hours=24))
        return conn.execute(
            "SELECT COALESCE(SUM(amount_paise), 0) FROM transactions WHERE from_wallet_id = ? AND status = 'SUCCESS' "
            "AND txn_type IN ('TRANSFER','WITHDRAW') AND created_at >= ?", (wallet_id, since)).fetchone()[0]

    def summary(self, conn, user) -> dict:
        w = self.wallet_of(conn, user["user_id"])
        spent = self.spent_24h(conn, w["wallet_id"])
        return {"wallet_code": w["wallet_code"], "balance_paise": self.balance(conn, w["wallet_id"]),
                "daily_limit_paise": w["daily_limit_paise"], "spent_24h_paise": spent,
                "otp_threshold_paise": self.cfg["OTP_THRESHOLD_PAISE"], "max_balance_paise": self.cfg["MAX_BALANCE_PAISE"],
                "member_since": w["created_at"]}

    # ------------------------------------------------------------------ AI risk
    def risk_context(self, conn, wallet, recipient, amount, kind) -> TxnContext:
        now = utcnow()
        local = local_dt(now, self.cfg["TZ_OFFSET_MINUTES"])
        since = iso(now - timedelta(hours=24))
        recent = conn.execute("SELECT amount_paise, created_at FROM transactions WHERE from_wallet_id = ? "
                              "AND status IN ('SUCCESS','PENDING_OTP') AND created_at >= ?", (wallet["wallet_id"], since)).fetchall()
        hist = conn.execute("SELECT amount_paise FROM transactions WHERE from_wallet_id = ? AND status = 'SUCCESS' "
                            "ORDER BY created_at DESC LIMIT 40", (wallet["wallet_id"],)).fetchall()
        known = False
        recipient_age = None
        if recipient is not None:
            known = conn.execute("SELECT 1 FROM transactions WHERE from_wallet_id = ? AND to_wallet_id = ? "
                                 "AND status = 'SUCCESS' LIMIT 1", (wallet["wallet_id"], recipient["wallet_id"])).fetchone() is not None
            recipient_age = (now - parse_iso(recipient["created_at"])).total_seconds() / 3600
        otp_fail = conn.execute(
            "SELECT COALESCE(SUM(o.attempts),0) FROM otp_challenges o JOIN transactions t ON t.txn_id = o.txn_id "
            "WHERE t.from_wallet_id = ? AND o.created_at >= ?", (wallet["wallet_id"], iso(now - timedelta(hours=1)))).fetchone()[0]
        return TxnContext(
            kind=kind, amount_paise=amount, balance_paise=wallet["balance_paise"],
            daily_limit_paise=wallet["daily_limit_paise"], spent_24h_paise=self.spent_24h(conn, wallet["wallet_id"]),
            otp_threshold_paise=self.cfg["OTP_THRESHOLD_PAISE"], local_hour=local.hour, local_minute=local.minute,
            history_amounts=[r[0] for r in hist],
            recent_ages_s=[(now - parse_iso(r[1])).total_seconds() for r in recent],
            recent_amounts=[r[0] for r in recent], is_new_recipient=not known, recipient_age_hours=recipient_age,
            failed_otp_1h=otp_fail)

    def preview(self, conn, user, to_ident, amount_paise, note, kind="TRANSFER") -> dict:
        """No side effects: what would happen if the user pressed Send now?"""
        w = self.wallet_of(conn, user["user_id"])
        recipient = self.find_recipient(conn, to_ident) if kind == "TRANSFER" else None
        if recipient is not None and recipient["wallet_id"] == w["wallet_id"]:
            raise WalletError("You can't send money to yourself.", "self_transfer")
        risk = self.fraud.assess(self.risk_context(conn, w, recipient, amount_paise, kind)).as_dict()
        text = f"{clean_note(note)} {recipient['full_name'] if recipient else ''}".strip()
        cat = self.categorizer.predict(text)
        needs_otp = amount_paise >= self.cfg["OTP_THRESHOLD_PAISE"] or risk["level"] == "MEDIUM"
        outcome = "BLOCKED" if risk["level"] == "HIGH" else "OTP" if needs_otp else "INSTANT"
        return {"risk": risk, "category": cat, "outcome": outcome,
                "recipient": {"name": recipient["full_name"], "wallet_code": recipient["wallet_code"]} if recipient else None,
                "balance_after_paise": w["balance_paise"] - amount_paise}

    # ------------------------------------------------------------------ main entry point
    def submit(self, conn, user, *, kind, amount_paise, to_ident=None, to_wallet_id=None, note="", category=None,
               source="WEB", skip_otp=False, trace=None) -> dict:
        """Create and (when allowed) execute a TOPUP / WITHDRAW / TRANSFER."""
        cfg = self.cfg
        tr = trace if trace is not None else Trace()
        if user["status"] != "active":
            raise WalletError("This wallet is frozen. Contact support.", "wallet_frozen", 403)
        w = self.wallet_of(conn, user["user_id"])
        note = clean_note(note)
        if amount_paise < cfg["MIN_AMOUNT_PAISE"]:
            raise WalletError("The smallest amount is ₹1.", "amount_too_small")
        cap = cfg["MAX_TOPUP_PAISE"] if kind == "TOPUP" else cfg["MAX_TRANSFER_PAISE"]
        if amount_paise > cap:
            raise WalletError(f"The most you can {'add' if kind == 'TOPUP' else 'send'} at once is {inr(cap)}.", "amount_too_large")

        recipient = None
        if kind == "TRANSFER":
            if to_wallet_id:
                recipient = conn.execute("SELECT w.*, u.full_name, u.status AS user_status FROM wallets w "
                                         "JOIN users u ON u.user_id = w.user_id WHERE w.wallet_id = ?", (to_wallet_id,)).fetchone()
                if recipient is None:
                    raise WalletError("Recipient wallet not found.", "recipient_not_found", 404)
            else:
                recipient = self.find_recipient(conn, to_ident)
            if recipient["wallet_id"] == w["wallet_id"]:
                raise WalletError("You can't send money to yourself.", "self_transfer")
            if recipient["user_status"] != "active":
                raise WalletError("That wallet can't receive money right now.", "recipient_unavailable", 409)

        tr.add("API", "Request validated", f"{kind.lower()} {inr(amount_paise)}" + (f" to {recipient['wallet_code']}" if recipient is not None else ""))
        if kind == "TOPUP":
            note = note or "Added from bank (UPI)"
            category = "Top-up"
        elif kind == "WITHDRAW":
            note = note or "Withdrawn to bank"
            category = "Withdrawal"
        else:
            text = f"{note} {recipient['full_name']}".strip()
            if category not in self.categorizer.counts:
                pred = self.categorizer.predict(text)
                category = pred["category"]
                tr.add("AI", "Category predicted", f"{category} ({min(99, round(pred['confidence'] * 100))}% sure)")
            else:
                tr.add("AI", "Category chosen by you", category)

        # ---- AI risk check (not for top-ups: the money comes in from the user's own bank)
        risk = None
        if kind != "TOPUP":
            risk = self.fraud.assess(self.risk_context(conn, w, recipient, amount_paise, kind)).as_dict()
            why = "; ".join(r["text"] for r in risk["reasons"][:2]) or "nothing unusual"
            tr.add("AI", "Risk scored", f"{risk['score']}/100 ({risk['level'].lower()}): {why}")
        ids = dict(from_wallet_id=w["wallet_id"] if kind != "TOPUP" else None,
                   to_wallet_id=(recipient["wallet_id"] if recipient is not None else w["wallet_id"] if kind == "TOPUP" else None))
        base = dict(txn_type=kind, amount_paise=amount_paise, note=note, category=category, source=source, risk=risk, **ids)

        if risk and risk["level"] == "HIGH":
            with tx(conn):
                t = insert_txn(conn, status="BLOCKED", failure_reason="Held by the AI fraud check for review", **base)
                conn.execute("INSERT INTO fraud_alerts (txn_id, risk_score, reasons) VALUES (?,?,?)",
                             (t["txn_id"], risk["score"], json.dumps(risk["reasons"])))
            rec = self.audit.append("payment.blocked", user["user_id"], {"txn": t["txn_ref"], "amount_paise": amount_paise, "risk": risk["score"]})
            tr.add("DBMS", "Payment held for review", "saved as BLOCKED with a fraud alert; no money moved")
            tr.add("FILE", "Audit record appended", f"#{rec['seq']} hash {rec['hash'][:12]}")
            return {"status": "BLOCKED", "txn_ref": t["txn_ref"], "risk": risk, "trace": tr.steps, "amount_paise": amount_paise, "created_at": iso(),
                    "message": "This payment looks risky, so it was held for review. No money was moved."}

        needs_otp = kind != "TOPUP" and (amount_paise >= cfg["OTP_THRESHOLD_PAISE"] or risk["level"] == "MEDIUM")
        if needs_otp:
            if skip_otp:
                with tx(conn):
                    t = insert_txn(conn, status="FAILED", failure_reason="Needs OTP verification - send it manually", **base)
                return {"status": "FAILED", "txn_ref": t["txn_ref"], "risk": risk,
                        "message": "This payment needs OTP verification, so it was not sent automatically."}
            with tx(conn):
                t = insert_txn(conn, status="PENDING_OTP", **base)
                otp, expires = self._issue_otp(conn, t["txn_id"], t["txn_ref"])
            rec = self.audit.append("payment.otp_issued", user["user_id"], {"txn": t["txn_ref"], "amount_paise": amount_paise})
            tr.add("API", "OTP required", "amount is at or above the OTP limit" if amount_paise >= cfg["OTP_THRESHOLD_PAISE"] else "medium risk needs extra verification")
            tr.add("FILE", "Audit record appended", f"#{rec['seq']} hash {rec['hash'][:12]}")
            out = {"status": "PENDING_OTP", "txn_ref": t["txn_ref"], "otp_expires_at": expires, "risk": risk, "trace": tr.steps,
                   "amount_paise": amount_paise, "created_at": iso(),
                   "message": "Enter the OTP sent to your phone to finish this payment."}
            if cfg["DEMO_MODE"]:
                out["demo_otp"] = otp
            return out

        with tx(conn):
            t = insert_txn(conn, status="PENDING", **base)
        tr.add("API", "No extra verification needed", "")
        return self._finalize(conn, t["txn_id"], user["user_id"], risk, trace=tr)

    # ------------------------------------------------------------------ OTP
    def _issue_otp(self, conn, txn_id, txn_ref):
        otp = new_otp()
        expires = iso(utcnow() + timedelta(seconds=self.cfg["OTP_TTL_SECONDS"]))
        conn.execute("INSERT OR REPLACE INTO otp_challenges (txn_id, otp_hash, expires_at, attempts) VALUES (?,?,?,0)",
                     (txn_id, hash_otp(otp, txn_ref, self.cfg["SECRET_KEY"]), expires))
        print(f"\n[SIMULATED SMS] OTP for {txn_ref}: {otp}  (valid {self.cfg['OTP_TTL_SECONDS'] // 60} minutes)\n", flush=True)
        return otp, expires

    def confirm_otp(self, conn, user, txn_ref, otp) -> dict:
        w = self.wallet_of(conn, user["user_id"])
        t = conn.execute("SELECT * FROM transactions WHERE txn_ref = ? AND from_wallet_id = ?", (txn_ref, w["wallet_id"])).fetchone()
        if t is None:
            raise WalletError("Payment not found.", "txn_not_found", 404)
        if t["status"] == "SUCCESS":
            return self._result(conn, t, already=True)
        if t["status"] != "PENDING_OTP":
            raise WalletError(f"This payment is {t['status'].replace('_', ' ').lower()} and can't be confirmed.", "not_pending", 409)
        ch = conn.execute("SELECT * FROM otp_challenges WHERE txn_id = ?", (t["txn_id"],)).fetchone()
        if ch is None:
            raise WalletError("No OTP is pending for this payment.", "no_otp", 409)
        if parse_iso(ch["expires_at"]) < utcnow():
            self._fail(conn, t["txn_id"], "OTP expired")
            raise WalletError("That OTP has expired. Start the payment again.", "otp_expired", 410)
        if not same(hash_otp(str(otp).strip(), txn_ref, self.cfg["SECRET_KEY"]), ch["otp_hash"]):
            conn.execute("UPDATE otp_challenges SET attempts = attempts + 1 WHERE txn_id = ?", (t["txn_id"],))
            left = self.cfg["OTP_MAX_ATTEMPTS"] - (ch["attempts"] + 1)
            self.audit.append("payment.otp_wrong", user["user_id"], {"txn": txn_ref})
            if left <= 0:
                self._fail(conn, t["txn_id"], "Too many wrong OTP attempts")
                raise WalletError("Too many wrong OTPs. The payment was cancelled.", "otp_locked", 429)
            raise WalletError(f"Wrong OTP. {left} attempt(s) left.", "otp_invalid", 400, attempts_left=left)
        risk = json.loads(t["risk_reasons"]) if t["risk_reasons"] else None
        tr = Trace()
        tr.add("API", "OTP verified", f"attempt {ch['attempts'] + 1} of {self.cfg['OTP_MAX_ATTEMPTS']}")
        return self._finalize(conn, t["txn_id"], user["user_id"], {"score": t["risk_score"], "level": t["risk_level"], "reasons": risk or []}, trace=tr)

    def _fail(self, conn, txn_id, reason):
        conn.execute("UPDATE transactions SET status = 'FAILED', failure_reason = ?, completed_at = ? "
                     "WHERE txn_id = ? AND status NOT IN ('SUCCESS','FAILED')", (reason, iso(), txn_id))

    # ------------------------------------------------------------------ execute (locked + atomic)
    def _finalize(self, conn, txn_id, actor_id, risk=None, trace=None) -> dict:
        tr = trace if trace is not None else Trace()
        t = conn.execute("SELECT * FROM transactions WHERE txn_id = ?", (txn_id,)).fetchone()
        wallet_ids = [x for x in (t["from_wallet_id"], t["to_wallet_id"]) if x]
        ids_text = ", ".join(str(w) for w in sorted(wallet_ids))
        asked = time.perf_counter()
        with self.locks.hold(wallet_ids):                        # OS: ordered locks -> no deadlock
            tr.add("OS", "Wallet locks taken", f"wallets {ids_text} in ascending order ({self.locks.mode}), waited {round((time.perf_counter() - asked) * 1000, 1)} ms")
            with tx(conn):                                       # DBMS: one atomic transaction
                tr.add("DBMS", "BEGIN IMMEDIATE", "SQLite write lock held, so no other payment can write now")
                t = conn.execute("SELECT * FROM transactions WHERE txn_id = ?", (txn_id,)).fetchone()
                if t["status"] in TERMINAL:                      # a double-click / retry already finished it
                    res = self._result(conn, t, already=True)
                    tr.add("DBMS", "Already processed", "an earlier request finished this payment; nothing repeated")
                    res["trace"] = tr.steps
                    return res
                problem = self._validate_for_posting(conn, t)
                if problem:
                    tr.add("DBMS", "Checks inside the lock failed", problem)
                    conn.execute("UPDATE transactions SET status = 'FAILED', failure_reason = ?, completed_at = ? WHERE txn_id = ?",
                                 (problem, iso(), txn_id))
                else:
                    tr.add("DBMS", "Balance and limits re-checked inside the lock", "nobody could change them since the first check")
                    apply_txn(conn, txn_id, max_balance=self.cfg["MAX_BALANCE_PAISE"])
                    n = 2 if t["txn_type"] == "TRANSFER" else 1
                    tr.add("DBMS", "Ledger posted", f"{n} immutable ledger {'entries' if n > 1 else 'entry'}, balance{'s' if n > 1 else ''} updated")
            tr.add("DBMS", "COMMIT", "every change became visible together, or none would have")
            self._invalidate(*wallet_ids)                        # cache invalidation while still holding the locks
            tr.add("CACHE", "Balance cache invalidated", f"wallets {ids_text}")
        tr.add("OS", "Wallet locks released", "")
        t = conn.execute("SELECT * FROM transactions WHERE txn_id = ?", (txn_id,)).fetchone()
        rec = self.audit.append(f"payment.{t['status'].lower()}", actor_id,
                                {"txn": t["txn_ref"], "type": t["txn_type"], "amount_paise": t["amount_paise"],
                                 "from": t["from_wallet_id"], "to": t["to_wallet_id"], "reason": t["failure_reason"]})
        tr.add("FILE", "Audit record appended", f"#{rec['seq']} hash {rec['hash'][:12]}, fsync'd to disk")
        res = self._result(conn, t)
        if risk:
            res["risk"] = risk
        res["trace"] = tr.steps
        return res

    def _validate_for_posting(self, conn, t):
        """Runs INSIDE the lock + transaction, so the numbers cannot change under our feet."""
        amt = t["amount_paise"]
        if t["from_wallet_id"]:
            src = conn.execute("SELECT w.*, u.status AS user_status FROM wallets w JOIN users u ON u.user_id = w.user_id "
                               "WHERE w.wallet_id = ?", (t["from_wallet_id"],)).fetchone()
            if src["user_status"] != "active":
                return "Wallet is frozen"
            if src["balance_paise"] < amt:
                return "Not enough balance"
            if self.spent_24h(conn, src["wallet_id"]) + amt > src["daily_limit_paise"]:
                return f"Daily limit of {inr(src['daily_limit_paise'])} would be exceeded"
        if t["to_wallet_id"]:
            dst = conn.execute("SELECT w.*, u.status AS user_status FROM wallets w JOIN users u ON u.user_id = w.user_id "
                               "WHERE w.wallet_id = ?", (t["to_wallet_id"],)).fetchone()
            if dst["user_status"] != "active":
                return "Recipient wallet is frozen"
            if dst["balance_paise"] + amt > self.cfg["MAX_BALANCE_PAISE"]:
                return f"Wallet balance limit of {inr(self.cfg['MAX_BALANCE_PAISE'])} would be exceeded"
        return None

    def _result(self, conn, t, already=False) -> dict:
        out = {"status": t["status"], "txn_ref": t["txn_ref"], "amount_paise": t["amount_paise"], "type": t["txn_type"],
               "category": t["category"], "note": t["note"], "created_at": t["created_at"], "already_processed": already}
        if t["status"] == "FAILED":
            out["message"] = f"The payment failed: {t['failure_reason']}."
        elif t["status"] == "SUCCESS":
            wid = t["from_wallet_id"] or t["to_wallet_id"]
            out["balance_paise"] = self.balance(conn, wid)
            out["message"] = "Done."
        return out

    # ------------------------------------------------------------------ admin review of blocked payments
    def resolve_alert(self, conn, admin, alert_id, approve: bool) -> dict:
        a = conn.execute("SELECT * FROM fraud_alerts WHERE alert_id = ?", (alert_id,)).fetchone()
        if a is None:
            raise WalletError("Alert not found.", "not_found", 404)
        if a["review_status"] != "OPEN":
            raise WalletError("This alert was already reviewed.", "already_reviewed", 409)
        t = conn.execute("SELECT * FROM transactions WHERE txn_id = ?", (a["txn_id"],)).fetchone()
        if approve:
            result = self._finalize(conn, t["txn_id"], admin["user_id"])
        else:
            self._fail(conn, t["txn_id"], "Rejected by reviewer")
            result = {"status": "FAILED", "txn_ref": t["txn_ref"]}
        conn.execute("UPDATE fraud_alerts SET review_status = ?, reviewed_by = ?, reviewed_at = ? WHERE alert_id = ?",
                     ("APPROVED" if approve else "REJECTED", admin["user_id"], iso(), alert_id))
        self.audit.append("alert.approved" if approve else "alert.rejected", admin["user_id"], {"alert": alert_id, "txn": t["txn_ref"]})
        return result

    # ------------------------------------------------------------------ scheduled payments
    def create_schedule(self, conn, user, *, to_ident, amount_paise, note, category, frequency, run_at, priority) -> dict:
        w = self.wallet_of(conn, user["user_id"])
        recipient = self.find_recipient(conn, to_ident)
        if recipient["wallet_id"] == w["wallet_id"]:
            raise WalletError("You can't schedule a payment to yourself.", "self_transfer")
        if amount_paise >= self.cfg["OTP_THRESHOLD_PAISE"]:
            raise WalletError(f"Scheduled payments must be below {inr(self.cfg['OTP_THRESHOLD_PAISE'])}. "
                              "Bigger payments need an OTP, so send them manually.", "schedule_too_large")
        if frequency not in ("ONCE", "DAILY", "WEEKLY", "MONTHLY"):
            raise WalletError("Choose how often the payment repeats.", "bad_frequency")
        when = parse_iso(run_at)
        if when < utcnow() - timedelta(seconds=30):
            raise WalletError("Pick a time in the future.", "bad_time")
        if when > utcnow() + timedelta(days=366):
            raise WalletError("You can schedule at most one year ahead.", "bad_time")
        active = conn.execute("SELECT COUNT(*) FROM scheduled_payments WHERE user_id = ? AND status IN ('ACTIVE','RUNNING')",
                              (user["user_id"],)).fetchone()[0]
        if active >= 20:
            raise WalletError("You can have at most 20 active scheduled payments.", "too_many_schedules", 409)
        note = clean_note(note)
        if category not in self.categorizer.counts:
            category = self.categorizer.predict(f"{note} {recipient['full_name']}")["category"]
        cur = conn.execute("INSERT INTO scheduled_payments (user_id, to_wallet_id, amount_paise, note, category, priority, "
                           "frequency, next_run_at) VALUES (?,?,?,?,?,?,?,?)",
                           (user["user_id"], recipient["wallet_id"], amount_paise, note, category, priority, frequency, iso(when)))
        self.audit.append("schedule.created", user["user_id"], {"sched": cur.lastrowid, "amount_paise": amount_paise})
        return {"sched_id": cur.lastrowid}

    def run_schedule(self, conn, sched_id) -> dict:
        """Called by a scheduler worker thread. Runs one due payment and re-plans the next run."""
        s = conn.execute("SELECT * FROM scheduled_payments WHERE sched_id = ?", (sched_id,)).fetchone()
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (s["user_id"],)).fetchone()
        try:
            res = self.submit(conn, user, kind="TRANSFER", amount_paise=s["amount_paise"], to_wallet_id=s["to_wallet_id"],
                              note=s["note"], category=s["category"], source="SCHEDULED", skip_otp=True)
            ok = res["status"] == "SUCCESS"
            result = "SUCCESS" if ok else f"{res['status']}: {res.get('message', '')}"
        except WalletError as e:
            ok, result = False, f"FAILED: {e.message}"
        nxt_status, nxt_time = "ACTIVE", parse_iso(s["next_run_at"])
        step = {"DAILY": timedelta(days=1), "WEEKLY": timedelta(weeks=1), "MONTHLY": timedelta(days=30)}.get(s["frequency"])
        if step is None:
            nxt_status = "DONE" if ok else "FAILED"
        else:
            while nxt_time <= utcnow():
                nxt_time += step
        conn.execute("UPDATE scheduled_payments SET status = ?, next_run_at = ?, last_result = ?, "
                     "run_count = run_count + ? WHERE sched_id = ?",
                     (nxt_status, iso(nxt_time), result, 1 if ok else 0, sched_id))
        return {"sched_id": sched_id, "ok": ok, "result": result}
