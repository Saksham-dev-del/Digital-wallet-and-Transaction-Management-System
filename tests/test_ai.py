import pytest

from app.ai import insights
from app.ai.assistant import Assistant
from app.ai.categorizer import Categorizer
from app.ai.fraud import FraudEngine, TxnContext
from app.services.ossim import compare_paging, simulate_cpu, simulate_paging
from app.util import utcnow


@pytest.fixture(scope="module")
def categorizer():
    return Categorizer()


@pytest.mark.parametrize("text,expected", [
    ("Swiggy dinner", "Food & Dining"), ("uber ride to campus", "Transport"), ("Netflix subscription", "Entertainment"),
    ("hostel rent october", "Rent & Housing"), ("bijli bill", "Bills & Recharge"), ("apollo pharmacy medicine", "Health"),
    ("college fees semester", "Education"), ("irctc ticket delhi", "Travel"), ("swigy order", "Food & Dining"),
    ("amazon order headphones", "Shopping"), ("zzzz qqq", "Other")])
def test_categorizer(categorizer, text, expected):
    assert categorizer.predict(text)["category"] == expected


def test_categorizer_learns_from_correction():
    c = Categorizer()
    assert c.predict("gaurav bhaiya")["category"] != "Education"
    for _ in range(2):
        c.learn("gaurav bhaiya", "Education")
    assert c.predict("gaurav bhaiya")["category"] == "Education"


def ctx(**kw):
    base = dict(kind="TRANSFER", amount_paise=250_00, balance_paise=18000_00, daily_limit_paise=50000_00, spent_24h_paise=0,
                otp_threshold_paise=5000_00, local_hour=14, history_amounts=[300_00, 150_00, 420_00, 250_00, 800_00, 199_00],
                is_new_recipient=False, recipient_age_hours=900)
    base.update(kw)
    return TxnContext(**base)


def test_fraud_levels_and_reasons():
    f = FraudEngine()
    assert f.assess(ctx()).level == "LOW"
    risky = f.assess(ctx(amount_paise=30000_00, balance_paise=32000_00, is_new_recipient=True, recipient_age_hours=2, local_hour=2))
    assert risky.level == "HIGH" and risky.score >= 70
    codes = {r["code"] for r in risky.reasons}
    assert {"drain", "new_account", "new_recipient", "night"} <= codes
    burst = f.assess(ctx(amount_paise=900_00, recent_ages_s=[30, 90, 200, 300, 500], recent_amounts=[900_00] * 5))
    assert any(r["code"] == "velocity" for r in burst.reasons)
    smurf = f.assess(ctx(amount_paise=4900_00, recent_ages_s=[3000, 7000], recent_amounts=[4800_00, 4950_00], balance_paise=40000_00))
    assert any(r["code"] == "structuring" for r in smurf.reasons)
    assert 0 <= smurf.score <= 100


def test_fraud_fallback_without_sklearn(monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("sklearn"):
            raise ImportError("no sklearn")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    f = FraudEngine()
    assert f.engine_name == "statistical-fallback"
    assert f.assess(ctx()).level == "LOW"
    assert f.assess(ctx(amount_paise=30000_00, balance_paise=32000_00, is_new_recipient=True, recipient_age_hours=2, local_hour=2)).level == "HIGH"


def test_insights_on_seeded_data(seeded):
    c = seeded.test_client()
    tok = c.post("/api/auth/login", json={"email": "aarav@wallet.test", "password": "Demo@1234"}).json["token"]
    ins = c.get("/api/ai/insights", headers={"Authorization": "Bearer " + tok}).json
    assert ins["total_spend_30d"] > 0 and ins["categories"] and ins["forecast"]["available"]
    names = " ".join(s["name"].lower() for s in ins["subscriptions"])
    assert "netflix" in names and "jio" in names
    assert 0 <= ins["health"]["score"] <= 100 and len(ins["daily"]) == 28
    chat = c.post("/api/ai/chat", json={"message": "is mahine food par kitna kharcha hua"}, headers={"Authorization": "Bearer " + tok}).json
    assert chat["intent"] == "spend" and chat["language"] == "hinglish" and "₹" in chat["reply"]
    pre = c.post("/api/wallet/transfer/preview", json={"to": "rohan@swallet", "amount": 300, "note": "dinner split"},
                 headers={"Authorization": "Bearer " + tok}).json
    assert pre["category"]["category"] == "Food & Dining" and pre["recipient"]["name"] == "Rohan Gupta"


def test_assistant_never_moves_money_and_prefills(seeded):
    c = seeded.test_client()
    h = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "aarav@wallet.test", "password": "Demo@1234"}).json["token"]}
    before = c.get("/api/wallet", headers=h).json["balance_paise"]
    r = c.post("/api/ai/chat", json={"message": "Rohan ko 500 bhejo"}, headers=h).json
    assert r["intent"] == "send_money" and r["action"] == {"type": "prefill_transfer", "to": "rohan@swallet", "amount": "500", "note": ""}
    assert c.get("/api/wallet", headers=h).json["balance_paise"] == before


def test_assistant_unknown_uses_help_when_no_key():
    a = Assistant({"ANTHROPIC_API_KEY": ""})
    now = utcnow()
    ins = insights.build([], income_30d=0, balance=0, flagged_30d=0, tz=330)
    out = a.answer("tell me a joke", {"name": "A", "balance_paise": 0, "tz": 330, "now": now, "rows": [], "insights": ins,
                                      "summary": {}, "recent": [], "flagged": [], "contacts": []})
    assert out["intent"] == "unknown" and out["source"] == "offline"


def test_forecast_needs_data():
    assert not insights.build([], income_30d=0, balance=0, flagged_30d=0, tz=330)["forecast"]["available"]


def test_cpu_scheduling_textbook_numbers():
    jobs = [{"pid": "P1", "arrival": 0, "burst": 5}, {"pid": "P2", "arrival": 1, "burst": 3},
            {"pid": "P3", "arrival": 2, "burst": 8}, {"pid": "P4", "arrival": 3, "burst": 6}]
    assert simulate_cpu(jobs, "FCFS")["avg_waiting"] == 5.75
    assert simulate_cpu(jobs, "SJF")["avg_waiting"] == 5.25
    assert simulate_cpu(jobs, "SRTF")["avg_waiting"] == 5.0
    rr = simulate_cpu(jobs, "RR", 2)
    assert sum(g["end"] - g["start"] for g in rr["gantt"] if g["pid"] != "idle") == 22
    with pytest.raises(ValueError):
        simulate_cpu([], "FCFS")


def test_page_replacement_textbook_numbers():
    refs = [7, 0, 1, 2, 0, 3, 0, 4, 2, 3, 0, 3, 2, 1, 2, 0, 1, 7, 0, 1]
    got = compare_paging(refs, 3)
    assert (got["FIFO"]["faults"], got["LRU"]["faults"], got["OPT"]["faults"]) == (15, 12, 9)
    belady = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]
    assert simulate_paging(belady, 3, "FIFO")["faults"] == 9 and simulate_paging(belady, 4, "FIFO")["faults"] == 10
