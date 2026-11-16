"""AI #2 - Fraud / risk engine (explainable + machine-learning).

Every payment gets a risk score 0-100:
  * RULES      - transparent checks that return plain-English reasons ("sends 92% of your balance")
  * ML         - an Isolation Forest (unsupervised anomaly detection) trained on normal payment behaviour.
                 It spots strange *combinations* of features that no single rule covers.
  score = 0.7 x rules + 0.3 x ML          LOW < 35 <= MEDIUM < 70 <= HIGH

  LOW    -> goes through          MEDIUM -> needs an OTP (step-up verification)
  HIGH   -> blocked and sent to the admin review queue (human in the loop)
If scikit-learn is missing the ML part falls back to a simple statistical anomaly score.
"""
import logging
import math
import statistics
import threading
from dataclasses import dataclass, field
from datetime import timedelta

from ..util import iso, parse_iso

log = logging.getLogger("wallet.fraud")

FEATURES = ["amount_log", "amount_vs_median", "balance_share", "limit_share", "night", "velocity_10m",
            "velocity_1h", "new_recipient", "recipient_age_log", "round_amount", "near_otp_limit"]


@dataclass
class TxnContext:
    kind: str                      # TRANSFER | WITHDRAW
    amount_paise: int
    balance_paise: int
    daily_limit_paise: int
    spent_24h_paise: int
    otp_threshold_paise: int
    local_hour: int
    local_minute: int = 0
    history_amounts: list = field(default_factory=list)   # recent successful outgoing amounts (paise)
    recent_ages_s: list = field(default_factory=list)     # age (seconds) of outgoing payments in last 24h
    recent_amounts: list = field(default_factory=list)    # their amounts (paise)
    is_new_recipient: bool = False
    recipient_age_hours: float | None = None
    failed_otp_1h: int = 0


def vectorize(c: TxnContext) -> list:
    amt = c.amount_paise / 100
    med = statistics.median(c.history_amounts) / 100 if len(c.history_amounts) >= 3 else None
    near = sum(1 for a in c.recent_amounts if 0.8 * c.otp_threshold_paise <= a < c.otp_threshold_paise)
    return [
        math.log1p(amt),
        min(amt / med, 25.0) if med else 1.0,
        min(c.amount_paise / max(c.balance_paise, 1), 1.5),
        min((c.spent_24h_paise + c.amount_paise) / max(c.daily_limit_paise, 1), 1.5),
        1.0 if 0 <= c.local_hour < 5 else 0.0,
        float(sum(1 for s in c.recent_ages_s if s <= 600)),
        float(sum(1 for s in c.recent_ages_s if s <= 3600)),
        1.0 if c.is_new_recipient else 0.0,
        math.log1p(c.recipient_age_hours) if c.recipient_age_hours is not None else math.log1p(2000),
        1.0 if (c.amount_paise >= 1_000_00 and c.amount_paise % 1_000_00 == 0) else 0.0,
        float(near),
    ]


@dataclass
class RiskResult:
    score: int
    level: str
    reasons: list
    rule_score: int
    ml_score: float
    engine: str

    def as_dict(self) -> dict:
        return {"score": self.score, "level": self.level, "reasons": self.reasons, "rule_score": self.rule_score,
                "ml_score": round(self.ml_score, 3), "engine": self.engine}


class FraudEngine:
    def __init__(self, medium: int = 35, high: int = 70):
        self.medium, self.high = medium, high
        self._lock = threading.Lock()
        self.model = None
        self.engine_name = "statistical-fallback"
        self.lo, self.hi = 0.0, 1.0
        self.trained_on = {"synthetic": 0, "real": 0}
        self.trained_at = None
        self.train([])

    # ------------------------------------------------------------------ rules (explainable)
    def _rules(self, c: TxnContext) -> list:
        out, amt = [], c.amount_paise
        share = amt / max(c.balance_paise, 1)
        if share >= 0.8 and amt >= 1_000_00:
            out.append(("drain", f"Sends {round(share * 100)}% of the wallet balance", 25))
        elif share >= 0.5 and amt >= 2_000_00:
            out.append(("half_balance", f"Sends about {round(share * 100)}% of the wallet balance", 10))
        if len(c.history_amounts) >= 3:
            ratio = amt / max(statistics.median(c.history_amounts), 1)
            if ratio >= 5 and amt >= 1_000_00:
                out.append(("unusual_size", f"{ratio:.0f}x bigger than a usual payment from this wallet", 25))
            elif ratio >= 3 and amt >= 500_00:
                out.append(("unusual_size", f"{ratio:.1f}x bigger than a usual payment from this wallet", 15))
        if c.kind == "TRANSFER":
            if c.is_new_recipient and amt >= 2_000_00:
                out.append(("new_recipient", "First payment to this recipient", 15))
            if c.recipient_age_hours is not None and c.recipient_age_hours < 24 and amt >= 1_000_00:
                out.append(("new_account", "Recipient's wallet is less than a day old", 20))
        last10 = sum(1 for s in c.recent_ages_s if s <= 600)
        last60 = sum(1 for s in c.recent_ages_s if s <= 3600)
        if last10 >= 4:
            out.append(("velocity", f"{last10 + 1} payments within 10 minutes", 20))
        elif last60 >= 8:
            out.append(("velocity", f"{last60 + 1} payments within an hour", 10))
        if 0 <= c.local_hour < 5 and amt >= 1_000_00:
            out.append(("night", f"Late-night payment ({c.local_hour:02d}:{c.local_minute:02d})", 10))
        if (c.spent_24h_paise + amt) / max(c.daily_limit_paise, 1) >= 0.8:
            out.append(("daily_limit", "Takes the wallet close to its daily limit", 10))
        if c.failed_otp_1h >= 2:
            out.append(("otp_failures", "Wrong OTPs were entered recently", 15))
        thr = c.otp_threshold_paise
        near = sum(1 for a in c.recent_amounts if 0.8 * thr <= a < thr) + (1 if 0.8 * thr <= amt < thr else 0)
        if near >= 3:
            out.append(("structuring", f"{near} payments just under the OTP limit in 24 hours", 20))
        if amt >= 10_000_00 and amt % 1_000_00 == 0:
            out.append(("round", "Large round-number amount", 5))
        return out

    # ------------------------------------------------------------------ machine learning
    def _synthetic_normal(self, n: int = 1500):
        import numpy as np

        rng = np.random.default_rng(7)
        amount = np.exp(rng.normal(5.9, 1.0, n))                 # median about Rs 365
        rows = np.column_stack([
            np.log1p(amount),
            np.clip(np.exp(rng.normal(0, 0.6, n)), 0.05, 6),
            np.clip(rng.beta(1.2, 12, n), 0, 1.2),
            np.clip(rng.beta(1.5, 10, n), 0, 1.2),
            (rng.random(n) < 0.03).astype(float),
            rng.poisson(0.15, n).astype(float),
            rng.poisson(0.7, n).astype(float),
            (rng.random(n) < 0.25).astype(float),
            np.log1p(rng.uniform(48, 2500, n)),
            (rng.random(n) < 0.12).astype(float),
            (rng.random(n) < 0.02).astype(float),
        ])
        return rows

    def train(self, real_contexts: list) -> dict:
        """(Re)train on synthetic 'normal' behaviour + every real successful payment in the database."""
        with self._lock:
            try:
                import numpy as np
                from sklearn.ensemble import IsolationForest

                synth = self._synthetic_normal()
                real = np.array([vectorize(c) for c in real_contexts[-5000:]]) if real_contexts else np.empty((0, len(FEATURES)))
                x = np.vstack([synth, real]) if len(real) else synth
                model = IsolationForest(n_estimators=120, max_samples=min(256, len(x)), contamination=0.02, random_state=7)
                model.fit(x)
                raw = -model.score_samples(x)
                # calibrate raw isolation scores to 0..1: normal behaviour ~0, clearly-abnormal ~1
                self.lo = float(np.percentile(raw, 75))
                self.hi = max(float(np.percentile(raw, 99.9)) + 0.10, self.lo + 0.20)
                self.model, self.engine_name = model, "IsolationForest (scikit-learn)"
                self.trained_on = {"synthetic": len(synth), "real": len(real)}
            except Exception as exc:
                log.warning("scikit-learn model unavailable (%s) - using statistical fallback", exc)
                self.model, self.engine_name = None, "statistical-fallback"
                self.trained_on = {"synthetic": 0, "real": len(real_contexts)}
            self.trained_at = iso()
            return self.info()

    def ml_score(self, vec: list) -> float:
        """0 = looks normal ... 1 = very unusual"""
        if self.model is not None:
            raw = float(-self.model.score_samples([vec])[0])
            return max(0.0, min(1.0, (raw - self.lo) / max(self.hi - self.lo, 1e-9)))
        # fallback: simple distance-style heuristic on the most informative features
        signals = [(vec[1] - 3) / 8, (vec[2] - 0.6) / 0.6, (vec[5] - 2) / 4, (vec[3] - 0.8) / 0.5]
        return max(0.0, min(1.0, max(signals)))

    # ------------------------------------------------------------------ public API
    def assess(self, ctx: TxnContext) -> RiskResult:
        rules = self._rules(ctx)
        rule_score = min(100, sum(p for _, _, p in rules))
        ml = self.ml_score(vectorize(ctx))
        score = int(round(min(100, 0.7 * rule_score + 30 * ml)))
        level = "HIGH" if score >= self.high else "MEDIUM" if score >= self.medium else "LOW"
        reasons = [{"code": c, "text": t, "points": p} for c, t, p in sorted(rules, key=lambda r: -r[2])]
        if ml >= 0.6:
            reasons.append({"code": "ai_anomaly", "points": round(ml * 30),
                            "text": f"AI model: this payment looks unusual compared with normal behaviour (anomaly {ml:.2f})"})
        return RiskResult(score, level, reasons, rule_score, ml, self.engine_name)

    def info(self) -> dict:
        return {"engine": self.engine_name, "features": FEATURES, "trained_on": self.trained_on,
                "trained_at": self.trained_at, "thresholds": {"medium": self.medium, "high": self.high},
                "formula": "score = 0.7 x rule points + 0.3 x ML anomaly (0-100)"}


def training_contexts(conn, otp_threshold: int, tz_offset: int) -> list:
    """Rebuild a TxnContext for every successful outgoing payment in the database (oldest first)."""
    rows = conn.execute(
        """SELECT t.txn_type, t.from_wallet_id, t.to_wallet_id, t.amount_paise, t.created_at,
                  e.balance_after_paise, w.daily_limit_paise, rw.created_at AS to_created
           FROM transactions t
           JOIN ledger_entries e ON e.txn_id = t.txn_id AND e.wallet_id = t.from_wallet_id
           JOIN wallets w        ON w.wallet_id = t.from_wallet_id
           LEFT JOIN wallets rw  ON rw.wallet_id = t.to_wallet_id
           WHERE t.status = 'SUCCESS' AND t.from_wallet_id IS NOT NULL
           ORDER BY t.created_at, t.txn_id""").fetchall()
    state, out = {}, []
    for r in rows:
        when = parse_iso(r["created_at"])
        st = state.setdefault(r["from_wallet_id"], {"hist": [], "seen": set(), "events": []})
        events = [(a, t) for a, t in st["events"] if when - t <= timedelta(hours=24)]
        local = when + timedelta(minutes=tz_offset)
        out.append(TxnContext(
            kind=r["txn_type"], amount_paise=r["amount_paise"],
            balance_paise=r["balance_after_paise"] + r["amount_paise"],
            daily_limit_paise=r["daily_limit_paise"], spent_24h_paise=sum(a for a, _ in events),
            otp_threshold_paise=otp_threshold, local_hour=local.hour, local_minute=local.minute,
            history_amounts=st["hist"][-30:], recent_ages_s=[(when - t).total_seconds() for _, t in events],
            recent_amounts=[a for a, _ in events],
            is_new_recipient=r["to_wallet_id"] not in st["seen"],
            recipient_age_hours=((when - parse_iso(r["to_created"])).total_seconds() / 3600) if r["to_created"] else None))
        st["hist"].append(r["amount_paise"])
        st["seen"].add(r["to_wallet_id"])
        st["events"] = events + [(r["amount_paise"], when)]
    return out
