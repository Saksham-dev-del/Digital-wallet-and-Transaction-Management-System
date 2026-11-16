"""Tamper-evident audit log - the file-system part of the project.

* append-only text file, one JSON record per line (sequential write = fast on every file system)
* every record stores the hash of the previous record (a hash chain, like a tiny blockchain)
* flush() + os.fsync() after each write so the record really reaches the disk (durability)
* verify() walks the file and proves that no line was edited, deleted or re-ordered
"""
import json
import os
import threading
from pathlib import Path

from ..util import canonical, iso, sha256

GENESIS = "0" * 64


class AuditLog:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._seq, self._last = 0, GENESIS
        self._load_tail()

    def _load_tail(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        with open(self.path, "rb") as fh:
            fh.seek(max(0, self.path.stat().st_size - 65536))
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
        try:
            rec = json.loads(lines[-1])
            self._seq, self._last = rec["seq"], rec["hash"]
        except Exception:
            self._seq, self._last = 0, GENESIS  # corrupt tail: verify() will report it

    def append(self, event: str, actor=None, data: dict | None = None) -> dict:
        with self._lock:
            self._seq += 1
            rec = {"seq": self._seq, "ts": iso(), "event": event, "actor": actor, "data": data or {},
                   "prev": self._last}
            rec["hash"] = sha256(canonical(rec))
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._last = rec["hash"]
            return rec

    @staticmethod
    def verify_file(path) -> dict:
        path = Path(path)
        if not path.exists():
            return {"ok": True, "entries": 0, "head": GENESIS, "note": "log is empty"}
        prev, count = GENESIS, 0
        with open(path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    claimed = rec.pop("hash")
                except Exception:
                    return {"ok": False, "entries": count, "bad_line": lineno, "reason": "line is not valid JSON"}
                if rec.get("seq") != count + 1:
                    return {"ok": False, "entries": count, "bad_line": lineno,
                            "reason": f"sequence number should be {count + 1} (a line was removed or re-ordered)"}
                if rec.get("prev") != prev:
                    return {"ok": False, "entries": count, "bad_line": lineno,
                            "reason": "previous-hash does not match (an earlier line was changed)"}
                if sha256(canonical(rec)) != claimed:
                    return {"ok": False, "entries": count, "bad_line": lineno,
                            "reason": "hash mismatch - this line was edited after it was written"}
                prev, count = claimed, count + 1
        return {"ok": True, "entries": count, "head": prev}

    def verify(self) -> dict:
        with self._lock:
            return self.verify_file(self.path)

    def tail(self, n: int = 15) -> list:
        if not self.path.exists():
            return []
        with open(self.path, "r", encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
        out = []
        for ln in lines[-n:]:
            try:
                out.append(json.loads(ln))
            except Exception:
                out.append({"corrupt": ln[:80]})
        return out

    def tamper_demo(self) -> dict:
        """Copy the log, edit ONE record in the copy, and show that verification catches it.
        The real log is never touched."""
        import tempfile

        with self._lock:
            if not self.path.exists():
                return {"ok": False, "reason": "no audit log yet"}
            lines = [ln for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if len(lines) < 2:
            return {"ok": False, "reason": "need at least 2 audit records for the demo"}
        idx = len(lines) // 2
        rec = json.loads(lines[idx])
        before = json.dumps(rec["data"], ensure_ascii=False)[:120]
        rec["data"] = {**rec["data"], "amount_paise": 1, "tampered": True}      # the attacker edits the amount
        lines[idx] = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "audit-copy.log"
            fake.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = self.verify_file(fake)
        return {"edited_line": idx + 1, "original_data": before, "verification_of_copy": result,
                "caught": not result["ok"]}
