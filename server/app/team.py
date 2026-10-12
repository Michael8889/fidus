"""Premium: mais 1 pessoa na conta e acesso do contabilista.

- Mais 1 pessoa (sócio, cônjuge): entra no app com o próprio login e usa a MESMA conta (despesas, faturas, lembretes,
  tarefas, documentos, agenda), com conversas só dela. Não lê os e-mails do titular, não mexe no plano, nas ligações
  nem nas definições. O titular remove quando quiser.
- Contabilista: página web só de leitura (/contabilista) com despesas, faturas, NIF, categorias do e-Fatura e
  exportação. Entra com código por e-mail. Não vê agenda, e-mails nem conversas. O cliente corta o acesso quando quiser.
Os convites saem pelo e-mail do Fidus, só quando o titular toca em Convidar e confirma (nunca pela IA).
"""
import hashlib
import html
import re
import secrets
import time

from . import accounts, config, mailer, store

EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
MAX_MEMBERS = 1


def init() -> None:
    with accounts._db() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS account_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id TEXT NOT NULL, email TEXT NOT NULL, user_id TEXT,
                created_at TEXT NOT NULL, removed_at TEXT);
            CREATE TABLE IF NOT EXISTS accountant_access (
                id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id TEXT NOT NULL, email TEXT NOT NULL,
                created_at TEXT NOT NULL, removed_at TEXT, last_access TEXT);
            CREATE TABLE IF NOT EXISTS accountant_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL, hash TEXT NOT NULL, expires REAL NOT NULL,
                used INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS accountant_sessions (hash TEXT PRIMARY KEY, email TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS accountant_fails (email TEXT NOT NULL, at REAL NOT NULL);
        """)
        if "member_of" not in {r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()}:
            c.execute("ALTER TABLE users ADD COLUMN member_of TEXT")


def _h(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


def _clean_email(email: str) -> str:
    e = (email or "").strip().lower()[:200]
    if not EMAIL_RE.match(e):
        raise ValueError("e-mail inválido")
    return e


def _owner() -> dict:
    u = store.current()
    if u.get("member_id"):
        raise PermissionError("só o titular da conta pode fazer isto")
    return u


def _owner_email(u: dict) -> str:
    return ((config.OWNER_EMAIL if u["id"] == store.OWNER_ID else u.get("email")) or "").lower()


def _lang() -> str:
    lang = store.user_lang()
    return "pt-pt" if lang == "pt-pt" else "pt" if lang.startswith("pt") else "en"


def _who() -> str:
    return (store.profile().get("name") or store.user_name() or "").strip() or "Um cliente"


# ---------------- mais 1 pessoa ----------------
def members(owner_id: str | None = None) -> list[dict]:
    oid = owner_id or store.current()["id"]
    with accounts._db() as c:
        rows = c.execute("SELECT m.*, u.last_seen FROM account_members m LEFT JOIN users u ON u.id=m.user_id "
                         "WHERE m.owner_id=? AND m.removed_at IS NULL ORDER BY m.id", (oid,)).fetchall()
    return [{"id": r["id"], "email": r["email"], "joined": bool(r["user_id"]), "since": r["created_at"],
             "last_seen": r["last_seen"]} for r in rows]


def member_invite_for(email: str) -> dict | None:
    with accounts._db() as c:
        r = c.execute("SELECT * FROM account_members WHERE lower(email)=lower(?) AND removed_at IS NULL "
                      "ORDER BY id DESC LIMIT 1", (email,)).fetchone()
    return dict(r) if r else None


def invite_member(email: str) -> dict:
    u = _owner()
    e = _clean_email(email)
    if e == _owner_email(u):
        raise ValueError("esse é o seu próprio e-mail")
    if len(members(u["id"])) >= MAX_MEMBERS:
        raise ValueError("o plano inclui 1 pessoa a mais; remova a atual para convidar outra")
    other = accounts.by_email(e)
    if other and other.get("member_of") != u["id"] and other["status"] != "apagado":
        raise ValueError("esse e-mail já tem uma conta Fidus própria; a pessoa precisa de usar outro e-mail")
    taken = member_invite_for(e)
    if taken and taken["owner_id"] != u["id"]:
        raise ValueError("esse e-mail já está noutra conta")
    with accounts._db() as c:
        cur = c.execute("INSERT INTO account_members(owner_id,email,user_id,created_at) VALUES(?,?,?,?)",
                        (u["id"], e, other["id"] if other else None, store.now()))
        mid = cur.lastrowid
    if other:  # já tinha sido a 2.ª pessoa desta conta antes: volta a entrar
        accounts.set_status(other["id"], "ativo")
    _mail_member(e)
    store.add_activity("member_added", f"Mais 1 pessoa: {e}", "convite enviado", "feito", str(mid))
    return {"ok": True, "id": mid, "email": e}


def remove_member(mid: int) -> dict:
    u = _owner()
    with accounts._db() as c:
        r = c.execute("SELECT * FROM account_members WHERE id=? AND owner_id=? AND removed_at IS NULL",
                      (int(mid), u["id"])).fetchone()
        if not r:
            raise ValueError("pessoa não encontrada")
        c.execute("UPDATE account_members SET removed_at=? WHERE id=?", (store.now(), r["id"]))
    if r["user_id"]:
        accounts.set_status(r["user_id"], "removido")  # sai de todos os aparelhos na hora
    store.add_activity("member_removed", f"Removida da conta: {r['email']}", "", "feito")
    return {"ok": True}


def link_member_user(uid: str, email: str) -> None:
    """Chamado quando a pessoa convidada entra no app pela primeira vez."""
    inv = member_invite_for(email)
    if not inv:
        return
    with accounts._db() as c:
        c.execute("UPDATE users SET member_of=? WHERE id=?", (inv["owner_id"], uid))
        c.execute("UPDATE account_members SET user_id=? WHERE id=?", (uid, inv["id"]))


def member_ctx(row: dict) -> dict | None:
    """Contexto da 2.ª pessoa: o banco do titular, marcado com quem está a usar. None = sem acesso."""
    owner = accounts.get_user(row["member_of"])
    inv = member_invite_for(row.get("email") or "")
    if not owner or owner["status"] != "ativo" or not inv or inv["owner_id"] != owner["id"]:
        return None
    ctx = accounts.user_ctx(owner)
    return {**ctx, "is_owner": False, "member_id": row["id"], "member_name": (row.get("name") or "").split(" ")[0],
            "member_email": row.get("email")}


MEMBER_MAIL = {
    "pt": ("{who} convidou você para a conta Fidus",
           "<p>{who} convidou você para usar a conta Fidus junto: despesas e recibos, lembretes, tarefas e "
           "documentos no mesmo lugar, cada um com as próprias conversas.</p>{dl}"
           "<p>Entre no app com este e-mail: <b>{e}</b>.</p>"),
    "pt-pt": ("{who} convidou-o para a conta Fidus",
              "<p>{who} convidou-o para usar a conta Fidus em conjunto: despesas e faturas, lembretes, tarefas e "
              "documentos no mesmo sítio, cada um com as suas conversas.</p>{dl}"
              "<p>Entre na app com este e-mail: <b>{e}</b>.</p>"),
    "en": ("{who} invited you to their Fidus account",
           "<p>{who} invited you to share their Fidus account: expenses and receipts, reminders, tasks and documents "
           "in one place, each with your own conversations.</p>{dl}<p>Sign in to the app with this email: <b>{e}</b>.</p>"),
}
DL = {"pt": "Baixar o Fidus", "pt-pt": "Descarregar o Fidus", "en": "Get Fidus"}


def _button(url: str, label: str) -> str:
    return (f"<p><a href='{html.escape(url)}' style='display:inline-block;background:#07090D;color:#fff;padding:12px 20px;"
            f"border-radius:12px;text-decoration:none;font-weight:700'>{html.escape(label)}</a></p>")


def _mail_member(email: str) -> None:
    lg = _lang()
    subject, body = MEMBER_MAIL[lg]
    who = html.escape(_who())
    dl = _button(config.APP_DOWNLOAD_URL, DL[lg]) if config.APP_DOWNLOAD_URL else ""
    mailer.send_raw(email, subject.format(who=_who()), body.format(who=who, dl=dl, e=html.escape(email)), wait=False)


# ---------------- contabilista ----------------
def accountants(owner_id: str | None = None) -> list[dict]:
    oid = owner_id or store.current()["id"]
    with accounts._db() as c:
        rows = c.execute("SELECT * FROM accountant_access WHERE owner_id=? AND removed_at IS NULL ORDER BY id",
                         (oid,)).fetchall()
    return [{"id": r["id"], "email": r["email"], "since": r["created_at"], "last_access": r["last_access"]} for r in rows]


def grant_accountant(email: str) -> dict:
    u = _owner()
    e = _clean_email(email)
    if e == _owner_email(u):
        raise ValueError("esse é o seu próprio e-mail")
    if any(a["email"] == e for a in accountants(u["id"])):
        raise ValueError("esse contabilista já tem acesso")
    if len(accountants(u["id"])) >= 3:
        raise ValueError("no máximo 3 contabilistas por conta")
    with accounts._db() as c:
        aid = c.execute("INSERT INTO accountant_access(owner_id,email,created_at) VALUES(?,?,?)",
                        (u["id"], e, store.now())).lastrowid
    _mail_accountant(e)
    store.add_activity("accountant_added", f"Contabilista com acesso: {e}", "só leitura das despesas", "feito", str(aid))
    return {"ok": True, "id": aid, "email": e}


def revoke_accountant(aid: int, record: bool = True) -> dict:
    u = store.current()
    with accounts._db() as c:
        r = c.execute("SELECT * FROM accountant_access WHERE id=? AND owner_id=? AND removed_at IS NULL",
                      (int(aid), u["id"])).fetchone()
        if not r:
            raise ValueError("acesso não encontrado")
        c.execute("UPDATE accountant_access SET removed_at=? WHERE id=?", (store.now(), r["id"]))
    if record:
        store.add_activity("accountant_removed", f"Acesso do contabilista cortado: {r['email']}", "", "feito")
    return {"ok": True}


def grants_for(email: str) -> list[dict]:
    with accounts._db() as c:
        rows = c.execute("SELECT a.id, a.owner_id, a.created_at, u.name, u.email FROM accountant_access a "
                         "JOIN users u ON u.id=a.owner_id WHERE lower(a.email)=lower(?) AND a.removed_at IS NULL "
                         "AND u.status='ativo' ORDER BY u.name", (email,)).fetchall()
    return [dict(r) for r in rows]


def grant(gid: int, email: str) -> dict | None:
    return next((g for g in grants_for(email) if g["id"] == int(gid)), None)


def touch(gid: int) -> None:
    with accounts._db() as c:
        c.execute("UPDATE accountant_access SET last_access=? WHERE id=?", (store.now(), int(gid)))


ACC_MAIL = {
    "pt": ("{who} deu acesso às despesas no Fidus",
           "<p>{who} deu a você acesso <b>só de leitura</b> às despesas e recibos no Fidus: valores, IVA, NIF, "
           "categorias e as fotos, com exportação para Excel.</p>{btn}<p>Entre com este e-mail: <b>{e}</b>. "
           "Você recebe um código na hora. Nada de agenda, e-mails ou conversas.</p>"),
    "pt-pt": ("{who} deu-lhe acesso às despesas no Fidus",
              "<p>{who} deu-lhe acesso <b>só de leitura</b> às despesas e faturas no Fidus: valores, IVA, NIF, "
              "categorias do e-Fatura e as fotografias, com exportação para Excel.</p>{btn}<p>Entre com este e-mail: "
              "<b>{e}</b>. Recebe um código na hora. Sem acesso a agenda, e-mails ou conversas.</p>"),
    "en": ("{who} shared their expenses with you on Fidus",
           "<p>{who} gave you <b>read-only</b> access to their expenses and receipts on Fidus: amounts, VAT, "
           "categories and the photos, with Excel export.</p>{btn}<p>Sign in with this email: <b>{e}</b>. You'll get "
           "a code straight away. No diary, emails or conversations.</p>"),
}
OPEN = {"pt": "Abrir as despesas", "pt-pt": "Abrir as despesas", "en": "Open the expenses"}


def portal_url() -> str:
    return f"{(config.PUBLIC_BASE_URL or '').rstrip('/')}/contabilista"


def _mail_accountant(email: str) -> None:
    lg = _lang()
    subject, body = ACC_MAIL[lg]
    mailer.send_raw(email, subject.format(who=_who()),
                    body.format(who=html.escape(_who()), btn=_button(portal_url(), OPEN[lg]), e=html.escape(email)),
                    wait=False)


# entrar no portal: código de 6 números por e-mail, sessão de 12 horas
CODE_TTL = 600
SESSION_TTL = 12 * 3600
FAILS_PER_DAY = 10


def start_login(email: str) -> None:
    """Manda o código só se esse e-mail tiver acesso a alguém (a resposta é igual nos dois casos)."""
    try:
        e = _clean_email(email)
    except ValueError:
        return
    if not grants_for(e):
        return
    code = f"{secrets.randbelow(10**6):06d}"
    with accounts._db() as c:
        c.execute("INSERT INTO accountant_codes(email,hash,expires) VALUES(?,?,?)", (e, _h(f"{e}:{code}"), time.time() + CODE_TTL))
    mailer.send_raw(e, f"Fidus: {code}", f"<p>O seu código de acesso / your access code:</p>"
                    f"<p style='font:700 30px monospace;letter-spacing:6px'>{code}</p><p>10 min.</p>", wait=False)


def verify_login(email: str, code: str) -> str | None:
    try:
        e = _clean_email(email)
    except ValueError:
        return None
    now = time.time()
    with accounts._db() as c:
        fails = c.execute("SELECT COUNT(*) FROM accountant_fails WHERE email=? AND at>?", (e, now - 86400)).fetchone()[0]
        if fails >= FAILS_PER_DAY:
            return None
        r = c.execute("SELECT id FROM accountant_codes WHERE email=? AND hash=? AND used=0 AND expires>?",
                      (e, _h(f"{e}:{(code or '').strip()}"), now)).fetchone()
        if not r:
            c.execute("INSERT INTO accountant_fails(email,at) VALUES(?,?)", (e, now))
            return None
        c.execute("UPDATE accountant_codes SET used=1 WHERE id=?", (r["id"],))
        token = secrets.token_urlsafe(32)
        c.execute("INSERT INTO accountant_sessions(hash,email,expires) VALUES(?,?,?)", (_h(token), e, now + SESSION_TTL))
    return token


def session_email(token: str) -> str | None:
    if not token:
        return None
    with accounts._db() as c:
        r = c.execute("SELECT email FROM accountant_sessions WHERE hash=? AND expires>?", (_h(token), time.time())).fetchone()
    return r["email"] if r else None


def end_session(token: str) -> None:
    with accounts._db() as c:
        c.execute("DELETE FROM accountant_sessions WHERE hash=?", (_h(token or ""),))
