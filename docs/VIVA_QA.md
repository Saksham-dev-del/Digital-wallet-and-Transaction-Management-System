# Viva questions and short answers

**1. Why do you store money as integer paise?**
Floating point cannot store values like 0.10 exactly, so sums drift. Integers are exact; the UI converts to rupees only for display.

**2. How do you stop two payments from spending the same money (race condition)?**
Three layers: per-wallet locks (OS), `BEGIN IMMEDIATE` (DBMS) and a re-check of balance and daily limit *inside* the lock and
transaction. The database also has `CHECK (balance_paise >= 0)` as a last line of defence.

**3. What are the four conditions for deadlock, and which one do you break?**
Mutual exclusion, hold-and-wait, no pre-emption, circular wait. Taking locks in ascending wallet id breaks *circular wait*, so
prevention is guaranteed. As a second layer the lock manager can *detect* a cycle in the wait-for graph and abort a victim.

**4. Prevention, avoidance and detection - what is the difference?**
Prevention removes one of the four conditions in advance. Avoidance (Banker's algorithm) checks each request against a safe
state. Detection lets deadlock happen, finds it with a wait-for graph, and recovers by killing or rolling back a victim.

**5. Explain the OS Lab deadlock demo.**
Transfer A locks wallet 1 then wants 2; transfer B locks 2 then wants 1. The detector finds the cycle A -> B -> A, chooses the
transaction holding the fewest locks as victim, the victim rolls back and retries in sorted order, and both finish.

**6. What does `BEGIN IMMEDIATE` do, and what is WAL?**
It acquires SQLite's write lock at the start instead of at the first write, so read-modify-write sequences cannot interleave.
WAL (write-ahead log) appends changes to a log first: readers do not block the writer, and a crash can be recovered from the log.

**7. Map ACID to your project.**
Atomic: `tx()` rolls back on error. Consistent: constraints, triggers, reconciliation view. Isolated: serial writers.
Durable: WAL + fsync'd audit log.

**8. What is idempotency and why does a payment API need it?**
Repeating the same request must not repeat the effect. If the network drops after the server took the money, the client retries
with the same `Idempotency-Key` and gets the stored answer instead of a second payment.

**9. How do you keep the cache consistent with the database?**
Cache-aside: read the cache, on a miss read SQLite and fill it. After a committed payment both wallets' keys are deleted while the
locks are still held, so no reader can re-cache an old value. If Redis fails, calls fall back safely.

**10. Why LRU, and what is Belady's anomaly?**
Recently used balances are likely to be read again, so LRU evicts the least recently used. Belady's anomaly: with FIFO, giving a
process *more* frames can cause *more* faults (see the Memory tab). LRU and Optimal never do this.

**11. How does your scheduler work?**
A dispatcher thread finds due payments and claims each with one atomic `UPDATE ... WHERE status='ACTIVE'`; claimed jobs go into a
thread-safe `PriorityQueue`; worker threads block on `get()` (no busy waiting) and run them. Priority 1 runs first, FCFS within
the same priority.

**12. Why a hash-chained audit log and what does `fsync` do?**
Each record contains the hash of the previous one, so editing, deleting or re-ordering any line breaks verification (see the
Tamper demo). `fsync` forces the OS to write its buffers to the disk, so a record survives a crash.

**13. How does the fraud model work, and why Isolation Forest?**
It isolates points with random splits; unusual points need fewer splits, so they get a higher anomaly score. It is unsupervised,
which fits a wallet that has almost no labelled fraud. Transparent rules are blended in so every decision comes with reasons.

**14. What do the score thresholds mean?**
Below 35 the payment goes through; 35-69 needs an OTP (step-up authentication); 70 and above is held and an administrator
approves or rejects it (human in the loop).

**15. Can the assistant move money?**
No. It only pre-fills the Send form. The user must press Send and pass the same checks, including OTP. This also limits damage
from prompt injection through transaction notes.

**16. Why are triggers and views used?**
Triggers enforce rules no application bug can bypass (append-only ledger, final states) and record status history. The
reconciliation view lets anyone prove balances equal the sum of the ledger.

**17. Which isolation level does SQLite give, and what would change on PostgreSQL?**
Writers are serialised, which behaves like SERIALIZABLE. On PostgreSQL you would use `SELECT ... FOR UPDATE` on the two wallet
rows (ordered by id, same deadlock logic) at READ COMMITTED or REPEATABLE READ.

**18. How did you test concurrency?**
`tests/test_os.py` and the OS Lab stress test run many threads moving money in opposite directions; the total money must stay
the same and every wallet must equal the sum of its ledger. The unsafe lock order is included to show the detector working.

**19. What are the limitations?**
SQLite allows one writer (fine for a demo, use PostgreSQL to scale); the audit log assumes one server process; OTP delivery is
simulated; Redis is optional; this is an educational system, not a licensed payment service.

**20. How would you scale it?**
PostgreSQL with row locks, several app servers sharing Redis locks and sessions, a message queue for scheduled jobs, and
partitioning of the transaction table by month.

**21. What is the "Under the hood" panel and how did you build it?**
Each payment request carries a small `Trace` object through the service layer. Every important step (rate limit, idempotency,
AI risk score, wallet locks, `BEGIN IMMEDIATE`, ledger posting, `COMMIT`, cache invalidation, audit append) adds a line with a layer and a
millisecond offset. The API returns the steps with the payment result and the browser animates them, so the invisible OS and DBMS work
becomes visible. It adds almost no cost because it only appends to a list.

**22. Why no React or other framework on the front end?**
The app is small enough for plain ES modules, which keeps the project dependency-free (no Node, no build) and easy to explain line by line.
A tagged template that auto-escapes values gives most of the safety a framework would, and separate view modules keep the code organised.
