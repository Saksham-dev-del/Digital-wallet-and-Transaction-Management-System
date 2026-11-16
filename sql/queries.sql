-- =====================================================================================
--  Smart Wallet - DBMS practice queries            run:  python manage.py sql sql/queries.sql
--  Each block starts with a "-- Qn." title. They only READ data, so they are safe to run any time.
-- =====================================================================================

-- Q1. Who holds how much? (JOIN, ORDER BY)
SELECT u.full_name, w.wallet_code, w.balance_paise / 100.0 AS balance_rupees
FROM wallets w JOIN users u ON u.user_id = w.user_id
WHERE u.account_type = 'PERSONAL'
ORDER BY w.balance_paise DESC;

-- Q2. Do the books balance? Every row must have diff_paise = 0 (uses the v_reconciliation VIEW)
SELECT COUNT(*) AS wallets_checked, SUM(diff_paise <> 0) AS wallets_not_matching FROM v_reconciliation;

-- Q3. Money invariant: money in the system = top-ups - withdrawals (transfers only move money around)
SELECT (SELECT COALESCE(SUM(amount_paise),0) FROM transactions WHERE txn_type='TOPUP'    AND status='SUCCESS')
     - (SELECT COALESCE(SUM(amount_paise),0) FROM transactions WHERE txn_type='WITHDRAW' AND status='SUCCESS') AS expected_paise,
       (SELECT SUM(balance_paise) FROM wallets) AS actual_paise;

-- Q4. A passbook with a running balance, computed with a WINDOW function (cross-check against ledger_entries)
SELECT t.created_at, t.note,
       CASE WHEN t.from_wallet_id = w.wallet_id THEN -t.amount_paise ELSE t.amount_paise END AS change_paise,
       SUM(CASE WHEN t.from_wallet_id = w.wallet_id THEN -t.amount_paise ELSE t.amount_paise END)
           OVER (ORDER BY t.created_at, t.txn_id) AS running_balance_paise
FROM wallets w
JOIN transactions t ON (t.from_wallet_id = w.wallet_id OR t.to_wallet_id = w.wallet_id) AND t.status = 'SUCCESS'
WHERE w.wallet_code = 'aarav@swallet'
ORDER BY t.created_at DESC, t.txn_id DESC
LIMIT 10;

-- Q5. Spending by category in the last 30 days (GROUP BY, HAVING, aggregate functions)
SELECT t.category, COUNT(*) AS payments, SUM(t.amount_paise) / 100.0 AS rupees, ROUND(AVG(t.amount_paise) / 100.0, 2) AS average_rupees
FROM transactions t JOIN wallets w ON w.wallet_id = t.from_wallet_id
WHERE w.wallet_code = 'aarav@swallet' AND t.txn_type = 'TRANSFER' AND t.status = 'SUCCESS'
  AND t.created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-30 days')
GROUP BY t.category
HAVING COUNT(*) >= 1
ORDER BY rupees DESC;

-- Q6. Top 5 payees of one wallet (two JOINs + LIMIT)
SELECT u.full_name AS payee, COUNT(*) AS times_paid, SUM(t.amount_paise) / 100.0 AS total_rupees
FROM transactions t
JOIN wallets me  ON me.wallet_id = t.from_wallet_id AND me.wallet_code = 'aarav@swallet'
JOIN wallets cp  ON cp.wallet_id = t.to_wallet_id
JOIN users u     ON u.user_id = cp.user_id
WHERE t.txn_type = 'TRANSFER' AND t.status = 'SUCCESS'
GROUP BY u.user_id
ORDER BY total_rupees DESC
LIMIT 5;

-- Q7. Wallets ranked by money sent (RANK window function)
SELECT u.full_name, SUM(t.amount_paise) / 100.0 AS sent_rupees, RANK() OVER (ORDER BY SUM(t.amount_paise) DESC) AS sender_rank
FROM transactions t JOIN wallets w ON w.wallet_id = t.from_wallet_id JOIN users u ON u.user_id = w.user_id
WHERE t.txn_type = 'TRANSFER' AND t.status = 'SUCCESS'
GROUP BY u.user_id
ORDER BY sender_rank
LIMIT 8;

-- Q8. Daily spend with a 7-day moving average (CTE + window frame)
WITH daily AS (
    SELECT substr(t.created_at, 1, 10) AS day, SUM(t.amount_paise) AS spent
    FROM transactions t JOIN wallets w ON w.wallet_id = t.from_wallet_id
    WHERE w.wallet_code = 'aarav@swallet' AND t.txn_type = 'TRANSFER' AND t.status = 'SUCCESS'
    GROUP BY day
)
SELECT day, spent / 100.0 AS rupees,
       ROUND(AVG(spent) OVER (ORDER BY day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) / 100.0, 2) AS moving_avg_7d
FROM daily ORDER BY day DESC LIMIT 10;

-- Q9. People who have never sent a payment (NOT EXISTS sub-query)
SELECT u.full_name FROM users u JOIN wallets w ON w.user_id = u.user_id
WHERE u.account_type = 'PERSONAL'
  AND NOT EXISTS (SELECT 1 FROM transactions t WHERE t.from_wallet_id = w.wallet_id AND t.txn_type = 'TRANSFER');

-- Q10. Transaction outcomes (conditional aggregation)
SELECT txn_type,
       SUM(status = 'SUCCESS') AS success, SUM(status = 'FAILED') AS failed,
       SUM(status = 'BLOCKED') AS blocked, SUM(status = 'PENDING_OTP') AS waiting_for_otp
FROM transactions GROUP BY txn_type;

-- Q11. Life of every transaction, written automatically by the trigger trg_txn_status_*
SELECT t.txn_ref, h.old_status, h.new_status, h.changed_at
FROM txn_status_history h JOIN transactions t ON t.txn_id = h.txn_id
ORDER BY h.hist_id DESC LIMIT 8;

-- Q12. Payments the AI held back and who reviewed them (LEFT JOIN)
SELECT a.alert_id, t.txn_ref, t.amount_paise / 100.0 AS rupees, a.risk_score, a.review_status, r.full_name AS reviewed_by
FROM fraud_alerts a JOIN transactions t ON t.txn_id = a.txn_id LEFT JOIN users r ON r.user_id = a.reviewed_by
ORDER BY a.created_at DESC;

-- Q13. Which index is used? Look for "USING INDEX idx_txn_from" in the plan (EXPLAIN QUERY PLAN)
EXPLAIN QUERY PLAN
SELECT SUM(amount_paise) FROM transactions
WHERE from_wallet_id = 2 AND status = 'SUCCESS' AND created_at >= '2026-01-01';

-- Q14. Integrity rules in action - these FAIL on purpose, try them in a SQLite shell:
--   UPDATE ledger_entries SET amount_paise = 1;               -- trigger: ledger_entries is append-only
--   DELETE FROM ledger_entries;                                -- trigger: ledger_entries is append-only
--   UPDATE wallets SET balance_paise = -5;                     -- CHECK (balance_paise >= 0)
--   UPDATE transactions SET status = 'FAILED' WHERE status = 'SUCCESS';   -- trigger: a finished transaction cannot change status
SELECT 'see the comments above for the statements that must fail' AS note;
