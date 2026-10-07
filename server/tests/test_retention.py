"""Ata de reunião, link de agendamento, semana, exportação, assinaturas e PDF."""
import base64
import json
import os
import tempfile
import time
import zipfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

from fastapi.testclient import TestClient  # noqa: E402

from app import booking, config, features, llm, main, meetings, store, tools, transcribe  # noqa: E402

H = {"Authorization": "Bearer t"}
client = TestClient(main.app)


class Exec:
    def __init__(self, v):
        self.v = v

    def execute(self):
        return self.v


class Cal:
    def __init__(self):
        self.inserted = []
        self.busy = []  # (start_iso, end_iso)

    def events(self):
        return self

    def insert(self, calendarId, body, **kw):
        self.inserted.append((body, kw))
        return Exec({"id": f"b{len(self.inserted)}"})

    def list(self, **kw):
        day = kw["timeMin"][:10]
        return Exec({"items": [{"id": "x", "summary": "Ocupado", "start": {"dateTime": a}, "end": {"dateTime": b}}
                               for a, b in self.busy if a[:10] == day]})

    def delete(self, **kw):
        return Exec({})


cal = Cal()


def setup_module():
    store.init_db()
    features.google_client.calendar = lambda: cal
    tools.google_client.calendar = lambda: cal
    booking.google_client.calendar = lambda: cal
    config.DATA_DIR = tempfile.mkdtemp()


# ---------- ata ----------
def test_meeting_flow_creates_my_tasks_and_minutes_email():
    transcribe.transcribe = lambda path, prompt=None, beam_size=5: "Mike vai mandar o orçamento até sexta. Ana revisa o contrato."
    summary = {"title": "Obra Wembley", "summary": "Combinamos o orçamento.", "decisions": ["Fechar com o fornecedor X"],
               "action_items": [{"owner": "Mike", "task": "Mandar orçamento Wembley", "due": "2026-10-09"},
                                {"owner": "Ana", "task": "Revisar contrato Wembley", "due": None}],
               "open_questions": []}
    llm.chat = lambda system, messages, t, **kw: {"text": "aqui está:\n" + json.dumps(summary), "tool_calls": []}
    meetings.llm.chat = llm.chat
    audio = base64.b64encode(b"0" * 5000).decode()
    mid = client.post("/v1/meeting_b64", json={"audio_b64": audio}, headers=H).json()["meeting_id"]
    for _ in range(50):
        st = client.get(f"/v1/meetings/{mid}", headers=H).json()
        if st["status"] != "processando":
            break
        time.sleep(0.05)
    assert st["status"] == "pronta", st
    assert "Decisões" in st["text"] and "Ana: Revisar contrato Wembley" in st["text"]
    titles = [t["title"] for t in features.list_tasks()["tasks"]]
    assert "Mandar orçamento Wembley" in titles and "Revisar contrato Wembley" not in titles
    assert not os.path.exists(store.get("meetings", mid)["audio_path"])  # áudio apagado
    r = meetings.prepare_minutes_email(mid, ["ana@x.com", "nao-email"])
    pend = store.get_pending(r["pending_action_id"])
    assert pend["kind"] == "send_email" and pend["status"] == "pending" and pend["payload"]["to"] == "ana@x.com"
    assert "Mike: Mandar orçamento Wembley" in pend["payload"]["body"]


def test_meeting_error_is_reported():
    transcribe.transcribe = lambda path, prompt=None, beam_size=5: ""
    mid = meetings.start(b"0" * 5000, ".m4a")
    for _ in range(50):
        if store.get("meetings", mid)["status"] != "processando":
            break
        time.sleep(0.05)
    assert store.get("meetings", mid)["status"] == "erro"


# ---------- agendamento ----------
def _future_weekday(n=3):
    from datetime import timedelta
    d = features._now().date() + timedelta(days=n)
    while d.weekday() > 4:
        d += timedelta(days=1)
    return d.isoformat()


def test_booking_slots_respect_busy_and_book():
    s = booking.settings()
    day = _future_weekday()
    cal.busy = [(f"{day}T10:00:00+01:00", f"{day}T11:00:00+01:00")]
    assert client.get(f"/book/{s['slug']}").status_code == 200
    assert client.get("/book/errado").status_code == 404
    slots = client.get(f"/book/{s['slug']}/slots", params={"type": "call", "day": day}).json()["slots"]
    assert "09:00" in slots and "10:00" not in slots and "10:30" not in slots and "09:30" not in slots
    assert "11:30" in slots  # 11:00 + 15 min de folga
    bad = client.post(f"/book/{s['slug']}", json={"type": "visit", "day": day, "time": "09:00", "name": "Jo",
                                                   "email": "jo@x.com"}).json()
    assert not bad["ok"] and "endereço" in bad["error"]
    ok = client.post(f"/book/{s['slug']}", json={"type": "call", "day": day, "time": "09:00", "name": "Jo",
                                                  "email": "jo@x.com", "phone": "07700"}).json()
    assert ok["ok"]
    body, kw = cal.inserted[-1]
    assert "sendUpdates" not in kw and "attendees" not in body  # página pública não manda e-mail
    assert "jo@x.com" in body["description"] and ok["start"].startswith(day)
    assert store.recent_messages(1)[0]["content"].startswith("Novo agendamento")


def test_booking_settings_and_new_link():
    old = booking.settings()["slug"]
    r = booking.update_booking_settings(start="08:00", end="17:00", weekdays=[0, 2], new_link=True)
    assert r["ok"] and r["hours"] == "08:00-17:00" and old not in r["link"]
    assert booking.update_booking_settings(start="8h")["error"]


# ---------- semana, exportação, assinaturas ----------
def test_weekly_text():
    d = features.weekly_review_data()
    assert "Sua semana com o Fidus" in features.weekly_text(d)
    assert client.get("/v1/weekly", headers=H).json()["text"]


def test_export_zip_has_sheet_and_receipts(tmp_path):
    rec = tmp_path / "r.jpg"
    rec.write_bytes(b"\xff\xd8x")
    store.add_expense("2024-02-10", 30, "GBP", "materiais", "HomB", "Screwfix", None, 5.0, str(rec))
    store.add_expense("2024-02-11", 12, "GBP", "alimentação", "Pessoal", "Pret", None, None, None)
    r = features.export_for_accountant("2024-02-01", "2024-02-29", "HomB")
    assert r["ok"] and r["expenses"] == 1 and r["receipts"] == 1
    path = store.get("documents", r["document_id"])["path"]
    names = zipfile.ZipFile(path).namelist()
    assert any(n.endswith(".xlsx") for n in names) and any(n.startswith("recibos/") for n in names)
    assert features.export_for_accountant("1990-01-01", "1990-01-31")["error"]


def test_subscription_price_increase():
    store.add_expense("2024-05-03", 10.99, "GBP", "software", "Pessoal", "Netflix")
    eid = store.add_expense("2024-06-03", 12.99, "GBP", "software", "Pessoal", "Netflix")
    alerts = features.expense_alerts(eid, 12.99, "GBP", "software", "Netflix", "2024-06-03")
    assert any("subiu de 10.99 para 12.99" in a for a in alerts)


# ---------- PDF ----------
def test_pdf_goes_to_model_as_document():
    seen = {}

    def chat(system, messages, t):
        seen["c"] = messages[-1]["content"]
        return {"text": "Guardei o contrato.", "tool_calls": []}

    main.agent.llm.chat = chat
    pdf = base64.b64encode(b"%PDF-1.4 fake").decode()
    r = client.post("/v1/photo", json={"image_b64": pdf, "media_type": "application/pdf"}, headers=H).json()
    assert r["reply"] == "Guardei o contrato."
    assert seen["c"][0]["media_type"] == "application/pdf" and "PDF enviado" in seen["c"][1]["text"]


def test_booking_page_escapes_type_names():
    booking.update_booking_settings(types=[{"name": "</script><script>alert(1)</script>", "minutes": 30}], slug="hack")
    s = booking.settings()
    assert s["slug"] != "hack"  # chave fora da lista é ignorada
    html_ = client.get(f"/book/{s['slug']}").text
    assert "</script><script>alert" not in html_


def test_google_oauth_needs_signed_link(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://fidus.example.com")
    assert client.get("/auth/google/start", follow_redirects=False).status_code == 403
    assert client.get("/auth/google/callback?code=x&state=y").status_code == 403
    url = client.get("/v1/auth/google/link", headers=H).json()["url"]
    assert "/auth/google/start?u=owner&exp=" in url


# ---------- planos ----------
def test_essential_plan_upsells_instead_of_acting():
    from app import agent, plans
    plans.set_plan("essencial")
    try:
        r = tools.run("get_booking_link", {})
        assert r["locked"] and r["upsell"]["plan"] == "negocio" and r["upsell"]["month"] == 49.90
        store.kv_set("primary_business", "Pessoal")
        r = tools.run("add_expense", {"amount": 10, "category": "outros", "business": "HomB"})
        assert r["locked"] and r["upsell"]["feature"] == "extra_business"
        ok = tools.run("add_expense", {"amount": 10, "category": "outros", "business": "Pessoal", "date": "2023-01-01"})
        assert ok["ok"]
        steps = iter([
            {"text": "", "tool_calls": [{"id": "1", "name": "export_for_accountant",
                                          "input": {"date_from": "2026-07-01", "date_to": "2026-09-30"}}]},
            {"text": "Isso faz parte do plano Negócio.", "tool_calls": []},
        ])
        agent.llm.chat = lambda s, m, t, **kw: next(steps)
        agent.tools.run = tools.run
        out = client.post("/v1/message", json={"text": "manda o pacote do contador do trimestre"}, headers=H).json()
        assert out["upsell"]["name"] == "Negócio" and out["documents"] == []
        assert client.post("/v1/meeting_b64", json={"audio_b64": "AAAA"}, headers=H).json()["locked"]
        assert "meetings_record" in client.get("/v1/plan", headers=H).json()["locked_features"]
    finally:
        plans.set_plan("premium")
    assert tools.run("get_booking_link", {}).get("link")
