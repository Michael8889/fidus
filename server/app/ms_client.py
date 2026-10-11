"""Outlook / Microsoft 365: conexão OAuth com a Microsoft e a agenda e o e-mail pelo Microsoft Graph.

Para não duplicar o Fidus inteiro, aqui ficam "adaptadores" com o MESMO formato das bibliotecas do Google que o resto do
código usa (calendar().events().insert(...).execute(), gmail().users().messages()...). Quando o cliente conectou o
Outlook, google_client.calendar()/gmail() devolvem estes adaptadores e todas as funções (agenda, lembretes, link de
agendamento, convites, e-mails) passam a funcionar no Outlook sem mudar nada nelas.

Regra de segurança igual à do Gmail: nenhuma ferramenta da IA envia. O envio (sendMail) só acontece por
tools.send_confirmed_email, chamado por actions.send_pending depois da confirmação do usuário.
"""
import base64
import hashlib
import json
import re
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

from . import config, store

GRAPH = "https://graph.microsoft.com/v1.0"
REDIRECT_PATH = "/auth/microsoft/callback"
REQUIRED = {"calendars.readwrite", "mail.read", "mail.send"}


def enabled() -> bool:
    return bool(config.MS_CLIENT_ID and config.MS_CLIENT_SECRET)


def _login(path: str) -> str:
    return f"https://login.microsoftonline.com/{config.MS_TENANT}/oauth2/v2.0/{path}"


def _redirect() -> str:
    return config.PUBLIC_BASE_URL.strip().rstrip("/") + REDIRECT_PATH


# ---------------- OAuth ----------------
def auth_url() -> tuple[str, str, str]:
    """(endereço da Microsoft, state, verificador PKCE)."""
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    q = {"client_id": config.MS_CLIENT_ID, "response_type": "code", "redirect_uri": _redirect(),
         "response_mode": "query", "scope": " ".join(config.MS_SCOPES), "state": state,
         "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account"}
    return _login("authorize") + "?" + urlencode(q), state, verifier


def _token(data: dict) -> dict:
    data = {"client_id": config.MS_CLIENT_ID, "client_secret": config.MS_CLIENT_SECRET, **data}
    r = requests.post(_login("token"), data=data, timeout=20)
    j = r.json() if r.content else {}
    if r.status_code >= 400 or "access_token" not in j:
        raise RuntimeError(f"Microsoft recusou ({j.get('error') or r.status_code}): "
                           f"{(j.get('error_description') or '')[:160]}")
    j["expires_at"] = time.time() + int(j.get("expires_in") or 3600) - 120
    return j


def exchange(code: str, verifier: str | None) -> dict:
    """Troca o código pelo token e confere as permissões e a caixa de e-mail conectada."""
    tok = _token({"grant_type": "authorization_code", "code": code, "redirect_uri": _redirect(),
                  "code_verifier": verifier or "", "scope": " ".join(config.MS_SCOPES)})
    granted = {s.split("/")[-1].lower() for s in (tok.get("scope") or "").split()}
    me = requests.get(f"{GRAPH}/me", headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=15).json()
    return {"token": tok, "full_access": REQUIRED.issubset(granted),
            "email": (me.get("mail") or me.get("userPrincipalName") or "").lower(), "name": me.get("displayName")}


def save(tok: dict, email: str = "") -> None:
    store.kv_set("ms_tokens", json.dumps({k: tok.get(k) for k in ("access_token", "refresh_token", "expires_at")}))
    if email:
        store.kv_set("ms_email", email)


def disconnect() -> None:
    for k in ("ms_tokens", "ms_email"):
        store.kv_del(k)


def is_connected() -> bool:
    return bool(store.kv_get("ms_tokens"))


def email() -> str:
    return store.kv_get("ms_email") or ""


def access_token() -> str:
    raw = store.kv_get("ms_tokens")
    if not raw:
        raise RuntimeError("Outlook ainda não conectado. No app: menu ⋯ › Configurações › Outlook.")
    t = json.loads(raw)
    if t.get("expires_at", 0) < time.time():
        if not t.get("refresh_token"):
            raise RuntimeError("A conexão com o Outlook expirou. Reconecte em menu ⋯ › Configurações › Outlook.")
        new = _token({"grant_type": "refresh_token", "refresh_token": t["refresh_token"],
                      "scope": " ".join(config.MS_SCOPES)})
        t = {"access_token": new["access_token"], "refresh_token": new.get("refresh_token") or t["refresh_token"],
             "expires_at": new["expires_at"]}
        store.kv_set("ms_tokens", json.dumps(t))
    return t["access_token"]


def graph(method: str, path: str, params: dict | None = None, body=None, headers: dict | None = None,
          raw: bytes | None = None):
    h = {"Authorization": f"Bearer {access_token()}", **(headers or {})}
    url = path if path.startswith("http") else GRAPH + path
    r = requests.request(method, url, params=params, json=body if raw is None else None, data=raw, headers=h, timeout=25)
    if r.status_code >= 400:
        try:
            err = r.json().get("error", {})
            msg = f"{err.get('code')}: {err.get('message')}"
        except ValueError:
            msg = r.text[:200]
        e = RuntimeError(f"Outlook {r.status_code} ({msg[:220]})")
        e.status = r.status_code  # type: ignore[attr-defined]
        raise e
    return r.json() if r.content else {}


class _Do:
    """Imita o .execute() das bibliotecas do Google."""
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


# ---------------- agenda: formato Google <-> Graph ----------------
def _tz() -> ZoneInfo:
    return ZoneInfo(store.user_tz())


def _to_utc(value: str, tzname: str | None = None) -> str:
    """'2026-10-12T16:00:00' (hora local) ou RFC3339 -> 'YYYY-MM-DDTHH:MM:SS' em UTC (o Graph recebe com timeZone=UTC)."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tzname) if tzname else _tz())
    return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _from_graph_time(d: dict | None) -> str:
    if not d or not d.get("dateTime"):
        return ""
    src = d.get("timeZone") or "UTC"
    dt = datetime.fromisoformat(d["dateTime"][:19])
    try:
        dt = dt.replace(tzinfo=ZoneInfo(src))
    except Exception:  # noqa: BLE001 (nome de fuso do Windows: pedimos sempre UTC, então é raro)
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_tz()).isoformat(timespec="seconds")


_DAYS = {"MO": "monday", "TU": "tuesday", "WE": "wednesday", "TH": "thursday", "FR": "friday", "SA": "saturday",
         "SU": "sunday"}
_INDEX = {1: "first", 2: "second", 3: "third", 4: "fourth", -1: "last"}


def rrule_to_graph(rule: str, start_local: datetime) -> dict:
    """RRULE do Google ('RRULE:FREQ=WEEKLY;BYDAY=TU') -> recurrence do Graph."""
    p = dict(x.split("=", 1) for x in rule.replace("RRULE:", "").split(";") if "=" in x)
    freq, interval = p.get("FREQ", "WEEKLY").upper(), int(p.get("INTERVAL", "1") or 1)
    pattern: dict = {"interval": interval}
    byday = [d for d in (p.get("BYDAY") or "").split(",") if d]
    if freq == "DAILY":
        pattern["type"] = "daily"
    elif freq == "WEEKLY":
        pattern["type"] = "weekly"
        pattern["daysOfWeek"] = [_DAYS[d[-2:]] for d in byday] or [start_local.strftime("%A").lower()]
        pattern["firstDayOfWeek"] = "monday"
    elif freq == "MONTHLY":
        m = re.fullmatch(r"([+-]?\d)?([A-Z]{2})", byday[0]) if byday else None
        if m and m.group(1):
            pattern.update(type="relativeMonthly", daysOfWeek=[_DAYS[m.group(2)]], index=_INDEX.get(int(m.group(1)), "first"))
        else:
            pattern.update(type="absoluteMonthly", dayOfMonth=int((p.get("BYMONTHDAY") or start_local.day)))
    elif freq == "YEARLY":
        pattern.update(type="absoluteYearly", dayOfMonth=start_local.day, month=int(p.get("BYMONTH") or start_local.month))
    else:
        raise ValueError(f"repetição não suportada no Outlook: {rule}")
    rng: dict = {"type": "noEnd", "startDate": start_local.date().isoformat()}
    if p.get("COUNT"):
        rng.update(type="numbered", numberOfOccurrences=int(p["COUNT"]))
    elif p.get("UNTIL"):
        u = p["UNTIL"][:8]
        rng.update(type="endDate", endDate=f"{u[:4]}-{u[4:6]}-{u[6:8]}")
    return {"pattern": pattern, "range": rng}


def event_to_graph(body: dict) -> dict:
    out: dict = {}
    if "summary" in body:
        out["subject"] = body["summary"]
    for k in ("start", "end"):
        if k in body:
            v = body[k]
            if v.get("date"):
                out[k] = {"dateTime": f"{v['date']}T00:00:00", "timeZone": "UTC"}
                out["isAllDay"] = True
            else:
                out[k] = {"dateTime": _to_utc(v["dateTime"], v.get("timeZone")), "timeZone": "UTC"}
    if body.get("location"):
        out["location"] = {"displayName": body["location"]}
    if body.get("description") is not None and "description" in body:
        out["body"] = {"contentType": "text", "content": body["description"]}
    if body.get("recurrence"):
        st = body.get("start", {}).get("dateTime")
        start_local = datetime.fromisoformat(st) if st else datetime.now(_tz())
        out["recurrence"] = rrule_to_graph(body["recurrence"][0], start_local)
    rem = body.get("reminders")
    if rem and not rem.get("useDefault"):
        ov = (rem.get("overrides") or [{}])[0]
        out["isReminderOn"] = True
        out["reminderMinutesBeforeStart"] = int(ov.get("minutes") or 0)
    if body.get("conferenceData"):
        out["isOnlineMeeting"] = True
        out["onlineMeetingProvider"] = "teamsForBusiness"
    if "attendees" in body:
        out["attendees"] = [{"emailAddress": {"address": a["email"]}, "type": "required"}
                            for a in body["attendees"] if a.get("email")]
    return out


def event_from_graph(e: dict) -> dict:
    if e.get("isAllDay"):
        st = {"date": (e.get("start") or {}).get("dateTime", "")[:10]}
        en = {"date": (e.get("end") or {}).get("dateTime", "")[:10]}
    else:
        st = {"dateTime": _from_graph_time(e.get("start"))}
        en = {"dateTime": _from_graph_time(e.get("end"))}
    me_resp = ((e.get("responseStatus") or {}).get("response") or "").lower()
    attendees = [{"email": (a.get("emailAddress") or {}).get("address"),
                  "responseStatus": ((a.get("status") or {}).get("response") or "")} for a in e.get("attendees") or []]
    if me_resp == "declined":
        attendees.append({"self": True, "responseStatus": "declined"})
    meet = (e.get("onlineMeeting") or {}).get("joinUrl") or e.get("onlineMeetingUrl")
    out = {"id": e.get("id"), "summary": e.get("subject"), "start": st, "end": en,
           "location": (e.get("location") or {}).get("displayName") or None, "htmlLink": e.get("webLink"),
           "description": e.get("bodyPreview"), "attendees": attendees,
           "transparency": "transparent" if e.get("showAs") == "free" else "opaque"}
    if meet:
        out["hangoutLink"] = meet
        out["conferenceData"] = {"entryPoints": [{"entryPointType": "video", "uri": meet}]}
    return out


class _Events:
    def insert(self, calendarId="primary", body=None, **_):
        def run():
            g = event_to_graph(body or {})
            try:
                return event_from_graph(graph("POST", "/me/events", body=g))
            except RuntimeError:
                if not g.get("isOnlineMeeting"):
                    raise
                # conta pessoal (Outlook.com) não cria Teams: marca sem o link e avisa
                g.pop("isOnlineMeeting"), g.pop("onlineMeetingProvider", None)
                ev = event_from_graph(graph("POST", "/me/events", body=g))
                ev["online_meeting_note"] = "esta conta do Outlook não cria link do Teams; evento criado sem link"
                return ev
        return _Do(run)

    def list(self, calendarId="primary", timeMin=None, timeMax=None, maxResults=25, **_):
        def run():
            res = graph("GET", "/me/calendarView", params={
                "startDateTime": _to_utc(timeMin) + "Z", "endDateTime": _to_utc(timeMax) + "Z",
                "$orderby": "start/dateTime", "$top": str(min(int(maxResults or 25), 250)),
                "$select": "id,subject,start,end,location,isAllDay,showAs,responseStatus,attendees,webLink,"
                           "onlineMeeting,bodyPreview"}, headers={"Prefer": 'outlook.timezone="UTC"'})
            return {"items": [event_from_graph(e) for e in res.get("value", [])]}
        return _Do(run)

    def get(self, calendarId="primary", eventId="", **_):
        return _Do(lambda: event_from_graph(graph("GET", f"/me/events/{eventId}",
                                                  headers={"Prefer": 'outlook.timezone="UTC"'})))

    def delete(self, calendarId="primary", eventId="", **_):
        return _Do(lambda: graph("DELETE", f"/me/events/{eventId}"))

    def patch(self, calendarId="primary", eventId="", body=None, **_):
        """Mudar convidados no Outlook já manda o convite (equivale a sendUpdates='all' do Google)."""
        return _Do(lambda: event_from_graph(graph("PATCH", f"/me/events/{eventId}", body=event_to_graph(body or {}),
                                                  headers={"Prefer": 'outlook.timezone="UTC"'})))


class Calendar:
    def events(self):
        return _Events()


# ---------------- e-mail: formato Gmail <-> Graph ----------------
def gmail_query_to_graph(q: str) -> dict:
    """Busca no estilo Gmail (a IA aprendeu essa) -> parâmetros do Graph ($search em KQL ou $filter)."""
    q = (q or "").strip()
    terms, unread = [], False
    for tok in re.findall(r'\S+:"[^"]*"|"[^"]*"|\S+', q):
        low = tok.lower()
        m = re.fullmatch(r"(newer_than|older_than):(\d+)([dmy])", low)
        if m:
            n = int(m.group(2)) * {"d": 1, "m": 30, "y": 365}[m.group(3)]
            day = (date.today() - timedelta(days=n)).isoformat()
            terms.append(f"received{'>=' if m.group(1) == 'newer_than' else '<'}{day}")
        elif re.fullmatch(r"(after|before):\d{4}[/-]\d{2}[/-]\d{2}", low):
            k, v = low.split(":", 1)
            terms.append(f"received{'>=' if k == 'after' else '<'}{v.replace('/', '-')}")
        elif low in ("is:unread",):
            unread = True
        elif low.startswith(("in:", "label:", "category:", "is:")):
            continue  # pastas/marcadores do Gmail não existem igual no Outlook
        elif low == "has:attachment":
            terms.append("hasattachments:true")
        else:
            terms.append(tok)
    if terms:
        return {"$search": '"' + " ".join(terms).replace('"', "'") + '"'}
    if unread:
        return {"$filter": "isRead eq false", "$orderby": "receivedDateTime desc"}
    return {"$orderby": "receivedDateTime desc"}


def _addr(a: dict | None) -> str:
    e = (a or {}).get("emailAddress") or {}
    name, addr = e.get("name") or "", e.get("address") or ""
    return f"{name} <{addr}>" if name and name != addr else addr


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode((s or "").encode("utf-8")).decode()


_SELECT = "id,conversationId,subject,from,replyTo,toRecipients,receivedDateTime,bodyPreview,internetMessageId"


def message_from_graph(m: dict, full: bool = False) -> dict:
    hdr = {h.get("name", "").lower(): h.get("value", "") for h in m.get("internetMessageHeaders") or []}
    headers = [{"name": "From", "value": _addr(m.get("from"))},
               {"name": "Subject", "value": m.get("subject") or ""},
               {"name": "Date", "value": m.get("receivedDateTime") or ""},
               {"name": "To", "value": ", ".join(_addr(x) for x in m.get("toRecipients") or [])},
               {"name": "Message-ID", "value": m.get("internetMessageId") or ""},
               {"name": "References", "value": hdr.get("references", "")}]
    if m.get("replyTo"):
        headers.append({"name": "Reply-To", "value": ", ".join(_addr(x) for x in m["replyTo"])})
    payload: dict = {"headers": headers, "mimeType": "multipart/alternative", "parts": []}
    if full:
        b = m.get("body") or {}
        mime = "text/html" if (b.get("contentType") or "").lower() == "html" else "text/plain"
        payload["parts"].append({"mimeType": mime, "body": {"data": _b64(b.get("content") or "")}})
    return {"id": m.get("id"), "threadId": m.get("conversationId"), "snippet": m.get("bodyPreview") or "",
            "payload": payload}


class _Messages:
    def __init__(self, cache: dict):
        self.cache = cache  # a busca já traz cabeçalhos: o get(format=metadata) logo depois não chama a Microsoft de novo

    def list(self, userId="me", q="", maxResults=5, **_):
        def run():
            params = {"$top": str(min(int(maxResults or 5), 25)), "$select": _SELECT, **gmail_query_to_graph(q)}
            res = graph("GET", "/me/messages", params=params)
            out = []
            for m in res.get("value", []):
                self.cache[m["id"]] = m
                out.append({"id": m["id"], "threadId": m.get("conversationId")})
            return {"messages": out}
        return _Do(run)

    def get(self, userId="me", id="", format="full", **_):  # noqa: A002 (mesmo nome da biblioteca do Google)
        def run():
            if format == "metadata" and id in self.cache:
                return message_from_graph(self.cache[id])
            sel = _SELECT + (",body,internetMessageHeaders" if format == "full" else ",internetMessageHeaders")
            m = graph("GET", f"/me/messages/{id}", params={"$select": sel})
            return message_from_graph(m, full=format == "full")
        return _Do(run)

    def send(self, userId="me", body=None, **_):
        """Recebe o MIME pronto (o mesmo do Gmail) e envia pelo Outlook. Só chamado depois da confirmação."""
        def run():
            mime = base64.urlsafe_b64decode((body or {})["raw"].encode())
            graph("POST", "/me/sendMail", raw=base64.b64encode(mime), headers={"Content-Type": "text/plain"})
            return {"id": "outlook-" + hashlib.sha1(mime).hexdigest()[:12]}
        return _Do(run)


class _Users:
    def __init__(self):
        self.cache: dict = {}

    def messages(self):
        return _Messages(self.cache)


class Mail:
    def __init__(self):
        self._u = _Users()

    def users(self):
        return self._u
