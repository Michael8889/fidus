"""v0.18: 7 dias grátis e assinatura pelo Stripe Checkout (sem rede: Stripe falso e avisos assinados aqui)."""
import hashlib
import hmac
import json
import os
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import accounts, agent, beta, billing, config, google_client, mailer, main, plans, store  # noqa: E402

client = TestClient(main.app)
H = {"Authorization": "Bearer t"}
SECRET = "whsec_test"


class FakeCreds:
    granted_scopes = sorted(google_client.REQUIRED)

    def to_json(self):
        return '{"token": "x", "refresh_token": "y", "client_id": "c", "client_secret": "s"}'


def login(monkeypatch, email):
    main._book_hits.clear()
    n = {"i": 0}

    def fake_auth_url():
        n["i"] += 1
        return f"https://accounts.google.com/fake?{n['i']}", f"bl-{email}-{n['i']}", "v"
    monkeypatch.setattr(google_client, "auth_url", fake_auth_url)
    monkeypatch.setattr(google_client, "exchange", lambda url, state, ver: (
        FakeCreds(), {"email": email, "name": "Joana Silva", "verified": True, "sub": "sub-" + email}))
    client.get("/auth/google/login", follow_redirects=False)
    page = client.get(f"/auth/google/callback?state=bl-{email}-{n['i']}&code=abc").text
    code = re.search(r"login\?code=([A-Z0-9]{8})", page).group(1)
    return {"Authorization": f"Bearer {client.post('/v1/auth/exchange', json={'code': code}).json()['token']}"}


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(config, "TRIAL_DAYS", 7)
    monkeypatch.setattr(config, "APP_DOWNLOAD_URL", "https://x/app.apk")
    monkeypatch.setattr(mailer, "send_raw", lambda *a, **k: True)
    monkeypatch.setattr(mailer, "send", lambda *a, **k: True)
    calls = []

    def fake_call(method, path, data=None):
        calls.append((method, path, data))
        if path == "/checkout/sessions":
            return {"id": "cs_1", "url": "https://checkout.stripe.com/c/pay/cs_1"}
        if path == "/billing_portal/sessions":
            return {"url": "https://billing.stripe.com/p/session/x"}
        raise AssertionError(path)
    monkeypatch.setattr(billing, "_call", fake_call)
    site = __import__("app.site_forms", fromlist=["x"])
    site._HITS.clear()
    return calls


def _signed(event: dict):
    payload = json.dumps(event).encode()
    ts = str(int(time.time()))
    sig = hmac.new(SECRET.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return payload, {"stripe-signature": f"t={ts},v1={sig}", "content-type": "application/json"}


def test_beta_user_gets_7_days_then_paywall(monkeypatch, _setup):
    client.post("/v1/site/waitlist", json={"email": "joana@x.pt", "platform": "android", "lang": "pt-PT"},
                headers={"x-real-ip": "10.7.0.1"})
    beta.invite("joana@x.pt")
    tok = login(monkeypatch, "joana@x.pt")
    me = client.get("/v1/me", headers=tok).json()
    assert me["access"] == "trial" and me["trial_days_left"] == 7 and me["plan"] == config.BETA_PLAN
    u = accounts.by_email("joana@x.pt")
    with store.as_user(accounts.user_ctx(u)):
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        store.kv_set("trial_ends", past)
        assert plans.access() == "expired"
        out = agent.handle("marca dentista amanhã às 10")
        assert out["upsell"]["expired"] and "grátis acabaram" in out["reply"]
    assert client.post("/v1/realtime/session", headers=tok).status_code == 402


def test_team_invite_has_no_trial(monkeypatch):
    accounts.invite("equipa@x.pt", "negocio")
    tok = login(monkeypatch, "equipa@x.pt")
    assert client.get("/v1/me", headers=tok).json()["access"] == "active"


def test_checkout_keeps_remaining_free_days_and_webhook_activates(monkeypatch, _setup):
    calls = _setup
    client.post("/v1/site/waitlist", json={"email": "rui@x.pt", "platform": "android", "lang": "pt-PT"},
                headers={"x-real-ip": "10.7.0.2"})
    beta.invite("rui@x.pt")
    tok = login(monkeypatch, "rui@x.pt")
    client.post("/v1/countries", json={"countries": ["PT"]}, headers=tok)
    r = client.post("/v1/billing/checkout", json={"plan": "premium", "period": "month"}, headers=tok).json()
    assert r["url"].startswith("https://checkout.stripe.com") and r["amount"] == 39.90 and r["currency"] == "EUR"
    data = calls[-1][2]
    assert data["mode"] == "subscription" and data["line_items[0][price_data][unit_amount]"] == "3990"
    assert data["line_items[0][price_data][currency]"] == "eur" and data["line_items[0][price_data][recurring][interval]"] == "month"
    assert int(data["subscription_data[trial_end]"]) > time.time() + 6 * 86400  # 1.ª cobrança só no fim do teste
    uid = accounts.by_email("rui@x.pt")["id"]
    assert data["client_reference_id"] == uid
    y = client.post("/v1/billing/checkout", json={"plan": "essencial", "period": "year"}, headers=tok).json()
    assert y["amount"] == 169.0
    assert client.post("/v1/billing/checkout", json={"plan": "x"}, headers=tok).status_code == 400
    # aviso falso é recusado
    bad = client.post("/billing/stripe", content=b"{}", headers={"stripe-signature": "t=1,v1=abc"})
    assert bad.status_code == 400
    ev = {"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {
        "mode": "subscription", "client_reference_id": uid, "customer": "cus_1",
        "metadata": {"fidus_user": uid, "plan": "premium"}}}}
    payload, hd = _signed(ev)
    assert client.post("/billing/stripe", content=payload, headers=hd).json()["plan"] == "premium"
    assert client.post("/billing/stripe", content=payload, headers=hd).json()["ignored"] == "repetido"
    me = client.get("/v1/me", headers=tok).json()
    assert me["access"] == "active" and me["plan"] == "premium" and me["countries"]["locked"]
    assert client.post("/v1/billing/portal", headers=tok).json()["url"].startswith("https://billing.stripe.com")
    # 1.ª cobrança de verdade e depois cancelamento
    payload, hd = _signed({"id": "evt_2", "type": "invoice.paid", "data": {"object": {
        "customer": "cus_1", "amount_paid": 3990, "currency": "eur", "id": "in_1"}}})
    assert client.post("/billing/stripe", content=payload, headers=hd).json()["paid"] == 39.9
    payload, hd = _signed({"id": "evt_3", "type": "customer.subscription.deleted", "data": {"object": {
        "customer": "cus_1", "metadata": {"fidus_user": uid, "plan": "premium"}}}})
    client.post("/billing/stripe", content=payload, headers=hd)
    assert client.get("/v1/me", headers=tok).json()["access"] == "expired"


def test_owner_is_never_blocked():
    assert client.get("/v1/me", headers=H).json()["access"] == "active"
    assert "Assinatura confirmada" in client.get("/assinatura/ok", headers={"accept-language": "pt-PT"}).text
