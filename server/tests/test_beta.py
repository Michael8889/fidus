"""v0.16: beta só com convite (fila com posição, link para subir, turmas, convites dos membros)."""
import os
import tempfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import accounts, beta, config, mailer, main, site_forms  # noqa: E402

client = TestClient(main.app)
H = {"Authorization": "Bearer t"}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    with accounts._db() as c:
        c.execute("DELETE FROM waitlist")
    site_forms._HITS.clear()
    monkeypatch.setattr(config, "APP_DOWNLOAD_URL", "https://expo.dev/artifacts/fidus.apk")
    monkeypatch.setattr(config, "BETA_INVITES", 3)
    yield
    with accounts._db() as c:
        c.execute("DELETE FROM waitlist")


def _mails(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send_raw", lambda to, subject, body, **k: sent.append((to, subject, body)) or True)
    return sent


def _join(email, ip, **kw):
    return client.post("/v1/site/waitlist", json={"email": email, "platform": "android", "lang": "pt-PT", **kw},
                       headers={"x-real-ip": f"10.9.0.{ip}"}).json()


def test_join_gives_position_and_link_and_friends_move_you_up(monkeypatch):
    _mails(monkeypatch)
    for i in range(15):
        _join(f"p{i}@x.com", i)
    last = _join("ultima@x.com", 20)
    assert last["position"] == 16 and last["status_url"].endswith("/beta?t=" + last["status_url"].split("t=")[1])
    code = last["share"].split("ref=")[1]
    assert last["share"].startswith(config.SITE_URL)
    _join("amigo@x.com", 21, ref=code)  # um amigo pelo link: sobe 10 lugares
    q = {r["email"]: r for r in beta.queue()}
    assert q["ultima@x.com"]["position"] == 6 and q["ultima@x.com"]["friends"] == 1
    page = client.get(last["status_url"].replace(config.PUBLIC_BASE_URL.rstrip("/"), "")).text
    assert "n.º 6 da fila" in page and code in page and "wa.me" in page
    again = _join("ultima@x.com", 22)  # repetido: não devolve o link de novo (só por e-mail)
    assert "status_url" not in again
    assert "Link inválido" in client.get("/beta?t=nada").text


def test_batch_invites_top_android_only_once(monkeypatch):
    sent = _mails(monkeypatch)
    _join("a1@x.com", 1)
    _join("i1@x.com", 2, platform="ios")
    _join("a2@x.com", 3)
    prev = beta.invite_batch(5, dry_run=True)["would_invite"]
    assert [p["email"] for p in prev] == ["a1@x.com", "a2@x.com"]  # iPhone espera
    sent.clear()
    r = beta.invite_batch(1)
    assert r["invited"] == 1 and r["emails"] == ["a1@x.com"]
    assert sent[0][0] == "a1@x.com" and "convite" in sent[0][1].lower() and "/beta?t=" in sent[0][2]
    assert accounts.can_signup("a1@x.com")[0]  # agora entra no app
    assert accounts.can_signup("a1@x.com")[1] == config.BETA_PLAN
    assert beta.invite_batch(5)["emails"] == ["a2@x.com"]  # quem já foi não recebe de novo
    tok = next(w["token"] for w in accounts.waitlist() if w["email"] == "a1@x.com")
    assert "Descarregar o Fidus" in client.get(f"/beta?t={tok}").text
    r = client.get(f"/beta/app?t={tok}", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == config.APP_DOWNLOAD_URL
    ios_tok = next(w["token"] for w in accounts.waitlist() if w["email"] == "i1@x.com")
    assert client.get(f"/beta/app?t={ios_tok}", follow_redirects=False).status_code == 404
    monkeypatch.setattr(config, "APP_DOWNLOAD_URL", "")
    _join("a3@x.com", 4)
    with pytest.raises(ValueError):
        beta.invite_batch(1)


def test_member_invites_skip_the_queue_three_times(monkeypatch):
    sent = _mails(monkeypatch)
    owner_code = accounts.referral_code(accounts.get_user(main.store.OWNER_ID)["id"])
    with accounts._db() as c:
        c.execute("DELETE FROM referrals WHERE referrer_id=?", (main.store.OWNER_ID,))
    assert accounts.beta_invites_left(main.store.OWNER_ID) == 3
    for i in range(3):
        r = _join(f"f{i}@x.com", 30 + i, ref=owner_code)
        assert r["invited"] is True
    assert accounts.beta_invites_left(main.store.OWNER_ID) == 0
    assert {s[0] for s in sent} >= {"f0@x.com", "f1@x.com", "f2@x.com"}
    r = _join("f3@x.com", 40, ref=owner_code)  # acabou: vai para a fila
    assert r["invited"] is False and r["position"] >= 1
    assert not accounts.can_signup("f3@x.com", owner_code)[0]
    # a página /r/ do membro avisa que os convites acabaram
    assert "acabaram" in client.get(f"/r/{owner_code}", headers={"accept-language": "pt"}).text
    me = client.get("/v1/referral", headers=H).json()
    assert me["beta_total"] == 3 and me["beta_left"] == 0


def test_admin_beta_tab(monkeypatch):
    sent = _mails(monkeypatch)
    _join("adm1@x.com", 50)
    _join("adm2@x.com", 51)
    code = client.post("/v1/admin/panel_code", headers=H).json()["code"]
    b = TestClient(main.app, base_url="https://testserver")
    b.post("/admin/api/login", json={"code": code})
    d = b.get("/admin/api/beta").json()
    assert d["waiting"] == 2 and d["queue"][0]["email"] == "adm1@x.com" and d["download_ready"]
    X = {"X-Fidus-Admin": "1"}
    assert b.post("/admin/api/beta/invite", json={"count": 1, "dry_run": True}, headers=X).json()["would_invite"][0]["email"] == "adm1@x.com"
    sent.clear()
    r = b.post("/admin/api/beta/invite", json={"count": 1}, headers=X).json()
    assert r["invited"] == 1 and sent[0][0] == "adm1@x.com"
    assert b.get("/admin/api/beta").json()["invited"] == 1
