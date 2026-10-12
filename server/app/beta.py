"""Beta só com convite: fila com posição, link para subir na fila, turmas de convites e convites dos membros.

- Quem entra na lista do site ganha um lugar na fila e um link próprio (heyfidus.com/?ref=CÓDIGO). Cada amigo que
  entrar pelo link sobe a pessoa BOOST lugares.
- O dono convida por turmas no painel (/admin › Site): os primeiros da fila recebem o e-mail do convite com a página
  de download do app. Só quem tem Android (ou entrou pelo computador) é convidado enquanto não há app de iPhone.
- Cada membro tem `config.BETA_INVITES` convites: quem entra na lista pelo link dele é convidado na hora (pula a fila).
Os e-mails são da própria empresa para quem pediu para entrar; nada sai em nome de um cliente.
"""
import html
import secrets
from urllib.parse import quote
from datetime import datetime, timezone

from . import accounts, config, mailer, site_forms

BOOST = 10  # lugares que cada amigo trazido sobe na fila
_ALPHA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _rows() -> list[dict]:
    with accounts._db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM waitlist ORDER BY created_at, email").fetchall()]


def _code_for(email: str) -> str:
    with accounts._db() as c:
        r = c.execute("SELECT code FROM waitlist WHERE email=?", (email,)).fetchone()
        if r and r["code"]:
            return r["code"]
        while True:
            code = "L" + "".join(secrets.choice(_ALPHA) for _ in range(6))
            if not c.execute("SELECT 1 FROM waitlist WHERE code=?", (code,)).fetchone():
                c.execute("UPDATE waitlist SET code=? WHERE email=?", (code, email))
                return code


def queue() -> list[dict]:
    """Quem espera (ainda sem convite), na ordem da fila, com posição e amigos trazidos."""
    rows = _rows()
    refs: dict = {}
    for r in rows:
        if r.get("ref"):
            refs[r["ref"]] = refs.get(r["ref"], 0) + 1
    waiting = [r for r in rows if not r.get("invited_at")]
    for i, r in enumerate(waiting):
        r["friends"] = refs.get(r.get("code") or "", 0)
        r["_key"] = (i - BOOST * r["friends"], -r["friends"], i)
    waiting.sort(key=lambda r: r["_key"])
    for pos, r in enumerate(waiting, 1):
        r["position"] = pos
        r.pop("_key")
    return waiting


def status(token: str) -> dict | None:
    with accounts._db() as c:
        row = c.execute("SELECT * FROM waitlist WHERE token=?", (token or "",)).fetchone()
    if not token or not row:
        return None
    row = dict(row)
    code = _code_for(row["email"])
    q = queue()
    me = next((r for r in q if r["email"] == row["email"]), None)
    return {"email": row["email"], "lang": site_forms._lang(row.get("lang")), "platform": row.get("platform") or "",
            "invited": bool(row.get("invited_at")), "position": me["position"] if me else None, "total": len(q),
            "friends": me["friends"] if me else sum(1 for r in _rows() if r.get("ref") == code),
            "share": f"{config.SITE_URL}/?ref={code}", "code": code}


def _can_invite(row: dict) -> bool:
    return (row.get("platform") or "") != "ios"  # sem app de iPhone ainda


def invite(email: str, via: str = "turma") -> bool:
    """Libera a entrada (lista de convidados do login) e manda o e-mail do convite. Uma vez por pessoa."""
    with accounts._db() as c:
        row = c.execute("SELECT * FROM waitlist WHERE email=?", (email,)).fetchone()
        if not row or row["invited_at"]:
            return False
        c.execute("UPDATE waitlist SET invited_at=?, invited_via=? WHERE email=? AND invited_at IS NULL",
                  (datetime.now(timezone.utc).isoformat(), via, email))
    accounts.invite(email, config.BETA_PLAN)
    _send_invite(dict(row), via)
    return True


def invite_batch(n: int, dry_run: bool = False) -> dict:
    """Convida os primeiros N da fila (que tenham Android). dry_run = só mostra quem seria."""
    n = max(0, min(int(n), 500))
    pick = [r for r in queue() if _can_invite(r)][:n]
    if dry_run:
        return {"would_invite": [{"email": r["email"], "position": r["position"], "friends": r["friends"]} for r in pick]}
    if not config.APP_DOWNLOAD_URL:
        raise ValueError("coloque FIDUS_APP_DOWNLOAD_URL (link do APK) no .env antes de convidar")
    sent = [r["email"] for r in pick if invite(r["email"])]
    return {"invited": len(sent), "emails": sent, "left_in_queue": len(queue())}


def on_join(email: str, ref: str) -> str | None:
    """Chamado quando alguém entra na lista. Se veio pelo link de um MEMBRO com convites, entra na hora."""
    _code_for(email)
    member = accounts.referrer_for_code(ref) if ref and config.BETA_INVITES > 0 else None
    if not member or accounts.beta_invites_left(member["id"]) <= 0:
        return None
    with accounts._db() as c:
        row = c.execute("SELECT * FROM waitlist WHERE email=?", (email,)).fetchone()
    if not row or not _can_invite(dict(row)) or not config.APP_DOWNLOAD_URL:
        return None
    return "invited" if invite(email, accounts.referral_code(member["id"])) else None


# ---------- textos ----------
T = {
    "pt": {
        "mail_subject": "Seu convite do Fidus chegou",
        "mail": "<p>Chegou a sua vez! Você está na turma de testes do Fidus.</p>"
                "<p><a href='{u}' style='display:inline-block;background:#07090D;color:#fff;padding:12px 20px;"
                "border-radius:12px;text-decoration:none;font-weight:700'>Baixar o Fidus</a></p>"
                "<p>Entre no app com este e-mail: <b>{e}</b>. É Android por enquanto; o iPhone vem em seguida.</p>"
                "<p>Você também ganhou {n} convites para amigos: estão no app, em Convide e ganhe.</p>"
                "<p>Tudo o que achar estranho, é só responder este e-mail. A gente lê tudo.</p>",
        "wait_h": "Você é o nº {p} da fila", "wait_p": "Convidamos por turmas. Cada amigo que entrar pelo seu link "
                  "faz você subir {b} lugares.", "share": "Seu link", "copy": "Copiar link", "copied": "Copiado",
        "friends": "Amigos que entraram pelo seu link: {f}",
        "inv_h": "Seu convite chegou", "inv_p": "Baixe o app e entre com <b>{e}</b>.", "dl": "Baixar o Fidus (Android)",
        "steps": "Se o Android pedir, permita instalar apps desta fonte. Depois abra o Fidus e entre com o Google ou "
                 "com o seu e-mail.", "ios": "O app de iPhone ainda não chegou. Você continua na fila e avisamos.",
        "none": "Link inválido", "none_p": "Abra o link do último e-mail do Fidus.",
        "msg": "Olha o Fidus, um assessor pessoal por voz. Entra pelo meu link:"},
    "pt-pt": {
        "mail_subject": "O seu convite do Fidus chegou",
        "mail": "<p>Chegou a sua vez! Está na turma de testes do Fidus.</p>"
                "<p><a href='{u}' style='display:inline-block;background:#07090D;color:#fff;padding:12px 20px;"
                "border-radius:12px;text-decoration:none;font-weight:700'>Descarregar o Fidus</a></p>"
                "<p>Entre na app com este e-mail: <b>{e}</b>. Para já é Android; o iPhone vem a seguir.</p>"
                "<p>Ganhou também {n} convites para amigos: estão na app, em Convide e ganhe.</p>"
                "<p>Tudo o que achar estranho, basta responder a este e-mail. Lemos tudo.</p>",
        "wait_h": "É o n.º {p} da fila", "wait_p": "Convidamos por turmas. Cada amigo que entrar pelo seu link "
                  "fá-lo subir {b} lugares.", "share": "O seu link", "copy": "Copiar link", "copied": "Copiado",
        "friends": "Amigos que entraram pelo seu link: {f}",
        "inv_h": "O seu convite chegou", "inv_p": "Descarregue a app e entre com <b>{e}</b>.",
        "dl": "Descarregar o Fidus (Android)",
        "steps": "Se o Android pedir, permita instalar apps desta origem. Depois abra o Fidus e entre com o Google ou "
                 "com o seu e-mail.", "ios": "A app de iPhone ainda não chegou. Continua na fila e avisamos.",
        "none": "Link inválido", "none_p": "Abra o link do último e-mail do Fidus.",
        "msg": "Veja o Fidus, um assistente pessoal por voz. Entre pelo meu link:"},
    "en": {
        "mail_subject": "Your Fidus invite is here",
        "mail": "<p>It's your turn! You're in the Fidus test group.</p>"
                "<p><a href='{u}' style='display:inline-block;background:#07090D;color:#fff;padding:12px 20px;"
                "border-radius:12px;text-decoration:none;font-weight:700'>Get Fidus</a></p>"
                "<p>Sign in to the app with this email: <b>{e}</b>. Android for now; iPhone comes next.</p>"
                "<p>You also get {n} invites for friends: they're in the app, under Invite and earn.</p>"
                "<p>Anything odd, just reply to this email. We read everything.</p>",
        "wait_h": "You're number {p} in the queue", "wait_p": "We invite in groups. Every friend who joins through "
                  "your link moves you up {b} places.", "share": "Your link", "copy": "Copy link", "copied": "Copied",
        "friends": "Friends who joined through your link: {f}",
        "inv_h": "Your invite is here", "inv_p": "Get the app and sign in with <b>{e}</b>.", "dl": "Get Fidus (Android)",
        "steps": "If Android asks, allow installing apps from this source. Then open Fidus and sign in with Google or "
                 "your email.", "ios": "The iPhone app isn't out yet. You stay in the queue and we'll let you know.",
        "none": "Invalid link", "none_p": "Open the link in the latest Fidus email.",
        "msg": "Check out Fidus, a personal assistant you talk to. Join through my link:"},
}


def _t(lang: str) -> dict:
    return T.get(lang) or T["en"]


def _send_invite(row: dict, via: str) -> None:
    lg = site_forms._lang(row.get("lang"))
    t = _t(lg)
    page = f"{site_forms._base()}/beta?t={row['token']}"
    leave = f"{site_forms._base()}/lista/sair?t={row['token']}&lang={lg}"
    mailer.send_raw(row["email"], t["mail_subject"],
                    t["mail"].format(u=html.escape(page), e=html.escape(row["email"]), n=config.BETA_INVITES),
                    wait=False, footer=site_forms._footer(leave, lg if lg in ("pt", "pt-pt", "en", "es") else "en"))


def page(token: str) -> tuple[str, str]:
    """(título, corpo HTML) da página do convite / da posição na fila."""
    st = status(token)
    if not st:
        t = _t("pt")
        return "Fidus", f"<h1>{t['none']}</h1><p>{t['none_p']}</p>"
    t = _t(st["lang"])
    e = html.escape(st["email"])
    share = html.escape(st["share"])
    share_box = (f"<p style='margin-top:26px'><b>{t['share']}</b></p><div class='code' style='font-size:15px;"
                 f"letter-spacing:0'>{share}</div>"
                 f"<button onclick=\"navigator.clipboard&&navigator.clipboard.writeText('{share}');"
                 f"this.textContent='{t['copied']}'\">{t['copy']}</button>"
                 f"<a class='b' href='https://wa.me/?text={html.escape(quote(t['msg'] + ' ' + st['share']))}' rel='noopener'>WhatsApp</a>"
                 f"<p style='font-size:14px'>{t['friends'].format(f=st['friends'])}</p>")
    if st["invited"]:
        if st["platform"] == "ios":
            return "Fidus", f"<h1>{t['inv_h']}</h1><p>{t['ios']}</p>{share_box}"
        dl = (f"<a class='b' href='/beta/app?t={html.escape(token)}'>{t['dl']}</a>" if config.APP_DOWNLOAD_URL else "")
        return "Fidus", f"<h1>{t['inv_h']}</h1><p>{t['inv_p'].format(e=e)}</p>{dl}<p style='font-size:14px'>{t['steps']}</p>"
    return "Fidus", (f"<h1>{t['wait_h'].format(p=st['position'])}</h1><p>{t['wait_p'].format(b=BOOST)}</p>"
                     + (f"<p>{t['ios']}</p>" if st["platform"] == "ios" else "") + share_box)


def download_url(token: str) -> str | None:
    st = status(token)
    return config.APP_DOWNLOAD_URL if st and st["invited"] and config.APP_DOWNLOAD_URL else None
