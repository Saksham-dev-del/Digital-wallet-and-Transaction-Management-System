-- ===================================================================
-- Digital Wallet and Payment Transaction Management System
-- Database Schema (DBMS Module)
-- ===================================================================

PRAGMA foreign_keys = ON;

-- Users table
CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name     TEXT NOT NULL,
    email         TEXT UNIQUE NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Wallets table (1-to-1 with users for now)
CREATE TABLE IF NOT EXISTS wallets (
    wallet_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL UNIQUE,
    balance       REAL NOT NULL DEFAULT 0.0 CHECK (balance >= 0),
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Transactions table (ledger of every operation)
CREATE TABLE IF NOT EXISTS transactions (
    txn_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_id         INTEGER NOT NULL,
    txn_type          TEXT NOT NULL CHECK (txn_type IN
                         ('DEPOSIT', 'WITHDRAW', 'TRANSFER_IN', 'TRANSFER_OUT')),
    amount            REAL NOT NULL CHECK (amount > 0),
    related_wallet_id INTEGER,               -- used only for transfers
    status            TEXT NOT NULL CHECK (status IN ('SUCCESS', 'FAILED')),
    timestamp         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (wallet_id) REFERENCES wallets(wallet_id) ON DELETE CASCADE,
    FOREIGN KEY (related_wallet_id) REFERENCES wallets(wallet_id)
);

-- Audit log table (used later by the OS/concurrency demo to record
-- which thread/process handled which transaction and when a lock
-- was acquired/released)
CREATE TABLE IF NOT EXISTS concurrency_audit_log (
    log_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_id     INTEGER NOT NULL,
    thread_name   TEXT NOT NULL,
    action        TEXT NOT NULL,   -- e.g. LOCK_ACQUIRED, LOCK_RELEASED, TXN_APPLIED
    detail        TEXT,
    timestamp     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Helpful index for fetching a wallet's transaction history quickly
CREATE INDEX IF NOT EXISTS idx_transactions_wallet_id ON transactions(wallet_id);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
