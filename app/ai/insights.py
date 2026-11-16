"""AI #3 - Spending insights, forecast and financial-health score.

Input is a list of *spending rows* (outgoing payments to other wallets):
    {"ts": datetime(UTC), "amount": paise, "category": str, "note": str, "party": str}
Everything here is plain statistics - easy to explain in a viva:
  * forecast   : exponentially-weighted moving average (recent days matter more) blended with the
                 average for the same weekday (people spend differently on Fridays and Sundays)
  * anomalies  : days whose spend is more than 2 standard deviations above the mean
  * subscriptions : same payee + same amount repeating about every 7 or 30 days
  * health score  : savings rate + balance runway + spending stability + safety flags
"""
import re
import statistics
from collections import defaultdict
from datetime import date, timedelta

from ..util import inr, utcnow

_MONTHS = r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"


def _d(ts, tz) -> date:
    return (ts + timedelta(minutes=tz)).date()


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def spend_between(rows, start: date, end: date, tz: int, category: str | None = None) -> int:
    return sum(r["amount"] for r in rows
               if start <= _d(r["ts"], tz) <= end and (category is None or r["category"] == category))


def daily_series(rows, today: date, days: int, tz: int) -> list:
    totals = defaultdict(int)
    for r in rows:
        totals[_d(r["ts"], tz)] += r["amount"]
    return [{"date": (today - timedelta(days=i)).isoformat(), "amount": totals.get(today - timedelta(days=i), 0)}
            for i in range(days - 1, -1, -1)]


def forecast(series: list, today: date, horizon: int = 7, alpha: float = 0.3) -> dict:
    amounts = [s["amount"] for s in series]
    if sum(1 for a in amounts if a > 0) < 3:
        return {"available": False, "reason": "Make a few more payments and a forecast will appear here."}
    level = amounts[0]
    for a in amounts[1:]:
        level = alpha * a + (1 - alpha) * level                      # EWMA
    by_weekday = defaultdict(list)
    for s in series:
        by_weekday[date.fromisoformat(s["date"]).weekday()].append(s["amount"])
    overall = statistics.mean(amounts)
    out = []
    for i in range(1, horizon + 1):
        d = today + timedelta(days=i)
        vals = by_weekday.get(d.weekday(), [])
        wd = statistics.mean(vals) if len(vals) >= 2 else overall
        out.append({"date": d.isoformat(), "amount": max(0, round(0.5 * level + 0.5 * wd))})
    return {"available": True, "method": "EWMA level blended with same-weekday average",
            "next_days": out, "next_7_total": sum(x["amount"] for x in out[:7])}


def detect_subscriptions(rows, tz: int) -> list:
    def norm(text):
        t = re.sub(r"\d+", " ", text.lower())
        t = re.sub(rf"\b({_MONTHS})[a-z]*\b", " ", t)
        return " ".join(re.findall(r"[a-z]+", t)[:2])

    groups = defaultdict(list)
    for r in rows:
        key = norm(r["note"]) or norm(r["party"])
        if key:
            groups[key].append(r)
    subs = []
    for key, rs in groups.items():
        if len(rs) < 2:
            continue
        rs = sorted(rs, key=lambda r: r["ts"])
        med = statistics.median(r["amount"] for r in rs)
        if med <= 0 or max(abs(r["amount"] - med) / med for r in rs) > 0.1:
            continue
        gaps = [(b["ts"] - a["ts"]).days for a, b in zip(rs, rs[1:])]
        avg = statistics.mean(gaps)
        if 27 <= avg <= 34 and all(abs(g - avg) <= 5 for g in gaps):
            every = "monthly"
        elif 6 <= avg <= 8 and all(abs(g - avg) <= 2 for g in gaps):
            every = "weekly"
        else:
            continue
        last = rs[-1]
        subs.append({"name": (last["note"] or last["party"]).title(), "amount": int(med), "every": every,
                     "payments": len(rs), "last_date": _d(last["ts"], tz).isoformat(),
                     "next_expected": (_d(last["ts"], tz) + timedelta(days=round(avg))).isoformat(),
                     "per_month": int(med * (4.33 if every == "weekly" else 1))})
    return sorted(subs, key=lambda s: -s["per_month"])


def health_score(income_30d, spend_30d, balance, series, flagged_30d) -> dict:
    amounts = [s["amount"] for s in series]
    avg_daily = spend_30d / 30 if spend_30d else 0
    factors = []
    # 1. savings rate (40 pts) - 30% or more saved = full marks
    if income_30d > 0:
        rate = (income_30d - spend_30d) / income_30d
        pts, note = 40 * _clamp(rate / 0.3), f"You kept {round(max(rate, 0) * 100)}% of the money that came in"
    else:
        pts, note = 20, "No money came in during the last 30 days, so this is scored neutrally"
    factors.append({"name": "Savings rate", "points": round(pts), "max": 40, "note": note})
    # 2. runway (25 pts) - balance covers 30+ days of spending = full marks
    if avg_daily > 0:
        days = balance / avg_daily
        pts, note = 25 * _clamp(days / 30), f"Balance covers about {int(days)} days at the current pace"
    else:
        pts, note = 25, "No spending in the last 30 days"
    factors.append({"name": "Balance runway", "points": round(pts), "max": 25, "note": note})
    # 3. stability (20 pts) - coefficient of variation of daily spend
    mean = statistics.mean(amounts) if amounts else 0
    if mean > 0 and len(amounts) > 1:
        cv = statistics.pstdev(amounts) / mean
        pts, note = 20 * (1 - _clamp(cv / 3)), "Steady daily spending scores higher than big spikes"
    else:
        pts, note = 20, "Not enough activity to measure spikes"
    factors.append({"name": "Spending stability", "points": round(pts), "max": 20, "note": note})
    # 4. safety (15 pts) - every flagged or blocked payment costs 5
    pts = max(0, 15 - 5 * flagged_30d)
    factors.append({"name": "Payment safety", "points": pts, "max": 15,
                    "note": "No flagged payments" if not flagged_30d else f"{flagged_30d} payment(s) were flagged by the AI"})
    score = sum(f["points"] for f in factors)
    label = "Excellent" if score >= 80 else "Good" if score >= 60 else "Fair" if score >= 40 else "Needs attention"
    return {"score": score, "label": label, "factors": factors}


def build(rows, *, income_30d: int, balance: int, flagged_30d: int, tz: int, now=None) -> dict:
    now = now or utcnow()
    today = _d(now, tz)
    series28 = daily_series(rows, today, 28, tz)
    d30, d60 = today - timedelta(days=29), today - timedelta(days=59)
    cur = defaultdict(int)
    prev = defaultdict(int)
    for r in rows:
        day = _d(r["ts"], tz)
        if day >= d30:
            cur[r["category"]] += r["amount"]
        elif day >= d60:
            prev[r["category"]] += r["amount"]
    total30 = sum(cur.values())
    categories = []
    for cat, amt in sorted(cur.items(), key=lambda kv: -kv[1]):
        before = prev.get(cat, 0)
        change = round((amt - before) / before * 100) if before else None
        categories.append({"category": cat, "amount": amt, "share": round(amt / total30, 3) if total30 else 0,
                           "change_pct": change})
    week = spend_between(rows, today - timedelta(days=6), today, tz)
    last_week = spend_between(rows, today - timedelta(days=13), today - timedelta(days=7), tz)
    month_start = today.replace(day=1)
    mtd = spend_between(rows, month_start, today, tz)
    fc = forecast(series28, today, 7)
    if fc["available"]:
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        left = (next_month - today).days - 1
        extra = fc["next_days"] if left <= 7 else fc["next_days"] + [fc["next_days"][i % 7] for i in range(7, left)]
        fc["month_to_date"] = mtd
        fc["month_end_projection"] = mtd + sum(x["amount"] for x in extra[:left])
    amounts = [s["amount"] for s in series28]
    anomalies = []
    if len(amounts) > 7 and statistics.pstdev(amounts) > 0:
        mu, sd = statistics.mean(amounts), statistics.pstdev(amounts)
        anomalies = [s for s in series28 if s["amount"] > mu + 2 * sd and s["amount"] >= 500_00]
    subs = detect_subscriptions([r for r in rows if _d(r["ts"], tz) >= today - timedelta(days=120)], tz)
    health = health_score(income_30d, total30, balance, series28, flagged_30d)

    tips = []
    if categories and total30:
        top = categories[0]
        if top["share"] >= 0.4:
            tips.append(f"{top['category']} is {round(top['share'] * 100)}% of your spending in the last 30 days - your biggest slice.")
        for c in categories:
            if c["change_pct"] is not None and c["change_pct"] >= 40 and c["amount"] >= 500_00:
                tips.append(f"{c['category']} spending is up {c['change_pct']}% compared with the 30 days before.")
                break
    if last_week and week > last_week * 1.3 and week >= 500_00:
        tips.append(f"This week you spent {inr(week)}, {round((week / last_week - 1) * 100)}% more than last week.")
    elif last_week and week < last_week * 0.8:
        tips.append(f"Nice - you spent {round((1 - week / last_week) * 100)}% less than last week.")
    if total30 and balance / (total30 / 30) < 10:
        tips.append(f"At the current pace your balance lasts about {int(balance / (total30 / 30))} days. Consider adding money.")
    if subs:
        tips.append(f"You have {len(subs)} recurring payment(s) costing about {inr(sum(s['per_month'] for s in subs))} a month.")
    if not tips:
        tips.append("Make a few payments and tips based on your own spending will appear here." if not total30
                    else "Your spending looks steady. Keep it up.")
    return {"as_of": today.isoformat(), "total_spend_30d": total30, "avg_daily": round(total30 / 30),
            "week_spend": week, "last_week_spend": last_week, "month_to_date": mtd,
            "categories": categories, "daily": series28, "forecast": fc, "health": health,
            "subscriptions": subs, "anomaly_days": anomalies, "tips": tips[:5]}
