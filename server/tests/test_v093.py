"""v0.9.3: custo de IA por cliente e uso justo, exportar e apagar a conta, backup e saúde do servidor."""
import io
import json
import os
import re
import tarfile
import tempfile
import zipfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import account_data, accounts, agent, backup, config, google_client, llm, main, store  # noqa: E402

client = TestClient(main.app)
H = {"Authorization": "Bearer t"}


class FakeCreds:
    granted_scopes = sorted(google_client.REQUIRED)

    def to_json(self):
        return '{"token": "x", "refresh_token": "y", "client_id": "c", "client_secret": "s"}'


def login(monkeypatch, email):
    main._book_hits.clear()
    accounts.invite(email, "essencial")
    monkeypatch.setattr(google_client, "auth_url", lambda: ("https://g/x", f"s93-{email}", "v"))
    monkeypatch.setattr(google_client, "exchange", lambda url, state, ver: (
        FakeCreds(), {"email": email, "name": "Zoe", "verified": True, "sub": "sub-" + email}))
    client.get("/auth/google/login", follow_redirects=False)
    page = client.get(f"/auth/google/callback?state=s93-{email}&code=abc").text
    code = re.search(r"login\?code=([A-Z0-9]{8})", page).group(1)
    tok = client.post("/v1/auth/exchange", json={"code": code}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}, accounts.by_email(email)


@pytest.fixture(autouse=True)
def no_external(monkeypatch):
    monkeypatch.setattr(account_data, "_revoke_google", lambda: None)


# ---------- custo e uso justo ----------
def test_usage_is_recorded_and_fair_use_blocks(monkeypatch):
    tok, u = login(monkeypatch, "zoe@x.com")
    with store.as_user(accounts.user_ctx(u)):
        store.add_usage({"model": "claude-sonnet-5-5", "calls": 3, "input": 1_000_000, "output": 100_000})
        assert store.usage_summary(30)["today"] == pytest.approx(3.0)  # 2 + 1
    monkeypatch.setattr(config, "FAIR_USE_DAILY_USD", 2.5)
    called = []
    monkeypatch.setattr(agent.llm, "chat", lambda s, m, t, **kw: (called.append(1), {"text": "oi", "tool_calls": []})[1])
    r = client.post("/v1/message", json={"text": "bom dia"}, headers=tok).json()
    assert r.get("fair_use") and not called  # passou do limite: não gasta mais IA hoje
    r = client.post("/v1/message", json={"text": "bom dia"}, headers=H).json()
    assert r["reply"] == "oi"  # o dono não tem limite
    costs = client.get("/v1/admin/costs", headers=H).json()
    row = [x for x in costs["users"] if x["email"] == "zoe@x.com"][0]
    assert row["month"] == pytest.approx(3.0) and costs["total_month_usd"] >= 3.0
    assert client.get("/v1/admin/costs", headers=tok).status_code == 403


def test_cost_formula_with_search():
    assert llm.cost_usd({"model": "claude-haiku-4-5-20251001", "input": 1_000_000, "searches": 2}) == pytest.approx(1.02)


# ---------- exportar ----------
def test_export_has_data_and_files_but_no_google_keys(monkeypatch):
    tok, u = login(monkeypatch, "yan@x.com")
    with store.as_user(accounts.user_ctx(u)):
        rec = os.path.join(store.receipts_dir(), "r1.jpg")
        open(rec, "wb").write(b"\xff\xd8recibo")
        store.add_expense("2026-10-01", 12.5, "GBP", "outros", "Pessoal", "Tesco", None, None, rec)
        assert store.kv_get("google_creds")
    r = client.post("/v1/account/export", headers=tok).json()
    assert r["ok"] and r["files"] == 1 and "/v1/documents/" in r["url"]
    with store.as_user(accounts.user_ctx(u)):
        path = store.get("documents", r["document_id"])["path"]
    z = zipfile.ZipFile(path)
    names = z.namelist()
    assert "dados/expenses.json" in names and "arquivos/r1.jpg" in names
    assert json.loads(z.read("dados/expenses.json"))[0]["merchant"] == "Tesco"
    assert "google_creds" not in z.read("dados/perfil_e_ajustes.json").decode()


# ---------- apagar ----------
def test_delete_account(monkeypatch):
    tok, u = login(monkeypatch, "xu@x.com")
    assert client.post("/v1/account/delete", json={"confirm": "sim"}, headers=tok).status_code == 400
    assert client.post("/v1/account/delete", json={"confirm": "APAGAR"}, headers=tok).json()["ok"]
    assert client.get("/v1/me", headers=tok).status_code == 401
    gone = accounts.get_user(u["id"])
    assert gone["status"] == "apagado" and gone["email"] is None
    assert not os.path.exists(accounts.user_ctx(u)["dir"])
    assert all(x["id"] != u["id"] for x in client.get("/v1/admin/users", headers=H).json()["users"])
    # o mesmo e-mail pode criar uma conta nova do zero
    tok2, u2 = login(monkeypatch, "xu@x.com")
    assert u2["id"] != u["id"]
    assert client.post("/v1/account/delete", json={"confirm": "APAGAR"}, headers=H).status_code == 400  # dono não


def test_purge_after_30_days():
    root = os.path.join(config.DATA_DIR, "deleted")
    os.makedirs(os.path.join(root, "velho-1000"), exist_ok=True)
    os.makedirs(os.path.join(root, f"novo-{int(__import__('time').time())}"), exist_ok=True)
    assert account_data.purge_deleted() >= 1
    assert not os.path.exists(os.path.join(root, "velho-1000")) and len(os.listdir(root)) >= 1


# ---------- backup e saúde ----------
def test_backup_and_health(monkeypatch):
    store.add_message("user", "mensagem para o backup")
    info = client.post("/v1/admin/backup", headers=H).json()
    assert info["ok"] and info["size"] > 0
    tar = tarfile.open(os.path.join(config.DATA_DIR, "backups", info["file"]))
    names = tar.getnames()
    assert any(n.startswith("bancos/") and n.endswith("accounts.db") for n in names)
    assert not any("/backups/" in n for n in names)
    h = client.get("/health")
    assert h.status_code == 200 and h.json()["backup_age_hours"] is not None
    monkeypatch.setattr(backup, "age_hours", lambda: 50.0)
    h = client.get("/health")
    assert h.status_code == 503 and "backup atrasado" in h.json()["problems"][0]
