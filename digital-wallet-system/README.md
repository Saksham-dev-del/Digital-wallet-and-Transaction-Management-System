# Digital Wallet and Payment Transaction Management System
### PBL Project — Operating Systems + DBMS (+ Redis)

**Status: a working core with a real web frontend and Redis-backed
session/caching/locking.** Not a finished product — see "Pending
Work" below for what's intentionally left for the next phase.

---

## Project Idea

A simplified digital wallet (like Paytm/PhonePe internals) where users
can register, hold a balance, deposit, withdraw, and transfer money to
other wallets. Three things are tied together:

- **DBMS**: relational schema design, foreign keys, ACID-safe
  transactions (BEGIN/COMMIT/ROLLBACK) for every money movement, and a
  full transaction ledger.
- **Operating Systems**: concurrency control — multiple simultaneous
  requests on the same wallet are handled safely using per-wallet
  locks (mutexes), avoiding race conditions on the balance field.
- **Redis**: an in-memory layer sitting in front of SQLite for three
  jobs — login sessions, a distributed lock, and balance caching (see
  "Where Redis Fits In" below). SQLite always remains the source of
  truth; Redis only makes things faster/safer.

## Tech Stack
- Python 3 (sqlite3, threading, hashlib — standard library)
- SQLite (file-based relational DB — easy to demo without a server)
- **Redis** (sessions, distributed locking, balance caching)
- Flask (thin REST API layer over the core logic)
- Plain HTML/CSS/JS frontend (no build step, no framework) — a
  "digital passbook" styled dashboard

## Where Redis Fits In

| Concern | Before (v1) | Now (with Redis) |
|---|---|---|
| Login sessions | None — frontend just remembered the user in `localStorage` and the backend trusted whatever `wallet_id` it sent | `session_store.py`: login creates a random token, stored in Redis with a 24h expiry, mapped to the user's real wallet. Every protected API call sends `Authorization: Bearer <token>`; the backend resolves the wallet from **Redis**, never from client input |
| Wallet locking | `threading.Lock` per wallet — only works within a single Python process | `concurrency.py` now has **both**: the original `threading.Lock` (fast path) plus a `RedisLock` (atomic `SET NX PX` + a Lua script for safe release) — the Redis lock would still work correctly even if this app were scaled to multiple server processes |
| Balance reads | Hit SQLite on every single read | `wallet.py` uses a cache-aside pattern: check Redis first (`wallet:balance:<id>`, 30s TTL) → on a miss, read SQLite and populate the cache. Every deposit/withdraw/transfer explicitly invalidates the cache so stale balances are never served |

If Redis isn't running, `wallet.py` and `concurrency.py` detect that
and fall back gracefully (skip the cache, skip the distributed lock —
the in-process `threading.Lock` still protects a single-process run).
This is a deliberate trade-off for a student project: it means a
missing Redis server degrades performance/robustness, but doesn't
crash the app outright.

## Folder Structure
```
digital-wallet-system/
├── database/
│   ├── schema.sql              # DDL: users, wallets, transactions, audit log
│   └── wallet_system.db        # created automatically on first run
├── src/
│   ├── db.py                   # connection + schema initialization
│   ├── cache.py                 # Redis connection helper (+ health check)
│   ├── session_store.py         # Redis-backed login session tokens
│   ├── auth.py                  # register / login (password check)
│   ├── wallet.py                # wallet lookups + Redis balance cache
│   ├── transaction.py           # deposit / withdraw / transfer (ACID + locking)
│   ├── concurrency.py           # OS module: threading.Lock + RedisLock, race demo
│   ├── main.py                  # CLI entry point (still works, terminal-only demo)
│   └── api.py                   # Flask REST API (token-authenticated) + serves frontend
├── frontend/
│   ├── index.html               # login/register + dashboard markup
│   ├── css/style.css            # passbook-styled design system
│   └── js/app.js                 # calls the API with the session token, renders the ledger
├── docs/
│   └── ER_Diagram_Description.md
├── requirements.txt
└── README.md
```

## How to Run (Web app — recommended)

**1. Install and start Redis** (one-time setup, then it just needs to
be running in the background):
```bash
# Ubuntu/Debian/WSL:
sudo apt-get install redis-server
redis-server --daemonize yes

# macOS (Homebrew):
brew install redis
brew services start redis

# Windows: easiest is via WSL (use the Ubuntu steps above), or
# run Redis in Docker: docker run -d -p 6379:6379 redis
```
Check it's up: `redis-cli ping` should print `PONG`.

**2. Install Python dependencies and run the app:**
```bash
pip install flask redis
cd src
python api.py
```
Then open **http://localhost:5000** in a browser. The database is
created automatically on first run. Register an account, log in, and
use Deposit / Withdraw / Transfer from the dashboard — the ledger
table updates live below.

*(If Redis isn't installed/running, the app still starts and still
works — you just lose session persistence across server restarts,
the distributed lock, and the balance cache. See "Where Redis Fits
In" above.)*

## How to Run (Terminal-only version)
The original CLI still works independently of the web app (and still
benefits from the Redis cache/lock transparently, if Redis is running):
```bash
cd src
python main.py
```

### See the OS concurrency demo separately
```bash
cd src
python concurrency.py
```
This spins up 5 threads simultaneously trying to withdraw ₹300 each
from a wallet that only has ₹1000 (i.e. only 3 can succeed) and shows
that locking (both the in-process lock and, if Redis is running, the
distributed lock) keeps the final balance mathematically correct
instead of going negative.

---

## What's Implemented

- [x] Full relational schema: users, wallets, transactions, audit log
- [x] Foreign keys + CHECK constraints (referential + domain integrity)
- [x] User registration & login (with password hashing)
- [x] Wallet auto-created with each user (1-to-1)
- [x] Deposit, Withdraw, Transfer — each wrapped in an explicit DB
      transaction (BEGIN/COMMIT/ROLLBACK) for atomicity
- [x] Full transaction ledger with success/failure logging
- [x] Per-wallet mutex locking (threading.Lock) to prevent race
      conditions on concurrent balance updates (OS synchronization)
- [x] **Redis-backed distributed lock** (`RedisLock`) as a second
      layer, correct even across multiple app processes
- [x] **Redis-backed login sessions** — real tokens with expiry,
      replacing the old "trust whatever the client sends" approach
- [x] **Redis balance cache** (cache-aside + invalidation-on-write)
- [x] Working CLI to demo the whole flow end-to-end
- [x] Flask REST API, now token-authenticated, exposing
      register/login/logout/deposit/withdraw/transfer/history/balance
- [x] Web frontend (login, register, balance, deposit/withdraw/transfer, live ledger)
- [x] ER diagram description

## Pending Work

This is what's left for the next phase — listing it explicitly so
it's clear what's scoped in vs out at this stage:

- [ ] **Deadlock handling for transfers**: two simultaneous transfers
      in opposite directions (A→B and B→A) can currently deadlock at
      both the threading.Lock and RedisLock layers, since locks
      aren't acquired in a fixed global order. Needs lock-ordering or
      a Banker's Algorithm-style avoidance scheme.
- [ ] **Process scheduling simulation** for a transaction request
      queue (FCFS/Priority scheduling of pending transactions) — a
      classic OS topic not yet touched.
- [ ] Proper password hashing with per-user random salt (bcrypt/argon2)
      instead of the current static-salt SHA-256 placeholder.
- [ ] Admin/analytics dashboard (spending trends, top wallets, etc.)
- [ ] Automated test suite (unit tests for transaction.py, concurrency.py)
- [ ] Concurrency stress test with a larger thread pool + connection
      pooling / semaphore limiting max simultaneous DB connections.
- [ ] Formal database normalization write-up (1NF/2NF/3NF proof) for
      the report.
- [ ] Backup & recovery demonstration (DBMS reliability topic).
- [ ] Rate limiting deposits/withdrawals per wallet using Redis
      (`INCR` + `EXPIRE`) to prevent request spamming — a natural
      next Redis use case once the above is done.

## Suggested Next Steps (for you to continue)
1. Implement lock ordering in `transaction.py -> transfer()` to fix
   the deadlock gap (this is usually the professor's favorite
   question in OS+DBMS PBLs, so it's worth doing next).
2. Add a `tests/` folder with a few unit tests using `unittest`.
3. Draw the ER diagram visually from `docs/ER_Diagram_Description.md`
   using draw.io for the final report.
4. If you want to show off the Redis work specifically in your viva,
   run `redis-cli monitor` in one terminal while using the app in the
   browser — you'll see every session lookup, lock acquire/release,
   and cache hit/miss happen live, which is a great demo moment.
