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


def test_apk_download(tmp_path, monkeypatch):
    from app import main
    c = TestClient(main.app)
    monkeypatch.setattr(main, "APK_PATH", str(tmp_path / "fidus.apk"))
    assert c.get("/baixar/fidus.apk").status_code == 404
    (tmp_path / "fidus.apk").write_bytes(b"PK\x03\x04apk")
    r = c.get("/baixar/fidus.apk")
    assert r.status_code == 200 and r.headers["content-type"] == "application/vnd.android.package-archive"


def test_strip_action_log():
    from app import agent
    t = ("Pronto, remarcado.\n\n• Pagar CUF\n\n[ações executadas: delete_calendar_event (ok); criou lembrete 'X' "
         "para 2026-10-15T14:00:00 (event_id abc, ok)]")
    assert agent.strip_action_log(t) == "Pronto, remarcado.\n\n• Pagar CUF"
    assert agent.strip_action_log(t + "\n\n[ações executadas: x (ok)]") == "Pronto, remarcado.\n\n• Pagar CUF"
    assert agent.strip_action_log("Uma lista [com colchetes] fica.") == "Uma lista [com colchetes] fica."


def test_old_requests_carry_their_date():
    from datetime import datetime, timedelta, timezone
    from app import agent
    old = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    new = datetime.now(timezone.utc).isoformat()
    out = agent._dated([{"role": "user", "content": "marca hoje às 21h", "created_at": old},
                        {"role": "assistant", "content": "ok", "created_at": old},
                        {"role": "user", "content": "e agora?", "created_at": new}])
    assert out[0]["content"].startswith("[pedido feito em ") and out[1]["content"] == "ok" and out[2]["content"] == "e agora?"
