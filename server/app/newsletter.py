"""Dicas por e-mail ("Notas do Fidus"): só para quem marcou a caixa nas boas-vindas ou nas Configurações.

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
    for k in (lang, lang.split("-")[0], "en", "pt"):  # pt-pt usa o texto de Portugal; sem ele, o do Brasil
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
    lang = _lang_key(row.get("lang"))
    txt = {"pt": "Você recebe este e-mail porque pediu dicas do Fidus. <a href='{u}'>Não quero mais receber</a>.",
           "pt-pt": "Recebe este e-mail porque pediu dicas do Fidus. <a href='{u}'>Não quero receber mais</a>.",
           "en": "You get this email because you asked for Fidus tips. <a href='{u}'>Unsubscribe</a>.",
           "es": "Recibes este correo porque pediste consejos de Fidus. <a href='{u}'>Darme de baja</a>."}
    company = ("Fidus Labs Limited · Company no. 17510962 · England &amp; Wales · "
               + html.escape(config.COMPANY_ADDRESS))
    return (f"<p style='color:#8A8A8A;font-size:12px;margin-top:28px'>{txt.get(lang, txt['en']).format(u=html.escape(url))}"
            f"<br>{company}</p>")


def _lang_key(lang: str | None) -> str:
    raw = (lang or "pt").lower()
    return "pt-pt" if raw.startswith("pt-pt") else raw.split("-")[0]


def current_lang(row: dict) -> str:
    """Idioma de HOJE da pessoa (pode ter mudado desde que aceitou): o do app; sem ele, o do país do plano
    (Portugal → pt-PT, Reino Unido → inglês, Brasil → pt)."""
    from . import countries, store
    u = accounts.get_user(row["user_id"])
    if not u:
        return _lang_key(row.get("lang"))
    try:
        with store.as_user(accounts.user_ctx(u)):
            if store.profile().get("language"):
                return store.user_lang()
            return {"PT": "pt-pt", "GB": "en", "BR": "pt"}.get(countries.primary(), "en")
    except Exception:  # noqa: BLE001
        return _lang_key(row.get("lang"))


# ---------- visual do e-mail (cara do Fidus: faixa escura com a marca, dica com botão, cartões; Gmail e Outlook) ----------
INK, SUB, LINE, BG, MINT, MINTBG = "#0B1220", "#5B6678", "#E6EAF0", "#F2F4F7", "#14804F", "#EAFBF3"
DARK, PANEL, GLOW = "#0B1220", "#101826", "#3DDC97"
FONT = "-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif"  # sem aspas: vai dentro de style='...'
ROLE = {"pt": "Fundador do Fidus", "pt-pt": "Fundador do Fidus", "en": "Founder, Fidus", "es": "Fundador de Fidus"}
SITE = {"pt": "Abrir o Fidus", "pt-pt": "Abrir o Fidus", "en": "Open Fidus", "es": "Abrir Fidus"}
TRY = {"pt": "Experimentar no Fidus", "pt-pt": "Experimentar no Fidus", "en": "Try it in Fidus", "es": "Probar en Fidus"}
TAGLINE = {"pt": "Gestão e atalhos para quem toca o próprio negócio.",
           "pt-pt": "Gestão e atalhos para quem gere o próprio negócio.",
           "en": "Management notes and shortcuts for people who run their own business.",
           "es": "Gestión y atajos para quien lleva su propio negocio."}
CARDS = {"pt": [("🎙️", "Fale do seu jeito", "Segure o microfone e peça como pediria a uma pessoa."),
                ("✋", "Nada sai sem você", "E-mails e convites só saem depois do seu toque em Enviar.")],
         "pt-pt": [("🎙️", "Fale à sua maneira", "Carregue no microfone e peça como pediria a uma pessoa."),
                   ("✋", "Nada sai sem si", "E-mails e convites só saem depois de tocar em Enviar.")],
         "en": [("🎙️", "Just say it", "Hold the mic and ask the way you'd ask a person."),
                ("✋", "Nothing goes out without you", "Emails and invites only go after you tap Send.")],
         "es": [("🎙️", "Habla a tu manera", "Mantén el micrófono y pide como se lo pedirías a una persona."),
                ("✋", "Nada sale sin ti", "Los correos e invitaciones solo salen cuando tocas Enviar.")]}


def _plain(body: str) -> str:
    import re
    t = re.sub(r"<br\s*/?>", "\n", body)
    t = re.sub(r"</p>", "\n\n", t)
    t = re.sub(r"<a [^>]*href='([^']+)'[^>]*>(.*?)</a>", r"\2: \1", t)
    t = re.sub(r"<[^>]+>", "", t)
    return html.unescape(t).strip()


def try_url(prompt: str, lang: str) -> str:
    """Link do botão "Experimentar no Fidus": abre o app com o pedido já escrito (a pessoa confere e envia)."""
    from urllib.parse import quote
    return f"{config.PUBLIC_BASE_URL.rstrip('/')}/abrir?q={quote(prompt[:200], safe='')}&l={quote(lang, safe='')}"


def _page(subject: str, body: str, row: dict, lang: str) -> str:
    """E-mail completo: faixa escura com a marca e o título, texto, dica com botão, dois cartões e assinatura."""
    import re
    m = re.match(r"^(.*?)#(\d+):\s*(.+)$", subject)
    series, num, title = (m.group(1).strip(), m.group(2), m.group(3)) if m else ("", "", subject)
    title = title[:1].upper() + title[1:]
    p = f"margin:0 0 18px;font:16px/1.65 {FONT};color:{INK}"

    # dica ("Dica de hoje:", "No Fidus:", "Today's tip:", "In Fidus:") vira um cartão com o botão de experimentar
    def tip(mt):
        text = mt.group(2)[:1].upper() + mt.group(2)[1:]
        said = re.search(r"<i>[“\"]?(.*?)[”\"]?</i>", text)
        button = ""
        if said:
            prompt = html.unescape(re.sub(r"<[^>]+>", "", said.group(1))).strip(" “”\"")
            if prompt:
                button = (f"<table role='presentation' cellpadding='0' cellspacing='0' style='margin-top:14px'><tr>"
                          f"<td style='background:{DARK};border-radius:999px'><a href='{html.escape(try_url(prompt, lang))}' "
                          f"style='display:inline-block;padding:12px 22px;font:700 14px {FONT};color:#FFFFFF;"
                          f"text-decoration:none'>{TRY.get(lang, TRY['en'])} →</a></td></tr></table>")
        return (f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='margin:6px 0 24px'><tr>"
                f"<td style='background:{MINTBG};border:1px solid #CDEFE0;border-radius:14px;padding:20px 20px 18px'>"
                f"<div style='font:700 12px/1.2 {FONT};letter-spacing:.08em;text-transform:uppercase;color:{MINT};"
                f"margin-bottom:8px'>⚡ {mt.group(1)}</div><div style='font:16px/1.6 {FONT};color:{INK}'>{text}</div>"
                f"{button}</td></tr></table>")
    body = re.sub(r"<p><b>([^<]{3,30}):</b>\s*(.*?)</p>", tip, body, flags=re.S)

    def btn(mt):  # convite (último e-mail)
        return (f"<table role='presentation' cellpadding='0' cellspacing='0' style='margin:6px 0 24px'><tr>"
                f"<td style='background:{GLOW};border-radius:999px'><a href='{mt.group(1)}' style='display:inline-block;"
                f"padding:14px 26px;font:800 15px {FONT};color:{DARK};text-decoration:none'>{mt.group(2)} →</a></td></tr></table>")
    body = re.sub(r"<!--cta--><p><a href='([^']+)'[^>]*>(.*?)</a></p>", btn, body, flags=re.S)

    closing = ""  # o "Mike" do fim vira o bloco com avatar
    mt = re.search(r"<p>(?:([^<]*?)<br>)?Mike</p>\s*$", body)
    if mt:
        closing = f"<p style='{p}'>{mt.group(1)}</p>" if mt.group(1) else ""
        body = body[:mt.start()]
    body = body.replace("<p>", f"<p style='{p}'>").replace("<i>", f"<i style='color:{INK}'>")

    cards = "".join(
        f"<td class='col' width='50%' valign='top' style='padding:{'0 6px 0 0' if i == 0 else '0 0 0 6px'}'>"
        f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0'><tr><td style='background:{BG};"
        f"border-radius:14px;padding:18px'><div style='font-size:22px;line-height:1'>{ic}</div>"
        f"<div style='font:700 15px/1.3 {FONT};color:{INK};margin:10px 0 4px'>{html.escape(h)}</div>"
        f"<div style='font:14px/1.5 {FONT};color:{SUB}'>{html.escape(d)}</div></td></tr></table></td>"
        for i, (ic, h, d) in enumerate(CARDS.get(lang, CARDS["en"])))
    sig = (f"<table role='presentation' cellpadding='0' cellspacing='0' style='margin-top:8px'><tr>"
           f"<td style='width:44px;height:44px;border-radius:22px;background:{DARK};color:{GLOW};text-align:center;"
           f"font:800 18px/44px {FONT}'>M</td><td style='padding-left:12px'><div style='font:700 15px {FONT};color:{INK}'>Mike</div>"
           f"<div style='font:13px {FONT};color:{SUB}'>{ROLE.get(lang, ROLE['en'])}</div></td></tr></table>")
    pre = html.escape(re.sub(r"\s+", " ", _plain(body))[:110])
    site, base = config.SITE_URL, config.PUBLIC_BASE_URL.rstrip("/")
    badge = (f"<table role='presentation' cellpadding='0' cellspacing='0' style='margin:22px 0 14px'><tr>"
             f"<td style='background:{GLOW};border-radius:999px;padding:6px 12px;font:800 11px/1 {FONT};letter-spacing:.06em;"
             f"text-transform:uppercase;color:{DARK}'>{html.escape(series)}{' · #' + num if num else ''}</td></tr></table>") if series else "<div style='height:18px'></div>"
    foot = (_footer(row).replace("<p style='color:#8A8A8A;font-size:12px;margin-top:28px'>", "").replace("</p>", "")
            .replace("<a href=", "<a style='color:#8A93A3;text-decoration:underline' href="))
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>{html.escape(subject)}</title>
<style>@media (max-width:620px){{.col{{display:block!important;width:100%!important;padding:0 0 12px!important}}
.hero-img{{display:none!important}}.pad{{padding:28px 22px!important}}}}</style></head>
<body style="margin:0;padding:0;background:{BG}">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{pre}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BG}"><tr><td align="center" style="padding:24px 10px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;border-radius:18px;overflow:hidden;background:#FFFFFF;border:1px solid {LINE}">
<tr><td style="background:{DARK}"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
<td class="pad" valign="middle" style="padding:30px 10px 32px 32px">
<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="width:32px;height:32px;border-radius:10px;background:{GLOW};color:{DARK};text-align:center;font:800 18px/32px {FONT}">F</td>
<td style="padding-left:10px;font:800 20px {FONT};color:#FFFFFF">Fidus</td></tr></table>
{badge}<h1 style="margin:0 0 10px;font:800 28px/1.2 {FONT};color:#FFFFFF;letter-spacing:-.01em">{html.escape(title)}</h1>
<div style="font:14px/1.5 {FONT};color:#A9B4C6">{TAGLINE.get(lang, TAGLINE['en'])}</div></td>
<td class="hero-img" width="200" valign="middle" style="background:{PANEL};width:200px">
<img src="{base}/email-hero.png" width="200" height="200" alt="" style="display:block;width:200px;height:200px;border:0"></td>
</tr></table></td></tr>
<tr><td class="pad" style="padding:34px 32px 30px">
{body}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:4px 0 26px"><tr>{cards}</tr></table>
{closing}{sig}
</td></tr></table>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px"><tr><td style="padding:20px 8px 0;text-align:center">
<a href="{site}" style="font:600 13px {FONT};color:{INK};text-decoration:none">{SITE.get(lang, SITE['en'])} →</a>
<div style="font:12px/1.6 {FONT};color:#8A93A3;margin-top:12px">{foot}</div>
</td></tr></table></td></tr></table></body></html>"""


def preview(step: int, lang: str, name: str = "Ana") -> tuple[str, str]:
    """Para ver/testar o visual: (assunto, HTML)."""
    row = {"name": name, "lang": lang, "token": "preview"}
    item = sequence()[step]
    subject, body = _render(item, row)
    return subject, _page(subject, body, row, _lang_key(lang))


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
        row["lang"] = current_lang(row)  # idioma de hoje: PT → pt-PT, Reino Unido → inglês, Brasil → pt
        subject, body = _render(seq[step], row)
        url = f"{config.PUBLIC_BASE_URL.rstrip('/')}/email/sair?t={row['token']}"
        try:
            mailer.send_raw(row["email"], subject, _plain(body), page_html=_page(subject, body, row, _lang_key(row["lang"])),
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
