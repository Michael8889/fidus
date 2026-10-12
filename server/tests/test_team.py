"""v0.17: Premium — mais 1 pessoa na conta e acesso do contabilista (portal só de leitura)."""
import os
import re
import tempfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import accounts, google_client, mailer, main, plans, store, team, tools  # noqa: E402

client = TestClient(main.app)
H = {"Authorization": "Bearer t"}


class FakeCreds:
    granted_scopes = sorted(google_client.REQUIRED)

    def to_json(self):
        return '{"token": "x", "refresh_token": "y", "client_id": "c", "client_secret": "s"}'


def login(monkeypatch, email, name="Rita Lopes"):
    main._book_hits.clear()
    n = {"i": 0}

    def fake_auth_url():
        n["i"] += 1
        return f"https://accounts.google.com/fake?{n['i']}", f"tm-{email}-{n['i']}", "v"
    monkeypatch.setattr(google_client, "auth_url", fake_auth_url)
    monkeypatch.setattr(google_client, "exchange", lambda url, state, ver: (
        FakeCreds(), {"email": email, "name": name, "verified": True, "sub": "sub-" + email}))
    client.get("/auth/google/login", follow_redirects=False)
    page = client.get(f"/auth/google/callback?state=tm-{email}-{n['i']}&code=abc").text
    m = re.search(r"login\?code=([A-Z0-9]{8})", page)
    if not m:
        return None
    return {"Authorization": f"Bearer {client.post('/v1/auth/exchange', json={'code': m.group(1)}).json()['token']}"}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send_raw", lambda to, subject, body, **k: sent.append((to, subject, body)) or True)
    with accounts._db() as c:
        for tb in ("account_members", "accountant_access", "accountant_codes", "accountant_sessions", "accountant_fails"):
            c.execute(f"DELETE FROM {tb}")
    plan, prof = store.kv_get("plan"), store.kv_get("profile")
    yield sent
    store.kv_set("plan", plan) if plan else store.kv_del("plan")
    store.kv_set("profile", prof) if prof is not None else store.kv_del("profile")


def test_plan_texts_have_nothing_soon():
    hl = " ".join(plans.PLANS["premium"]["highlights"])
    assert "Cobrança e fatura" not in hl and "contador" in hl and "Mais 1 pessoa" in hl
    assert "client_invoices" not in plans.FEATURE_MIN and plans.FEATURE_MIN["accountant_access"] == "premium"


def test_needs_premium(_clean):
    plans.set_plan("negocio")
    r = client.post("/v1/accountant", json={"email": "cont@gabinete.pt"}, headers=H).json()
    assert r["locked"] and r["upsell"]["plan"] == "premium"
    r = client.post("/v1/members", json={"email": "rita@x.pt"}, headers=H).json()
    assert r["locked"] and r["upsell"]["feature"] == "extra_user"


def test_member_shares_account_but_not_email_or_settings(monkeypatch, _clean):
    sent = _clean
    plans.set_plan("premium")
    assert login(monkeypatch, "rita@x.pt") is None  # sem convite não entra
    r = client.post("/v1/members", json={"email": "Rita@X.pt"}, headers=H).json()
    assert r["ok"] and sent[-1][0] == "rita@x.pt"
    assert client.post("/v1/members", json={"email": "outra@x.pt"}, headers=H).status_code == 400  # só 1 pessoa
    tok = login(monkeypatch, "rita@x.pt")
    assert tok
    me = client.get("/v1/me", headers=tok).json()
    assert me["member"]["email"] == "rita@x.pt" and me["id"] == store.OWNER_ID and not me["is_owner"]
    assert not me["onboarding_pending"]
    # mesma conta: a despesa dela aparece para o titular, com o nome dela na Atividade
    with store.as_user(accounts.user_ctx(accounts.by_email("rita@x.pt"))):
        r = tools.run("add_expense", {"amount": 12.5, "category": "outros", "business": store.businesses()[0],
                                      "date": "2021-02-03"})
        assert r["ok"]
        store.add_activity("expense_added", "Despesa 12.50", "", "feito", str(r["expense_id"]))
        assert "search_emails" not in {t["name"] for t in tools.available_tools()}
        assert "só para o titular" in tools.run("read_email", {"message_id": "x"})["error"]
        from app import actions
        with pytest.raises(actions.SendError):
            actions.send_pending("qualquer")
    eid = r["expense_id"]
    assert any(e["id"] == eid for e in store.query_expenses("2021-02-01", "2021-02-28"))
    acts = client.get("/v1/activity", headers=H).json()
    items = acts.get("items") if isinstance(acts, dict) else acts
    assert any("Rita" in (a.get("detail") or "") for a in items)
    tools.run_delete_expense(eid)
    # conversas separadas
    with store.as_user(accounts.user_ctx(accounts.by_email("rita@x.pt"))):
        store.add_message("user", "olá, sou a Rita")
        mine = store.current_conv()
        assert [c["id"] for c in store.list_conversations()] == [mine]
    assert mine not in [c["id"] for c in store.list_conversations()]
    assert not store.open_conversation(mine)  # o titular não abre a conversa dela
    # nada de plano, ligações, definições, conta
    for path in ("/v1/members", "/v1/accountant", "/v1/countries", "/v1/account/delete", "/v1/mail_provider",
                 "/v1/wallets"):
        assert client.post(path, json={}, headers=tok).status_code == 403, path
    assert client.get("/v1/auth/google/link", headers=tok).status_code == 403
    assert client.get("/v1/wallets", headers=tok).status_code == 200
    assert client.post("/v1/plan", json={"plan": "global"}, headers=tok).status_code == 403
    p0 = store.profile().get("language")
    client.post("/v1/profile", json={"language": "en"}, headers=tok)
    assert store.profile().get("language") == p0  # o perfil é do titular
    # titular baixa o plano: a 2.ª pessoa fica sem acesso
    plans.set_plan("negocio")
    assert client.get("/v1/me", headers=tok).status_code == 403
    plans.set_plan("premium")
    # titular remove: sai na hora
    mid = client.get("/v1/members", headers=H).json()["members"][0]["id"]
    assert client.post(f"/v1/members/{mid}/remove", headers=H).json()["ok"]
    assert client.get("/v1/me", headers=tok).status_code == 401
    assert login(monkeypatch, "rita@x.pt") is None
    # convidar de novo volta a funcionar
    client.post("/v1/members", json={"email": "rita@x.pt"}, headers=H)
    assert login(monkeypatch, "rita@x.pt")
    client.post(f"/v1/members/{client.get('/v1/members', headers=H).json()['members'][0]['id']}/remove", headers=H)


def test_member_cannot_be_someone_with_own_account(monkeypatch, _clean):
    plans.set_plan("premium")
    accounts.invite("dono2@x.pt", "essencial")
    assert login(monkeypatch, "dono2@x.pt", "Dono Dois")
    r = client.post("/v1/members", json={"email": "dono2@x.pt"}, headers=H)
    assert r.status_code == 400 and "conta Fidus própria" in r.json()["detail"]


def _portal_login(sent, email):
    X = {"X-Fidus-Cont": "1"}
    c = TestClient(main.app, base_url="https://testserver")
    assert c.post("/contabilista/api/start", json={"email": email}, headers=X).json()["ok"]
    code = re.search(r"(\d{6})", sent[-1][1]).group(1)
    assert c.post("/contabilista/api/login", json={"email": email, "code": "000000" if code != "000000" else "111111"}, headers=X).status_code == 400
    assert c.post("/contabilista/api/login", json={"email": email, "code": code}, headers=X).json()["ok"]
    return c


def test_accountant_portal_read_only(monkeypatch, _clean):
    sent = _clean
    plans.set_plan("premium")
    store.save_profile(country="PT", language="pt-PT", countries=["PT"])
    r = client.post("/v1/accountant", json={"email": "cont@gabinete.pt"}, headers=H).json()
    assert r["ok"] and sent[-1][0] == "cont@gabinete.pt" and "/contabilista" in sent[-1][2]
    gid = r["id"]
    e1 = tools.run("add_expense", {"amount": 23.8, "currency": "EUR", "vat": 3.97, "category": "alimentacao",
                                   "business": store.businesses()[0], "date": "2022-03-10", "merchant": "Tasca",
                                   "buyer_nif": "", "supplier_nif": "", "irs_category": "restauracao_alojamento"})["expense_id"]
    # quem não tem acesso não recebe código (e a resposta é a mesma)
    n = len(sent)
    X = {"X-Fidus-Cont": "1"}
    assert client.post("/contabilista/api/start", json={"email": "curioso@x.pt"}, headers=X).json()["ok"]
    assert len(sent) == n
    assert client.post("/contabilista/api/start", json={"email": "cont@gabinete.pt"}).status_code == 403  # sem cabeçalho
    c = _portal_login(sent, "cont@gabinete.pt")
    me = c.get("/contabilista/api/me").json()
    assert me["clients"][0]["id"] == gid
    d = c.get(f"/contabilista/api/c/{gid}/expenses?month=2022-03").json()
    assert d["count"] == 1 and d["totals"]["EUR"] == 23.8 and d["portugal"] and d["invoices_without_nif"] == 1
    assert d["expenses"][0]["irs_category"].startswith("Restauração")
    zipr = c.get(f"/contabilista/api/c/{gid}/export?month=2022-03")
    assert zipr.status_code == 200 and zipr.content[:2] == b"PK"
    assert c.get(f"/contabilista/api/c/{gid}/receipt/{e1}").status_code == 404  # sem foto
    assert c.get(f"/contabilista/api/c/{gid + 999}/expenses").status_code == 404
    assert "Contabilista" in c.get("/contabilista").text
    lst = client.get("/v1/accountant", headers=H).json()["accountants"]
    assert lst[0]["last_access"]  # o cliente vê quando o contabilista entrou
    # o cliente corta o acesso: acabou na hora
    assert client.post(f"/v1/accountant/{gid}/remove", headers=H).json()["ok"]
    assert c.get(f"/contabilista/api/c/{gid}/expenses").status_code == 404
    tools.run_delete_expense(e1)
    # sem sessão: 401
    assert TestClient(main.app).get("/contabilista/api/me").status_code == 401


def test_accountant_grant_undo_and_member_blocked(monkeypatch, _clean):
    plans.set_plan("premium")
    r = client.post("/v1/accountant", json={"email": "c2@gab.pt"}, headers=H).json()
    acts = client.get("/v1/activity", headers=H).json()
    items = acts.get("items") if isinstance(acts, dict) else acts
    a = next(x for x in items if x["kind"] == "accountant_added" and x.get("ref") == str(r["id"]))
    assert client.post(f"/v1/activity/{a['id']}/undo", headers=H).status_code == 200
    assert not client.get("/v1/accountant", headers=H).json()["accountants"]
