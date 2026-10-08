"""Contas de clientes: cadastro pelo Google, tokens do app, convites e mapa de links públicos.

Fica num banco separado (accounts.db). Os dados de cada cliente ficam no banco dele (store.py).
Tokens e códigos de login são guardados só como hash: quem lê o banco não consegue entrar.
"""
import hashlib
import hmac
import secrets
import sqlite3
import time
import uuid

from . import config, store

LOGIN_CODE_TTL = 600     # código mostrado após o Google: 10 minutos
PENDING_TTL = 900        # ida e volta ao Google: 15 minutos


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(config.ACCOUNTS_DB)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    import os
    if os.path.dirname(config.ACCOUNTS_DB):
        os.makedirs(os.path.dirname(config.ACCOUNTS_DB), exist_ok=True)
    with _db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, email TEXT UNIQUE, name TEXT, status TEXT NOT NULL DEFAULT 'ativo',
                created_at TEXT NOT NULL, last_seen TEXT);
            CREATE TABLE IF NOT EXISTS tokens (
                hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS invites (
                email TEXT PRIMARY KEY, plan TEXT NOT NULL, created_at TEXT NOT NULL, used_at TEXT);
            CREATE TABLE IF NOT EXISTS login_pending (
                state TEXT PRIMARY KEY, verifier TEXT, user_id TEXT, expires REAL NOT NULL,
                browser TEXT, app_challenge TEXT);
            CREATE TABLE IF NOT EXISTS login_codes (
                hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0,
                app_challenge TEXT);
            CREATE TABLE IF NOT EXISTS used_links (sig TEXT PRIMARY KEY, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS public_slugs (slug TEXT PRIMARY KEY, user_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS referral_codes (user_id TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL);
            CREATE TABLE IF NOT EXISTS referrals (
                invitee_id TEXT PRIMARY KEY, referrer_id TEXT NOT NULL, created_at TEXT NOT NULL, paid_at TEXT);
            CREATE TABLE IF NOT EXISTS referral_credits (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, invitee_id TEXT UNIQUE NOT NULL,
                percent INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'disponivel', created_at TEXT NOT NULL,
                used_at TEXT);
            """
        )
        pcols = {r[1] for r in c.execute("PRAGMA table_info(login_pending)").fetchall()}
        if "ref" not in pcols:
            c.execute("ALTER TABLE login_pending ADD COLUMN ref TEXT")
        cols = {r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()}
        if "google_sub" not in cols:  # banco antigo: acrescenta a coluna
            c.execute("ALTER TABLE users ADD COLUMN google_sub TEXT")
        c.execute("INSERT OR IGNORE INTO users(id,email,name,created_at) VALUES(?,?,?,?)",
                  (store.OWNER_ID, config.OWNER_EMAIL or None, config.USER_NAME, store.now()))


def _h(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


# ---------- usuários ----------
def user_ctx(row: dict) -> dict:
    """Dicionário que o store usa para abrir o banco certo."""
    return {"id": row["id"], "email": row.get("email"), "name": row.get("name"),
            "is_owner": row["id"] == store.OWNER_ID, **store.user_paths(row["id"])}


def get_user(uid: str) -> dict | None:
    with _db() as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return dict(r) if r else None


def by_email(email: str) -> dict | None:
    with _db() as c:
        r = c.execute("SELECT * FROM users WHERE lower(email)=lower(?)", (email,)).fetchone()
    return dict(r) if r else None


def list_users() -> list[dict]:
    with _db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()]


def set_status(uid: str, status: str) -> None:
    with _db() as c:
        c.execute("UPDATE users SET status=? WHERE id=?", (status, uid))
        if status != "ativo":
            c.execute("UPDATE tokens SET revoked=1 WHERE user_id=?", (uid,))


def can_signup(email: str, ref: str | None = None) -> tuple[bool, str | None]:
    """(pode entrar?, plano do convite)"""
    if config.OWNER_EMAIL and email.lower() == config.OWNER_EMAIL:
        return True, None
    with _db() as c:
        inv = c.execute("SELECT plan FROM invites WHERE lower(email)=lower(?)", (email,)).fetchone()
    if inv:
        return True, inv["plan"]
    if ref and config.REFERRAL_SIGNUP and referrer_for_code(ref) and _ref_signups_today(ref) < REFERRAL_DAILY_CAP:
        return True, None  # indicação de um cliente vale como convite (com limite por dia)
    return config.SIGNUP_OPEN, None


def by_sub(sub: str) -> dict | None:
    with _db() as c:
        r = c.execute("SELECT * FROM users WHERE google_sub=?", (sub,)).fetchone()
    return dict(r) if r else None


def _link_sub(uid: str, sub: str | None) -> None:
    if sub:
        with _db() as c:
            c.execute("UPDATE users SET google_sub=? WHERE id=? AND google_sub IS NULL", (sub, uid))


def find_or_create(email: str, name: str | None, sub: str | None = None, ref: str | None = None) -> dict | None:
    """Usuário existente, ou novo se convidado/cadastro aberto. None = sem permissão.

    A conta é presa ao ID permanente do Google (sub): se o e-mail mudar de dono no futuro, quem recebe o
    e-mail não herda a conta antiga."""
    email = email.strip().lower()
    if sub:
        u = by_sub(sub)
        if u:
            return u if u["status"] == "ativo" else None
    if config.OWNER_EMAIL and email == config.OWNER_EMAIL:
        owner = get_user(store.OWNER_ID)
        if owner.get("google_sub") and sub and owner["google_sub"] != sub:
            return None
        _link_sub(store.OWNER_ID, sub)
        return get_user(store.OWNER_ID)
    u = by_email(email)
    if u:
        if u.get("google_sub") and sub and u["google_sub"] != sub:
            return None  # mesmo e-mail, outra pessoa no Google
        _link_sub(u["id"], sub)
        return u if u["status"] == "ativo" else None
    ok, invite_plan = can_signup(email, ref)
    if not ok:
        return None
    uid = uuid.uuid4().hex[:16]
    with _db() as c:
        c.execute("INSERT INTO users(id,email,name,created_at,google_sub) VALUES(?,?,?,?,?)",
                  (uid, email, name, store.now(), sub))
        c.execute("UPDATE invites SET used_at=? WHERE lower(email)=lower(?)", (store.now(), email))
    u = get_user(uid)
    from . import plans
    with store.as_user(user_ctx(u)):
        store.init_db()
        plans.set_plan(invite_plan or config.NEW_USER_PLAN)
        store.save_profile(name=(name or "").split(" ")[0] or None)
    return u


def invite(email: str, plan: str) -> None:
    with _db() as c:
        c.execute("INSERT INTO invites(email,plan,created_at) VALUES(?,?,?) "
                  "ON CONFLICT(email) DO UPDATE SET plan=excluded.plan", (email.strip().lower(), plan, store.now()))


def list_invites() -> list[dict]:
    with _db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM invites ORDER BY created_at DESC").fetchall()]


# ---------- tokens do app ----------
def issue_token(uid: str) -> str:
    tok = "fx_" + secrets.token_urlsafe(32)
    with _db() as c:
        c.execute("INSERT INTO tokens(hash,user_id,created_at) VALUES(?,?,?)", (_h(tok), uid, store.now()))
    return tok


def user_for_token(token: str) -> dict | None:
    if not token:
        return None
    if config.APP_TOKEN and hmac.compare_digest(token, config.APP_TOKEN):
        return get_user(store.OWNER_ID) or {"id": store.OWNER_ID, "email": config.OWNER_EMAIL, "name": config.USER_NAME}
    if not token.startswith("fx_"):
        return None
    with _db() as c:
        r = c.execute("SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id "
                      "WHERE t.hash=? AND t.revoked=0 AND u.status='ativo'", (_h(token),)).fetchone()
        if r and time.time() - _seen.get(r["id"], 0) > 300:  # grava "visto por último" no máx. a cada 5 min
            _seen[r["id"]] = time.time()
            c.execute("UPDATE users SET last_seen=? WHERE id=?", (store.now(), r["id"]))
    return dict(r) if r else None


_seen: dict = {}


def revoke(token: str) -> None:
    with _db() as c:
        c.execute("UPDATE tokens SET revoked=1 WHERE hash=?", (_h(token),))


# ---------- ida e volta ao Google ----------
def new_pending(verifier: str | None, user_id: str | None, state: str, browser_nonce: str,
                app_challenge: str | None = None, ref: str | None = None) -> None:
    """Guarda a ida ao Google. `browser_nonce` vai num cookie do navegador que começou o login (anti-CSRF);
    `app_challenge` é o hash de um segredo que só o app que pediu o login conhece."""
    with _db() as c:
        c.execute("DELETE FROM login_pending WHERE expires<?", (time.time(),))
        c.execute("INSERT INTO login_pending(state,verifier,user_id,expires,browser,app_challenge,ref) "
                  "VALUES(?,?,?,?,?,?,?)",
                  (state, verifier, user_id, time.time() + PENDING_TTL, _h(browser_nonce), app_challenge, ref))


def take_pending(state: str, browser_nonce: str) -> dict | None:
    """Uso único (apaga ao ler) e só no mesmo navegador que começou o login."""
    with _db() as c:
        r = c.execute("DELETE FROM login_pending WHERE state=? RETURNING *", (state or "",)).fetchone()
    if not r or r["expires"] < time.time():
        return None
    if not browser_nonce or not hmac.compare_digest(r["browser"] or "", _h(browser_nonce)):
        return None
    return dict(r)


def use_link_once(sig: str, expires: float) -> bool:
    """Links assinados de reconexão valem uma vez só."""
    with _db() as c:
        c.execute("DELETE FROM used_links WHERE expires<?", (time.time(),))
        try:
            c.execute("INSERT INTO used_links(sig,expires) VALUES(?,?)", (sig, expires))
            return True
        except sqlite3.IntegrityError:
            return False


def new_login_code(uid: str, app_challenge: str | None = None) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O e 1/I para não confundir
    code = "".join(secrets.choice(alphabet) for _ in range(8))
    with _db() as c:
        c.execute("DELETE FROM login_codes WHERE expires<?", (time.time() - 86400,))
        c.execute("INSERT INTO login_codes(hash,user_id,expires,app_challenge) VALUES(?,?,?,?)",
                  (_h(code), uid, time.time() + LOGIN_CODE_TTL, app_challenge))
    return code


def redeem_code(code: str, app_verifier: str | None = None) -> str | None:
    """Troca o código (uso único, 10 min) por um token do app. Se o login começou no app, exige também o
    segredo do app: outro aplicativo que capture o link fidus://login não consegue usar o código."""
    code = (code or "").strip().upper().replace(" ", "").replace("-", "")
    with _db() as c:
        row = c.execute("SELECT * FROM login_codes WHERE hash=? AND used=0 AND expires>=?",
                        (_h(code), time.time())).fetchone()
        if not row:
            return None
        if row["app_challenge"]:
            if not app_verifier or not hmac.compare_digest(row["app_challenge"], _h(app_verifier)):
                return None
        cur = c.execute("UPDATE login_codes SET used=1 WHERE hash=? AND used=0", (_h(code),))
        if cur.rowcount != 1:
            return None
        uid = row["user_id"]
    return issue_token(uid)


# ---------- links públicos (agendamento) ----------
def register_slug(slug: str, uid: str) -> None:
    with _db() as c:
        c.execute("INSERT OR REPLACE INTO public_slugs(slug,user_id) VALUES(?,?)", (slug, uid))


def drop_slug(slug: str) -> None:
    with _db() as c:
        c.execute("DELETE FROM public_slugs WHERE slug=?", (slug,))


def user_for_slug(slug: str) -> dict | None:
    with _db() as c:
        r = c.execute("SELECT user_id FROM public_slugs WHERE slug=?", (slug,)).fetchone()
    if not r:
        return None
    u = get_user(r["user_id"])
    return u if u and u["status"] == "ativo" else None


# ---------- Convide e ganhe ----------
# Quem convida ganha REFERRAL_PERCENT% de desconto na próxima cobrança quando o convidado paga o 1º mês.
# Os descontos não somam: no máximo um por cobrança; os que sobram ficam para as cobranças seguintes.
# Quem é convidado ganha REFERRAL_TRIAL_DAYS dias grátis.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
REFERRAL_WINDOW_DAYS = 7
REFERRAL_DAILY_CAP = 10  # contas novas por código por dia (um link vazado não abre a porta para todo mundo)


def _ref_signups_today(code: str) -> int:
    ref = referrer_for_code(code)
    if not ref:
        return 0
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with _db() as c:
        return c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=? AND created_at>=?", (ref["id"], since)).fetchone()[0]  # quem esqueceu o código pode colocar nos primeiros dias da conta


def _norm_code(code: str | None) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())[:12]


def referral_code(uid: str) -> str:
    with _db() as c:
        r = c.execute("SELECT code FROM referral_codes WHERE user_id=?", (uid,)).fetchone()
        if r:
            return r["code"]
        for _ in range(20):
            code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
            try:
                c.execute("INSERT INTO referral_codes(user_id,code) VALUES(?,?)", (uid, code))
                return code
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError("não consegui gerar o código de convite")


def referrer_for_code(code: str | None) -> dict | None:
    code = _norm_code(code)
    if not code:
        return None
    with _db() as c:
        r = c.execute("SELECT user_id FROM referral_codes WHERE code=?", (code,)).fetchone()
    u = get_user(r["user_id"]) if r else None
    return u if u and u["status"] == "ativo" else None


def apply_referral(invitee_id: str, code: str | None) -> dict:
    """Liga o convidado a quem convidou. Só vale para conta nova (até 7 dias) e uma vez só."""
    from datetime import datetime, timedelta, timezone
    ref = referrer_for_code(code)
    if not ref:
        return {"error": "código de convite não encontrado"}
    if ref["id"] == invitee_id:
        return {"error": "não dá para usar o próprio código"}
    u = get_user(invitee_id)
    if not u or invitee_id == store.OWNER_ID:
        return {"error": "conta inválida"}
    try:
        created = datetime.fromisoformat(u["created_at"])
    except (TypeError, ValueError):
        created = datetime.now(timezone.utc)
    if datetime.now(timezone.utc) - created > timedelta(days=REFERRAL_WINDOW_DAYS):
        return {"error": "o código de convite só pode ser usado nos primeiros dias da conta"}
    with _db() as c:
        try:
            c.execute("INSERT INTO referrals(invitee_id,referrer_id,created_at) VALUES(?,?,?)",
                      (invitee_id, ref["id"], store.now()))
        except sqlite3.IntegrityError:
            return {"error": "esta conta já usou um código de convite"}
    return {"ok": True, "referrer_name": (ref.get("name") or "").split(" ")[0],
            "trial_days": config.REFERRAL_TRIAL_DAYS}


def mark_paid(invitee_id: str) -> dict | None:
    """Chamar quando o convidado pagar a 1ª cobrança (webhook do pagamento): dá o desconto a quem convidou."""
    with _db() as c:
        r = c.execute("UPDATE referrals SET paid_at=? WHERE invitee_id=? AND paid_at IS NULL RETURNING referrer_id",
                      (store.now(), invitee_id)).fetchone()
        if not r:
            return None
        c.execute("INSERT OR IGNORE INTO referral_credits(user_id,invitee_id,percent,created_at) VALUES(?,?,?,?)",
                  (r["referrer_id"], invitee_id, config.REFERRAL_PERCENT, store.now()))
    return {"referrer_id": r["referrer_id"], "percent": config.REFERRAL_PERCENT}


def revoke_referral_reward(invitee_id: str) -> None:
    """Convidado pediu reembolso: o crédito de quem convidou some, se ainda não foi usado."""
    with _db() as c:
        c.execute("DELETE FROM referral_credits WHERE invitee_id=? AND status='disponivel'", (invitee_id,))
        c.execute("UPDATE referrals SET paid_at=NULL WHERE invitee_id=?", (invitee_id,))


def referral_trial(uid: str) -> bool:
    """Entrou por convite e ainda não pagou: a loja oferece a oferta de dias grátis do convite."""
    with _db() as c:
        return bool(c.execute("SELECT 1 FROM referrals WHERE invitee_id=? AND paid_at IS NULL", (uid,)).fetchone())


def next_discount(uid: str) -> int:
    """Desconto (%) da próxima cobrança. Não soma: no máximo um crédito por cobrança."""
    with _db() as c:
        r = c.execute("SELECT percent FROM referral_credits WHERE user_id=? AND status='disponivel' ORDER BY id LIMIT 1",
                      (uid,)).fetchone()
    return r["percent"] if r else 0


def consume_discount(uid: str) -> int:
    """Chamar ao fechar cada cobrança: usa um crédito (o mais antigo) e devolve o % aplicado."""
    with _db() as c:
        r = c.execute("SELECT id, percent FROM referral_credits WHERE user_id=? AND status='disponivel' ORDER BY id LIMIT 1",
                      (uid,)).fetchone()
        if not r:
            return 0
        done = c.execute("UPDATE referral_credits SET status='usado', used_at=? WHERE id=? AND status='disponivel'",
                         (store.now(), r["id"])).rowcount
    return r["percent"] if done else 0


def referral_stats(uid: str) -> dict:
    with _db() as c:
        invited = c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (uid,)).fetchone()[0]
        paid = c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=? AND paid_at IS NOT NULL", (uid,)).fetchone()[0]
        avail = c.execute("SELECT COUNT(*) FROM referral_credits WHERE user_id=? AND status='disponivel'", (uid,)).fetchone()[0]
        used = c.execute("SELECT COUNT(*) FROM referral_credits WHERE user_id=? AND status='usado'", (uid,)).fetchone()[0]
        mine = c.execute("SELECT r.referrer_id, u.name FROM referrals r LEFT JOIN users u ON u.id=r.referrer_id "
                         "WHERE r.invitee_id=?", (uid,)).fetchone()
    return {"invited": invited, "paid": paid, "credits_available": avail, "credits_used": used,
            "next_discount": next_discount(uid), "percent": config.REFERRAL_PERCENT,
            "trial_days": config.REFERRAL_TRIAL_DAYS,
            "invited_by": ((mine["name"] or "").split(" ")[0] or "um amigo") if mine else None}
