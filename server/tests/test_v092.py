"""v0.9.2: um aparelho por conta, entrar com código no e-mail, e-mails automáticos."""
import os
import re
import tempfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import accounts, config, google_client, mailer, main, store  # noqa: E402

client = TestClient(main.app)
H = {"Authorization": "Bearer t"}


@pytest.fixture(autouse=True)
def mails(monkeypatch):
    main._book_hits.clear()
    out = []
    monkeypatch.setattr(config, "RESEND_API_KEY", "re_teste")
    monkeypatch.setattr(config, "EMAIL_FROM", "Fidus <ola@fidus.test>")
    monkeypatch.setattr(mailer, "_deliver", lambda to, subject, html, text: out.append({"to": to, "subject": subject, "html": html}))

    class Now:  # e-mails "em segundo plano" rodam na hora nos testes
        def __init__(self, target, daemon=None):
            self.t = target

        def start(self):
            self.t()
    monkeypatch.setattr(mailer.threading, "Thread", Now)
    return out


class FakeCreds:
    granted_scopes = sorted(google_client.REQUIRED)

    def to_json(self):
        return '{"token": "x", "refresh_token": "y", "client_id": "c", "client_secret": "s"}'


def google_login(monkeypatch, email, device):
    n = {"i": 0}

    def fake_auth_url():
        n["i"] += 1
        return f"https://accounts.google.com/fake?{n['i']}", f"s92-{email}-{device}-{n['i']}", "verif"
    monkeypatch.setattr(google_client, "auth_url", fake_auth_url)
    monkeypatch.setattr(google_client, "exchange", lambda url, state, ver: (
        FakeCreds(), {"email": email, "name": "Bia Lima", "verified": True, "sub": "sub-" + email}))
    client.get("/auth/google/login", follow_redirects=False)
    page = client.get(f"/auth/google/callback?state=s92-{email}-{device}-{n['i']}&code=abc").text
    code = re.search(r"login\?code=([A-Z0-9]{8})", page).group(1)
    tok = client.post("/v1/auth/exchange", json={"code": code, "device_id": device, "device_name": f"Celular {device}"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def test_one_device_per_account(monkeypatch):
    accounts.invite("bia@x.com", "essencial")
    a = google_login(monkeypatch, "bia@x.com", "aparelhoA")
    assert client.get("/v1/me", headers=a).status_code == 200
    b = google_login(monkeypatch, "bia@x.com", "aparelhoB")
    r = client.get("/v1/me", headers=a)
    assert r.status_code == 401 and r.json()["detail"] == "outro_aparelho"  # o primeiro celular saiu
    assert client.get("/v1/me", headers=b).status_code == 200
    assert client.get("/v1/auth/device", headers=b).json()["device_name"] == "Celular aparelhoB"
    uid = accounts.by_email("bia@x.com")["id"]
    assert accounts.device_switches(uid) == 2
    users = {u["email"]: u for u in client.get("/v1/admin/users", headers=H).json()["users"]}
    assert users["bia@x.com"]["device_switches_30d"] == 2
    # o mesmo aparelho entrando de novo não conta como troca
    c = google_login(monkeypatch, "bia@x.com", "aparelhoB")
    assert accounts.device_switches(uid) == 2 and client.get("/v1/me", headers=c).status_code == 200
    assert client.get("/v1/me", headers=H).status_code == 200  # token de administrador do dono não é afetado
    client.post("/v1/auth/logout_all", headers=c)
    assert client.get("/v1/me", headers=c).json()["detail"] == "saiu"


def test_email_code_login(mails):
    accounts.invite("cid@x.com", "negocio")
    assert client.get("/v1/auth/options").json()["email"] is True
    secret = "segredo-do-app"
    import hashlib
    cc = hashlib.sha256(secret.encode()).hexdigest()
    assert client.post("/v1/auth/email/start", json={"email": "cid@x.com", "cc": cc}).json()["ok"]
    code = re.search(r"(\d{6})", mails[-1]["subject"]).group(1)
    assert mails[-1]["to"] == "cid@x.com"
    # outro app (sem o segredo) não usa o código; código errado conta tentativa
    assert client.post("/v1/auth/email/verify", json={"email": "cid@x.com", "code": code}).status_code == 400
    assert client.post("/v1/auth/email/verify", json={"email": "cid@x.com", "code": "000000", "verifier": secret}).status_code == 400
    r = client.post("/v1/auth/email/verify", json={"email": "cid@x.com", "code": code, "verifier": secret, "device_id": "d1"})
    assert r.status_code == 200 and r.json()["token"].startswith("fx_")
    assert client.post("/v1/auth/email/verify", json={"email": "cid@x.com", "code": code, "verifier": secret}).status_code == 400  # uso único
    # quem não tem acesso: mesma resposta, nenhum e-mail sai
    n = len(mails)
    assert client.post("/v1/auth/email/start", json={"email": "estranho@x.com"}).json()["ok"]
    assert len(mails) == n


def test_email_code_blocks_after_10_wrong_even_with_new_codes(mails):
    accounts.invite("dan@x.com", "essencial")
    client.post("/v1/auth/email/start", json={"email": "dan@x.com"})
    code = re.search(r"(\d{6})", mails[-1]["subject"]).group(1)
    wrong = "111111" if code != "111111" else "222222"
    for _ in range(10):
        client.post("/v1/auth/email/verify", json={"email": "dan@x.com", "code": wrong})
    main._book_hits.clear()
    client.post("/v1/auth/email/start", json={"email": "dan@x.com"})  # pedir outro não zera os erros
    assert client.post("/v1/auth/email/verify", json={"email": "dan@x.com", "code": code}).status_code == 400


def test_new_request_does_not_kill_existing_code(mails):
    accounts.invite("gil@x.com", "essencial")
    client.post("/v1/auth/email/start", json={"email": "gil@x.com"})
    first = re.search(r"(\d{6})", mails[-1]["subject"]).group(1)
    client.post("/v1/auth/email/start", json={"email": "gil@x.com"})  # outra pessoa pedindo de novo
    assert client.post("/v1/auth/email/verify", json={"email": "gil@x.com", "code": first}).status_code == 200


def test_google_accounts_and_owner_only_enter_with_google(monkeypatch, mails):
    accounts.invite("hel@x.com", "essencial")
    google_login(monkeypatch, "hel@x.com", "h1")  # conta presa a um Google
    client.post("/v1/auth/email/start", json={"email": "hel@x.com"})
    assert "Google" in mails[-1]["subject"] and not re.search(r"\d{6}", mails[-1]["subject"])
    monkeypatch.setattr(config, "OWNER_EMAIL", "dono@x.com")
    n = len(mails)
    client.post("/v1/auth/email/start", json={"email": "dono@x.com"})
    assert len(mails) == n + 1 and "Google" in mails[-1]["subject"]


def test_no_welcome_for_existing_customers(monkeypatch, mails):
    accounts.invite("ivo@x.com", "essencial")
    tok = google_login(monkeypatch, "ivo@x.com", "i1")
    with accounts._db() as c:
        c.execute("UPDATE users SET created_at='2026-01-01T00:00:00+00:00' WHERE email='ivo@x.com'")
    client.post("/v1/profile", json={"language": "pt", "only_if_empty": True}, headers=tok)
    assert not [m for m in mails if m["to"] == "ivo@x.com" and "Bem-vindo" in m["subject"]]


def test_email_login_off_without_provider(monkeypatch):
    monkeypatch.setattr(config, "RESEND_API_KEY", "")
    assert client.get("/v1/auth/options").json()["email"] is False
    assert client.post("/v1/auth/email/start", json={"email": "a@x.com"}).status_code == 503


def test_welcome_once_in_user_language(monkeypatch, mails):
    accounts.invite("eva@x.com", "essencial")
    tok = google_login(monkeypatch, "eva@x.com", "e1")
    client.post("/v1/profile", json={"language": "en-GB", "country": "GB", "only_if_empty": True}, headers=tok)
    client.post("/v1/profile", json={"language": "en-GB", "only_if_empty": True}, headers=tok)
    welcome = [m for m in mails if m["to"] == "eva@x.com" and "Welcome" in m["subject"]]
    assert len(welcome) == 1


def test_subscription_and_referral_emails(monkeypatch, mails):
    monkeypatch.setattr(config, "BILLING_WEBHOOK_SECRET", "seg")
    monkeypatch.setattr(config, "OWNER_EMAIL", "mike@x.com")
    monkeypatch.setattr(config, "REFERRAL_SIGNUP", True)
    accounts.invite("fred@x.com", "essencial")
    tok = google_login(monkeypatch, "fred@x.com", "f1")
    uid = accounts.by_email("fred@x.com")["id"]
    client.post("/v1/referral/apply", json={"code": accounts.referral_code(store.OWNER_ID)}, headers=tok)
    ev = {"event": {"type": "INITIAL_PURCHASE", "app_user_id": uid, "product_id": "fidus_premium:mensal", "period_type": "NORMAL"}}
    client.post("/billing/revenuecat", json=ev, headers={"Authorization": "Bearer seg"})
    assert any(m["to"] == "fred@x.com" and "Premium" in m["subject"] for m in mails)
    assert any(m["to"] == "mike@x.com" and "10%" in m["subject"] for m in mails)  # quem convidou fica sabendo
    ev["event"]["type"] = "BILLING_ISSUE"
    client.post("/billing/revenuecat", json=ev, headers={"Authorization": "Bearer seg"})
    assert any(m["to"] == "fred@x.com" and ("cobrar" in m["subject"] or "charge" in m["subject"]) for m in mails)


def test_email_template_escapes_names():
    subject, body = mailer.render("welcome", "pt", name="<script>x</script>")
    assert "<script>" not in body and "&lt;script&gt;" in body
