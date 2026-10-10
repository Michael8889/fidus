"""v0.12: backend do site (lista de espera com confirmação, sair da lista, aviso da loja, parceria, painel)."""
import os
import tempfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

from fastapi.testclient import TestClient  # noqa: E402

from app import accounts, config, mailer, main, site_forms  # noqa: E402

client = TestClient(main.app)
H = {"Authorization": "Bearer t"}


def _mails(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send_raw", lambda to, subject, body, **k: sent.append((to, subject, body, k)) or True)
    site_forms._HITS.clear()
    return sent


def _ip(n):
    return {"x-real-ip": f"10.0.0.{n}"}


def test_waitlist_confirms_once_with_plan_ref_and_leave_link(monkeypatch):
    sent = _mails(monkeypatch)
    body = {"email": "Bia@Site.com", "lang": "pt-BR", "platform": "android", "plan": "negocio", "ref": "ana"}
    assert client.post("/v1/site/waitlist", json=body, headers=_ip(1)).status_code == 200
    assert client.post("/v1/site/waitlist", json=body, headers=_ip(1)).status_code == 200  # repetido: sem 2º e-mail
    assert len(sent) == 1 and sent[0][0] == "bia@site.com" and "lista do Fidus" in sent[0][1]
    assert "Negócio" in sent[0][2] and "/lista/sair?t=" in sent[0][3]["footer"]
    row = next(w for w in accounts.waitlist() if w["email"] == "bia@site.com")
    assert row["plan"] == "negocio" and row["ref"] == "ANA" and row["platform"] == "android"
    # sair da lista: GET só pergunta (leitor de e-mail não apaga sozinho), POST apaga
    tok = row["token"]
    assert "Sair da lista" in client.get(f"/lista/sair?t={tok}&lang=pt").text
    assert any(w["email"] == "bia@site.com" for w in accounts.waitlist())
    assert "saiu da lista" in client.post("/lista/sair", data={"t": tok, "lang": "pt"}).text
    assert not any(w["email"] == "bia@site.com" for w in accounts.waitlist())


def test_waitlist_rejects_bad_email_and_rate_limits(monkeypatch):
    _mails(monkeypatch)
    assert client.post("/v1/site/waitlist", json={"email": "x"}, headers=_ip(2)).status_code == 400
    codes = [client.post("/v1/site/waitlist", json={"email": f"r{i}@x.com"}, headers=_ip(3)).status_code for i in range(7)]
    assert codes[:5] == [200] * 5 and codes[-1] == 429


def test_partner_page_and_application(monkeypatch):
    sent = _mails(monkeypatch)
    r = client.get("/parceiros")
    assert r.status_code == 200 and "Seja parceiro do Fidus" in r.text and "20%" in r.text and "/v1/site/partner" in r.text
    assert "Become a Fidus partner" in client.get("/partners").text
    d = {"name": "Carla Souza", "email": "carla@cria.com", "kind": "criador", "link": "https://instagram.com/carla",
         "audience": "5 a 50 mil", "country": "Brasil", "message": "posts e stories", "lang": "pt"}
    assert client.post("/v1/site/partner", json=d, headers=_ip(4)).status_code == 200
    app = accounts.partner_applications()[0]
    assert app["email"] == "carla@cria.com" and app["status"] == "nova"
    tos = [x[0] for x in sent]
    assert "carla@cria.com" in tos and config.SUPPORT_EMAIL in tos
    # robô (campo escondido preenchido) não grava; e-mail ruim dá 400
    n = len(accounts.partner_applications())
    assert client.post("/v1/site/partner", json={**d, "website": "spam"}, headers=_ip(5)).status_code == 200
    assert len(accounts.partner_applications()) == n
    assert client.post("/v1/site/partner", json={**d, "email": "x"}, headers=_ip(5)).status_code == 400


def test_admin_site_tab_csv_status_and_store_notify(monkeypatch):
    sent = _mails(monkeypatch)
    client.post("/v1/site/waitlist", json={"email": "and@x.com", "platform": "android", "lang": "en"}, headers=_ip(6))
    client.post("/v1/site/waitlist", json={"email": "ios@x.com", "platform": "ios", "lang": "pt"}, headers=_ip(6))
    client.post("/v1/site/partner", json={"name": "Dan", "email": "dan@x.com", "lang": "en"}, headers=_ip(6))
    code = client.post("/v1/admin/panel_code", headers=H).json()["code"]
    b = TestClient(main.app, base_url="https://testserver")
    b.post("/admin/api/login", json={"code": code})
    d = b.get("/admin/api/site").json()
    assert d["total"] >= 2 and d["applications"] and d["can_manage"]
    assert b.get("/admin/api/waitlist.csv").text.startswith("email,lang,platform,plan,ref")
    app_id = d["applications"][0]["id"]
    X = {"X-Fidus-Admin": "1"}
    assert b.post(f"/admin/api/partner-apps/{app_id}/status", json={"status": "aprovada"}, headers=X).status_code == 200
    assert b.post(f"/admin/api/partner-apps/{app_id}/status", json={"status": "x"}, headers=X).status_code == 400
    # sem loja configurada não avisa ninguém
    monkeypatch.setattr(config, "PLAY_STORE_URL", "")
    monkeypatch.setattr(config, "APP_STORE_URL", "")
    assert b.post("/admin/api/waitlist/notify", headers=X).status_code == 400
    # só Google Play no ar: avisa o Android, o iPhone espera; segunda vez não repete
    monkeypatch.setattr(config, "PLAY_STORE_URL", "https://play.google.com/store/apps/details?id=fidus")
    sent.clear()
    r = b.post("/admin/api/waitlist/notify", headers=X).json()
    assert "and@x.com" in [x[0] for x in sent] and "ios@x.com" not in [x[0] for x in sent]
    assert r["sent"] >= 1 and r["waiting_store"] >= 1
    sent.clear()
    assert b.post("/admin/api/waitlist/notify", headers=X).json()["sent"] == 0 and not sent


def test_site_has_real_buttons():
    html = client.get("/").text
    for must in ("/v1/site/waitlist", "/privacy?lang=", "/terms?lang=", "partnerHref", "joinErr", "detectRef", "p.pick"):
        assert must in html, must
