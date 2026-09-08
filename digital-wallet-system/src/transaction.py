"""
transaction.py
---------------
Core money-movement logic: deposit, withdraw, transfer.

DBMS concept demonstrated: every operation is wrapped in an explicit
BEGIN / COMMIT / ROLLBACK block so that a balance update and its
corresponding ledger entry either both succeed or both fail
(Atomicity + Consistency from ACID).

OS concept demonstrated: a per-wallet threading.Lock (in-process) AND
a Redis-backed distributed lock are both acquired before touching a
wallet's balance, to prevent a race condition when two operations try
to update the same wallet at the same time (mutual exclusion /
critical section handling). See concurrency.py for the full
explanation of both layers and the race-condition demo.

After every successful balance change, the Redis balance cache for
that wallet is invalidated so wallet.get_balance() is forced to
re-read the fresh value from SQLite (the source of truth) on the
next call.
"""

from db import get_connection
from concurrency import lock_manager, RedisLock
from wallet import invalidate_balance_cache


def deposit(wallet_id: int, amount: float):
    if amount <= 0:
        raise ValueError("Deposit amount must be positive.")

    with lock_manager.get_lock(wallet_id):
        with RedisLock(wallet_id):
            conn = get_connection()
            cur = conn.cursor()
            try:
                cur.execute("BEGIN")
                cur.execute(
                    "UPDATE wallets SET balance = balance + ? WHERE wallet_id = ?",
                    (amount, wallet_id),
                )
                cur.execute(
                    """INSERT INTO transactions (wallet_id, txn_type, amount, status)
                       VALUES (?, 'DEPOSIT', ?, 'SUCCESS')""",
                    (wallet_id, amount),
                )
                conn.commit()
                print(f"[TXN] Deposited {amount} into wallet {wallet_id}.")
            except Exception as e:
                conn.rollback()
                print(f"[TXN] Deposit failed, rolled back. Reason: {e}")
                raise
            finally:
                conn.close()
            invalidate_balance_cache(wallet_id)


def withdraw(wallet_id: int, amount: float):
    if amount <= 0:
        raise ValueError("Withdraw amount must be positive.")

    with lock_manager.get_lock(wallet_id):
        with RedisLock(wallet_id):
            conn = get_connection()
            cur = conn.cursor()
            try:
                cur.execute("BEGIN")
                cur.execute("SELECT balance FROM wallets WHERE wallet_id = ?", (wallet_id,))
                row = cur.fetchone()
                if row is None:
                    raise ValueError(f"Wallet {wallet_id} does not exist.")
                if row["balance"] < amount:
                    # Log the failed attempt too - useful for audits
                    cur.execute(
                        """INSERT INTO transactions (wallet_id, txn_type, amount, status)
                           VALUES (?, 'WITHDRAW', ?, 'FAILED')""",
                        (wallet_id, amount),
                    )
                    conn.commit()
                    raise ValueError("Insufficient balance.")

                cur.execute(
                    "UPDATE wallets SET balance = balance - ? WHERE wallet_id = ?",
                    (amount, wallet_id),
                )
                cur.execute(
                    """INSERT INTO transactions (wallet_id, txn_type, amount, status)
                       VALUES (?, 'WITHDRAW', ?, 'SUCCESS')""",
                    (wallet_id, amount),
                )
                conn.commit()
                print(f"[TXN] Withdrew {amount} from wallet {wallet_id}.")
            except Exception as e:
                conn.rollback()
                print(f"[TXN] Withdraw failed, rolled back. Reason: {e}")
                raise
            finally:
                conn.close()
            invalidate_balance_cache(wallet_id)


def transfer(from_wallet_id: int, to_wallet_id: int, amount: float):
    """
    NOTE (pending work): to fully avoid deadlocks when two transfers
    happen in opposite directions at the same time (A->B and B->A),
    locks should be acquired in a fixed global order (e.g. lower
    wallet_id first). That ordering logic is NOT yet implemented -
    see README -> Pending Work (Deadlock handling / Banker's Algorithm).
    This applies to both the threading.Lock and the RedisLock layers.
    """
    if amount <= 0:
        raise ValueError("Transfer amount must be positive.")
    if from_wallet_id == to_wallet_id:
        raise ValueError("Cannot transfer to the same wallet.")

    with lock_manager.get_lock(from_wallet_id):
        with lock_manager.get_lock(to_wallet_id):
            with RedisLock(from_wallet_id):
                with RedisLock(to_wallet_id):
                    conn = get_connection()
                    cur = conn.cursor()
                    try:
                        cur.execute("BEGIN")
                        cur.execute(
                            "SELECT balance FROM wallets WHERE wallet_id = ?",
                            (from_wallet_id,),
                        )
                        row = cur.fetchone()
                        if row is None or row["balance"] < amount:
                            raise ValueError("Insufficient balance or invalid source wallet.")

                        cur.execute(
                            "UPDATE wallets SET balance = balance - ? WHERE wallet_id = ?",
                            (amount, from_wallet_id),
                        )
                        cur.execute(
                            "UPDATE wallets SET balance = balance + ? WHERE wallet_id = ?",
                            (amount, to_wallet_id),
                        )
                        cur.execute(
                            """INSERT INTO transactions
                               (wallet_id, txn_type, amount, related_wallet_id, status)
                               VALUES (?, 'TRANSFER_OUT', ?, ?, 'SUCCESS')""",
                            (from_wallet_id, amount, to_wallet_id),
                        )
                        cur.execute(
                            """INSERT INTO transactions
                               (wallet_id, txn_type, amount, related_wallet_id, status)
                               VALUES (?, 'TRANSFER_IN', ?, ?, 'SUCCESS')""",
                            (to_wallet_id, amount, from_wallet_id),
                        )
                        conn.commit()
                        print(f"[TXN] Transferred {amount} from wallet {from_wallet_id} "
                              f"to {to_wallet_id}.")
                    except Exception as e:
                        conn.rollback()
                        print(f"[TXN] Transfer failed, rolled back. Reason: {e}")
                        raise
                    finally:
                        conn.close()
                    invalidate_balance_cache(from_wallet_id)
                    invalidate_balance_cache(to_wallet_id)


def get_transaction_history(wallet_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM transactions WHERE wallet_id = ? ORDER BY timestamp DESC",
        (wallet_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]
