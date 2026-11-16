"""Smart Digital Wallet & Payment Transaction Management System - application factory."""
import logging
import os
import time
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from .ai.assistant import Assistant
from .ai.categorizer import Categorizer
from .ai.fraud import FraudEngine, training_contexts
from .config import ROOT, load_config
from .db import connect, init_db
from .security import hash_password
from .seed import seed_demo
from .services.audit import AuditLog
from .services.cache import make_cache
from .services.ledger import WalletService
from .services.locks import LockManager, WalletLocks
from .services.ratelimit import RateLimiter
from .services.redis_support import connect_redis
from .services.scheduler import PaymentScheduler
from .services.sessions import SessionStore
from .util import WalletError, iso

log = logging.getLogger("wallet")


def create_app(overrides: dict | None = None) -> Flask:
    cfg = load_config(overrides)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/static")
    app.config.update(cfg)
    Path(cfg["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    init_db(cfg["DB_PATH"])

    # ---- demo data on the very first run
    conn = connect(cfg["DB_PATH"])
    empty = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    conn.close()
    if cfg["AUTO_SEED"] and empty:
        info = seed_demo(cfg)
        log.info("demo data created: %d users, %d transactions", info["users"], info["transactions"])

    # ---- services
    redis_client = connect_redis(cfg["REDIS_URL"], cfg["USE_REDIS"])
    local_locks = LockManager("wallet-locks", default_timeout=10)
    locks = WalletLocks(local_locks, redis_client)
    cache = make_cache(redis_client, cfg["LRU_CAPACITY"], cfg["CACHE_TTL"])
    audit = AuditLog(cfg["AUDIT_LOG"])
    categorizer, fraud = Categorizer(), FraudEngine(cfg["RISK_MEDIUM"], cfg["RISK_HIGH"])
    conn = connect(cfg["DB_PATH"])
    categorizer.warm_start((r["text"], r["category"]) for r in conn.execute("SELECT text, category FROM category_feedback"))
    fraud.train(training_contexts(conn, cfg["OTP_THRESHOLD_PAISE"], cfg["TZ_OFFSET_MINUTES"]))
    conn.close()
    wallet = WalletService(cfg, locks, cache, audit, fraud, categorizer)
    scheduler = PaymentScheduler(cfg["DB_PATH"], wallet, cfg["SCHEDULER_WORKERS"], cfg["SCHEDULER_POLL_SECONDS"])
    app.extensions["wallet"] = SimpleNamespace(
        cfg=cfg, redis=redis_client, local_locks=local_locks, locks=locks, cache=cache, audit=audit, limiter=RateLimiter(redis_client),
        sessions=SessionStore(cfg["SESSION_TTL"], redis_client), categorizer=categorizer, fraud=fraud, wallet=wallet,
        assistant=Assistant(cfg), scheduler=scheduler, started_at=time.time(),
        dummy_hash=hash_password("not-a-real-password-1", cfg["PASSWORD_ITERATIONS"]))
    if cfg["START_SCHEDULER"] and (not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
        scheduler.start()

    # ---- routes
    from .routes import admin, ai, auth, oslab, wallet as wallet_routes
    for module in (auth, wallet_routes, ai, oslab, admin):
        app.register_blueprint(module.bp)

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/manifest.webmanifest")
    def manifest():
        return send_from_directory(app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json")

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "redis": redis_client is not None, "scheduler": scheduler.running, "time": iso()})

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                                                   "font-src https://fonts.gstatic.com; img-src 'self' data:; script-src 'self'; "
                                                   "connect-src 'self'; frame-ancestors 'none'")
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(WalletError)
    def wallet_error(e):
        resp = jsonify({"ok": False, "error": e.message, "code": e.code, **e.extra})
        resp.status_code = e.status
        if e.code == "rate_limited":
            resp.headers["Retry-After"] = str(e.extra.get("retry_after", 1))
        return resp

    @app.errorhandler(HTTPException)
    def http_error(e):
        if request.path.startswith("/api/"):
            msg = {404: "That API endpoint does not exist.", 405: "That method is not allowed here.",
                   413: "The request is too large."}.get(e.code, e.description)
            resp = jsonify({"ok": False, "error": msg, "code": e.name.lower().replace(" ", "_")})
            resp.status_code = e.code
            return resp
        return e

    @app.errorhandler(Exception)
    def crash(e):
        log.exception("unhandled error")
        resp = jsonify({"ok": False, "error": "Something went wrong on our side. Please try again.", "code": "server_error"})
        resp.status_code = 500
        return resp

    return app
