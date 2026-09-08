# ER Diagram — Digital Wallet and Payment Transaction Management System

## Entities

**USERS**
- user_id (PK)
- username
- password_hash
- full_name
- email
- created_at

**WALLETS**
- wallet_id (PK)
- user_id (FK -> USERS.user_id) — one wallet per user
- balance
- created_at

**TRANSACTIONS**
- txn_id (PK)
- wallet_id (FK -> WALLETS.wallet_id)
- txn_type (DEPOSIT / WITHDRAW / TRANSFER_IN / TRANSFER_OUT)
- amount
- related_wallet_id (FK -> WALLETS.wallet_id, nullable — used only for transfers)
- status (SUCCESS / FAILED)
- timestamp

**CONCURRENCY_AUDIT_LOG** (used by the OS/locking module)
- log_id (PK)
- wallet_id (FK -> WALLETS.wallet_id)
- thread_name
- action
- detail
- timestamp

## Relationships
- USERS (1) --- (1) WALLETS
- WALLETS (1) --- (M) TRANSACTIONS
- WALLETS (1) --- (M) CONCURRENCY_AUDIT_LOG

## Notes
A hand-drawn / draw.io version of this diagram should be added here
before final submission — this file is a text description only,
so you can quickly redraw it in draw.io / Lucidchart / a notebook
sketch for the report.
