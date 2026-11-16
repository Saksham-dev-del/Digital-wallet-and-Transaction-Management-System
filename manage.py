"""Maintenance commands:  python manage.py <command>

  seed     add the demo users + history (only when the database has no users)
  reset    delete the database + audit log and start fresh (asks first)
  check    reconcile balances, verify the audit hash-chain, run PRAGMA integrity_check
  backup   take an online backup into data/backups/
  train    retrain the AI fraud model from the database
  sql FILE run the SELECT statements in a .sql file (for example sql/queries.sql) and print the results
"""
import os
import sys

from app import create_app
from app.config import load_config
from app.db import connect
from app.services import oslab


def run_sql_file(conn, path):
    """Tiny SQL runner so the practice queries work on Windows too (no sqlite3 command-line tool needed)."""
    title, buf = "", []
    for line in open(path, encoding="utf-8"):
        stripped = line.strip()
        if stripped.startswith("--"):
            if stripped.lstrip("- ").startswith("Q") and "." in stripped[:8]:
                title = stripped.lstrip("- ")
            continue
        if not stripped:
            continue
        buf.append(line.rstrip())
        if stripped.endswith(";"):
            sql = "\n".join(buf)
            buf = []
            cur = conn.execute(sql)
            rows = cur.fetchall()
            print(f"\n== {title or sql[:60]}")
            if cur.description:
                names = [d[0] for d in cur.description]
                print(" | ".join(names))
                for r in rows[:15]:
                    print(" | ".join(str(r[n]) for n in names))
                if len(rows) > 15:
                    print(f"... {len(rows) - 15} more rows")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    cfg = load_config()
    if cmd == "reset":
        if input("This deletes ALL data (database, audit log, backups). Type 'yes' to continue: ").strip() != "yes":
            return print("Cancelled.")
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(cfg["DB_PATH"] + suffix):
                os.remove(cfg["DB_PATH"] + suffix)
        if os.path.exists(cfg["AUDIT_LOG"]):
            os.remove(cfg["AUDIT_LOG"])
        return print("Reset done. Start the app again to recreate the demo data.")
    app = create_app({"START_SCHEDULER": False})
    s = app.extensions["wallet"]
    conn = connect(cfg["DB_PATH"])
    if cmd == "seed":
        print("Demo data is created automatically when the database is empty (AUTO_SEED=true).")
    elif cmd == "check":
        bad = conn.execute("SELECT * FROM v_reconciliation WHERE diff_paise <> 0").fetchall()
        print("wallet reconciliation :", "OK" if not bad else f"{len(bad)} MISMATCHES")
        print("audit hash chain      :", s.audit.verify())
        print("sqlite integrity      :", conn.execute("PRAGMA integrity_check").fetchone()[0])
    elif cmd == "backup":
        print(oslab.create_backup(cfg["DB_PATH"], cfg["BACKUP_DIR"]))
    elif cmd == "sql":
        run_sql_file(conn, sys.argv[2] if len(sys.argv) > 2 else "sql/queries.sql")
    elif cmd == "train":
        from app.ai.fraud import training_contexts
        print(s.fraud.train(training_contexts(conn, cfg["OTP_THRESHOLD_PAISE"], cfg["TZ_OFFSET_MINUTES"])))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
