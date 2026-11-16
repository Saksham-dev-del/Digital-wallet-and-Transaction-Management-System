"""Small helpers shared by every module: errors, time, money, hashing."""
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


class WalletError(Exception):
    """A problem the user can understand and fix. Converted to a JSON error by the API layer."""

    def __init__(self, message: str, code: str = "bad_request", status: int = 400, **extra):
        super().__init__(message)
        self.message, self.code, self.status, self.extra = message, code, status, extra


# ------------------------------------------------------------------ time
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    dt = (dt or utcnow()).astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{dt.microsecond // 1000:03d}Z"


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def local_dt(dt: datetime, offset_minutes: int) -> datetime:
    return dt + timedelta(minutes=offset_minutes)


# ------------------------------------------------------------------ money
def to_paise(value, field: str = "amount") -> int:
    """'250', 250, '1,250.50' -> paise. Rejects zero, negatives, NaN and more than 2 decimals."""
    if value is None or isinstance(value, bool) or str(value).strip() == "":
        raise WalletError(f"Enter the {field}.", "invalid_amount")
    try:
        d = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise WalletError(f"Enter the {field} as a number, for example 250 or 250.50.", "invalid_amount")
    if not d.is_finite() or abs(d) > Decimal("100000000"):
        raise WalletError(f"That {field} is not valid.", "invalid_amount")
    if d <= 0:
        raise WalletError(f"The {field} must be more than zero.", "invalid_amount")
    if d != d.quantize(Decimal("0.01")):
        raise WalletError(f"The {field} can have at most 2 decimal places.", "invalid_amount")
    return int((d * 100).to_integral_value(ROUND_HALF_UP))


def inr(paise: int, symbol: bool = True) -> str:
    """Indian digit grouping: 1234567 paise -> ₹12,345.67 ; 12345678 -> ₹1,23,456.78"""
    sign = "-" if paise < 0 else ""
    rupees, ps = divmod(abs(int(paise)), 100)
    s = str(rupees)
    if len(s) > 3:
        head, tail, parts = s[:-3], s[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return f"{sign}{'₹' if symbol else ''}{s}.{ps:02d}"


# ------------------------------------------------------------------ hashing / ids
def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_txn_ref() -> str:
    return "TXN" + utcnow().strftime("%y%m%d") + secrets.token_hex(3).upper()


def clean_note(note, limit: int = 80) -> str:
    return " ".join(str(note or "").split())[:limit]
