"""Armazenamento em SQLite: tokens do Google, histórico curto e ações pendentes."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone

from . import config


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
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
            CREATE TABLE IF NOT EXISTS pending_actions (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL);
            """
        )


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
        c.execute("INSERT INTO messages(role,content,created_at) VALUES(?,?,?)", (role, content, now()))


def recent_messages(limit: int = 10) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in reversed(rows)]


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


def update_pending(pid: str, status: str, payload: dict | None = None) -> None:
    with _conn() as c:
        if payload is None:
            c.execute("UPDATE pending_actions SET status=? WHERE id=?", (status, pid))
        else:
            c.execute("UPDATE pending_actions SET status=?, payload=? WHERE id=?", (status, json.dumps(payload), pid))


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
