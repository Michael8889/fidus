"""Testes das funcionalidades novas, com Google Calendar simulado."""
import os
import tempfile

os.environ["FIDUS_DB_PATH"] = tempfile.mktemp(suffix=".db")
os.environ["FIDUS_APP_TOKEN"] = "t"

from fastapi.testclient import TestClient  # noqa: E402

from app import agent, features, main, store, tools  # noqa: E402

H = {"Authorization": "Bearer t"}
client = TestClient(main.app)


class FakeCal:
    """Imita google_client.calendar() guardando os eventos em memória."""
    def __init__(self):
        self.events_db: dict = {}
        self.patches: list = []
        self._n = 0

    def events(self):
        return self

    def insert(self, calendarId, body, **kw):
        self._n += 1
        eid = f"ev{self._n}"
        self.events_db[eid] = dict(body, id=eid)
        return _Exec(self.events_db[eid])

    def get(self, calendarId, eventId):
        return _Exec(self.events_db[eventId])

    def delete(self, calendarId, eventId):
        self.events_db.pop(eventId, None)
        return _Exec({})

    def patch(self, calendarId, eventId, body, **kw):
        self.patches.append((eventId, body, kw))
        self.events_db[eventId].update(body)
        if "conferenceData" in body:
            self.events_db[eventId]["hangoutLink"] = "https://meet.google.com/abc-defg-hij"
        return _Exec(self.events_db[eventId])

    def list(self, **kw):
        return _Exec({"items": []})


class _Exec:
    def __init__(self, v):
        self.v = v

    def execute(self):
        return self.v


cal = FakeCal()
REAL_RUN = tools.run


def setup_module():
    features.google_client.calendar = lambda: cal
    tools.google_client.calendar = lambda: cal
    store.init_db()


def script(steps):
    it = iter(steps)
    return lambda system, messages, t: next(it)


def test_reminder_has_popup_and_can_be_undone():
    r = features.create_reminder("Pagar o IVA", "2026-11-05T09:00:00", "RRULE:FREQ=MONTHLY;BYMONTHDAY=5")
    ev = cal.events_db[r["event_id"]]
    assert ev["reminders"]["overrides"][0] == {"method": "popup", "minutes": 0}
    assert ev["recurrence"] == ["RRULE:FREQ=MONTHLY;BYMONTHDAY=5"]
    agent.tools.run = REAL_RUN
    agent.llm.chat = script([
        {"text": "", "tool_calls": [{"id": "1", "name": "create_reminder",
                                      "input": {"text": "Ligar pro contador", "when": "2026-10-09T10:00:00"}}]},
        {"text": "Combinado.", "tool_calls": []},
    ])
    client.post("/v1/message", json={"text": "me lembra de ligar pro contador sexta 10h"}, headers=H)
    a = [i for i in client.get("/v1/activity", headers=H).json()["items"] if i["kind"] == "reminder_created"][0]
    assert a["can_undo"]
    eid = a["ref"]
    assert eid in cal.events_db
    client.post(f"/v1/activity/{a['id']}/undo", headers=H)
    assert eid not in cal.events_db


def test_event_with_meet_and_recurrence():
    r = tools._create_event("Reunião semanal", "2026-10-13T09:00:00", "2026-10-13T10:00:00",
                            recurrence="FREQ=WEEKLY;BYDAY=TU", add_meet=True)
    ev = cal.events_db[r["event_id"]]
    assert ev["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU"]
    assert ev["conferenceData"]["createRequest"]["conferenceSolutionKey"]["type"] == "hangoutsMeet"


def test_invite_only_sent_after_confirm():
    ev = tools._create_event("Call fornecedor", "2026-10-14T15:00:00", "2026-10-14T15:30:00")
    cal.patches.clear()
    agent.llm.chat = script([
        {"text": "", "tool_calls": [{"id": "1", "name": "prepare_event_invite",
                                      "input": {"event_id": ev["event_id"], "emails": ["joao@x.com"]}}]},
        {"text": "Convite pronto para confirmar.", "tool_calls": []},
    ])
    r = client.post("/v1/message", json={"text": "convida o joão"}, headers=H).json()
    pa = r["pending_actions"][0]
    assert pa["kind"] == "calendar_invite"
    assert cal.patches == []  # nada enviado ainda
    assert client.post(f"/v1/actions/{pa['id']}/confirm", headers=H).json()["status"] == "sent"
    eid, body, kw = cal.patches[-1]
    assert kw.get("sendUpdates") == "all" and body["attendees"] == [{"email": "joao@x.com"}]
    assert client.post(f"/v1/actions/{pa['id']}/confirm", headers=H).status_code == 409


def test_tasks_endpoints():
    t = client.post("/v1/tasks", json={"title": "Revisar contrato", "due": "2020-01-01"}, headers=H).json()
    lst = client.get("/v1/tasks", headers=H).json()["tasks"]
    mine = [x for x in lst if x["id"] == t["task_id"]][0]
    assert mine["overdue"] is True
    client.post(f"/v1/tasks/{t['task_id']}/done", headers=H)
    assert all(x["id"] != t["task_id"] for x in client.get("/v1/tasks", headers=H).json()["tasks"])
    client.post(f"/v1/tasks/{t['task_id']}/reopen", headers=H)
    assert any(x["id"] == t["task_id"] for x in client.get("/v1/tasks", headers=H).json()["tasks"])


def test_document_saved_found_and_signed_link(tmp_path):
    img = tmp_path / "seguro.jpg"
    img.write_bytes(b"\xff\xd8fake")
    tools.CURRENT_RECEIPT["path"] = str(img)
    r = tools.run("save_document", {"title": "Seguro do Land Rover", "description": "Apólice Admiral 123",
                                    "tags": "seguro,carro", "expires_on": "2027-03-01"})
    assert r["ok"] and r["reminder"]
    tools.CURRENT_RECEIPT["path"] = None
    assert tools.run("save_document", {"title": "x", "description": "y"}).get("error")  # sem foto
    found = client.get("/v1/documents", params={"q": "seguro carro"}, headers=H).json()["documents"]
    assert found[0]["title"] == "Seguro do Land Rover"
    url = found[0]["url"].split("/v1/", 1)[1]
    assert client.get("/v1/" + url).content == b"\xff\xd8fake"
    assert client.get("/v1/" + url.replace("sig=", "sig=0")).status_code == 403


def test_bill_creates_monthly_reminder_and_shows_in_briefing():
    r = features.add_bill("Aluguel", 10, 1200, "GBP", "Pessoal", "moradia")
    ev = cal.events_db[store.get("bills", r["bill_id"])["event_id"]]
    assert ev["recurrence"] == ["RRULE:FREQ=MONTHLY;BYMONTHDAY=8"]
    assert features.list_bills()["bills"][0]["name"] == "Aluguel"
    features.delete_bill(r["bill_id"])
    assert features.list_bills()["bills"] == []


def test_expense_duplicate_alert_and_projection():
    a = tools._add_expense(45.5, "combustível", "HomB", "GBP", "2025-03-02", "Shell")
    assert "alerts" not in a
    b = tools._add_expense(45.5, "combustível", "HomB", "GBP", "2025-03-03", "Shell")
    assert any("duplicado" in x for x in b["alerts"])
    s = tools._summarize_expenses("2025-03-01", "2025-03-31")
    assert "previous_period" in s and s["previous_period"]["from"] == "2025-02-01"


def test_briefing_text():
    store.insert("tasks", title="Mandar orçamento", due="2000-01-01", priority="alta")
    data = features.briefing_data("2026-10-07")
    text = features.briefing_text(data)
    assert "Quarta, 07/10" in text and "atrasada: Mandar orçamento" in text
    assert client.get("/v1/briefing", headers=H).status_code == 200


def test_stats():
    s = client.get("/v1/stats", headers=H).json()
    assert s["actions_this_month"] >= 0 and "minutes_saved_estimate" in s
