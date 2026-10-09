"""v0.10: boas-vindas em conversa, dicas por e-mail (leads), parceiros, pt-PT, privacidade/termos, exportar por e-mail."""
import json
import os
import re
import tempfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

from fastapi.testclient import TestClient  # noqa: E402

from app import (accounts, agent, config, google_client, i18n, mailer, main, metrics, newsletter,  # noqa: E402
                 onboarding, partners, store)

client = TestClient(main.app)
H = {"Authorization": "Bearer t"}
X = {"X-Fidus-Admin": "1"}


class FakeCreds:
    granted_scopes = sorted(google_client.REQUIRED)

    def to_json(self):
        return '{"token": "x", "refresh_token": "y", "client_id": "c", "client_secret": "s"}'


def login(monkeypatch, email, ref=""):
    main._book_hits.clear()
    n = {"i": 0}

    def fake_auth_url():
        n["i"] += 1
        return f"https://accounts.google.com/fake?{n['i']}", f"s10-{email}-{n['i']}", "v"
    monkeypatch.setattr(google_client, "auth_url", fake_auth_url)
    monkeypatch.setattr(google_client, "exchange", lambda url, state, ver: (
        FakeCreds(), {"email": email, "name": "Ana Souza", "verified": True, "sub": "sub-" + email}))
    client.get("/auth/google/login" + (f"?ref={ref}" if ref else ""), follow_redirects=False)
    page = client.get(f"/auth/google/callback?state=s10-{email}-{n['i']}&code=abc").text
    code = re.search(r"login\?code=([A-Z0-9]{8})", page).group(1)
    return {"Authorization": f"Bearer {client.post('/v1/auth/exchange', json={'code': code}).json()['token']}"}


def fake_extract(monkeypatch):
    """O modelo leve entende as respostas livres das boas-vindas."""
    def chat(system, messages, tools, **kw):
        txt = messages[-1]["content"]
        if "businesses/accounts" in system:
            return {"text": json.dumps({"wallets": [{"name": "Salão Ana", "currency": "EUR"},
                                                    {"name": "Pessoal", "currency": "EUR"}]}), "tool_calls": []}
        if "IANA" in system:
            return {"text": '{"city": "Lisboa", "timezone": "Europe/Lisbon"}', "tool_calls": []}
        if "name the person" in system:
            return {"text": '{"name": "Ana"}', "tool_calls": []}
        return {"text": txt, "tool_calls": []}
    monkeypatch.setattr(onboarding.llm, "chat", chat)


# ---------- boas-vindas ----------
def test_onboarding_full_flow(monkeypatch):
    accounts.invite("ana10@x.com", "negocio")
    tok = login(monkeypatch, "ana10@x.com")
    client.post("/v1/profile", json={"language": "pt-PT", "country": "PT"}, headers=tok)
    assert client.get("/v1/me", headers=tok).json()["onboarding_pending"]
    fake_extract(monkeypatch)
    q = client.get("/v1/onboarding", headers=tok).json()
    assert q["step"] == "name" and "intro" in q and "Olá" in q["intro"]  # português de Portugal escrito à mão
    q = client.post("/v1/onboarding/answer", json={"step": "name", "value": "Ana"}, headers=tok).json()
    assert q["step"] == "work" and {o["id"] for o in q["options"]} == {"self", "company", "both"}
    q = client.post("/v1/onboarding/answer", json={"step": "work", "value": "company"}, headers=tok).json()
    assert q["step"] == "wallets" and q["suggested_currency"] == "EUR"
    q = client.post("/v1/onboarding/answer", json={"step": "wallets", "value": "o salão em euros e o pessoal"},
                    headers=tok).json()
    q = client.post("/v1/onboarding/answer", json={"step": "city", "value": "estou em Lisboa"}, headers=tok).json()
    assert q["step"] == "priorities" and q["kind"] == "multi" and q["max"] == 3
    q = client.post("/v1/onboarding/answer", json={"step": "priorities", "value": ["expenses", "agenda", "x", "email", "tasks"]},
                    headers=tok).json()
    q = client.post("/v1/onboarding/answer", json={"step": "style", "skip": True}, headers=tok).json()
    q = client.post("/v1/onboarding/answer", json={"step": "briefing", "value": "07:00"}, headers=tok).json()
    assert q["step"] == "emails"
    done = client.post("/v1/onboarding/answer", json={"step": "emails", "value": "yes"}, headers=tok).json()
    assert done["done"] and "Anular" in done["messages"][0] and done["messages"][0].startswith("Pronto, Ana!")
    me = client.get("/v1/me", headers=tok).json()
    p = me["profile"]
    assert p["name"] == "Ana" and p["work_type"] == "company" and p["timezone"] == "Europe/Lisbon"
    assert p["businesses"] == ["Salão Ana", "Pessoal"] and p["wallet_currency"]["Salão Ana"] == "EUR"
    assert p["priorities"] == ["expenses", "agenda", "email"] and p["briefing_time"] == "07:00"
    assert "reply_style" not in p and not me["onboarding_pending"]
    assert client.get("/v1/marketing", headers=tok).json()["yes"]
    # o assistente passa a saber o que a pessoa disse (e escreve em português de Portugal)
    uid = accounts.by_email("ana10@x.com")["id"]
    with store.as_user(accounts.user_ctx(accounts.get_user(uid))):
        ctx = agent._context()
    assert "Salão Ana (EUR)" in ctx and "português de Portugal" in ctx and "tem empresa" in ctx


def test_onboarding_wallet_limit_and_order(monkeypatch):
    accounts.invite("bia10@x.com", "essencial")
    tok = login(monkeypatch, "bia10@x.com")
    fake_extract(monkeypatch)
    client.get("/v1/onboarding", headers=tok)
    assert "error" in client.post("/v1/onboarding/answer", json={"step": "city", "value": "x"}, headers=tok).json()
    client.post("/v1/onboarding/answer", json={"step": "name", "skip": True}, headers=tok)
    client.post("/v1/onboarding/answer", json={"step": "work", "value": "self"}, headers=tok)
    r = client.post("/v1/onboarding/answer", json={"step": "wallets", "value": "salão e pessoal"}, headers=tok).json()
    assert r["notes"] and "Salão Ana" in r["notes"][0]  # Essencial: só a primeira carteira, e avisa
    assert client.get("/v1/me", headers=tok).json()["profile"]["businesses"] == ["Salão Ana"]


def test_owner_not_forced_into_onboarding():
    assert client.get("/v1/me", headers=H).json()["onboarding_pending"] is False
    q = client.post("/v1/onboarding/restart", headers=H).json()  # mas pode refazer pelas Configurações
    assert q["step"] == "name"


# ---------- dicas por e-mail ----------
def test_newsletter_sequence_and_unsubscribe(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "enabled", lambda: True)
    monkeypatch.setattr(mailer, "_deliver", lambda to, subject, html, text, att=None, headers=None:
                        sent.append((to, subject, html, headers)))
    monkeypatch.setattr(config, "MENTOR_BOOKING_URL", "https://fidus.test/book/mike")
    user = {"id": "lead-1", "email": "lead1@x.com", "name": "Carla Dias"}
    newsletter.set_consent(user, True, {"language": "pt", "country": "BR", "work_type": "company"})
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    newsletter.run_due(now)
    mine = [x for x in sent if x[0] == "lead1@x.com"]
    assert len(mine) == 1 and "Notas do Mike #1" in mine[-1][1] and "Carla" in mine[-1][2]
    assert "List-Unsubscribe" in mine[-1][3] and "/email/sair?t=" in mine[-1][2]
    newsletter.run_due(now + timedelta(hours=1))
    assert len([x for x in sent if x[0] == "lead1@x.com"]) == 1  # um por vez
    for d in (3, 7, 12):
        newsletter.run_due(now + timedelta(days=d, hours=1))
    mine = [x for x in sent if x[0] == "lead1@x.com"]
    assert len(mine) == 4 and "diagnóstico" in mine[-1][2] and "fidus.test/book/mike" in mine[-1][2]
    token = re.search(r"t=([\w-]+)", mine[-1][2]).group(1)
    assert "Parar de receber" in client.get(f"/email/sair?t={token}").text
    client.post("/email/sair", data={"t": token})
    assert not newsletter.consent_of("lead-1")
    newsletter.run_due(now + timedelta(days=30))
    assert len([x for x in sent if x[0] == "lead1@x.com"]) == 4


def test_leads_tab_and_csv():
    code = client.post("/v1/admin/panel_code", headers=H).json()["code"]
    b = TestClient(main.app, base_url="https://testserver")
    b.post("/admin/api/login", json={"code": code})
    d = b.get("/admin/api/leads").json()
    assert "leads" in d and d["sequence_len"] >= 4
    assert b.get("/admin/api/leads.csv").text.startswith("email,")


# ---------- parceiros ----------
def test_partner_code_discount_and_commission(monkeypatch):
    monkeypatch.setattr(config, "BILLING_WEBHOOK_SECRET", "seg")
    monkeypatch.setattr(config, "REFERRAL_SIGNUP", True)
    code = client.post("/v1/admin/panel_code", headers=H).json()["code"]
    b = TestClient(main.app, base_url="https://testserver")
    b.post("/admin/api/login", json={"code": code})
    r = b.post("/admin/api/partners", json={"code": "ana", "name": "Ana Criadora", "email": "ana@cria.pt"}, headers=X)
    assert r.status_code == 200 and r.json()["partner"]["code"] == "ANA"
    assert b.post("/admin/api/partners", json={"code": "ANA", "name": "x"}, headers=X).status_code == 400
    tok = login(monkeypatch, "seguidor10@x.com", ref="ANA")  # código do criador abre o cadastro
    uid = accounts.by_email("seguidor10@x.com")["id"]
    bc = client.get("/v1/billing", headers=tok).json()
    assert bc["referral_trial"] and bc["trial_offer_tag"] == "parceiro" and bc["offer_discount"] == 20
    auth = {"Authorization": "Bearer seg"}
    ev = {"event": {"id": "e1", "type": "INITIAL_PURCHASE", "app_user_id": uid, "product_id": "fidus_negocio_monthly",
                    "period_type": "NORMAL", "price_in_purchased_currency": 39.92, "currency": "EUR"}}
    client.post("/billing/revenuecat", json=ev, headers=auth)
    client.post("/billing/revenuecat", json=ev, headers=auth)  # aviso repetido: não conta duas vezes
    ren = {"event": {**ev["event"], "id": "e2", "type": "RENEWAL", "price_in_purchased_currency": 49.90}}
    client.post("/billing/revenuecat", json=ren, headers=auth)
    rep = {p["code"]: p for p in b.get("/admin/api/partners").json()["partners"]}["ANA"]
    assert rep["signups"] == 1 and rep["paying"] == 1 and rep["due"] == {"EUR": round(3.99 + 4.99, 2)}
    assert client.get("/v1/billing", headers=tok).json()["offer_kind"] is None  # já pagou: sem desconto de 1º mês
    # depois de 12 meses, não gera mais comissão
    with partners._db() as c:
        c.execute("UPDATE partner_links SET first_paid_at='2020-01-01T00:00:00+00:00' WHERE user_id=?", (uid,))
    late = {"event": {**ev["event"], "id": "e3", "type": "RENEWAL"}}
    client.post("/billing/revenuecat", json=late, headers=auth)
    assert {p["code"]: p for p in b.get("/admin/api/partners").json()["partners"]}["ANA"]["due"]["EUR"] == 8.98
    assert b.post("/admin/api/partners/ANA/paid", headers=X).json()["marked"] == 2
    assert {p["code"]: p for p in b.get("/admin/api/partners").json()["partners"]}["ANA"]["due"] == {}


# ---------- pt-PT, páginas legais, exportar por e-mail, tempos ----------
def test_portuguese_from_portugal():
    assert i18n.norm("pt-PT") == "pt-pt" and i18n.norm("pt_BR") == "pt" and i18n.norm("pt") == "pt"
    assert "Portugal" in i18n.name("pt-PT")


def test_privacy_and_terms_pages(monkeypatch):
    monkeypatch.setattr(config, "COMPANY_ADDRESS", "1 Test St, London")
    p = client.get("/privacy").text
    assert "Fidus Labs Limited" in p and "17510962" in p and "Limited Use" in p and "1 Test St" in p
    assert "Política de Privacidade" in client.get("/privacy?lang=pt").text
    assert "Terms of Use" in client.get("/terms").text and "Termos de Uso" in client.get("/terms?lang=pt").text


def test_export_to_own_email(monkeypatch):
    from app import tools
    sent = []
    monkeypatch.setattr(mailer, "enabled", lambda: True)
    monkeypatch.setattr(mailer, "_deliver", lambda to, subject, html, text, att=None, headers=None: sent.append((to, att)))
    monkeypatch.setattr(config, "OWNER_EMAIL", "dono@x.com")
    tools.run("add_expense", {"amount": 12, "category": config.CATEGORIES[0], "business": store.businesses()[0],
                              "date": "2026-02-10"})
    r = client.post("/v1/expenses/export", json={"month": "2026-02", "email": True}, headers=H).json()
    assert r.get("locked") or (r["emailed_to"] == "dono@x.com" and sent[-1][1][0]["filename"].endswith(".zip"))
    monkeypatch.setattr(mailer, "enabled", lambda: False)
    r2 = client.post("/v1/expenses/export", json={"month": "2026-02", "email": True}, headers=H)
    assert r2.status_code == 503 or r2.json().get("locked")


def test_voice_stage_timings():
    before = metrics.stage_p50()["voz"]["n"]
    for ms in (900, 1800, 3000):
        metrics.record_stage("voz", ms)
    got = metrics.stage_p50()["voz"]
    assert got["n"] == before + 3 and got["p50"] is not None
