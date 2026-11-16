import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402


def build_app(tmp_path, **overrides):
    cfg = {"DATA_DIR": str(tmp_path), "DB_PATH": str(tmp_path / "wallet.db"), "AUDIT_LOG": str(tmp_path / "audit.log"),
           "BACKUP_DIR": str(tmp_path / "backups"), "USE_REDIS": False, "START_SCHEDULER": False, "AUTO_SEED": False,
           "PASSWORD_ITERATIONS": 1000, "DEMO_MODE": True}
    cfg.update(overrides)
    return create_app(cfg)


@pytest.fixture()
def app(tmp_path):
    return build_app(tmp_path)


@pytest.fixture()
def seeded(tmp_path):
    return build_app(tmp_path, AUTO_SEED=True)


@pytest.fixture()
def client(app):
    return app.test_client()


class Api:
    """Tiny helper so tests read like the user story."""

    def __init__(self, client):
        self.c = client

    def register(self, name, email=None, password="Passw0rd1"):
        email = email or f"{name.lower().replace(' ', '.')}@t.test"
        r = self.c.post("/api/auth/register", json={"full_name": name, "email": email, "password": password})
        assert r.status_code == 201, r.json
        return {"Authorization": "Bearer " + r.json["token"]}, r.json["user"]

    def topup(self, h, amount):
        r = self.c.post("/api/wallet/topup", json={"amount": amount}, headers=h)
        assert r.status_code == 201, r.json
        return r.json

    def balance(self, h):
        return self.c.get("/api/wallet", headers=h).json["balance_paise"]

    def pay(self, h, to, amount, note="", key=None):
        headers = dict(h)
        if key:
            headers["Idempotency-Key"] = key
        return self.c.post("/api/wallet/transfer", json={"to": to, "amount": amount, "note": note}, headers=headers)


@pytest.fixture()
def api(client):
    return Api(client)
