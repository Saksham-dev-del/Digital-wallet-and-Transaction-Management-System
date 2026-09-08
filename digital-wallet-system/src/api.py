"""
api.py
------
Flask REST API layer on top of the existing OS+DBMS backend
(auth.py, wallet.py, transaction.py, session_store.py). Also serves
the frontend (the /frontend folder) so the whole project runs with
one command.

Session handling (Redis-backed, see session_store.py):
  - POST /api/login returns a token.
  - The frontend sends that token back as "Authorization: Bearer <token>"
    on every protected request.
  - This API looks the token up in Redis to find out which wallet the
    caller actually owns - it does NOT trust a wallet_id the client
    might put in the request body for "my own wallet" actions
    (deposit/withdraw/history/balance). This closes a real gap from
    the earlier version, where any wallet_id sent by the frontend was
    trusted blindly.
  - transfer() is the one exception where a *second* wallet_id (the
    destination) legitimately comes from the client, since you are
    allowed to send money to someone else's wallet.

Run:
    pip install flask redis
    (make sure a Redis server is running - see README)
    python api.py
Then open http://localhost:5000 in a browser.
"""

import os
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, g

from db import init_db
import auth
import wallet
import transaction
import session_store

FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend"
)

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")


def require_session(f):
    """
    Decorator for protected endpoints. Reads the Authorization header,
    resolves it to a session via Redis, and stashes the session on
    flask.g.session for the view function to use. Rejects with 401
    if the token is missing/invalid/expired.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = session_store.extract_token(request.headers.get("Authorization", ""))
        session = session_store.get_session(token)
        if session is None:
            return jsonify(success=False, message="Session expired. Please log in again."), 401
        g.session = session
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------- #
# Frontend
# ---------------------------------------------------------------- #
@app.route("/")
def serve_index():
    return send_from_directory(FRONTEND_DIR, "index.html")


# ---------------------------------------------------------------- #
# Auth
# ---------------------------------------------------------------- #
@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    full_name = (data.get("full_name") or "").strip()
    email = (data.get("email") or "").strip()

    if not all([username, password, full_name, email]):
        return jsonify(success=False, message="All fields are required."), 400

    user_id = auth.register_user(username, password, full_name, email)
    if user_id is None:
        return jsonify(success=False, message="Username or email already exists."), 409

    return jsonify(success=True, message="Account created. You can log in now.")


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    user = auth.login_user(username, password)
    if user is None:
        return jsonify(success=False, message="Invalid username or password."), 401

    w = wallet.get_wallet_by_user_id(user["user_id"])
    session_payload = {
        "user_id": user["user_id"],
        "full_name": user["full_name"],
        "username": user["username"],
        "wallet_id": w["wallet_id"],
    }
    token = session_store.create_session(session_payload)

    return jsonify(
        success=True,
        token=token,
        user={**session_payload, "balance": w["balance"]},
    )


@app.route("/api/logout", methods=["POST"])
@require_session
def api_logout():
    token = session_store.extract_token(request.headers.get("Authorization", ""))
    session_store.destroy_session(token)
    return jsonify(success=True)


# ---------------------------------------------------------------- #
# Wallet (all scoped to the logged-in user's own wallet via session)
# ---------------------------------------------------------------- #
@app.route("/api/balance", methods=["GET"])
@require_session
def api_balance():
    wallet_id = g.session["wallet_id"]
    try:
        bal = wallet.get_balance(wallet_id)
        return jsonify(success=True, balance=bal)
    except ValueError as e:
        return jsonify(success=False, message=str(e)), 404


@app.route("/api/history", methods=["GET"])
@require_session
def api_history():
    wallet_id = g.session["wallet_id"]
    history = transaction.get_transaction_history(wallet_id)
    return jsonify(success=True, history=history)


# ---------------------------------------------------------------- #
# Transactions (wallet_id always comes from the session, never the
# client - the client can no longer act on an arbitrary wallet)
# ---------------------------------------------------------------- #
@app.route("/api/deposit", methods=["POST"])
@require_session
def api_deposit():
    data = request.get_json(force=True)
    wallet_id = g.session["wallet_id"]
    try:
        amount = float(data.get("amount"))
        transaction.deposit(wallet_id, amount)
        return jsonify(success=True, balance=wallet.get_balance(wallet_id))
    except Exception as e:
        return jsonify(success=False, message=str(e)), 400


@app.route("/api/withdraw", methods=["POST"])
@require_session
def api_withdraw():
    data = request.get_json(force=True)
    wallet_id = g.session["wallet_id"]
    try:
        amount = float(data.get("amount"))
        transaction.withdraw(wallet_id, amount)
        return jsonify(success=True, balance=wallet.get_balance(wallet_id))
    except Exception as e:
        return jsonify(success=False, message=str(e)), 400


@app.route("/api/transfer", methods=["POST"])
@require_session
def api_transfer():
    data = request.get_json(force=True)
    from_wallet_id = g.session["wallet_id"]  # always the logged-in user's own wallet
    try:
        to_wallet_id = int(data.get("to_wallet_id"))
        amount = float(data.get("amount"))
        transaction.transfer(from_wallet_id, to_wallet_id, amount)
        return jsonify(success=True, balance=wallet.get_balance(from_wallet_id))
    except Exception as e:
        return jsonify(success=False, message=str(e)), 400


if __name__ == "__main__":
    init_db()
    print("Digital Wallet running at http://localhost:5000")
    app.run(debug=True, port=5000)
