"""Link de agendamento: página pública onde o cliente escolhe um horário livre na agenda.

A disponibilidade sai do Google Calendar (eventos existentes + regras de horário). Nenhum e-mail sai da
conta do usuário: o cliente baixa o arquivo .ics na própria página. Assim a página pública não pode ser
usada para mandar convites (spam) para endereços quaisquer.
"""
import html
import json
import re
import secrets
import threading
from datetime import date, datetime, timedelta

from . import config, features, google_client, store

DEFAULTS = {
    "enabled": True,
    "title": "",  # ex. "HomB · Mike"; vazio = nome do usuário
    "types": [
        {"id": "call", "name": "Ligação", "minutes": 30, "needs_address": False},
        {"id": "visit", "name": "Visita / orçamento no local", "minutes": 60, "needs_address": True},
    ],
    "weekdays": [0, 1, 2, 3, 4],  # seg-sex
    "start": "09:00",
    "end": "18:00",
    "min_notice_hours": 12,
    "horizon_days": 21,
    "buffer_minutes": 15,
    "max_per_day": 6,
}

TOOLS = [
    {
        "name": "get_booking_link",
        "description": "Devolve o link público de agendamento do usuário (clientes escolhem um horário livre) e as "
                       "regras atuais. Use para 'me manda meu link de agendamento'.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "update_booking_settings",
        "description": "Muda as regras do link de agendamento. Só passe o que mudar.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "nome que aparece na página, ex. 'HomB · Mike'"},
                "weekdays": {"type": "array", "items": {"type": "integer"}, "description": "0=seg ... 6=dom"},
                "start": {"type": "string", "description": "HH:MM"},
                "end": {"type": "string", "description": "HH:MM"},
                "min_notice_hours": {"type": "integer"},
                "horizon_days": {"type": "integer"},
                "buffer_minutes": {"type": "integer"},
                "types": {"type": "array", "description": "tipos de horário",
                          "items": {"type": "object", "properties": {
                              "name": {"type": "string"}, "minutes": {"type": "integer"},
                              "needs_address": {"type": "boolean"}}}},
                "enabled": {"type": "boolean"},
                "new_link": {"type": "boolean", "description": "true para gerar um link novo e desativar o antigo"},
            },
        },
    },
]


def settings() -> dict:
    raw = store.kv_get("booking")
    s = {**DEFAULTS, **(json.loads(raw) if raw else {})}
    if not s.get("slug"):
        s["slug"] = secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:10].lower()
        store.kv_set("booking", json.dumps(s))
    from . import accounts
    accounts.register_slug(s["slug"], store.current()["id"])  # a página pública acha o dono por aqui
    return s


def link(s: dict | None = None) -> str:
    s = s or settings()
    return f"{config.PUBLIC_BASE_URL.rstrip('/')}/book/{s['slug']}"


def get_booking_link():
    s = settings()
    dias = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
    return {"link": link(s), "enabled": s["enabled"], "types": [f"{t['name']} ({t['minutes']} min)" for t in s["types"]],
            "days": ", ".join(dias[d] for d in s["weekdays"]), "hours": f"{s['start']}-{s['end']}",
            "min_notice_hours": s["min_notice_hours"]}


ALLOWED = {"title", "weekdays", "start", "end", "min_notice_hours", "horizon_days", "buffer_minutes", "types",
           "enabled", "max_per_day"}


def update_booking_settings(**kw):
    s = settings()
    kw = {k: v for k, v in kw.items() if k in ALLOWED or k == "new_link"}
    if kw.pop("new_link", False):
        from . import accounts
        accounts.drop_slug(s["slug"])  # o link antigo para de funcionar
        s["slug"] = ""
    for k, v in kw.items():
        if v is None:
            continue
        if k in ("start", "end") and not re.fullmatch(r"\d{1,2}:\d{2}", str(v)):
            return {"error": f"{k} precisa ser HH:MM"}
        if k == "title":
            v = str(v)[:60]
        if k == "types":
            v = [{"id": re.sub(r"\W+", "-", t["name"].lower()).strip("-")[:20] or f"t{i}", "name": str(t["name"])[:60],
                  "minutes": int(t.get("minutes") or 30), "needs_address": bool(t.get("needs_address"))}
                 for i, t in enumerate(v) if t.get("name")]
        s[k] = v
    store.kv_set("booking", json.dumps(s))
    settings()  # gera e registra o link novo, se for o caso
    return {"ok": True, **get_booking_link()}


# ---------- disponibilidade ----------
def _hm(x: str) -> tuple[int, int]:
    h, m = x.split(":")
    return int(h), int(m)


def _busy(day: date) -> list[tuple[datetime, datetime]]:
    from . import tools
    res = google_client.calendar().events().list(
        calendarId="primary", timeMin=tools._rfc3339(f"{day}T00:00:00"), timeMax=tools._rfc3339(f"{day}T23:59:59"),
        timeZone=store.user_tz(), singleEvents=True, orderBy="startTime", maxResults=250).execute()
    out = []
    for e in res.get("items", []):
        st = e.get("start", {}).get("dateTime") or ""
        en = e.get("end", {}).get("dateTime") or ""
        if not st or not en:  # evento de dia inteiro não bloqueia (feriado, aniversário)
            continue
        if e.get("transparency") == "transparent":  # marcado como "livre"
            continue
        if any(a.get("self") and a.get("responseStatus") == "declined" for a in e.get("attendees", [])):
            continue
        if (e.get("summary") or "").startswith(("⏰", "🔁", "📄")):  # lembretes do Fidus não ocupam a agenda
            continue
        out.append((datetime.fromisoformat(st).replace(tzinfo=None), datetime.fromisoformat(en).replace(tzinfo=None)))
    return out


def slots(type_id: str, day: str) -> list[str]:
    s = settings()
    t = next((x for x in s["types"] if x["id"] == type_id), None)
    d = date.fromisoformat(day)
    now = features._now().replace(tzinfo=None)
    if not t or not s["enabled"] or d.weekday() not in s["weekdays"]:
        return []
    if d < now.date() or d > now.date() + timedelta(days=int(s["horizon_days"])):
        return []
    taken = store.select("SELECT count(*) n FROM bookings WHERE substr(start,1,10)=?", (day,))[0]["n"]
    if taken >= int(s["max_per_day"]):
        return []
    busy = _busy(d)
    buf = timedelta(minutes=int(s["buffer_minutes"]))
    dur = timedelta(minutes=int(t["minutes"]))
    cur = datetime.combine(d, datetime.min.time()).replace(hour=_hm(s["start"])[0], minute=_hm(s["start"])[1])
    end = datetime.combine(d, datetime.min.time()).replace(hour=_hm(s["end"])[0], minute=_hm(s["end"])[1])
    earliest = now + timedelta(hours=int(s["min_notice_hours"]))
    out = []
    while cur + dur <= end:
        free = all(cur + dur + buf <= b0 or cur - buf >= b1 for b0, b1 in busy)
        if free and cur >= earliest:
            out.append(cur.strftime("%H:%M"))
        cur += timedelta(minutes=30)
    return out


def days_available(type_id: str) -> list[str]:
    s = settings()
    today = features._now().date()
    return [(today + timedelta(days=i)).isoformat() for i in range(int(s["horizon_days"]) + 1)
            if (today + timedelta(days=i)).weekday() in s["weekdays"]]


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_book_lock = threading.Lock()  # dois clientes no mesmo horário: só o primeiro leva


def book(type_id: str, day: str, hhmm: str, name: str, email: str, phone: str = "", address: str = "",
         notes: str = "") -> dict:
    s = settings()
    t = next((x for x in s["types"] if x["id"] == type_id), None)
    name, email = (name or "").strip()[:80], (email or "").strip()[:120]
    if not t:
        return {"ok": False, "error": "tipo de horário inválido"}
    if not name or not EMAIL_RE.match(email):
        return {"ok": False, "error": "Preencha nome e um e-mail válido."}
    if t["needs_address"] and len((address or "").strip()) < 6:
        return {"ok": False, "error": "Informe o endereço completo da visita."}
    with _book_lock:
        return _book_locked(s, t, day, hhmm, name, email, phone or "", address or "", notes or "")


def _book_locked(s, t, day, hhmm, name, email, phone, address, notes) -> dict:
    if hhmm not in slots(t["id"], day):  # confere de novo: alguém pode ter pego o horário
        return {"ok": False, "error": "Esse horário acabou de ser ocupado. Escolha outro."}
    start = datetime.fromisoformat(f"{day}T{hhmm}:00")
    end = start + timedelta(minutes=int(t["minutes"]))
    tz = store.user_tz()
    desc = "\n".join(x for x in ["Agendado pelo link do Fidus.", f"Nome: {name}", f"E-mail: {email}",
                                 f"Telefone: {phone}" if phone else "", f"Observações: {notes}" if notes else ""] if x)
    # só a agenda do usuário recebe o evento; nenhum convite é enviado a partir da conta dele
    body = {"summary": f"{t['name']} · {name[:40]}", "description": desc,
            "start": {"dateTime": start.isoformat(), "timeZone": tz}, "end": {"dateTime": end.isoformat(), "timeZone": tz},
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 60}]}}
    if address:
        body["location"] = address.strip()[:300]
    ev = google_client.calendar().events().insert(calendarId="primary", body=body).execute()
    store.insert("bookings", type_id=t["id"], start=start.isoformat(), name=name, email=email, phone=phone[:40],
                 address=address[:300], notes=notes[:500], event_id=ev["id"])
    store.add_activity("booking_received", f"{t['name']} · {name}", f"{start:%d/%m %H:%M}" + (f" · {address[:40]}" if address else ""),
                       "feito", ev["id"])
    store.add_message("assistant", f"Novo agendamento pelo seu link: {t['name']} com {name}, "
                                   f"{start:%d/%m} às {start:%H:%M}" + (f", em {address}" if address else "") +
                                   ". Já está na sua agenda.")
    host = s.get("title") or store.user_name()
    return {"ok": True, "when": start.strftime("%d/%m/%Y %H:%M"), "type": t["name"], "host": host,
            "start": start.isoformat(), "end": end.isoformat(), "tz": tz, "location": address or ""}


# ---------- página pública ----------
def page(s: dict) -> str:
    title = html.escape(s.get("title") or store.user_name())
    # "<" escapado: um nome de tipo não consegue fechar o <script>
    types = json.dumps([{k: t[k] for k in ("id", "name", "minutes", "needs_address")} for t in s["types"]]).replace("<", "\\u003c")
    return PAGE.replace("{{TITLE}}", title).replace("{{TYPES}}", types).replace("{{SLUG}}", s["slug"])


PAGE = r"""<!doctype html><html lang="pt"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Agendar com {{TITLE}}</title>
<style>
:root{--bg:#F5F7FB;--card:#fff;--text:#0E1E3A;--sub:#5B6B85;--accent:#0E1E3A;--mint:#3DDC97;--line:#E3E8F0}
@media (prefers-color-scheme:dark){:root{--bg:#0B1426;--card:#14223F;--text:#EEF2F8;--sub:#9AA8C0;--accent:#3DDC97;--line:#22345A}}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text)}
main{max-width:560px;margin:0 auto;padding:24px 16px 48px}h1{font-size:24px;margin:0 0 4px}p.sub{color:var(--sub);margin:0 0 20px}
.card{background:var(--card);border-radius:16px;padding:16px;margin-bottom:14px;border:1px solid var(--line)}
h2{font-size:15px;margin:0 0 10px;color:var(--sub);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.opts{display:flex;flex-wrap:wrap;gap:8px}button.o{border:1px solid var(--line);background:transparent;color:var(--text);
border-radius:999px;padding:10px 14px;font-size:15px;cursor:pointer}button.o.sel{background:var(--accent);color:var(--bg);border-color:var(--accent)}
.days{display:flex;gap:8px;overflow-x:auto;padding-bottom:4px}.days button{min-width:64px;text-align:center}
input,textarea{font:inherit;width:100%;padding:12px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--text);font-size:16px;margin-bottom:10px}
.go{width:100%;padding:14px;border:0;border-radius:12px;background:var(--accent);color:var(--bg);font-size:16px;font-weight:700;cursor:pointer}
.go:disabled{opacity:.5}.muted{color:var(--sub);font-size:14px}.ok{border-left:4px solid var(--mint)}.hp{position:absolute;left:-9999px}
</style></head><body><main>
<h1>Agendar com {{TITLE}}</h1><p class="sub">Escolha o tipo, o dia e o horário.</p>
<div class="card"><h2>Tipo</h2><div class="opts" id="types"></div></div>
<div class="card" id="dayCard" hidden><h2>Dia</h2><div class="days opts" id="days"></div></div>
<div class="card" id="slotCard" hidden><h2>Horário</h2><div class="opts" id="slots"></div><p class="muted" id="slotMsg"></p></div>
<form class="card" id="form" hidden><h2>Seus dados</h2>
<input name="name" placeholder="Nome" required maxlength="80"><input name="email" type="email" placeholder="E-mail" required maxlength="120">
<input name="phone" placeholder="Telefone (opcional)" maxlength="40"><input name="address" id="addr" placeholder="Endereço completo da visita" maxlength="300" hidden>
<textarea name="notes" rows="3" placeholder="Algo que eu deva saber? (opcional)" maxlength="500"></textarea>
<input name="website" class="hp" tabindex="-1" autocomplete="off">
<button class="go" id="go">Confirmar</button><p class="muted" id="err"></p></form>
<div class="card ok" id="done" hidden></div>
<p class="muted" style="text-align:center;margin-top:24px">Agendamento pelo Fidus</p>
</main><script>
const TYPES={{TYPES}},SLUG="{{SLUG}}",$=id=>document.getElementById(id);let T=null,D=null,H=null;
const W=["dom","seg","ter","qua","qui","sex","sáb"];
function btn(txt,on,sel,small){const b=document.createElement("button");b.type="button";b.className="o"+(sel?" sel":"");
 if(small){b.appendChild(document.createTextNode(small));b.appendChild(document.createElement("br"));const x=document.createElement("b");x.textContent=txt;b.appendChild(x)}else{b.textContent=txt}
 b.onclick=on;return b}
function drawTypes(){$("types").textContent="";TYPES.forEach(t=>$("types").appendChild(btn(`${t.name} · ${t.minutes} min`,()=>{T=t;D=null;H=null;drawTypes();loadDays()},T&&T.id===t.id)))}
async function loadDays(){$("dayCard").hidden=false;$("slotCard").hidden=true;$("form").hidden=true;$("addr").hidden=!T.needs_address;$("addr").required=T.needs_address;
 const r=await fetch(`/book/${SLUG}/days?type=${T.id}`);const days=(await r.json()).days||[];$("days").innerHTML="";
 days.forEach(d=>{const dt=new Date(d+"T12:00:00");$("days").appendChild(btn(`${d.slice(8,10)}/${d.slice(5,7)}`,(e)=>{D=d;H=null;[...$("days").children].forEach(c=>c.classList.remove("sel"));e.currentTarget.classList.add("sel");loadSlots()},false,W[dt.getDay()]))})}
async function loadSlots(){$("slotCard").hidden=false;$("form").hidden=true;$("slots").innerHTML="";$("slotMsg").textContent="Carregando…";
 const r=await fetch(`/book/${SLUG}/slots?type=${T.id}&day=${D}`);const s=(await r.json()).slots||[];$("slotMsg").textContent=s.length?"":"Sem horários livres neste dia.";
 s.forEach(h=>$("slots").appendChild(btn(h,(e)=>{H=h;[...$("slots").children].forEach(c=>c.classList.remove("sel"));e.currentTarget.classList.add("sel");$("form").hidden=false;$("form").scrollIntoView({behavior:"smooth"})},false)))}
$("form").onsubmit=async e=>{e.preventDefault();const f=new FormData(e.target);if(f.get("website"))return;$("go").disabled=true;$("err").textContent="";
 const body=Object.fromEntries(f.entries());Object.assign(body,{type:T.id,day:D,time:H});
 const r=await fetch(`/book/${SLUG}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});const j=await r.json();$("go").disabled=false;
 if(!j.ok){$("err").textContent=j.error||"Não foi possível agendar.";if(/ocupado/.test(j.error||""))loadSlots();return}
 ["types","dayCard","slotCard","form"].forEach(id=>{const el=$(id);(el.closest(".card")||el).hidden=true});
 const done=$("done");done.hidden=false;done.textContent="";
 const h=document.createElement("h2");h.textContent="Confirmado";const p=document.createElement("p");const b=document.createElement("b");b.textContent=j.type;
 p.appendChild(b);p.appendChild(document.createElement("br"));p.appendChild(document.createTextNode(j.when+" · com "+j.host));
 const a=document.createElement("a");a.className="go";a.style.display="block";a.style.textAlign="center";a.style.textDecoration="none";a.textContent="Adicionar à minha agenda";
 const st=j.start.replace(/[-:]/g,""),en=j.end.replace(/[-:]/g,""),esc=x=>String(x||"").replace(/[\\;,]/g,m=>"\\"+m).replace(/\n/g," ");
 const ics=["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//Fidus//Agendamento//PT","BEGIN:VEVENT","UID:"+Date.now()+"@fidus",
  "DTSTAMP:"+new Date().toISOString().replace(/[-:]/g,"").slice(0,15)+"Z","DTSTART;TZID="+j.tz+":"+st,"DTEND;TZID="+j.tz+":"+en,
  "SUMMARY:"+esc(j.type+" com "+j.host),"LOCATION:"+esc(j.location),"END:VEVENT","END:VCALENDAR"].join("\r\n");
 a.href=URL.createObjectURL(new Blob([ics],{type:"text/calendar"}));a.download="agendamento.ics";
 done.append(h,p,a)}
drawTypes();
</script></body></html>"""

DISPATCH = {"get_booking_link": get_booking_link, "update_booking_settings": update_booking_settings}
