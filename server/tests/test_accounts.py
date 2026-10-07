"""Contas de clientes: login pelo Google, dados separados, administração."""
import os
import re
import tempfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

from fastapi.testclient import TestClient  # noqa: E402

from app import accounts, config, features, google_client, main, plans, store, tools  # noqa: E402

client = TestClient(main.app)
OWNER = {"Authorization": "Bearer t"}


class FakeCreds:
    granted_scopes = sorted(google_client.REQUIRED)

    def to_json(self):
        return '{"token": "x", "refresh_token": "y", "client_id": "c", "client_secret": "s"}'


def login(monkeypatch, email, name="Ana Souza", verified=True, cc="", sub=None, cl=None):
    cl = cl or client
    n = {"i": 0}

    def fake_auth_url():
        n["i"] += 1
        return f"https://accounts.google.com/fake?{n['i']}", f"state-{email}-{n['i']}", "verif"

    monkeypatch.setattr(google_client, "auth_url", fake_auth_url)
    monkeypatch.setattr(google_client, "exchange",
                        lambda url, state, ver: (FakeCreds(), {"email": email, "name": name, "verified": verified,
                                                               "sub": sub or "sub-" + email}))
    r = cl.get("/auth/google/login" + (f"?cc={cc}" if cc else ""), follow_redirects=False)
    assert r.status_code in (302, 307)
    page = cl.get(f"/auth/google/callback?state=state-{email}-{n['i']}&code=abc").text
    m = re.search(r'login\?code=([A-Z0-9]{8})', page)
    return page, (m.group(1) if m else None)


def token_for(monkeypatch, email, plan="essencial"):
    accounts.invite(email, plan)
    _, code = login(monkeypatch, email)
    r = client.post("/v1/auth/exchange", json={"code": code}).json()
    return {"Authorization": f"Bearer {r['token']}"}


def test_uninvited_cannot_enter(monkeypatch):
    monkeypatch.setattr(config, "SIGNUP_OPEN", False)
    page, code = login(monkeypatch, "estranho@x.com")
    assert code is None and "ainda não" in page
    assert accounts.by_email("estranho@x.com") is None


def test_invited_login_code_is_single_use(monkeypatch):
    accounts.invite("ana@x.com", "negocio")
    page, code = login(monkeypatch, "ana@x.com")
    assert code and "Abrir o Fidus" in page
    r = client.post("/v1/auth/exchange", json={"code": code[:4] + "-" + code[4:]})
    assert r.status_code == 200
    H = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.post("/v1/auth/exchange", json={"code": code}).status_code == 400  # uso único
    me = client.get("/v1/me", headers=H).json()
    assert me["email"] == "ana@x.com" and me["plan"] == "negocio" and not me["is_owner"]
    assert me["profile"]["name"] == "Ana" and me["google_connected"]
    # callback reutilizado não funciona
    assert client.get("/auth/google/callback?state=state-ana@x.com-1&code=abc").status_code == 403


def test_data_is_separated_between_clients(monkeypatch):
    A = token_for(monkeypatch, "a@x.com", "negocio")
    B = token_for(monkeypatch, "b@x.com", "negocio")
    ua = accounts.by_email("a@x.com")
    with store.as_user(accounts.user_ctx(ua)):
        r = tools._add_expense(99, "outros", "Pessoal", "GBP", "2026-10-01", "Loja A")
        assert r["ok"]
        store.add_message("user", "segredo da A")
    hist_b = client.get("/v1/history", headers=B).json()["messages"]
    assert all("segredo" not in m["text"] for m in hist_b)
    assert any("segredo" in m["text"] for m in client.get("/v1/history", headers=A).json()["messages"])
    hist_owner = client.get("/v1/history", headers=OWNER).json()["messages"]
    assert all("segredo" not in m["text"] for m in hist_owner)
    ub = accounts.by_email("b@x.com")
    with store.as_user(accounts.user_ctx(ub)):
        assert tools._summarize_expenses("2026-10-01", "2026-10-31")["count"] == 0
    assert store.user_paths(ua["id"])["db"] != store.user_paths(ub["id"])["db"]


def test_document_link_is_bound_to_its_owner(monkeypatch, tmp_path):
    A = token_for(monkeypatch, "doc-a@x.com", "negocio")
    token_for(monkeypatch, "doc-b@x.com", "negocio")
    ua, ub = accounts.by_email("doc-a@x.com"), accounts.by_email("doc-b@x.com")
    img = tmp_path / "x.jpg"
    img.write_bytes(b"\xff\xd8A")
    with store.as_user(accounts.user_ctx(ua)):
        did = store.insert("documents", title="RG da A", description="d", path=str(img), media_type="image")
        url = features.sign(did)
    path = url.split("/v1/", 1)[1]
    assert client.get("/v1/" + path).content == b"\xff\xd8A"
    forged = path.replace(f"u={ua['id']}", f"u={ub['id']}")
    assert client.get("/v1/" + forged).status_code == 403
    assert client.get("/v1/documents", headers=A).json()["documents"][0]["title"] == "RG da A"


def test_booking_link_opens_the_right_client(monkeypatch):
    class Cal:
        inserted = []

        def events(self):
            return self

        def list(self, **kw):
            return type("E", (), {"execute": lambda s: {"items": []}})()

        def insert(self, calendarId, body, **kw):
            Cal.inserted.append(body)
            return type("E", (), {"execute": lambda s: {"id": "ev"}})()

    monkeypatch.setattr(google_client, "calendar", lambda: Cal())
    token_for(monkeypatch, "book@x.com", "negocio")
    ub = accounts.by_email("book@x.com")
    with store.as_user(accounts.user_ctx(ub)):
        slug = plans and __import__("app.booking", fromlist=["x"]).settings()["slug"]
        store.save_profile(name="Bia")
    assert "Agendar com Bia" in client.get(f"/book/{slug}").text
    with store.as_user(accounts.user_ctx(ub)):
        assert store.select("SELECT count(*) n FROM bookings")[0]["n"] == 0


def test_admin_is_owner_only(monkeypatch):
    C = token_for(monkeypatch, "cli@x.com", "essencial")
    assert client.get("/v1/admin/users", headers=C).status_code == 403
    assert client.post("/v1/plan", json={"plan": "premium"}, headers=C).status_code == 403
    users = client.get("/v1/admin/users", headers=OWNER).json()["users"]
    cli = [u for u in users if u["email"] == "cli@x.com"][0]
    assert cli["plan"] == "essencial"
    assert client.post(f"/v1/admin/users/{cli['id']}/plan", json={"plan": "premium"}, headers=OWNER).json()["ok"]
    assert client.get("/v1/me", headers=C).json()["plan"] == "premium"
    assert client.post("/v1/admin/invites", json={"email": "novo@x.com", "plan": "negocio"}, headers=OWNER).json()["ok"]
    client.post(f"/v1/admin/users/{cli['id']}/status", json={"status": "suspenso"}, headers=OWNER)
    assert client.get("/v1/me", headers=C).status_code == 401  # suspenso perde o acesso


def test_logout_revokes(monkeypatch):
    H = token_for(monkeypatch, "out@x.com")
    assert client.post("/v1/auth/logout", headers=H).json()["ok"]
    assert client.get("/v1/me", headers=H).status_code == 401


def test_essential_client_cannot_add_second_business(monkeypatch):
    token_for(monkeypatch, "ess@x.com", "essencial")
    u = accounts.by_email("ess@x.com")
    with store.as_user(accounts.user_ctx(u)):
        r = tools.run("update_profile", {"add_business": "Loja Nova"})
        assert r.get("locked")
        assert tools.run("update_profile", {"name": "Edu", "timezone": "Europe/Lisbon"})["ok"]
        assert store.user_tz() == "Europe/Lisbon" and store.user_name() == "Edu"
        assert tools.run("update_profile", {"timezone": "Lua/Base"}).get("error")


def test_callback_needs_the_same_browser(monkeypatch):
    """Login CSRF: o link de retorno do Google aberto em outro navegador não vale."""
    accounts.invite("csrf@x.com", "essencial")
    attacker = TestClient(main.app)
    monkeypatch.setattr(google_client, "auth_url", lambda: ("https://g/x", "state-csrf", "v"))
    monkeypatch.setattr(google_client, "exchange", lambda u, s, v: (FakeCreds(), {"email": "csrf@x.com", "name": "X",
                                                                                   "verified": True, "sub": "s1"}))
    attacker.get("/auth/google/login", follow_redirects=False)
    victim = TestClient(main.app)  # sem o cookie do atacante
    assert victim.get("/auth/google/callback?state=state-csrf&code=abc").status_code == 403


def test_code_needs_app_secret_when_login_started_in_app(monkeypatch):
    import hashlib
    accounts.invite("pkce@x.com", "essencial")
    verifier = "segredo-do-app-123456"
    cc = hashlib.sha256(verifier.encode()).hexdigest()
    _, code = login(monkeypatch, "pkce@x.com", cc=cc)
    assert client.post("/v1/auth/exchange", json={"code": code}).status_code == 400          # app intruso
    assert client.post("/v1/auth/exchange", json={"code": code, "verifier": verifier}).status_code == 200


def test_login_does_not_replace_connected_google_of_another_account(monkeypatch):
    token_for(monkeypatch, "keep@x.com", "negocio")
    u = accounts.by_email("keep@x.com")
    with store.as_user(accounts.user_ctx(u)):
        store.kv_set("google_email", "outra@x.com")
        store.kv_set("google_creds", '{"token": "original"}')
    _, code = login(monkeypatch, "keep@x.com", sub="sub-keep@x.com")
    assert code
    with store.as_user(accounts.user_ctx(u)):
        assert store.kv_get("google_creds") == '{"token": "original"}'


def test_same_email_different_google_person_is_refused(monkeypatch):
    token_for(monkeypatch, "dono@x.com", "essencial")
    page, code = login(monkeypatch, "dono@x.com", sub="outra-pessoa")
    assert code is None


def test_existing_booking_link_registered_at_startup():
    with store.as_user(store.owner_user()):
        store.kv_set("booking", '{"slug": "linkantigo1"}')
    accounts.drop_slug("linkantigo1")
    main._resume_all_meetings()
    assert accounts.user_for_slug("linkantigo1")["id"] == "owner"
