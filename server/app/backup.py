"""Backup diário de tudo (bancos + recibos + documentos) em /data/backups, guardando os últimos 14.

Os bancos são copiados com a cópia segura do SQLite (não corrompe com o Fidus funcionando). Roda sozinho todo dia
às 03:30 (UTC) dentro do servidor; também dá para rodar na mão: `docker exec fidus_server python -m app.backup`.
Para ter cópia fora do servidor, sincronize /opt/fidus/server/deploy/data/backups com um armazenamento externo
(ex. Hetzner Storage Box) — ver README.
"""
import glob
import json
import logging
import os
import sqlite3
import tarfile
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

from . import config

log = logging.getLogger("fidus.backup")
KEEP = 14


def _dir() -> str:
    d = os.path.join(config.DATA_DIR, "backups")
    os.makedirs(d, exist_ok=True)
    return d


def _databases() -> list[str]:
    dbs = [config.ACCOUNTS_DB, os.path.abspath(config.DB_PATH)]
    dbs += glob.glob(os.path.join(config.DATA_DIR, "users", "*", "fidus.db"))
    return [d for d in dict.fromkeys(dbs) if os.path.isfile(d)]


def run() -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = os.path.join(_dir(), f"fidus-{stamp}.tar.gz")
    data_root = os.path.realpath(config.DATA_DIR)
    skip = {os.path.realpath(os.path.join(data_root, x)) for x in ("backups", "deleted")}
    try:
        with tempfile.TemporaryDirectory() as tmp, tarfile.open(out + ".part", "w:gz") as tar:
            for db in _databases():  # cópia consistente de cada banco
                rel = os.path.relpath(os.path.realpath(db), data_root) if os.path.realpath(db).startswith(data_root) \
                    else os.path.basename(db)
                copy = os.path.join(tmp, rel.replace(os.sep, "__"))
                src = sqlite3.connect(db)
                dst = sqlite3.connect(copy)
                with dst:
                    src.backup(dst)
                src.close()
                dst.close()
                tar.add(copy, arcname=os.path.join("bancos", rel))
            for root, dirs, files in os.walk(data_root):
                if os.path.realpath(root) in skip:
                    dirs[:] = []
                    continue
                dirs[:] = [d for d in dirs if os.path.realpath(os.path.join(root, d)) not in skip]
                for f in files:
                    if f.endswith((".db", ".db-wal", ".db-shm", ".db-journal", ".part")):
                        continue
                    p = os.path.join(root, f)
                    tar.add(p, arcname=os.path.join("arquivos", os.path.relpath(p, data_root)))
        os.replace(out + ".part", out)
    except Exception as e:  # noqa: BLE001
        try:
            os.remove(out + ".part")
        except OSError:
            pass
        _status(False, str(e))
        _alert(f"O backup do Fidus falhou: {e}")
        raise
    for old in sorted(glob.glob(os.path.join(_dir(), "fidus-*.tar.gz")))[:-KEEP]:
        os.remove(old)
    try:
        from . import account_data, metrics
        account_data.purge_deleted()
        metrics.purge_old()
    except Exception:  # noqa: BLE001
        pass
    info = _status(True, "", out)
    log.info("backup ok: %s", out)
    return info


def _status(ok: bool, error: str, path: str | None = None) -> dict:
    info = {"ok": ok, "at": datetime.now(timezone.utc).isoformat(), "error": error,
            "file": os.path.basename(path) if path else None, "size": os.path.getsize(path) if path else 0}
    prev = last()
    if not ok and prev.get("last_ok"):
        info["last_ok"] = prev["last_ok"]
    elif ok:
        info["last_ok"] = info["at"]
    with open(os.path.join(_dir(), "last.json"), "w") as f:
        json.dump(info, f)
    return info


def last() -> dict:
    try:
        with open(os.path.join(_dir(), "last.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def age_hours() -> float | None:
    ok = last().get("last_ok")
    if not ok:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(ok)).total_seconds() / 3600


def _alert(text: str) -> None:
    """Avisa o dono por e-mail (se o envio de e-mails estiver configurado)."""
    try:
        from . import mailer
        if config.OWNER_EMAIL:
            mailer.send(config.OWNER_EMAIL, "admin_alert", "pt", text=text)
    except Exception:  # noqa: BLE001
        pass


def start_daily(hour: int = 3, minute: int = 30) -> None:
    """Agenda o backup diário dentro do próprio servidor (sem mexer no cron da máquina compartilhada)."""
    def loop():
        while True:
            now = datetime.now(timezone.utc)
            nxt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if nxt <= now:
                nxt += timedelta(days=1)
            time.sleep((nxt - now).total_seconds())
            try:
                run()
            except Exception as e:  # noqa: BLE001
                log.error("backup falhou: %s", e)
    threading.Thread(target=loop, daemon=True, name="fidus-backup").start()


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
