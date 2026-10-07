"""Ferramentas que o cérebro do Fidus pode usar.

Regra de segurança fixa: nenhuma ferramenta envia e-mail. `prepare_email_reply`
apenas cria um rascunho pendente; o envio acontece só em /actions/{id}/confirm,
chamado quando o usuário toca em Enviar no app.
"""
import base64
import threading
import json
from email.mime.text import MIMEText

from . import booking, config, features, google_client, meetings, plans, store

TOOLS = [
    {
        "name": "add_expense",
        "description": "Registra um gasto do usuário. Use quando ele disser que pagou/gastou algo ou mandar foto de recibo.",
        "parameters": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "valor total pago, ex. 45.90"},
                "currency": {"type": "string", "description": "GBP, EUR, BRL... se não dito, a moeda padrão"},
                "category": {"type": "string", "enum": config.CATEGORIES},
                "business": {"type": "string", "enum": config.BUSINESSES,
                             "description": "a qual empresa/carteira pertence; se não dito, pergunte ou use 'Pessoal'"},
                "date": {"type": "string", "description": "AAAA-MM-DD; se não dito, hoje"},
                "merchant": {"type": "string", "description": "estabelecimento, ex. Shell, Tesco"},
                "vat": {"type": "number", "description": "IVA/VAT do recibo, se houver"},
                "note": {"type": "string"},
                "attach_receipt": {"type": "boolean", "description": "true quando o gasto veio da foto de recibo desta mensagem"},
            },
            "required": ["amount", "category", "business"],
        },
    },
    {
        "name": "summarize_expenses",
        "description": "Totais de gastos num período, por categoria, empresa e moeda (nunca soma moedas diferentes). "
                       "Pode filtrar por categoria e/ou empresa. Também devolve os últimos lançamentos.",
        "parameters": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "AAAA-MM-DD"},
                "date_to": {"type": "string", "description": "AAAA-MM-DD"},
                "category": {"type": "string"},
                "business": {"type": "string"},
            },
            "required": ["date_from", "date_to"],
        },
    },
    {
        "name": "delete_expense",
        "description": "Apaga um gasto pelo id (de summarize_expenses), só quando o usuário pedir para corrigir/remover.",
        "parameters": {"type": "object", "properties": {"expense_id": {"type": "integer"}}, "required": ["expense_id"]},
    },
    {
        "name": "create_calendar_event",
        "description": "Cria um compromisso no Google Calendar do usuário. Se já existir um evento com o "
                       "mesmo título no mesmo horário, não duplica e devolve o existente.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start": {"type": "string", "description": "ISO 8601 local, ex. 2026-10-12T16:00:00"},
                "end": {"type": "string", "description": "ISO 8601 local; se não dito, 1h após o início"},
                "location": {"type": "string"},
                "description": {"type": "string"},
                "recurrence": {"type": "string", "description": "opcional, para eventos que se repetem. RRULE, ex. "
                               "'RRULE:FREQ=WEEKLY;BYDAY=TU' (toda terça) ou 'RRULE:FREQ=MONTHLY;BYMONTHDAY=1'"},
                "add_meet": {"type": "boolean", "description": "true para gerar link do Google Meet"},
                "remind_minutes_before": {"type": "integer", "description": "alerta no celular N minutos antes (padrão da agenda se omitido)"},
            },
            "required": ["title", "start", "end"],
        },
    },
    {
        "name": "list_calendar_events",
        "description": "Lista compromissos entre duas datas/horas (ISO 8601 local).",
        "parameters": {
            "type": "object",
            "properties": {"time_min": {"type": "string"}, "time_max": {"type": "string"}},
            "required": ["time_min", "time_max"],
        },
    },
    {
        "name": "find_place",
        "description": "Busca o endereço completo de um lugar físico (empresa, restaurante, oficina, clínica, "
                       "endereço parcial). Use SEMPRE antes de criar um evento num lugar físico, para colocar o "
                       "endereço completo no campo location. Inclua a cidade na busca quando souber.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "ex. 'Norauto Coimbra' ou 'Nando's Wembley'"}},
            "required": ["query"],
        },
    },
    {
        "name": "delete_calendar_event",
        "description": "Apaga um compromisso pelo event_id (obtido em list_calendar_events). Use só quando o "
                       "usuário pedir para apagar/cancelar, ou para remover cópias duplicadas que ele pediu para limpar.",
        "parameters": {"type": "object", "properties": {"event_id": {"type": "string"}}, "required": ["event_id"]},
    },
    {
        "name": "search_emails",
        "description": "Busca e-mails no Gmail com a sintaxe de busca do Gmail (ex. 'from:carlos orçamento newer_than:14d').",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 5}},
            "required": ["query"],
        },
    },
    {
        "name": "read_email",
        "description": "Lê o conteúdo completo de um e-mail pelo id.",
        "parameters": {"type": "object", "properties": {"message_id": {"type": "string"}}, "required": ["message_id"]},
    },
    {
        "name": "prepare_email_reply",
        "description": "Prepara uma RESPOSTA a um e-mail como rascunho para o usuário revisar. NÃO envia. "
                       "O usuário confirma o envio no app.",
        "parameters": {
            "type": "object",
            "properties": {"message_id": {"type": "string"}, "body": {"type": "string"}},
            "required": ["message_id", "body"],
        },
    },
]


TOOLS += features.TOOLS + meetings.TOOLS + booking.TOOLS + [plans.UPSELL_TOOL]

# foto de recibo da mensagem atual (definida pelo agente antes de rodar as ferramentas)
class _PerRequest(threading.local):
    """Anexo (foto/PDF) da mensagem atual, separado por requisição para pedidos simultâneos não se misturarem."""
    def __init__(self):
        self.d = {"path": None}

    def __getitem__(self, k):
        return self.d[k]

    def __setitem__(self, k, v):
        self.d[k] = v

    def get(self, k, default=None):
        return self.d.get(k, default)


CURRENT_RECEIPT = _PerRequest()


def run(name: str, args: dict) -> dict:
    fn = {
        "create_calendar_event": _create_event,
        "list_calendar_events": _list_events,
        "delete_calendar_event": _delete_event,
        "find_place": _find_place,
        "add_expense": _add_expense,
        "summarize_expenses": _summarize_expenses,
        "delete_expense": _delete_expense,
        "search_emails": _search_emails,
        "read_email": _read_email,
        "prepare_email_reply": _prepare_reply,
    }.get(name) or features.DISPATCH.get(name) or meetings.DISPATCH.get(name) or booking.DISPATCH.get(name)
    if name == "save_document":
        fn = lambda **a: features.save_document(**a, _path=CURRENT_RECEIPT.get("path"))  # noqa: E731
    if name == "offer_upgrade":
        return {"ok": True, "upsell": plans.upsell(args.get("feature", "extra_business"))}
    if not fn:
        return {"error": f"ferramenta desconhecida: {name}"}
    blocked = plans.gate(name, args)
    if blocked:
        return blocked
    try:
        return fn(**args)
    except Exception as e:  # o modelo recebe o erro e explica ao usuário
        return {"error": str(e)}


# ---------- Agenda ----------
def _create_event(title, start, end, location=None, description=None, recurrence=None, add_meet=False,
                  remind_minutes_before=None):
    tz = config.USER_TIMEZONE
    # proteção contra duplicados: mesmo título no mesmo horário de início
    try:
        from datetime import datetime, timedelta
        st = datetime.fromisoformat(start)
        same = _list_events((st - timedelta(minutes=1)).isoformat(), (st + timedelta(minutes=1)).isoformat())
        for e in same.get("events", []):
            if (e.get("title") or "").strip().lower() == title.strip().lower():
                return {"ok": True, "already_existed": True, "event_id": e["event_id"], "title": title, "start": start}
    except Exception:
        pass
    body = {"summary": title, "start": {"dateTime": start, "timeZone": tz}, "end": {"dateTime": end, "timeZone": tz}}
    if location:
        body["location"] = location
    if description:
        body["description"] = description
    if recurrence:
        body["recurrence"] = [recurrence if recurrence.startswith("RRULE:") else f"RRULE:{recurrence}"]
    if remind_minutes_before is not None:
        body["reminders"] = {"useDefault": False, "overrides": [{"method": "popup", "minutes": int(remind_minutes_before)}]}
    extra = {}
    if add_meet:
        import uuid
        body["conferenceData"] = {"createRequest": {"requestId": uuid.uuid4().hex,
                                                    "conferenceSolutionKey": {"type": "hangoutsMeet"}}}
        extra["conferenceDataVersion"] = 1
    ev = google_client.calendar().events().insert(calendarId="primary", body=body, **extra).execute()
    out = {"ok": True, "event_id": ev["id"], "link": ev.get("htmlLink"), "title": title, "start": start}
    if add_meet:
        out["meet_link"] = ev.get("hangoutLink")
    if recurrence:
        out["recurring"] = True
    return out


def _list_events(time_min, time_max):
    tz = config.USER_TIMEZONE
    res = google_client.calendar().events().list(
        calendarId="primary", timeMin=_rfc3339(time_min), timeMax=_rfc3339(time_max),
        timeZone=tz, singleEvents=True, orderBy="startTime", maxResults=25).execute()
    return {"events": [{"event_id": e["id"], "title": e.get("summary"),
                        "start": e["start"].get("dateTime", e["start"].get("date")),
                        "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date")),
                        "location": e.get("location")} for e in res.get("items", [])]}


def _find_place(query):
    """Geocodificação gratuita via OpenStreetMap (Nominatim). Limite: 1 busca por segundo."""
    import requests

    params = {"q": query, "format": "jsonv2", "addressdetails": 1, "limit": 3}
    if config.HOME_COUNTRIES:
        params["countrycodes"] = config.HOME_COUNTRIES
    r = requests.get("https://nominatim.openstreetmap.org/search", params=params, timeout=10,
                     headers={"User-Agent": "Fidus/0.1 (assistente pessoal; contato via app)",
                              "Accept-Language": "pt,en"})
    r.raise_for_status()
    places = [{"name": p.get("name") or query, "address": p.get("display_name"),
               "maps_link": f"https://www.google.com/maps/search/?api=1&query={p['lat']},{p['lon']}"}
              for p in r.json()]
    if not places:
        return {"places": [], "hint": "Nada encontrado. Tente com a cidade ou o bairro, ou pergunte ao usuário."}
    return {"places": places}


def _delete_event(event_id):
    cal = google_client.calendar()
    title = None
    try:
        title = cal.events().get(calendarId="primary", eventId=event_id).execute().get("summary")
    except Exception:
        pass
    cal.events().delete(calendarId="primary", eventId=event_id).execute()
    return {"ok": True, "deleted": event_id, "title": title}


# ---------- Finanças ----------
def _today() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(config.USER_TIMEZONE)).date().isoformat()


def _add_expense(amount, category, business, currency=None, date=None, merchant=None, vat=None, note=None,
                 attach_receipt=False):
    amount = round(float(amount), 2)
    if amount <= 0:
        return {"error": "valor precisa ser maior que zero"}
    cur = (currency or config.DEFAULT_CURRENCY).upper()
    receipt = CURRENT_RECEIPT.get("path") if attach_receipt else None
    eid = store.add_expense(date or _today(), amount, cur, category, business, merchant, note,
                            float(vat) if vat is not None else None, receipt)
    out = {"ok": True, "expense_id": eid, "amount": amount, "currency": cur, "category": category,
           "business": business, "merchant": merchant, "date": date or _today(), "receipt_saved": bool(receipt)}
    try:
        alerts = features.expense_alerts(eid, amount, cur, category, merchant, date or _today())
        if alerts:
            out["alerts"] = alerts
    except Exception:
        pass
    return out


def _summarize_expenses(date_from, date_to, category=None, business=None):
    rows = store.query_expenses(date_from, date_to, category, business)
    totals: dict = {}
    by_cat: dict = {}
    by_biz: dict = {}
    for r in rows:
        c = r["currency"]
        totals[c] = round(totals.get(c, 0) + r["amount"], 2)
        by_cat.setdefault(r["category"], {}).setdefault(c, 0)
        by_cat[r["category"]][c] = round(by_cat[r["category"]][c] + r["amount"], 2)
        by_biz.setdefault(r["business"], {}).setdefault(c, 0)
        by_biz[r["business"]][c] = round(by_biz[r["business"]][c] + r["amount"], 2)
    recent = [{k: r[k] for k in ("id", "date", "amount", "currency", "category", "business", "merchant")}
              for r in rows[:15]]
    out = {"count": len(rows), "totals_by_currency": totals, "by_category": by_cat,
           "by_business": by_biz, "recent": recent}
    try:
        out.update(features.period_compare(date_from, date_to, category, business))
    except Exception:
        pass
    return out


def _delete_expense(expense_id):
    store.delete_expense(int(expense_id))
    return {"ok": True, "deleted": int(expense_id)}


def run_delete_expense(expense_id: int) -> None:
    """Usado pelo botão Desfazer da aba Atividade."""
    store.delete_expense(int(expense_id))


def _rfc3339(local_iso: str) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    dt = datetime.fromisoformat(local_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(config.USER_TIMEZONE))
    return dt.isoformat()


# ---------- E-mail ----------
def _header(msg, name):
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _search_emails(query, max_results=5):
    g = google_client.gmail()
    ids = g.users().messages().list(userId="me", q=query, maxResults=max_results).execute().get("messages", [])
    out = []
    for m in ids:
        msg = g.users().messages().get(userId="me", id=m["id"], format="metadata",
                                       metadataHeaders=["From", "Subject", "Date"]).execute()
        out.append({"id": m["id"], "from": _header(msg, "From"), "subject": _header(msg, "Subject"),
                    "date": _header(msg, "Date"), "snippet": msg.get("snippet", "")})
    return {"emails": out}


def _body_text(payload) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "ignore")
    for part in payload.get("parts", []) or []:
        t = _body_text(part)
        if t:
            return t
    return ""


def _read_email(message_id):
    msg = google_client.gmail().users().messages().get(userId="me", id=message_id, format="full").execute()
    return {"id": message_id, "from": _header(msg, "From"), "subject": _header(msg, "Subject"),
            "date": _header(msg, "Date"), "body": _body_text(msg["payload"])[:6000]}


def _prepare_reply(message_id, body):
    msg = google_client.gmail().users().messages().get(
        userId="me", id=message_id, format="metadata",
        metadataHeaders=["From", "Reply-To", "Subject", "Message-ID", "References"]).execute()
    subject = _header(msg, "Subject")
    payload = {
        "to": _header(msg, "Reply-To") or _header(msg, "From"),
        "subject": subject if subject.lower().startswith("re:") else f"Re: {subject}",
        "body": body,
        "thread_id": msg.get("threadId"),
        "in_reply_to": _header(msg, "Message-ID"),
        "references": (_header(msg, "References") + " " + _header(msg, "Message-ID")).strip(),
    }
    pid = store.create_pending("send_email", payload)
    return {"ok": True, "pending_action_id": pid, "status": "aguardando confirmação do usuário", "draft": payload}


def send_confirmed_email(payload: dict) -> dict:
    """Chamado SOMENTE pelo endpoint de confirmação do app."""
    mime = MIMEText(payload["body"], "plain", "utf-8")
    mime["To"] = payload["to"]
    mime["Subject"] = payload["subject"]
    if payload.get("in_reply_to"):
        mime["In-Reply-To"] = payload["in_reply_to"]
        mime["References"] = payload.get("references", payload["in_reply_to"])
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    body = {"raw": raw}
    if payload.get("thread_id"):
        body["threadId"] = payload["thread_id"]
    sent = google_client.gmail().users().messages().send(userId="me", body=body).execute()
    return {"ok": True, "message_id": sent["id"]}


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)


def run_delete_event(event_id: str) -> None:
    """Usado pelo botão Desfazer da aba Atividade (ação do próprio usuário)."""
    _delete_event(event_id)
