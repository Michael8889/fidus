"""v0.13: Outlook / Microsoft 365. As mesmas ferramentas de agenda e e-mail, pelo Microsoft Graph (sem rede: Graph falso)."""
import base64
import json
import os
import tempfile
import time
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

from fastapi.testclient import TestClient  # noqa: E402

from app import actions, config, google_client, main, ms_client, store, tools  # noqa: E402

H = {"Authorization": "Bearer t"}
_REAL = {"calendar": google_client.calendar, "gmail": google_client.gmail}  # outros testes trocam por falsos


class FakeGraph:
    def __init__(self):
        self.calls = []
        self.events = {}
        self.sent = []

    def __call__(self, method, path, params=None, body=None, headers=None, raw=None):
        self.calls.append((method, path, params, body))
        if method == "POST" and path == "/me/events":
            eid = f"AAMk{len(self.events) + 1}=="
            ev = {"id": eid, "subject": body["subject"], "start": body["start"], "end": body["end"],
                  "location": body.get("location"), "webLink": "https://outlook.live.com/x",
                  "isAllDay": False, "showAs": "busy", "attendees": []}
            if body.get("isOnlineMeeting"):
                ev["onlineMeeting"] = {"joinUrl": "https://teams.microsoft.com/l/meetup-join/abc"}
            self.events[eid] = ev
            return ev
        if method == "GET" and path == "/me/calendarView":
            return {"value": list(self.events.values())}
        if method == "GET" and path.startswith("/me/events/"):
            return self.events[path.rsplit("/", 1)[1]]
        if method == "DELETE" and path.startswith("/me/events/"):
            self.events.pop(path.rsplit("/", 1)[1], None)
            return {}
        if method == "PATCH" and path.startswith("/me/events/"):
            ev = self.events[path.rsplit("/", 1)[1]]
            ev.update({k: v for k, v in body.items() if k == "attendees"})
            return ev
        if method == "GET" and path == "/me/messages":
            return {"value": [{"id": "MSG1", "conversationId": "C1", "subject": "Orçamento da obra",
                               "from": {"emailAddress": {"name": "Carlos", "address": "carlos@obra.co.uk"}},
                               "receivedDateTime": "2026-10-10T09:00:00Z", "bodyPreview": "Segue o orçamento",
                               "internetMessageId": "<abc@obra.co.uk>"}]}
        if method == "GET" and path.startswith("/me/messages/"):
            return {"id": "MSG1", "conversationId": "C1", "subject": "Orçamento da obra",
                    "from": {"emailAddress": {"name": "Carlos", "address": "carlos@obra.co.uk"}},
                    "receivedDateTime": "2026-10-10T09:00:00Z", "internetMessageId": "<abc@obra.co.uk>",
                    "internetMessageHeaders": [{"name": "References", "value": "<prev@obra.co.uk>"}],
                    "body": {"contentType": "html", "content": "<p>Total <b>£1.200</b> <a href='https://obra.co.uk/pdf'>PDF</a></p>"}}
        if method == "POST" and path == "/me/sendMail":
            self.sent.append(base64.b64decode(raw).decode())
            return {}
        raise AssertionError(f"chamada inesperada {method} {path}")


def _outlook(monkeypatch):
    fake = FakeGraph()
    monkeypatch.setattr(ms_client, "graph", fake)
    for k, fn in _REAL.items():
        monkeypatch.setattr(google_client, k, fn)
    ms_client.save({"access_token": "a", "refresh_token": "r", "expires_at": time.time() + 3600}, "mike@homb.co.uk")
    store.kv_set("mail_provider", "microsoft")
    store.save_profile(timezone="Europe/London")
    return fake


def test_rrule_and_search_translation():
    from datetime import datetime
    st = datetime(2026, 10, 13, 9, 0)
    r = ms_client.rrule_to_graph("RRULE:FREQ=WEEKLY;BYDAY=TU,TH", st)
    assert r["pattern"] == {"interval": 1, "type": "weekly", "daysOfWeek": ["tuesday", "thursday"], "firstDayOfWeek": "monday"}
    assert r["range"]["type"] == "noEnd" and r["range"]["startDate"] == "2026-10-13"
    assert ms_client.rrule_to_graph("FREQ=MONTHLY;BYMONTHDAY=1;COUNT=6", st)["pattern"]["dayOfMonth"] == 1
    assert ms_client.rrule_to_graph("FREQ=MONTHLY;BYMONTHDAY=1;COUNT=6", st)["range"]["numberOfOccurrences"] == 6
    last_fri = ms_client.rrule_to_graph("FREQ=MONTHLY;BYDAY=-1FR", st)["pattern"]
    assert last_fri["type"] == "relativeMonthly" and last_fri["index"] == "last" and last_fri["daysOfWeek"] == ["friday"]
    q = ms_client.gmail_query_to_graph("from:carlos orçamento newer_than:14d in:inbox")
    assert q["$search"].startswith('"from:carlos orçamento received>=') and "in:inbox" not in q["$search"]
    assert ms_client.gmail_query_to_graph("is:unread") == {"$filter": "isRead eq false", "$orderby": "receivedDateTime desc"}


def test_calendar_tools_work_on_outlook(monkeypatch):
    fake = _outlook(monkeypatch)
    assert google_client.provider() == "microsoft" and isinstance(google_client.calendar(), ms_client.Calendar)
    r = tools.run("create_calendar_event", {"title": "Contador", "start": "2026-10-16T10:00:00",
                                            "end": "2026-10-16T11:00:00", "location": "Harrow",
                                            "remind_minutes_before": 60, "add_meet": True})
    assert r["ok"] and r["meet_link"].startswith("https://teams.microsoft.com"), r
    post = next(c for c in fake.calls if c[0] == "POST")[3]
    # 10:00 em Londres (horário de verão, BST) = 09:00 UTC
    assert post["start"] == {"dateTime": "2026-10-16T09:00:00", "timeZone": "UTC"} and post["reminderMinutesBeforeStart"] == 60
    lst = tools.run("list_calendar_events", {"time_min": "2026-10-16T00:00:00", "time_max": "2026-10-16T23:59:00"})
    assert lst["events"][0]["title"] == "Contador" and lst["events"][0]["start"].startswith("2026-10-16T10:00:00+01:00")
    # não duplica o mesmo compromisso
    again = tools.run("create_calendar_event", {"title": "Contador", "start": "2026-10-16T10:00:00", "end": "2026-10-16T11:00:00"})
    assert again.get("already_existed")
    assert tools.run("delete_calendar_event", {"event_id": r["event_id"]})["ok"] and not fake.events


def test_reminder_and_invite_need_confirmation(monkeypatch):
    from app import features
    fake = _outlook(monkeypatch)
    rem = features.create_reminder("pagar o VAT", "2026-11-05T09:00:00")
    assert rem["ok"] and fake.events[rem["event_id"]]["subject"] == "⏰ pagar o VAT"
    inv = features.prepare_event_invite(rem["event_id"], ["ana@x.com"])
    assert inv["pending_action_id"] and not fake.events[rem["event_id"]]["attendees"]  # nada enviado ainda
    actions.send_pending(inv["pending_action_id"])
    assert fake.events[rem["event_id"]]["attendees"][0]["emailAddress"]["address"] == "ana@x.com"


def test_email_search_read_and_send_only_after_confirmation(monkeypatch):
    fake = _outlook(monkeypatch)
    found = tools.run("search_emails", {"query": "from:carlos orçamento"})
    assert found["emails"][0]["from"] == "Carlos <carlos@obra.co.uk>" and found["emails"][0]["subject"] == "Orçamento da obra"
    assert sum(1 for c in fake.calls if c[1].startswith("/me/messages")) == 1  # cabeçalhos vêm da própria busca
    msg = tools.run("read_email", {"message_id": "MSG1"})
    assert "£1.200" in msg["body"] and any(l["url"] == "https://obra.co.uk/pdf" for l in msg["links"])
    draft = tools.run("prepare_email_reply", {"message_id": "MSG1", "body": "Obrigado, **aprovado**."})
    assert draft["draft"]["to"] == "Carlos <carlos@obra.co.uk>" and draft["draft"]["subject"] == "Re: Orçamento da obra"
    assert not fake.sent  # a ferramenta só prepara
    actions.send_pending(draft["pending_action_id"])
    assert len(fake.sent) == 1 and "In-Reply-To: <abc@obra.co.uk>" in fake.sent[0]
    assert "<prev@obra.co.uk>" in fake.sent[0] and "Subject: " in fake.sent[0]


def test_provider_switching_and_google_login_keeps_outlook(monkeypatch):
    _outlook(monkeypatch)

    class Creds:
        def to_json(self):
            return "{}"
    google_client.save_credentials(Creds(), "mike@gmail.com", make_default=False)  # login com Google noutro celular
    assert google_client.provider() == "microsoft"
    google_client.save_credentials(Creds(), "mike@gmail.com")  # "Reconectar Google" escolhe o Google
    assert google_client.provider() == "google"
    r = TestClient(main.app).post("/v1/auth/microsoft/disconnect", headers=H)
    assert r.json()["mail_provider"] == "google" and not ms_client.is_connected()
    store.kv_del("google_creds")
    assert google_client.provider() is None


def test_connect_flow_link_start_callback(monkeypatch):
    monkeypatch.setattr(config, "MS_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "MS_CLIENT_SECRET", "sec")
    ms_client.disconnect()
    c = TestClient(main.app)
    me = c.get("/v1/me", headers=H).json()
    assert me["outlook_available"] and not me["outlook_connected"]
    link = c.get("/v1/auth/microsoft/link", headers=H).json()["url"]
    r = c.get(link.replace(config.PUBLIC_BASE_URL.rstrip("/"), ""), follow_redirects=False)
    assert r.status_code in (302, 307)
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["client_id"] == ["cid"] and "Mail.Send" in q["scope"][0] and q["code_challenge_method"] == ["S256"]
    # link usado não vale de novo
    assert c.get(link.replace(config.PUBLIC_BASE_URL.rstrip("/"), ""), follow_redirects=False).status_code == 403
    seen = {}

    def fake_exchange(code, verifier):
        seen["code"], seen["verifier"] = code, verifier
        return {"token": {"access_token": "x", "refresh_token": "y", "expires_at": time.time() + 3000},
                "full_access": True, "email": "mike@homb.co.uk", "name": "Mike"}
    monkeypatch.setattr(ms_client, "exchange", fake_exchange)
    # outro navegador (sem o cookie) não consegue usar o retorno
    assert TestClient(main.app).get(f"/auth/microsoft/callback?state={q['state'][0]}&code=abc").status_code == 403
    # o state anterior foi consumido pela tentativa sem cookie: começa de novo com um link novo
    time.sleep(1.1)  # link novo (outro horário de validade)
    link2 = c.get("/v1/auth/microsoft/link", headers=H).json()["url"]
    r = c.get(link2.replace(config.PUBLIC_BASE_URL.rstrip("/"), ""), follow_redirects=False)
    st = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    page = c.get(f"/auth/microsoft/callback?state={st}&code=abc")
    assert "Outlook conectado" in page.text and seen["code"] == "abc" and seen["verifier"]
    me = c.get("/v1/me", headers=H).json()
    assert me["outlook_connected"] and me["mail_provider"] == "microsoft" and me["outlook_email"] == "mike@homb.co.uk"
    ms_client.disconnect()


def test_token_refresh(monkeypatch):
    ms_client.save({"access_token": "old", "refresh_token": "r1", "expires_at": time.time() - 10})
    monkeypatch.setattr(ms_client, "_token", lambda data: {"access_token": "new", "expires_at": time.time() + 3000,
                                                            **({} if data.get("refresh_token") != "r1" else {"refresh_token": "r2"})})
    assert ms_client.access_token() == "new"
    assert json.loads(store.kv_get("ms_tokens"))["refresh_token"] == "r2"
    ms_client.disconnect()
