"""Central configuration.

Every value can be overridden with an environment variable (or a `.env` file next to run.py).
Money is always stored as integer *paise* (1 rupee = 100 paise) - floats are never used for money.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #")[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def load_config(overrides: dict | None = None) -> dict:
    data_dir = Path(os.environ.get("WALLET_DATA_DIR", ROOT / "data"))
    cfg = {
        "SECRET_KEY": os.environ.get("SECRET_KEY", "dev-only-secret-change-me"),
        # ---- storage (DBMS + file-system part)
        "DATA_DIR": str(data_dir),
        "DB_PATH": os.environ.get("WALLET_DB", str(data_dir / "wallet.db")),
        "AUDIT_LOG": os.environ.get("WALLET_AUDIT_LOG", str(data_dir / "audit.log")),
        "BACKUP_DIR": os.environ.get("WALLET_BACKUP_DIR", str(data_dir / "backups")),
        # ---- redis (optional)
        "USE_REDIS": _bool("USE_REDIS", True),
        "REDIS_URL": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        # ---- sessions / security
        "SESSION_TTL": _int("SESSION_TTL", 8 * 3600),
        "PASSWORD_ITERATIONS": _int("PASSWORD_ITERATIONS", 260_000),
        "DEMO_MODE": _bool("DEMO_MODE", True),
        "AUTO_SEED": _bool("AUTO_SEED", True),
        # ---- money rules (paise)
        "OTP_THRESHOLD_PAISE": _int("OTP_THRESHOLD_PAISE", 5_000_00),       # >= Rs 5,000 needs OTP
        "OTP_TTL_SECONDS": _int("OTP_TTL_SECONDS", 300),
        "OTP_MAX_ATTEMPTS": _int("OTP_MAX_ATTEMPTS", 3),
        "MIN_AMOUNT_PAISE": 100,                                             # Rs 1
        "MAX_TOPUP_PAISE": _int("MAX_TOPUP_PAISE", 50_000_00),
        "MAX_TRANSFER_PAISE": _int("MAX_TRANSFER_PAISE", 50_000_00),
        "MAX_BALANCE_PAISE": _int("MAX_BALANCE_PAISE", 2_00_000_00),
        "DEFAULT_DAILY_LIMIT_PAISE": _int("DEFAULT_DAILY_LIMIT_PAISE", 50_000_00),
        # ---- rate limits (per minute unless stated)
        "RATE_LOGIN_PER_MIN": _int("RATE_LOGIN_PER_MIN", 8),
        "RATE_REGISTER_PER_HOUR": _int("RATE_REGISTER_PER_HOUR", 20),
        "RATE_PAY_PER_MIN": _int("RATE_PAY_PER_MIN", 10),
        "RATE_LOOKUP_PER_MIN": _int("RATE_LOOKUP_PER_MIN", 30),
        "RATE_CHAT_PER_MIN": _int("RATE_CHAT_PER_MIN", 20),
        # ---- OS-style components
        "LRU_CAPACITY": _int("LRU_CAPACITY", 256),
        "CACHE_TTL": _int("CACHE_TTL", 30),
        "START_SCHEDULER": _bool("START_SCHEDULER", True),
        "SCHEDULER_WORKERS": _int("SCHEDULER_WORKERS", 3),
        "SCHEDULER_POLL_SECONDS": float(os.environ.get("SCHEDULER_POLL_SECONDS", 2)),
        # ---- AI
        "RISK_MEDIUM": 35,
        "RISK_HIGH": 70,
        "TZ_OFFSET_MINUTES": _int("TZ_OFFSET_MINUTES", 330),                # IST
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
        "ANTHROPIC_MODEL": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        "MAX_CONTENT_LENGTH": 64 * 1024,
    }
    if overrides:
        cfg.update(overrides)
    return cfg
