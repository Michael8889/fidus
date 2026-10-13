from fastapi.testclient import TestClient

from app import ads, config, main


def test_no_pixel_no_banner(monkeypatch):
    monkeypatch.setattr(config, "META_PIXEL_ID", "")
    assert ads.banner() == ""
    assert "fidus_ads_consent" not in TestClient(main.app).get("/").text


def test_banner_and_consent_only(monkeypatch):
    monkeypatch.setattr(config, "META_PIXEL_ID", "1234567890")
    monkeypatch.setattr(config, "META_CAPI_TOKEN", "x")
    sent = []
    monkeypatch.setattr(ads.requests, "post", lambda url, json, timeout: sent.append(json) or type("R", (), {"status_code": 200})())
    html = TestClient(main.app).get("/").text
    assert "fidus_ads_consent" in html and "1234567890" in html
    c = TestClient(main.app)
    c.post("/v1/site/waitlist", json={"email": "semconsent@exemplo.pt", "lang": "pt-pt"})
    assert ads.send("Lead", "semconsent@exemplo.pt", "e1", wait=True) is False  # sem "Aceitar", nada vai
    c.post("/v1/site/waitlist", json={"email": "comconsent@exemplo.pt", "lang": "pt-pt", "ads_consent": True,
                                      "fbp": "fb.1.1.2", "event_id": "lead-abc"})
    assert ads.send("Subscribe", "comconsent@exemplo.pt", "s1", value=16.9, currency="eur", wait=True) is True
    body = sent[-1]["data"][0]
    assert body["user_data"]["fbp"] == "fb.1.1.2" and "comconsent" not in str(body["user_data"]["em"])
    assert body["custom_data"] == {"value": 16.9, "currency": "EUR"}


def test_invoice_paid_finds_user_by_subscription_metadata():
    from app import billing, store
    obj = {"parent": {"subscription_details": {"metadata": {"fidus_user": store.OWNER_ID, "plan": "essencial"}}}}
    assert billing._meta(obj)["fidus_user"] == store.OWNER_ID
    assert billing._meta({"subscription_details": {"metadata": {"fidus_user": "x"}}})["fidus_user"] == "x"
    assert billing._meta({"metadata": {"a": 1}}) == {"a": 1}
