"""Dados do cliente: exportar tudo (direito de portabilidade) e apagar a conta (exigido pela GDPR e pela Google Play).

Apagar: a conta sai na hora (acessos encerrados, Google desconectado, link público desligado) e a pasta do cliente vai
para /data/deleted, onde é destruída de vez depois de 30 dias (prazo para desfazer um engano a pedido do cliente).
"""
import json
import os
import shutil
import time
import zipfile
from datetime import datetime, timezone

from . import accounts, config, store

TABLES = ["messages", "activities", "expenses", "tasks", "documents", "bills", "meetings", "bookings", "pending_actions"]
SECRET_KEYS = ("creds", "token", "secret")
PURGE_AFTER_DAYS = 30


def export_zip() -> dict:
    """Gera um .zip com os dados em JSON e os arquivos (recibos, documentos). Devolve o documento para o link."""
    u = store.current()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = os.path.join(store.files_dir("exports"), f"fidus-dados-{stamp}.zip")
    base_dirs = [os.path.realpath(u["dir"]), os.path.realpath(u["receipts"])]
    files: set = set()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for t in TABLES:
            rows = store.select(f"SELECT * FROM {t}")
            z.writestr(f"dados/{t}.json", json.dumps(rows, ensure_ascii=False, indent=1, default=str))
            for r in rows:
                for k in ("receipt_path", "path"):
                    p = r.get(k)
                    if p and os.path.isfile(p) and any(os.path.realpath(p).startswith(d) for d in base_dirs):
                        files.add(os.path.realpath(p))
        kv = {r["k"]: r["v"] for r in store.select("SELECT k, v FROM kv") if not any(x in r["k"] for x in SECRET_KEYS)}
        z.writestr("dados/perfil_e_ajustes.json", json.dumps(kv, ensure_ascii=False, indent=1))
        for p in sorted(files):
            z.write(p, "arquivos/" + os.path.basename(p))
        z.writestr("LEIA-ME.txt", "Exportação dos seus dados do Fidus. Pasta dados: tudo em JSON. Pasta arquivos: recibos "
                                 "e documentos que você mandou.\n")
    did = store.insert("documents", title=f"Seus dados do Fidus ({stamp[:8]})", description="exportação completa",
                       tags="exportacao", path=path, media_type="application/zip")
    return {"ok": True, "document_id": did, "files": len(files)}


def _revoke_google() -> None:
    raw = store.kv_get("google_creds")
    if not raw:
        return
    try:
        import requests
        tok = json.loads(raw).get("refresh_token") or json.loads(raw).get("token")
        if tok:
            requests.post("https://oauth2.googleapis.com/revoke", params={"token": tok}, timeout=8)
    except Exception:  # noqa: BLE001 - melhor esforço; a credencial é apagada de qualquer jeito
        pass


def delete_account(uid: str) -> dict:
    if uid == store.OWNER_ID:
        return {"error": "a conta do administrador não pode ser apagada pelo app"}
    u = accounts.get_user(uid)
    if not u:
        return {"error": "conta não encontrada"}
    ctx = accounts.user_ctx(u)
    with store.as_user(ctx):
        _revoke_google()
        store.kv_set("google_creds", "")
    accounts.forget_user(uid, u.get("email"))
    src = ctx["dir"]
    if os.path.isdir(src):
        dest_root = os.path.join(config.DATA_DIR, "deleted")
        os.makedirs(dest_root, exist_ok=True)
        shutil.move(src, os.path.join(dest_root, f"{uid}-{int(time.time())}"))
    store._ready.discard(ctx["db"])
    return {"ok": True}


def purge_deleted(days: int = PURGE_AFTER_DAYS) -> int:
    """Destrói de vez as contas apagadas há mais de N dias."""
    root = os.path.join(config.DATA_DIR, "deleted")
    if not os.path.isdir(root):
        return 0
    n = 0
    limit = time.time() - days * 86400
    for name in os.listdir(root):
        p = os.path.join(root, name)
        try:
            when = int(name.rsplit("-", 1)[1])
        except (IndexError, ValueError):
            when = os.path.getmtime(p)
        if when < limit:
            shutil.rmtree(p, ignore_errors=True)
            n += 1
    return n
