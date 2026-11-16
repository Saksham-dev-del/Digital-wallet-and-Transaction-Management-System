"""Shared Flask helpers: service access, per-request DB connection, auth decorator, JSON body."""
from functools import wraps

from flask import current_app, g, request

from .db import connect
from .util import WalletError


def svc():
    return current_app.extensions["wallet"]


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"])
    return g.db


def body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise WalletError("Send the request as a JSON object.", "bad_json")
    return data


def bearer_token() -> str:
    header = request.headers.get("Authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else ""


def auth_required(admin: bool = False):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            conn, token = get_db(), bearer_token()
            uid = svc().sessions.resolve(conn, token)
            user = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone() if uid else None
            if user is None:
                raise WalletError("Please sign in again.", "unauthorized", 401)
            if admin and user["role"] != "admin":
                raise WalletError("Only administrators can do this.", "forbidden", 403)
            g.user, g.token = user, token
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def user_json(user, wallet=None) -> dict:
    out = {"user_id": user["user_id"], "full_name": user["full_name"], "email": user["email"], "phone": user["phone"],
           "role": user["role"], "status": user["status"]}
    if wallet is not None:
        out["wallet_code"] = wallet["wallet_code"]
    return out
