import re
import sqlite3

from flask import Blueprint, g, jsonify, request

from ..deps import auth_required, body, get_db, svc, user_json
from ..security import EMAIL_RE, PHONE_RE, hash_password, password_problem, verify_password
from ..util import WalletError, clean_note

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _wallet_code(conn, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]", "", name.split()[0].lower()) or "user"
    code, n = f"{slug}@swallet", 1
    while conn.execute("SELECT 1 FROM wallets WHERE wallet_code = ? COLLATE NOCASE", (code,)).fetchone():
        n += 1
        code = f"{slug}{n}@swallet"
    return code


@bp.post("/register")
def register():
    s, cfg, conn, data = svc(), svc().cfg, get_db(), body()
    s.limiter.enforce("register", request.remote_addr, cfg["RATE_REGISTER_PER_HOUR"], 3600)
    name, email = clean_note(data.get("full_name"), 60), str(data.get("email", "")).strip().lower()
    phone, password = str(data.get("phone") or "").strip() or None, str(data.get("password", ""))
    if len(name) < 2:
        raise WalletError("Enter your full name.", "invalid_name")
    if not EMAIL_RE.match(email):
        raise WalletError("Enter a valid email address.", "invalid_email")
    if phone and not PHONE_RE.match(phone):
        raise WalletError("Enter a 10-digit Indian mobile number or leave it empty.", "invalid_phone")
    problem = password_problem(password)
    if problem:
        raise WalletError(f"Password too weak. {problem}", "weak_password")
    try:
        conn.execute("BEGIN IMMEDIATE")
        uid = conn.execute("INSERT INTO users (full_name, email, phone, password_hash) VALUES (?,?,?,?)",
                           (name, email, phone, hash_password(password, cfg["PASSWORD_ITERATIONS"]))).lastrowid
        conn.execute("INSERT INTO wallets (user_id, wallet_code, daily_limit_paise) VALUES (?,?,?)",
                     (uid, _wallet_code(conn, name), cfg["DEFAULT_DAILY_LIMIT_PAISE"]))
        conn.execute("COMMIT")
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK")
        raise WalletError("That email or phone number is already registered. Try signing in.", "already_registered", 409)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
    wallet = s.wallet.wallet_of(conn, uid)
    token = s.sessions.create(conn, uid, request.remote_addr or "", request.headers.get("User-Agent", ""))
    s.audit.append("user.registered", uid, {"email_domain": email.split("@")[-1]})
    return jsonify({"ok": True, "token": token, "user": user_json(user, wallet)}), 201


@bp.post("/login")
def login():
    s, cfg, conn, data = svc(), svc().cfg, get_db(), body()
    email, password = str(data.get("email", "")).strip().lower(), str(data.get("password", ""))
    s.limiter.enforce("login", f"{request.remote_addr}:{email}", cfg["RATE_LOGIN_PER_MIN"], 60)
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    ok = verify_password(user["password_hash"] if user else s.dummy_hash, password)   # same work either way
    if not user or not ok:
        s.audit.append("login.failed", None, {"email_domain": email.split("@")[-1] if "@" in email else ""})
        raise WalletError("Wrong email or password.", "bad_credentials", 401)
    wallet = s.wallet.wallet_of(conn, user["user_id"])
    token = s.sessions.create(conn, user["user_id"], request.remote_addr or "", request.headers.get("User-Agent", ""))
    s.audit.append("login.ok", user["user_id"], {})
    return jsonify({"ok": True, "token": token, "user": user_json(user, wallet)})


@bp.post("/logout")
@auth_required()
def logout():
    svc().sessions.revoke(get_db(), g.token)
    return jsonify({"ok": True})


@bp.get("/me")
@auth_required()
def me():
    conn = get_db()
    wallet = svc().wallet.wallet_of(conn, g.user["user_id"])
    return jsonify({"ok": True, "user": user_json(g.user, wallet), "wallet": svc().wallet.summary(conn, g.user)})
