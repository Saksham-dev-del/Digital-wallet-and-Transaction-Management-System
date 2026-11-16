"""Demo data: a few users, merchants and ~75 days of realistic student spending, so every screen has something to show.
Created through the same low-level ledger primitives as real payments, so balances and the ledger always agree."""
import random
from datetime import timedelta

from .db import connect, tx
from .security import hash_password
from .services.ledger import apply_txn, insert_txn
from .util import iso, utcnow

DEMO_PASSWORD = "Demo@1234"
ADMIN_PASSWORD = "Admin@123"

PEOPLE = [  # name, email, phone, code, role
    ("Admin User", "admin@wallet.test", None, "admin@swallet", "admin"),
    ("Aarav Sharma", "aarav@wallet.test", "9876500001", "aarav@swallet", "user"),
    ("Priya Verma", "priya@wallet.test", "9876500002", "priya@swallet", "user"),
    ("Rohan Gupta", "rohan@wallet.test", "9876500003", "rohan@swallet", "user"),
    ("Neha Singh", "neha@wallet.test", "9876500004", "neha@swallet", "user"),
    ("Sunita Sharma", "sunita@wallet.test", "9876500005", "sunita@swallet", "user"),
]
MERCHANTS = ["Swiggy", "Zomato", "Uber India", "Netflix", "Amazon", "Jio Prepaid", "Apollo Pharmacy", "BigBasket",
             "Campus Canteen", "BookMyShow", "Hostel Office"]


def seed_demo(cfg: dict, days: int = 75) -> dict:
    rnd = random.Random(42)
    conn = connect(cfg["DB_PATH"])
    now = utcnow()
    tz = cfg["TZ_OFFSET_MINUTES"]
    born = iso(now - timedelta(days=days + 5))
    iters = cfg["PASSWORD_ITERATIONS"]
    user_hash, admin_hash, merchant_hash = hash_password(DEMO_PASSWORD, iters), hash_password(ADMIN_PASSWORD, iters), hash_password("x-merchant-no-login-" + str(rnd.random()), iters)
    wallet, bal = {}, {}

    def add_user(name, email, phone, code, role, pw_hash, kind="PERSONAL"):
        uid = conn.execute("INSERT INTO users (full_name,email,phone,password_hash,role,account_type,created_at) VALUES (?,?,?,?,?,?,?)",
                           (name, email, phone, pw_hash, role, kind, born)).lastrowid
        wid = conn.execute("INSERT INTO wallets (user_id,wallet_code,daily_limit_paise,created_at) VALUES (?,?,?,?)",
                           (uid, code, cfg["DEFAULT_DAILY_LIMIT_PAISE"], born)).lastrowid
        wallet[name], bal[wid] = wid, 0

    for name, email, phone, code, role in PEOPLE:
        add_user(name, email, phone, code, role, admin_hash if role == "admin" else user_hash)
    for m in MERCHANTS:
        slug = m.lower().replace(" ", "")
        add_user(m, f"{slug}@merchant.test", None, f"{slug}@swallet", "user", merchant_hash, "MERCHANT")

    n_events = 0

    def emit(ts, kind, src, dst, amount, note, category):
        nonlocal n_events
        if ts > now - timedelta(minutes=1):
            return
        s, d = wallet.get(src), wallet.get(dst)
        if kind == "TRANSFER" and bal[s] < amount:                           # top up first, like a real student would
            need = ((amount - bal[s]) // 500_000 + 1) * 500_000
            emit(ts - timedelta(minutes=2), "TOPUP", None, src, need, "Added from bank (UPI)", "Top-up")
        with tx(conn):
            t = insert_txn(conn, txn_type=kind, amount_paise=amount, from_wallet_id=s, to_wallet_id=d, note=note,
                           category=category, status="PENDING", created_at=iso(ts))
            apply_txn(conn, t["txn_id"], ts=iso(ts))
            conn.execute("UPDATE txn_status_history SET changed_at = ? WHERE txn_id = ?", (iso(ts), t["txn_id"]))
        if kind == "TOPUP":
            bal[d] += amount
        else:
            bal[s] -= amount
            bal[d] += amount
        n_events += 1

    def at(day_offset, hour, minute=0):
        local_midnight = (now + timedelta(minutes=tz)).replace(hour=0, minute=0, second=0, microsecond=0)
        local = local_midnight - timedelta(days=day_offset) + timedelta(hours=hour, minutes=minute)
        return local - timedelta(minutes=tz)

    food_notes = [("Swiggy", "Swiggy dinner"), ("Zomato", "Zomato lunch"), ("Swiggy", "Swiggy order late night"),
                  ("Campus Canteen", "chai nashta"), ("Campus Canteen", "canteen lunch"), ("Zomato", "Zomato order pizza")]
    for off in range(days, -1, -1):
        r = rnd.random
        # monthly family money, rent and subscriptions
        if off in (days - 1, days - 31, days - 61) and off >= 1:
            emit(at(off, 10, 5), "TOPUP", None, "Sunita Sharma", 40_000_00, "Added from bank (UPI)", "Top-up")
            emit(at(off, 10, 20), "TRANSFER", "Sunita Sharma", "Aarav Sharma", 12_000_00, "pocket money", "Friends & Family")
        if off in (days - 3, days - 33, days - 63) and off >= 1:
            emit(at(off, 11, 0), "TRANSFER", "Aarav Sharma", "Hostel Office", 6_000_00, "hostel rent", "Rent & Housing")
        if off % 30 == 4:
            emit(at(off, 9, 15), "TRANSFER", "Aarav Sharma", "Netflix", 649_00, "Netflix subscription", "Entertainment")
        if off % 28 == 6:
            emit(at(off, 9, 40), "TRANSFER", "Aarav Sharma", "Jio Prepaid", 299_00, "Jio recharge", "Bills & Recharge")
        # daily life
        for _ in range(rnd.choice([0, 1, 1, 2, 2, 3])):
            who, note = rnd.choice(food_notes)
            amt = rnd.randint(40, 90) * 100 if who == "Campus Canteen" else rnd.randint(120, 460) * 100
            emit(at(off, rnd.randint(8, 22), rnd.randint(0, 59)), "TRANSFER", "Aarav Sharma", who, amt, note, "Food & Dining")
        if r() < 0.4:
            emit(at(off, rnd.randint(8, 21), rnd.randint(0, 59)), "TRANSFER", "Aarav Sharma", "Uber India", rnd.randint(80, 260) * 100, "Uber ride to campus", "Transport")
        if off % 7 == 2:
            emit(at(off, 18, rnd.randint(0, 59)), "TRANSFER", "Aarav Sharma", "BigBasket", rnd.randint(400, 950) * 100, "groceries", "Groceries")
        if off % 11 == 5:
            emit(at(off, 20, rnd.randint(0, 59)), "TRANSFER", "Aarav Sharma", "Amazon", rnd.randint(500, 2500) * 100, "Amazon order", "Shopping")
        if r() < 0.06:
            emit(at(off, 17, 30), "TRANSFER", "Aarav Sharma", "Apollo Pharmacy", rnd.randint(150, 600) * 100, "medicine", "Health")
        if r() < 0.07:
            emit(at(off, 19, 45), "TRANSFER", "Aarav Sharma", "BookMyShow", rnd.randint(300, 650) * 100, "movie tickets", "Entertainment")
        if r() < 0.22:
            friend = rnd.choice(["Rohan Gupta", "Priya Verma", "Neha Singh"])
            emit(at(off, rnd.randint(13, 22), rnd.randint(0, 59)), "TRANSFER", "Aarav Sharma", friend, rnd.randint(2, 8) * 100_00 // 10, "dinner split", "Food & Dining")
        if r() < 0.12:
            friend = rnd.choice(["Rohan Gupta", "Priya Verma"])
            emit(at(off, rnd.randint(12, 21), rnd.randint(0, 59)), "TRANSFER", friend, "Aarav Sharma", rnd.randint(2, 6) * 100_00 // 10, "paid back", "Friends & Family")
        if off == 2:
            emit(at(off, 10, 5), "TOPUP", None, "Sunita Sharma", 20_000_00, "Added from bank (UPI)", "Top-up")
            emit(at(off, 10, 20), "TRANSFER", "Sunita Sharma", "Aarav Sharma", 10_000_00, "pocket money", "Friends & Family")
        if off % 20 == 9:
            emit(at(off, 12, 0), "TOPUP", None, "Aarav Sharma", 3_000_00, "Added from bank (UPI)", "Top-up")
        # the other friends have a little history of their own
        if r() < 0.25:
            who = rnd.choice(["Priya Verma", "Rohan Gupta", "Neha Singh"])
            emit(at(off, rnd.randint(9, 21), rnd.randint(0, 59)), "TRANSFER", who, rnd.choice(["Swiggy", "Zomato", "Uber India", "Amazon"]),
                 rnd.randint(100, 900) * 100, rnd.choice(["Swiggy dinner", "Zomato lunch", "Uber ride", "Amazon order"]),
                 "Food & Dining")
    conn.close()
    return {"users": len(PEOPLE) + len(MERCHANTS), "transactions": n_events, "demo_password": DEMO_PASSWORD,
            "admin_password": ADMIN_PASSWORD}
