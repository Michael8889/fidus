"""Medição do produto e do sistema (para o painel da empresa em /admin).

Banco próprio (metrics.db), separado dos dados dos clientes. NUNCA guarda conteúdo: só quem (id), quando, qual
tipo de pedido, se deu certo, quanto demorou e notas que o próprio cliente deu. Assim a equipe vê a saúde do
produto sem ler conversas, e-mails ou gastos de ninguém.
"""
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

from . import config

_init_lock = threading.Lock()
_ready: set = set()
_queue: list = []          # gravações de medição esperando (não travam a resposta ao cliente)
_qlock = threading.Lock()
STARTED = time.time()
KEEP_DAYS = 180

# caminhos que contam como "pedido de verdade" (uso do produto)
REQUEST_KINDS = {"/v1/message": "texto", "/v1/voice_b64": "voz", "/v1/voice": "voz", "/v1/photo": "foto",
                 "/v1/meeting_b64": "reuniao"}


def _path() -> str:
    import os
    return os.path.join(config.DATA_DIR, "metrics.db")


def db() -> sqlite3.Connection:
    p = _path()
    if p not in _ready:
        with _init_lock:
            if p not in _ready:
                import os
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with sqlite3.connect(p) as c:
                    c.executescript("""
                        CREATE TABLE IF NOT EXISTS requests (ts REAL NOT NULL, user_id TEXT, path TEXT, kind TEXT,
                            status INTEGER, ms INTEGER);
                        CREATE INDEX IF NOT EXISTS requests_ts ON requests(ts);
                        CREATE TABLE IF NOT EXISTS tasks (ts REAL NOT NULL, user_id TEXT, kind TEXT, ok INTEGER,
                            tools INTEGER, tool_errors INTEGER, ms INTEGER);
                        CREATE INDEX IF NOT EXISTS tasks_ts ON tasks(ts);
                        CREATE TABLE IF NOT EXISTS errors (ts REAL NOT NULL, path TEXT, status INTEGER, detail TEXT);
                        CREATE TABLE IF NOT EXISTS feedback (ts REAL NOT NULL, user_id TEXT, value INTEGER, area TEXT);
                        CREATE TABLE IF NOT EXISTS nps (ts REAL NOT NULL, user_id TEXT, score INTEGER, comment TEXT);
                        CREATE TABLE IF NOT EXISTS staff (email TEXT PRIMARY KEY, role TEXT NOT NULL, added_by TEXT,
                            created_at TEXT NOT NULL);
                        CREATE TABLE IF NOT EXISTS admin_sessions (hash TEXT PRIMARY KEY, email TEXT, role TEXT,
                            expires REAL NOT NULL);
                        CREATE TABLE IF NOT EXISTS panel_codes (hash TEXT PRIMARY KEY, email TEXT, role TEXT,
                            expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
                        CREATE TABLE IF NOT EXISTS audit (ts REAL NOT NULL, email TEXT, action TEXT, target TEXT);
                        CREATE TABLE IF NOT EXISTS client_info (user_id TEXT PRIMARY KEY, caps TEXT, ts REAL NOT NULL);
                        CREATE TABLE IF NOT EXISTS stages (ts REAL NOT NULL, stage TEXT NOT NULL, ms INTEGER NOT NULL);
                        CREATE INDEX IF NOT EXISTS stages_ts ON stages(ts);
                    """)
                _ready.add(p)
    c = sqlite3.connect(p, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def norm_path(path: str) -> str:
    """/v1/meetings/12 -> /v1/meetings/:id (o painel agrupa sem guardar ids, códigos nem links públicos)."""
    p = re.sub(r"^/(book|r)/[^/]+", r"/\1/:id", path or "")
    return re.sub(r"/(\d+|[0-9a-f]{8,}|[A-Za-z0-9_-]{20,})(?=/|$)", "/:id", p)[:120]


def flush() -> None:
    """Grava o que está na fila (o painel chama antes de ler; um processo de fundo chama a cada segundo)."""
    with _qlock:
        rows, _queue[:] = list(_queue), []
    if not rows:
        return
    try:
        with db() as c:
            for sql, args in rows:
                c.execute(sql, args)
    except sqlite3.Error:
        pass


def _writer():
    while True:
        time.sleep(1)
        flush()


threading.Thread(target=_writer, daemon=True, name="fidus-metrics").start()


def _enqueue(sql: str, args: tuple) -> None:
    with _qlock:
        if len(_queue) < 50_000:
            _queue.append((sql, args))


def record_request(user_id: str | None, path: str, status: int, ms: int, add_error: bool = True) -> None:
    if not user_id and status < 500:
        return  # chamadas sem conta (robôs, páginas públicas) só contam quando dão erro do servidor
    p = norm_path(path)
    _enqueue("INSERT INTO requests(ts,user_id,path,kind,status,ms) VALUES(?,?,?,?,?,?)",
             (time.time(), user_id, p, REQUEST_KINDS.get(p, "outro"), status, ms))
    if status >= 500 and add_error:
        _enqueue("INSERT INTO errors(ts,path,status,detail) VALUES(?,?,?,?)", (time.time(), p, status, ""))


def error_detail(e: BaseException) -> str:
    """Só o tipo do erro e onde aconteceu (arquivo:linha). Nunca a mensagem, que pode trazer dados do cliente."""
    import traceback
    tb = traceback.extract_tb(e.__traceback__)
    ours = [f for f in tb if "/app/" in f.filename.replace("\\", "/")] or tb
    where = f"{ours[-1].filename.rsplit('/', 1)[-1]}:{ours[-1].lineno}" if ours else ""
    return f"{type(e).__name__} {where}".strip()


def record_error(path: str, detail: str) -> None:
    _enqueue("INSERT INTO errors(ts,path,status,detail) VALUES(?,?,?,?)", (time.time(), norm_path(path), 500, (detail or "")[:200]))


def record_task(user_id: str | None, kind: str, ok: bool, tools: int = 0, tool_errors: int = 0, ms: int = 0) -> None:
    """Pedido ao Fidus terminou: deu certo (respondeu sem cair no 'não consegui') ou não."""
    _enqueue("INSERT INTO tasks(ts,user_id,kind,ok,tools,tool_errors,ms) VALUES(?,?,?,?,?,?,?)",
             (time.time(), user_id, kind, int(ok), tools, tool_errors, ms))


def add_feedback(user_id: str, value: int, area: str = "") -> bool:
    """👍/👎. No máximo 100 por cliente por dia (ninguém distorce o painel sozinho)."""
    with db() as c:
        n = c.execute("SELECT COUNT(*) FROM feedback WHERE user_id=? AND ts>?", (user_id, time.time() - 86400)).fetchone()[0]
        if n >= 100:
            return False
        c.execute("INSERT INTO feedback(ts,user_id,value,area) VALUES(?,?,?,?)", (time.time(), user_id, 1 if value > 0 else -1,
                                                                                  (area or "")[:30]))
    return True


def add_nps(user_id: str, score: int, comment: str = "") -> bool:
    """Nota de 0 a 10: uma por cliente a cada 30 dias."""
    with db() as c:
        last = c.execute("SELECT MAX(ts) FROM nps WHERE user_id=?", (user_id,)).fetchone()[0]
        if last and time.time() - last < 30 * 86400:
            return False
        c.execute("INSERT INTO nps(ts,user_id,score,comment) VALUES(?,?,?,?)", (time.time(), user_id, max(0, min(10, score)),
                                                                               (comment or "")[:500]))
    return True


def nps_due(user_id: str, created_at: str | None) -> bool:
    """Pergunta a nota (0 a 10) depois de 7 dias de conta e no máximo uma vez a cada 30 dias."""
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(created_at or "")
    except ValueError:
        return False
    if age < timedelta(days=7):
        return False
    flush()
    with db() as c:
        last = c.execute("SELECT MAX(ts) FROM nps WHERE user_id=?", (user_id,)).fetchone()[0]
        used = c.execute("SELECT COUNT(*) FROM tasks WHERE user_id=?", (user_id,)).fetchone()[0]
    return used >= 5 and (not last or time.time() - last > 30 * 86400)


def record_stage(stage: str, ms: int) -> None:
    """Tempo de cada etapa (transcricao, ia, voz): mostra no painel onde a voz demora."""
    _enqueue("INSERT INTO stages(ts,stage,ms) VALUES(?,?,?)", (time.time(), stage[:20], int(ms)))


def stage_p50(hours: int = 24) -> dict:
    flush()
    out = {}
    with db() as c:
        for st in ("transcricao", "ia", "voz"):
            vals = [r[0] for r in c.execute("SELECT ms FROM stages WHERE stage=? AND ts>? ORDER BY ms",
                                             (st, time.time() - hours * 3600))]
            out[st] = {"p50": vals[len(vals) // 2] if vals else None, "n": len(vals)}
    return out


def set_client(user_id: str, caps: str) -> None:
    """O que o app do cliente tem (APK com transcrição no celular, voz, versão): para o painel e para o suporte."""
    import re as _re
    caps = _re.sub(r"[^\w=,.:-]", "", caps or "")[:200]
    if caps:
        _enqueue("INSERT INTO client_info(user_id,caps,ts) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                 "caps=excluded.caps, ts=excluded.ts", (user_id, caps, time.time()))


def client_caps() -> dict:
    with db() as c:
        return {r["user_id"]: {"caps": r["caps"], "ts": r["ts"]} for r in c.execute("SELECT * FROM client_info")}


def purge_old() -> None:
    limit = time.time() - KEEP_DAYS * 86400
    with db() as c:
        for t in ("requests", "tasks", "errors", "stages"):
            c.execute(f"DELETE FROM {t} WHERE ts<?", (limit,))
        c.execute("DELETE FROM admin_sessions WHERE expires<?", (time.time(),))
        c.execute("DELETE FROM panel_codes WHERE expires<?", (time.time(),))


class Middleware:
    """Mede cada chamada da API (tempo e resultado). Fica DENTRO do UserContext para saber de quem é o pedido."""

    def __init__(self, app_):
        self.app = app_

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith(("/v1/", "/book/", "/auth/")):
            return await self.app(scope, receive, send)
        from . import store
        t0 = time.time()
        status = {"code": 500, "crashed": False}

        async def _send(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            await send(msg)
        try:
            await self.app(scope, receive, _send)
        except Exception as e:
            status["crashed"] = True
            record_error(scope.get("path", ""), error_detail(e))
            raise
        finally:
            u = store.CURRENT.get()
            record_request(u["id"] if u else None, scope.get("path", ""), status["code"], int((time.time() - t0) * 1000),
                           add_error=not status["crashed"])
