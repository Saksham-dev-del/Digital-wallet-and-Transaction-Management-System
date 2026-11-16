-- =====================================================================================
--  Smart Digital Wallet - relational schema (SQLite)
--  DBMS concepts shown here: 3NF tables, PK/FK, CHECK + UNIQUE constraints, indexes,
--  triggers (append-only ledger, status history), views (statement, reconciliation).
--  Money is stored as INTEGER paise so there is never a rounding error.
-- =====================================================================================
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name     TEXT    NOT NULL CHECK (length(trim(full_name)) >= 2),
    email         TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    phone         TEXT    UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'user'     CHECK (role IN ('user', 'admin')),
    account_type  TEXT    NOT NULL DEFAULT 'PERSONAL' CHECK (account_type IN ('PERSONAL', 'MERCHANT')),
    status        TEXT    NOT NULL DEFAULT 'active'   CHECK (status IN ('active', 'frozen')),
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS wallets (
    wallet_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
    wallet_code       TEXT    NOT NULL UNIQUE COLLATE NOCASE,          -- public handle, e.g. aarav@swallet
    balance_paise     INTEGER NOT NULL DEFAULT 0 CHECK (balance_paise >= 0),   -- can never go negative
    daily_limit_paise INTEGER NOT NULL DEFAULT 5000000 CHECK (daily_limit_paise > 0),
    version           INTEGER NOT NULL DEFAULT 0,                      -- bumped on every change (optimistic-lock style)
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS transactions (
    txn_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_ref        TEXT    NOT NULL UNIQUE,
    txn_type       TEXT    NOT NULL CHECK (txn_type IN ('TOPUP', 'WITHDRAW', 'TRANSFER')),
    from_wallet_id INTEGER REFERENCES wallets(wallet_id),
    to_wallet_id   INTEGER REFERENCES wallets(wallet_id),
    amount_paise   INTEGER NOT NULL CHECK (amount_paise > 0),
    note           TEXT    NOT NULL DEFAULT '',
    category       TEXT    NOT NULL DEFAULT 'Other',
    status         TEXT    NOT NULL CHECK (status IN ('PENDING', 'PENDING_OTP', 'SUCCESS', 'FAILED', 'BLOCKED')),
    failure_reason TEXT,
    risk_score     INTEGER CHECK (risk_score BETWEEN 0 AND 100),
    risk_level     TEXT    CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH')),
    risk_reasons   TEXT,                                               -- JSON array written by the AI fraud engine
    source         TEXT    NOT NULL DEFAULT 'WEB' CHECK (source IN ('WEB', 'SCHEDULED', 'SYSTEM')),
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at   TEXT,
    CHECK (
        (txn_type = 'TOPUP'    AND from_wallet_id IS NULL     AND to_wallet_id IS NOT NULL) OR
        (txn_type = 'WITHDRAW' AND from_wallet_id IS NOT NULL AND to_wallet_id IS NULL) OR
        (txn_type = 'TRANSFER' AND from_wallet_id IS NOT NULL AND to_wallet_id IS NOT NULL
                               AND from_wallet_id <> to_wallet_id)
    )
);
CREATE INDEX IF NOT EXISTS idx_txn_from ON transactions(from_wallet_id, created_at);
CREATE INDEX IF NOT EXISTS idx_txn_to   ON transactions(to_wallet_id, created_at);
CREATE INDEX IF NOT EXISTS idx_txn_status ON transactions(status);

-- Double-entry style ledger: every posted transaction creates one or two immutable entries
CREATE TABLE IF NOT EXISTS ledger_entries (
    entry_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id              INTEGER NOT NULL REFERENCES transactions(txn_id),
    wallet_id           INTEGER NOT NULL REFERENCES wallets(wallet_id),
    direction           TEXT    NOT NULL CHECK (direction IN ('DEBIT', 'CREDIT')),
    amount_paise        INTEGER NOT NULL CHECK (amount_paise > 0),
    balance_after_paise INTEGER NOT NULL CHECK (balance_after_paise >= 0),
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_ledger_wallet ON ledger_entries(wallet_id, entry_id);
CREATE INDEX IF NOT EXISTS idx_ledger_txn    ON ledger_entries(txn_id);

CREATE TRIGGER IF NOT EXISTS trg_ledger_no_update BEFORE UPDATE ON ledger_entries
BEGIN SELECT RAISE(ABORT, 'ledger_entries is append-only: updates are not allowed'); END;

CREATE TRIGGER IF NOT EXISTS trg_ledger_no_delete BEFORE DELETE ON ledger_entries
BEGIN SELECT RAISE(ABORT, 'ledger_entries is append-only: deletes are not allowed'); END;

-- Every status change of a transaction is recorded automatically (audit trail by trigger)
CREATE TABLE IF NOT EXISTS txn_status_history (
    hist_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id     INTEGER NOT NULL REFERENCES transactions(txn_id) ON DELETE CASCADE,
    old_status TEXT,
    new_status TEXT NOT NULL,
    changed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TRIGGER IF NOT EXISTS trg_txn_status_insert AFTER INSERT ON transactions
BEGIN
    INSERT INTO txn_status_history (txn_id, old_status, new_status) VALUES (NEW.txn_id, NULL, NEW.status);
END;

CREATE TRIGGER IF NOT EXISTS trg_txn_status_update AFTER UPDATE OF status ON transactions
WHEN OLD.status <> NEW.status
BEGIN
    INSERT INTO txn_status_history (txn_id, old_status, new_status) VALUES (NEW.txn_id, OLD.status, NEW.status);
END;

-- SUCCESS and FAILED are final states
CREATE TRIGGER IF NOT EXISTS trg_txn_final_state BEFORE UPDATE OF status ON transactions
WHEN OLD.status IN ('SUCCESS', 'FAILED') AND NEW.status <> OLD.status
BEGIN SELECT RAISE(ABORT, 'a finished transaction cannot change status'); END;

CREATE TABLE IF NOT EXISTS otp_challenges (
    txn_id     INTEGER PRIMARY KEY REFERENCES transactions(txn_id) ON DELETE CASCADE,
    otp_hash   TEXT    NOT NULL,
    expires_at TEXT    NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Idempotency keys make retried requests safe (same key + same body = same answer, money moves once)
CREATE TABLE IF NOT EXISTS idempotency_keys (
    user_id       INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    idem_key      TEXT    NOT NULL,
    endpoint      TEXT    NOT NULL,
    request_hash  TEXT    NOT NULL,
    state         TEXT    NOT NULL CHECK (state IN ('IN_PROGRESS', 'DONE')),
    status_code   INTEGER,
    response_json TEXT,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (user_id, idem_key)
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT    PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    expires_at TEXT    NOT NULL,
    ip         TEXT,
    user_agent TEXT
);

CREATE TABLE IF NOT EXISTS scheduled_payments (
    sched_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    to_wallet_id  INTEGER NOT NULL REFERENCES wallets(wallet_id),
    amount_paise  INTEGER NOT NULL CHECK (amount_paise > 0),
    note          TEXT    NOT NULL DEFAULT '',
    category      TEXT    NOT NULL DEFAULT 'Other',
    priority      INTEGER NOT NULL DEFAULT 5 CHECK (priority BETWEEN 1 AND 9),   -- 1 = most urgent
    frequency     TEXT    NOT NULL DEFAULT 'ONCE' CHECK (frequency IN ('ONCE', 'DAILY', 'WEEKLY', 'MONTHLY')),
    next_run_at   TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'RUNNING', 'DONE', 'CANCELLED', 'FAILED')),
    last_result   TEXT,
    run_count     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_sched_due ON scheduled_payments(status, next_run_at);

CREATE TABLE IF NOT EXISTS fraud_alerts (
    alert_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id        INTEGER NOT NULL UNIQUE REFERENCES transactions(txn_id) ON DELETE CASCADE,
    risk_score    INTEGER NOT NULL,
    reasons       TEXT    NOT NULL,
    review_status TEXT    NOT NULL DEFAULT 'OPEN' CHECK (review_status IN ('OPEN', 'APPROVED', 'REJECTED')),
    reviewed_by   INTEGER REFERENCES users(user_id),
    reviewed_at   TEXT,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- When a user corrects a category the AI learns from it (and re-learns after a restart)
CREATE TABLE IF NOT EXISTS category_feedback (
    fb_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    text       TEXT    NOT NULL,
    category   TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ------------------------------------------------------------------ views
-- Reconciliation: stored balance must equal the sum of ledger entries. Every row should have diff = 0.
CREATE VIEW IF NOT EXISTS v_reconciliation AS
SELECT w.wallet_id,
       w.wallet_code,
       w.balance_paise,
       COALESCE(SUM(CASE e.direction WHEN 'CREDIT' THEN e.amount_paise ELSE -e.amount_paise END), 0) AS ledger_paise,
       w.balance_paise - COALESCE(SUM(CASE e.direction WHEN 'CREDIT' THEN e.amount_paise ELSE -e.amount_paise END), 0) AS diff_paise
FROM wallets w
LEFT JOIN ledger_entries e ON e.wallet_id = w.wallet_id
GROUP BY w.wallet_id;

-- Passbook view: one row per ledger entry with the counterparty resolved
CREATE VIEW IF NOT EXISTS v_statement AS
SELECT e.entry_id, e.wallet_id, e.direction, e.amount_paise, e.balance_after_paise, e.created_at,
       t.txn_ref, t.txn_type, t.note, t.category, t.status,
       cw.wallet_code AS counterparty_code, cu.full_name AS counterparty_name
FROM ledger_entries e
JOIN transactions t       ON t.txn_id = e.txn_id
LEFT JOIN wallets cw      ON cw.wallet_id = CASE WHEN t.from_wallet_id = e.wallet_id THEN t.to_wallet_id ELSE t.from_wallet_id END
LEFT JOIN users cu        ON cu.user_id = cw.user_id;
