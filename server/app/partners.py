"""Parceiros (criadores/influenciadores): código próprio, desconto para o seguidor e comissão para o criador.

Regras (decididas pelo dono):
- o seguidor entra com o código do criador (ex. ANA) e ganha desconto no 1º mês (padrão 20%, oferta "parceiro"
  na loja);
- o criador ganha 10% de cada mensalidade paga por esse cliente, durante 12 meses a partir do 1º pagamento;
- só enquanto o cliente pagar: cancelou, não há próxima cobrança, logo não há comissão; reembolso estorna.
Tudo fica no banco de contas (accounts.db). O painel mostra quanto pagar a cada criador por mês.
"""
import sqlite3
from datetime import datetime, timedelta, timezone

from . import accounts, store

DEFAULT_PERCENT = 10
DEFAULT_DISCOUNT = 20
DEFAULT_MONTHS = 12
OFFER_TAG = "parceiro"


def _db() -> sqlite3.Connection:
    c = accounts._db()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS partners (code TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT,
            percent INTEGER NOT NULL, discount INTEGER NOT NULL, months INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS partner_links (user_id TEXT PRIMARY KEY, code TEXT NOT NULL, created_at TEXT NOT NULL,
            first_paid_at TEXT);
        CREATE TABLE IF NOT EXISTS commissions (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL,
            user_id TEXT NOT NULL, event_id TEXT UNIQUE, amount REAL NOT NULL, currency TEXT NOT NULL,
            commission REAL NOT NULL, created_at TEXT NOT NULL, paid_out_at TEXT, reversed INTEGER NOT NULL DEFAULT 0);
    """)
    return c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm(code: str | None) -> str:
    return accounts._norm_code(code)


def get(code: str | None) -> dict | None:
    code = norm(code)
    if not code:
        return None
    with _db() as c:
        r = c.execute("SELECT * FROM partners WHERE code=? AND active=1", (code,)).fetchone()
    return dict(r) if r else None


def create(code: str, name: str, email: str = "", percent: int = DEFAULT_PERCENT, discount: int = DEFAULT_DISCOUNT,
           months: int = DEFAULT_MONTHS) -> dict:
    code = norm(code)
    if len(code) < 3:
        raise ValueError("código com pelo menos 3 letras ou números")
    if accounts.referrer_for_code(code):
        raise ValueError("esse código já é de um cliente (convide e ganhe)")
    if not 0 < int(percent) <= 50 or not 0 <= int(discount) <= 100 or not 1 <= int(months) <= 36:
        raise ValueError("valores fora do limite")
    with _db() as c:
        try:
            c.execute("INSERT INTO partners(code,name,email,percent,discount,months,created_at) VALUES(?,?,?,?,?,?,?)",
                      (code, (name or code)[:80], (email or "")[:120], int(percent), int(discount), int(months), _now()))
        except sqlite3.IntegrityError:
            raise ValueError("esse código já existe")
    return get(code)


def set_active(code: str, active: bool) -> None:
    with _db() as c:
        c.execute("UPDATE partners SET active=? WHERE code=?", (1 if active else 0, norm(code)))


def link(user_id: str, code: str | None) -> dict:
    """Liga um cliente novo ao criador. Uma vez só, e não junto com o convide e ganhe."""
    p = get(code)
    if not p:
        return {"error": "código não encontrado"}
    u = accounts.get_user(user_id)
    if not u or user_id == store.OWNER_ID:
        return {"error": "conta inválida"}
    try:
        created = datetime.fromisoformat(u["created_at"])
    except (TypeError, ValueError):
        created = datetime.now(timezone.utc)
    if datetime.now(timezone.utc) - created > timedelta(days=accounts.REFERRAL_WINDOW_DAYS):
        return {"error": "o código só pode ser usado nos primeiros dias da conta"}
    with accounts._db() as c:
        if c.execute("SELECT 1 FROM referrals WHERE invitee_id=?", (user_id,)).fetchone():
            return {"error": "esta conta já usou um código"}
    with _db() as c:
        try:
            c.execute("INSERT INTO partner_links(user_id,code,created_at) VALUES(?,?,?)", (user_id, p["code"], _now()))
        except sqlite3.IntegrityError:
            return {"error": "esta conta já usou um código"}
    return {"ok": True, "partner": p["name"], "discount": p["discount"]}


def link_for(user_id: str) -> dict | None:
    with _db() as c:
        r = c.execute("SELECT l.*, p.discount, p.percent, p.months, p.name FROM partner_links l "
                      "JOIN partners p ON p.code=l.code WHERE l.user_id=?", (user_id,)).fetchone()
    return dict(r) if r else None


def first_month_offer(user_id: str) -> dict | None:
    """Ainda não pagou e veio de um criador: a loja mostra a oferta de desconto do 1º mês."""
    lk = link_for(user_id)
    if lk and not lk["first_paid_at"]:
        return {"tag": OFFER_TAG, "discount": lk["discount"], "partner": lk["name"]}
    return None


def on_payment(user_id: str, event_id: str, amount: float, currency: str) -> dict | None:
    """Cada cobrança paga (1ª ou renovação): se o cliente veio de um criador e está nos 12 meses, gera a comissão."""
    lk = link_for(user_id)
    if not lk or not amount or amount <= 0:
        return None
    now = datetime.now(timezone.utc)
    with _db() as c:
        if not lk["first_paid_at"]:
            c.execute("UPDATE partner_links SET first_paid_at=? WHERE user_id=?", (now.isoformat(), user_id))
            lk["first_paid_at"] = now.isoformat()
        start = datetime.fromisoformat(lk["first_paid_at"])
        if now > start + timedelta(days=round(lk["months"] * 30.44)):
            return None
        commission = round(float(amount) * lk["percent"] / 100, 2)
        try:
            c.execute("INSERT INTO commissions(code,user_id,event_id,amount,currency,commission,created_at) "
                      "VALUES(?,?,?,?,?,?,?)", (lk["code"], user_id, event_id or f"{user_id}:{now.isoformat()}",
                                                round(float(amount), 2), (currency or "").upper()[:3], commission,
                                                now.isoformat()))
        except sqlite3.IntegrityError:
            return None  # a RevenueCat mandou o mesmo aviso de novo
    return {"code": lk["code"], "commission": commission, "currency": (currency or "").upper()[:3]}


def on_refund(user_id: str) -> None:
    """Reembolso: a última comissão ainda não paga desse cliente é estornada."""
    with _db() as c:
        r = c.execute("SELECT id FROM commissions WHERE user_id=? AND paid_out_at IS NULL AND reversed=0 "
                      "ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
        if r:
            c.execute("UPDATE commissions SET reversed=1 WHERE id=?", (r["id"],))


def report() -> list[dict]:
    """Para o painel: por criador, quantos entraram, quantos pagam, comissão do mês e quanto falta pagar."""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    out = []
    with _db() as c:
        for p in c.execute("SELECT * FROM partners ORDER BY created_at DESC").fetchall():
            code = p["code"]
            signups = c.execute("SELECT COUNT(*) FROM partner_links WHERE code=?", (code,)).fetchone()[0]
            paying = c.execute("SELECT COUNT(DISTINCT user_id) FROM commissions WHERE code=? AND reversed=0 AND created_at>=?",
                               (code, (datetime.now(timezone.utc) - timedelta(days=40)).isoformat())).fetchone()[0]
            due: dict = {}
            this_month: dict = {}
            for r in c.execute("SELECT currency, commission, created_at, paid_out_at FROM commissions "
                               "WHERE code=? AND reversed=0", (code,)):
                if not r["paid_out_at"]:
                    due[r["currency"]] = round(due.get(r["currency"], 0) + r["commission"], 2)
                if r["created_at"].startswith(month):
                    this_month[r["currency"]] = round(this_month.get(r["currency"], 0) + r["commission"], 2)
            out.append({"code": code, "name": p["name"], "email": p["email"], "percent": p["percent"],
                        "discount": p["discount"], "months": p["months"], "active": bool(p["active"]),
                        "signups": signups, "paying": paying, "due": due, "this_month": this_month})
    return out


def mark_paid_out(code: str) -> int:
    """Você pagou o criador: tudo que estava pendente dele fica como pago."""
    with _db() as c:
        cur = c.execute("UPDATE commissions SET paid_out_at=? WHERE code=? AND paid_out_at IS NULL AND reversed=0",
                        (_now(), norm(code)))
        return cur.rowcount
