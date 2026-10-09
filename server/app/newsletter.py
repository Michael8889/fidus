"""Dicas por e-mail ("Notas do Mike"): só para quem marcou a caixa nas boas-vindas ou nas Configurações.

- A lista fica no banco de contas (Fidus Labs). Nada do conteúdo do cliente (e-mails, agenda, gastos) é usado aqui:
  só nome, e-mail, idioma, país e as respostas dadas nas boas-vindas (perfil e prioridades).
- Uma sequência automática (newsletter.json, editável): dica de gestão + dica de uso do Fidus; de vez em quando,
  convite para o diagnóstico gratuito de 30 minutos (FIDUS_MENTOR_BOOKING_URL).
- Todo e-mail tem link de descadastro (e o cabeçalho List-Unsubscribe). Sai pelo Resend; sem ele, nada é enviado.
"""
import html
import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from . import accounts, config, mailer

log = logging.getLogger("fidus.newsletter")
_FILE = os.path.join(os.path.dirname(__file__), "newsletter.json")


def _db():
    c = accounts._db()
    c.execute("""CREATE TABLE IF NOT EXISTS marketing (user_id TEXT PRIMARY KEY, email TEXT NOT NULL, name TEXT,
        lang TEXT, country TEXT, work_type TEXT, priorities TEXT, consent INTEGER NOT NULL, consent_at TEXT,
        unsub_at TEXT, step INTEGER NOT NULL DEFAULT 0, last_sent_at TEXT, token TEXT UNIQUE NOT NULL,
        source TEXT)""")
    return c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def set_consent(user: dict, yes: bool, profile: dict | None = None, source: str = "boas-vindas") -> None:
    email = (user.get("email") or config.OWNER_EMAIL or "").strip()
    if not email:
        return
    p = profile or {}
    with _db() as c:
        row = c.execute("SELECT token FROM marketing WHERE user_id=?", (user["id"],)).fetchone()
        if row:
            c.execute("UPDATE marketing SET email=?, name=?, lang=?, country=?, work_type=?, priorities=?, consent=?, "
                      "consent_at=CASE WHEN ?=1 THEN ? ELSE consent_at END, unsub_at=CASE WHEN ?=1 THEN NULL ELSE ? END "
                      "WHERE user_id=?",
                      (email, p.get("name") or user.get("name"), p.get("language"), p.get("country"), p.get("work_type"),
                       ",".join(p.get("priorities") or []), int(yes), int(yes), _now(), int(yes), _now(), user["id"]))
        else:
            c.execute("INSERT INTO marketing(user_id,email,name,lang,country,work_type,priorities,consent,consent_at,"
                      "unsub_at,token,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (user["id"], email, p.get("name") or user.get("name"), p.get("language"), p.get("country"),
                       p.get("work_type"), ",".join(p.get("priorities") or []), int(yes), _now() if yes else None,
                       None if yes else _now(), secrets.token_urlsafe(18), source))


def consent_of(user_id: str) -> bool:
    with _db() as c:
        r = c.execute("SELECT consent FROM marketing WHERE user_id=?", (user_id,)).fetchone()
    return bool(r and r["consent"])


def unsubscribe(token: str) -> bool:
    with _db() as c:
        cur = c.execute("UPDATE marketing SET consent=0, unsub_at=? WHERE token=? AND consent=1", (_now(), token or ""))
        return cur.rowcount > 0


def forget(user_id: str) -> None:
    """Conta apagada: sai da lista."""
    with _db() as c:
        c.execute("DELETE FROM marketing WHERE user_id=?", (user_id,))


def leads() -> list[dict]:
    with _db() as c:
        rows = [dict(r) for r in c.execute("SELECT user_id,email,name,lang,country,work_type,priorities,consent,"
                                            "consent_at,unsub_at,step,last_sent_at,source FROM marketing "
                                            "ORDER BY consent_at DESC")]
    return rows


# ---------- a sequência ----------
def sequence() -> list[dict]:
    try:
        with open(_FILE, encoding="utf-8") as f:
            return json.load(f)["emails"]
    except (OSError, ValueError, KeyError):
        return []


def _pick(item: dict, lang: str) -> dict:
    lang = (lang or "pt").lower()
    for k in (lang, lang.split("-")[0], "en", "pt"):
        if k in item:
            return item[k]
    return next(iter(v for k, v in item.items() if isinstance(v, dict)))


def _render(item: dict, row: dict) -> tuple[str, str]:
    t = _pick(item, row.get("lang") or "pt")
    name = html.escape((row.get("name") or "").split(" ")[0] or "")
    booking = html.escape(config.MENTOR_BOOKING_URL or "")
    body = t["body"].replace("{name}", name).replace("{booking}", booking)
    if "{booking}" in t["body"] and not config.MENTOR_BOOKING_URL:
        body = body.split("<!--cta-->")[0]  # sem link de agendamento configurado: não manda o convite
    return t["subject"].replace("{name}", name), body


def _footer(row: dict) -> str:
    url = f"{config.PUBLIC_BASE_URL.rstrip('/')}/email/sair?t={row['token']}"
    lang = (row.get("lang") or "pt").split("-")[0]
    txt = {"pt": "Você recebe este e-mail porque pediu dicas do Fidus. <a href='{u}'>Não quero mais receber</a>.",
           "en": "You get this email because you asked for Fidus tips. <a href='{u}'>Unsubscribe</a>.",
           "es": "Recibes este correo porque pediste consejos de Fidus. <a href='{u}'>Darme de baja</a>."}
    company = "Fidus Labs Limited · Company no. 17510962 · England &amp; Wales"
    return (f"<p style='color:#8A8A8A;font-size:12px;margin-top:28px'>{txt.get(lang, txt['en']).format(u=html.escape(url))}"
            f"<br>{company}</p>")


def run_due(now: datetime | None = None) -> int:
    """Manda o próximo e-mail de quem está na vez (dias contados desde o consentimento). Devolve quantos saíram."""
    seq = sequence()
    if not seq or not mailer.enabled():
        return 0
    now = now or datetime.now(timezone.utc)
    sent = 0
    with _db() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM marketing WHERE consent=1")]
    for row in rows:
        step = row["step"]
        if step >= len(seq) or not row.get("consent_at"):
            continue
        due = datetime.fromisoformat(row["consent_at"]) + timedelta(days=int(seq[step].get("day", 0)))
        last = datetime.fromisoformat(row["last_sent_at"]) if row.get("last_sent_at") else None
        if now < due or (last and now - last < timedelta(hours=20)):
            continue
        subject, body = _render(seq[step], row)
        url = f"{config.PUBLIC_BASE_URL.rstrip('/')}/email/sair?t={row['token']}"
        try:
            mailer.send_raw(row["email"], subject, body, footer=_footer(row),
                            headers={"List-Unsubscribe": f"<{url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"})
        except Exception as e:  # noqa: BLE001
            log.warning("newsletter para %s falhou: %s", row["email"], e)
            continue
        with _db() as c:
            c.execute("UPDATE marketing SET step=step+1, last_sent_at=? WHERE user_id=?", (now.isoformat(), row["user_id"]))
        sent += 1
    return sent


def start_hourly() -> None:
    def loop():
        while True:
            time.sleep(3600)
            try:
                run_due()
            except Exception as e:  # noqa: BLE001
                log.error("newsletter: %s", e)
    threading.Thread(target=loop, daemon=True, name="fidus-newsletter").start()
