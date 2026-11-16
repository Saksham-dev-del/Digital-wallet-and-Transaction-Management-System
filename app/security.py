"""Passwords, tokens and OTPs."""
import hmac
import re
import secrets

from werkzeug.security import check_password_hash, generate_password_hash

from .util import sha256

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
PHONE_RE = re.compile(r"^[6-9]\d{9}$")  # Indian mobile numbers


def hash_password(password: str, iterations: int = 260_000) -> str:
    return generate_password_hash(password, method=f"pbkdf2:sha256:{iterations}")


def verify_password(stored_hash: str, password: str) -> bool:
    return check_password_hash(stored_hash, password)


def password_problem(password: str) -> str | None:
    if len(password) < 8:
        return "Use at least 8 characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Use both letters and numbers."
    return None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return sha256(token)


def new_otp() -> str:
    return f"{secrets.randbelow(10 ** 6):06d}"


def hash_otp(otp: str, txn_ref: str, secret: str) -> str:
    return sha256(f"{secret}:{txn_ref}:{otp}")


def same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
