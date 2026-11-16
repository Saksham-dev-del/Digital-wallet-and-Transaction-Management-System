from flask import Blueprint, g, jsonify

from ..ai import insights
from ..deps import auth_required, body, get_db, svc
from ..services import queries
from ..util import WalletError, utcnow

bp = Blueprint("ai", __name__, url_prefix="/api/ai")


def _insights(conn, user):
    s = svc()
    w = s.wallet.wallet_of(conn, user["user_id"])
    wid = w["wallet_id"]
    balance = s.wallet.balance(conn, wid)
    rows = queries.spending_rows(conn, wid)
    ins = insights.build(rows, income_30d=queries.income_30d(conn, wid), balance=balance,
                         flagged_30d=queries.flagged_30d(conn, wid), tz=s.cfg["TZ_OFFSET_MINUTES"])
    return w, rows, ins, balance


@bp.get("/insights")
@auth_required()
def get_insights():
    conn = get_db()
    w, _rows, ins, _bal = _insights(conn, g.user)
    ins["risk_overview"] = queries.risk_overview(conn, w["wallet_id"])
    return jsonify({"ok": True, **ins})


@bp.post("/chat")
@auth_required()
def chat():
    s, conn, data = svc(), get_db(), body()
    s.limiter.enforce("chat", g.user["user_id"], s.cfg["RATE_CHAT_PER_MIN"], 60)
    message = str(data.get("message", "")).strip()
    if not message:
        raise WalletError("Type a question first.", "empty_message")
    w, rows, ins, balance = _insights(conn, g.user)
    recent, _ = queries.list_transactions(conn, w["wallet_id"], s.cfg["TZ_OFFSET_MINUTES"], limit=10)
    for t in recent:
        t["counterparty_name"] = (t["counterparty"] or {}).get("name")
    ctx = {"name": g.user["full_name"].split()[0], "balance_paise": balance, "tz": s.cfg["TZ_OFFSET_MINUTES"], "now": utcnow(),
           "rows": rows, "insights": ins, "summary": s.wallet.summary(conn, g.user), "recent": recent,
           "flagged": queries.flagged_list(conn, w["wallet_id"]), "contacts": queries.contacts(conn, w["wallet_id"])}
    return jsonify({"ok": True, **s.assistant.answer(message, ctx)})


@bp.post("/categorize")
@auth_required()
def categorize():
    text = str(body().get("text", ""))[:120]
    return jsonify({"ok": True, **svc().categorizer.predict(text)})


@bp.get("/model")
@auth_required()
def model():
    s = svc()
    claude = bool(s.cfg["ANTHROPIC_API_KEY"])
    return jsonify({"ok": True, "fraud": s.fraud.info(), "categorizer": s.categorizer.info(),
                    "forecast": {"method": "EWMA level blended with same-weekday average", "horizon_days": 7},
                    "assistant": {"mode": "rules + Claude" if claude else "offline rules (set ANTHROPIC_API_KEY to enable Claude)",
                                  "model": s.cfg["ANTHROPIC_MODEL"] if claude else None,
                                  "languages": ["English", "Hinglish"]}})
