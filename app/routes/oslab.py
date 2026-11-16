from flask import Blueprint, g, jsonify

from ..deps import auth_required, body, svc
from ..services import oslab, ossim
from ..util import WalletError

bp = Blueprint("oslab", __name__, url_prefix="/api/os")


def _guard(name, per_minute=6):
    svc().limiter.enforce(f"os-{name}", g.user["user_id"], per_minute, 60)


@bp.get("/overview")
@auth_required()
def overview():
    s = svc()
    return jsonify({"ok": True, "system": oslab.system_info(),
                    "locks": {"mode": s.locks.mode, **s.local_locks.snapshot()},
                    "cache": s.cache.stats(), "scheduler": s.scheduler.snapshot(),
                    "redis": s.redis is not None})


@bp.post("/deadlock")
@auth_required()
def deadlock():
    _guard("deadlock")
    return jsonify({"ok": True, **oslab.deadlock_demo(body().get("mode", "naive"))})


@bp.post("/stress")
@auth_required()
def stress():
    _guard("stress", 4)
    d = body()
    return jsonify({"ok": True, **oslab.stress_test(d.get("threads", 8), d.get("ops", 40), d.get("wallets", 6),
                                                    bool(d.get("ordered", True)))})


@bp.post("/cpu")
@auth_required()
def cpu():
    d = body()
    try:
        return jsonify({"ok": True, **ossim.simulate_cpu(d.get("jobs") or [], d.get("policy", "FCFS"), d.get("quantum", 2))})
    except ValueError as e:
        raise WalletError(str(e), "bad_input")


@bp.post("/paging")
@auth_required()
def paging():
    d = body()
    try:
        refs = d.get("refs")
        if isinstance(refs, str):
            refs = [x for x in refs.replace(",", " ").split()]
        results = {a: ossim.simulate_paging(refs or [], d.get("frames", 3), a) for a in ("FIFO", "LRU", "OPT")}
        return jsonify({"ok": True, "results": results})
    except ValueError as e:
        raise WalletError(str(e), "bad_input")


@bp.post("/cache/flush")
@auth_required(admin=True)
def flush_cache():
    svc().cache.clear()
    return jsonify({"ok": True})


@bp.get("/audit/verify")
@auth_required()
def audit_verify():
    return jsonify({"ok": True, **svc().audit.verify()})


@bp.get("/files")
@auth_required(admin=True)
def files():
    s = svc()
    return jsonify({"ok": True, "data_files": oslab.data_files(s.cfg["DATA_DIR"]), "backups": oslab.list_backups(s.cfg["BACKUP_DIR"]),
                    "audit": s.audit.verify(), "audit_tail": s.audit.tail(12)})


@bp.post("/backup")
@auth_required(admin=True)
def backup():
    s = svc()
    _guard("backup", 5)
    res = oslab.create_backup(s.cfg["DB_PATH"], s.cfg["BACKUP_DIR"])
    s.audit.append("backup.created", g.user["user_id"], {"file": res["name"]})
    return jsonify({"ok": True, **res})


@bp.post("/audit/tamper-demo")
@auth_required(admin=True)
def tamper():
    return jsonify({"ok": True, **svc().audit.tamper_demo()})
