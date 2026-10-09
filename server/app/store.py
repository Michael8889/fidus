"""Armazenamento em SQLite.

Cada cliente tem o PRÓPRIO arquivo de banco (e a própria pasta de arquivos): os dados de um nunca
aparecem para outro, mesmo com um erro de consulta. Quem é o cliente da requisição atual fica em
`CURRENT` (contextvar), definido pelo middleware de autenticação ou por `as_user(...)`.
Sem cliente definido, vale o dono (Mike), cujo banco é o FIDUS_DB_PATH de sempre.
"""
import contextlib
import contextvars
import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from . import config

CURRENT: contextvars.ContextVar = contextvars.ContextVar("fidus_user", default=None)
_ready: set = set()
_ready_lock = threading.Lock()

OWNER_ID = "owner"


def owner_user() -> dict:
    return {"id": OWNER_ID, "email": config.OWNER_EMAIL, "name": config.USER_NAME, "is_owner": True,
            "db": config.DB_PATH, "dir": config.DATA_DIR, "receipts": config.RECEIPTS_DIR}


def user_paths(uid: str) -> dict:
    if uid == OWNER_ID:
        return owner_user()
    base = os.path.join(config.DATA_DIR, "users", uid)
    return {"db": os.path.join(base, "fidus.db"), "dir": base, "receipts": os.path.join(base, "receipts")}


def current() -> dict:
    return CURRENT.get() or owner_user()


@contextlib.contextmanager
def as_user(user: dict):
    """Executa o bloco no banco desse cliente."""
    tok = CURRENT.set(user)
    try:
        yield user
    finally:
        CURRENT.reset(tok)


def files_dir(*parts: str) -> str:
    d = os.path.join(current()["dir"], *parts)
    os.makedirs(d, exist_ok=True)
    return d


def receipts_dir() -> str:
    d = current()["receipts"]
    os.makedirs(d, exist_ok=True)
    return d


def _conn() -> sqlite3.Connection:
    path = current()["db"]
    if path not in _ready:
        with _ready_lock:
            if path not in _ready:
                if os.path.dirname(path):
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                _ready.add(path)
                _create(path)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    _conn().close()


def _create(path: str) -> None:
    c0 = sqlite3.connect(path)
    with c0 as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, title TEXT NOT NULL,
                detail TEXT, status TEXT NOT NULL, ref TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, amount REAL NOT NULL,
                currency TEXT NOT NULL, category TEXT NOT NULL, business TEXT NOT NULL,
                merchant TEXT, note TEXT, vat REAL, receipt_path TEXT, deleted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, notes TEXT, due TEXT,
                priority TEXT NOT NULL DEFAULT 'normal', status TEXT NOT NULL DEFAULT 'aberta',
                event_id TEXT, created_at TEXT NOT NULL, done_at TEXT);
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT, tags TEXT,
                path TEXT NOT NULL, media_type TEXT, expires_on TEXT, event_id TEXT,
                deleted INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, amount REAL, currency TEXT,
                business TEXT, category TEXT, day_of_month INTEGER NOT NULL, event_id TEXT,
                active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, status TEXT NOT NULL, audio_path TEXT,
                transcript TEXT, summary TEXT, duration_s REAL, error TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT, type_id TEXT, start TEXT NOT NULL, name TEXT NOT NULL,
                email TEXT, phone TEXT, address TEXT, notes TEXT, event_id TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS usage (
                day TEXT NOT NULL, model TEXT NOT NULL, calls INTEGER NOT NULL DEFAULT 0, input INTEGER NOT NULL DEFAULT 0,
                output INTEGER NOT NULL DEFAULT 0, cache_write INTEGER NOT NULL DEFAULT 0, cache_read INTEGER NOT NULL DEFAULT 0,
                searches INTEGER NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0, PRIMARY KEY (day, model));
            CREATE TABLE IF NOT EXISTS pending_actions (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL);
            """
        )
        cols = {r[1] for r in c.execute("PRAGMA table_info(messages)").fetchall()}
        if "conv" not in cols:  # banco antigo: tudo o que já existe vira a conversa 1
            c.execute("ALTER TABLE messages ADD COLUMN conv INTEGER NOT NULL DEFAULT 1")
    c0.close()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def kv_get(k: str) -> str | None:
    with _conn() as c:
        row = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return row["v"] if row else None


def kv_set(k: str, v: str) -> None:
    with _conn() as c:
        c.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


def add_message(role: str, content: str) -> None:
    with _conn() as c:
        c.execute("INSERT INTO messages(role,content,created_at,conv) VALUES(?,?,?,?)",
                  (role, content, now(), current_conv()))


def recent_messages(limit: int = 10, conv: int | None = None) -> list[dict]:
    """Últimas mensagens da conversa aberta (ou da conversa `conv`)."""
    with _conn() as c:
        rows = c.execute("SELECT role, content, created_at FROM messages WHERE conv=? ORDER BY id DESC LIMIT ?",
                         (conv or current_conv(), limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


# ---------- Conversas (menu: Nova conversa / Conversas anteriores) ----------
def current_conv() -> int:
    try:
        return int(kv_get("conv") or 1)
    except ValueError:
        return 1


def new_conversation() -> int:
    """Abre uma conversa nova. Se a atual ainda está vazia, continua nela."""
    cur = current_conv()
    with _conn() as c:
        used = c.execute("SELECT COUNT(*) FROM messages WHERE conv=?", (cur,)).fetchone()[0]
        if not used:
            return cur
        top = c.execute("SELECT COALESCE(MAX(conv),0) FROM messages").fetchone()[0]
    nxt = max(top, cur) + 1
    kv_set("conv", str(nxt))
    return nxt


def open_conversation(conv: int) -> bool:
    with _conn() as c:
        ok = c.execute("SELECT 1 FROM messages WHERE conv=? LIMIT 1", (conv,)).fetchone()
    if ok:
        kv_set("conv", str(conv))
    return bool(ok)


def list_conversations(limit: int = 50) -> list[dict]:
    import re
    with _conn() as c:
        rows = c.execute("SELECT conv, COUNT(*) n, MIN(created_at) started, MAX(created_at) last, MAX(id) mx "
                         "FROM messages GROUP BY conv ORDER BY mx DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            first = c.execute("SELECT content FROM messages WHERE conv=? AND role='user' ORDER BY id LIMIT 1",
                              (r["conv"],)).fetchone()
            title = re.sub(r"^\[foto enviada\]\s*", "📷 ", (first["content"] if first else "") or "").strip()
            title = title.split("\n")[0][:70] or "Conversa"
            out.append({"id": r["conv"], "title": title, "messages": r["n"], "started": r["started"],
                        "last": r["last"]})
    return out


def create_pending(kind: str, payload: dict) -> str:
    pid = uuid.uuid4().hex[:12]
    with _conn() as c:
        c.execute(
            "INSERT INTO pending_actions(id,kind,payload,status,created_at) VALUES(?,?,?,?,?)",
            (pid, kind, json.dumps(payload), "pending", now()),
        )
    return pid


def get_pending(pid: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM pending_actions WHERE id=?", (pid,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["payload"] = json.loads(d["payload"])
    return d


def claim_pending(pid: str) -> bool:
    """Passa de 'pending' para 'sending' numa única operação; False se outro pedido já pegou."""
    with _conn() as c:
        return c.execute("UPDATE pending_actions SET status='sending' WHERE id=? AND status='pending'", (pid,)).rowcount == 1


def update_pending(pid: str, status: str, payload: dict | None = None, only_if: str | None = None) -> bool:
    """Muda status/conteúdo. Com only_if, só muda se o status atual for esse (evita corrida com um envio)."""
    with _conn() as c:
        if only_if is not None:
            return c.execute("UPDATE pending_actions SET status=?, payload=COALESCE(?, payload) WHERE id=? AND status=?",
                             (status, json.dumps(payload) if payload is not None else None, pid, only_if)).rowcount == 1
        if payload is None:
            c.execute("UPDATE pending_actions SET status=? WHERE id=?", (status, pid))
        else:
            c.execute("UPDATE pending_actions SET status=?, payload=? WHERE id=?", (status, json.dumps(payload), pid))
    return True


# ---------- Atividade: registro do que o Fidus fez ----------
def add_activity(kind: str, title: str, detail: str = "", status: str = "feito", ref: str | None = None) -> int:
    with _conn() as c:
        cur = c.execute("INSERT INTO activities(kind,title,detail,status,ref,created_at) VALUES(?,?,?,?,?,?)",
                        (kind, title, detail, status, ref, now()))
        return cur.lastrowid


def list_activities(limit: int = 100) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM activities ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_activity(aid: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
    return dict(row) if row else None


def update_activity_by_ref(kind: str, ref: str, status: str) -> None:
    with _conn() as c:
        c.execute("UPDATE activities SET status=? WHERE kind=? AND ref=?", (status, kind, ref))


def set_activity_status(aid: int, status: str) -> None:
    with _conn() as c:
        c.execute("UPDATE activities SET status=? WHERE id=?", (status, aid))


# ---------- Gastos ----------
def add_expense(date: str, amount: float, currency: str, category: str, business: str,
                merchant: str | None = None, note: str | None = None, vat: float | None = None,
                receipt_path: str | None = None) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO expenses(date,amount,currency,category,business,merchant,note,vat,receipt_path,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (date, amount, currency, category, business, merchant, note, vat, receipt_path, now()))
        return cur.lastrowid


def query_expenses(date_from: str, date_to: str, category: str | None = None,
                   business: str | None = None, limit: int = 500) -> list[dict]:
    sql = "SELECT * FROM expenses WHERE deleted=0 AND date>=? AND date<=?"
    args: list = [date_from, date_to]
    if category:
        sql += " AND lower(category)=lower(?)"; args.append(category)
    if business:
        sql += " AND lower(business)=lower(?)"; args.append(business)
    sql += " ORDER BY date DESC, id DESC LIMIT ?"; args.append(limit)
    with _conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def delete_expense(eid: int) -> None:
    with _conn() as c:
        c.execute("UPDATE expenses SET deleted=1 WHERE id=?", (eid,))


# ---------- Genérico (tarefas, documentos, contas fixas) ----------
def insert(table: str, **cols) -> int:
    cols.setdefault("created_at", now())
    keys = ",".join(cols)
    with _conn() as c:
        cur = c.execute(f"INSERT INTO {table}({keys}) VALUES({','.join('?' * len(cols))})", list(cols.values()))
        return cur.lastrowid


def update(table: str, rid: int, **cols) -> None:
    sets = ",".join(f"{k}=?" for k in cols)
    with _conn() as c:
        c.execute(f"UPDATE {table} SET {sets} WHERE id=?", [*cols.values(), rid])


def get(table: str, rid: int) -> dict | None:
    with _conn() as c:
        row = c.execute(f"SELECT * FROM {table} WHERE id=?", (rid,)).fetchone()
    return dict(row) if row else None


def select(sql: str, args: tuple | list = ()) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


# ---------- Perfil do cliente (nome, fuso, moeda, empresas) ----------
def profile() -> dict:
    u = current()
    if u.get("is_owner"):
        base = {"name": config.USER_NAME, "timezone": config.USER_TIMEZONE, "currency": config.DEFAULT_CURRENCY,
                "businesses": list(config.BUSINESSES), "language": config.OWNER_LANGUAGE,
                "country": config.OWNER_COUNTRY}
    else:
        base = {"name": u.get("name") or "", "timezone": config.USER_TIMEZONE, "currency": config.DEFAULT_CURRENCY,
                "businesses": ["Pessoal"], "language": "", "country": ""}
    raw = kv_get("profile")
    if raw:
        base.update({k: v for k, v in json.loads(raw).items() if v})
    return base


def save_profile(**changes) -> dict:
    p = profile()
    p.update({k: v for k, v in changes.items() if v is not None})
    kv_set("profile", json.dumps(p, ensure_ascii=False))
    return p


def user_name() -> str:
    return profile()["name"] or "você"


def user_lang() -> str:
    """Idioma do usuário (código ISO, ex. 'pt', 'en', 'ms'); 'pt' se ainda não sabemos."""
    raw = (profile().get("language") or "pt").lower().replace("_", "-")
    return "pt-pt" if raw.startswith("pt-pt") else raw.split("-")[0]


def user_tz() -> str:
    return profile()["timezone"]


def default_currency() -> str:
    return profile()["currency"]


def businesses() -> list:
    return profile()["businesses"] or ["Pessoal"]


def match_business(name: str | None) -> str | None:
    if not name:
        return None
    for b in businesses():
        if b.strip().lower() == name.strip().lower():
            return b
    return None


# ---------- Carteiras (empresas/contas, cada uma com a sua moeda) ----------
def _valid_currency(cur: str | None) -> str | None:
    c = (cur or "").strip().upper()
    return c if re.fullmatch(r"[A-Z]{3}", c) else None


def wallet_currency(name: str | None) -> str | None:
    b = match_business(name)
    return (profile().get("wallet_currency") or {}).get(b) if b else None


def wallets() -> list[dict]:
    cur = profile().get("wallet_currency") or {}
    return [{"name": b, "currency": cur.get(b)} for b in businesses()]


def add_wallet(name: str, currency: str | None = None) -> dict:
    """Cria a carteira (ou só muda a moeda dela, se já existe). Devolve a carteira."""
    name = re.sub(r"\s+", " ", (name or "").strip())[:40]
    if not name:
        raise ValueError("nome da carteira vazio")
    cur = _valid_currency(currency)
    if currency and not cur:
        raise ValueError("moeda inválida (use o código de 3 letras, ex. GBP, EUR, BRL)")
    p = profile()
    known = match_business(name)
    biz = p["businesses"] or ["Pessoal"]
    if not known:
        biz = biz + [name]
        known = name
    wc = dict(p.get("wallet_currency") or {})
    if cur:
        wc[known] = cur
    save_profile(businesses=biz, wallet_currency=wc)
    return {"name": known, "currency": wc.get(known)}


def remove_wallet(name: str) -> dict | None:
    """Tira a carteira da lista (os gastos já lançados nela continuam guardados). Nunca deixa a lista vazia."""
    b = match_business(name)
    p = profile()
    if not b or len(p["businesses"] or []) <= 1:
        return None
    wc = dict(p.get("wallet_currency") or {})
    old = {"name": b, "currency": wc.pop(b, None)}
    kv_set("profile", json.dumps({**p, "businesses": [x for x in p["businesses"] if x != b], "wallet_currency": wc},
                                 ensure_ascii=False))
    return old


# ---------- Custo de IA por cliente ----------
def add_usage(u: dict) -> None:
    if not u or not u.get("calls"):
        return
    from . import llm
    cost = llm.cost_usd(u)
    day = datetime.now(timezone.utc).date().isoformat()
    with _conn() as c:
        c.execute("INSERT INTO usage(day,model,calls,input,output,cache_write,cache_read,searches,cost) VALUES(?,?,?,?,?,?,?,?,?) "
                  "ON CONFLICT(day,model) DO UPDATE SET calls=calls+excluded.calls, input=input+excluded.input, "
                  "output=output+excluded.output, cache_write=cache_write+excluded.cache_write, "
                  "cache_read=cache_read+excluded.cache_read, searches=searches+excluded.searches, cost=cost+excluded.cost",
                  (day, u.get("model") or "?", u.get("calls", 0), u.get("input", 0), u.get("output", 0),
                   u.get("cache_write", 0), u.get("cache_read", 0), u.get("searches", 0), cost))


def usage_cost(since_day: str) -> float:
    with _conn() as c:
        return round(c.execute("SELECT COALESCE(SUM(cost),0) FROM usage WHERE day>=?", (since_day,)).fetchone()[0], 4)


def usage_summary(days: int = 30) -> dict:
    from datetime import timedelta
    today = datetime.now(timezone.utc).date()
    since = (today - timedelta(days=days - 1)).isoformat()
    with _conn() as c:
        r = c.execute("SELECT COALESCE(SUM(calls),0) calls, COALESCE(SUM(input),0) input, COALESCE(SUM(output),0) output, "
                      "COALESCE(SUM(cache_write),0) cache_write, COALESCE(SUM(cache_read),0) cache_read, "
                      "COALESCE(SUM(searches),0) searches, COALESCE(SUM(cost),0) cost FROM usage WHERE day>=?", (since,)).fetchone()
    out = dict(r)
    out["cost"] = round(out["cost"], 4)
    out["today"] = usage_cost(today.isoformat())
    out["month"] = usage_cost(today.replace(day=1).isoformat())
    return out
