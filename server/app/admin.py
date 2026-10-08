"""Painel da empresa (/admin): saúde do sistema, HEART, negócio, clientes e equipe.

Entrada: no app, menu › "Painel da empresa" gera um código de 8 letras (5 minutos, uso único); no computador,
/admin pede o código e abre uma sessão de 12 h (cookie HttpOnly, Secure, SameSite=Strict). Não precisa de senha
nem de mais nada no Google.

Papéis: owner (o dono) e admin veem e mudam tudo; support vê sistema, HEART e clientes; finance vê negócio e
clientes. NINGUÉM da equipe vê conversas, e-mails, gastos ou documentos de clientes: o painel só mostra números.
Tudo o que a equipe faz fica no registro de auditoria.
"""
import hashlib
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import accounts, backup, config, google_client, metrics, plans, store

router = APIRouter()
SESSION_TTL = 12 * 3600
CODE_TTL = 300
ROLES = ("admin", "support", "finance")
SCREENS = {"owner": {"system", "heart", "business", "clients", "team"}, "admin": {"system", "heart", "business", "clients", "team"},
           "support": {"system", "heart", "clients"}, "finance": {"business", "clients"}}
FX_TO_USD = {"USD": 1.0, "GBP": 1.27, "EUR": 1.08}  # aproximado, só para estimar margem no painel
_tries: dict = {}


def _h(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


def audit(email: str | None, action: str, target: str = "") -> None:
    with metrics.db() as c:
        c.execute("INSERT INTO audit(ts,email,action,target) VALUES(?,?,?,?)", (time.time(), email or "?", action, target[:200]))


# ---------- quem é da equipe ----------
def role_for(user: dict) -> str | None:
    if user.get("is_owner") or user.get("id") == store.OWNER_ID:
        return "owner"
    email = (user.get("email") or "").lower()
    if not email:
        return None
    with metrics.db() as c:
        r = c.execute("SELECT role FROM staff WHERE email=?", (email,)).fetchone()
    return r["role"] if r else None


def new_panel_code(user: dict) -> dict:
    role = role_for(user)
    if not role:
        raise HTTPException(403, "só para a equipe")
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    email = config.OWNER_EMAIL if role == "owner" else (user.get("email") or "").lower()
    with metrics.db() as c:
        c.execute("INSERT INTO panel_codes(hash,email,role,expires) VALUES(?,?,?,?)",
                  (_h(code), email or "dono", role, time.time() + CODE_TTL))
    return {"code": code, "url": f"{config.PUBLIC_BASE_URL.rstrip('/')}/admin", "expires_in": CODE_TTL, "role": role}


class Session(dict):
    pass


def session(request: Request) -> Session:
    tok = request.cookies.get("fidus_admin", "")
    if not tok:
        raise HTTPException(401, "entre com o código do app")
    with metrics.db() as c:
        r = c.execute("SELECT * FROM admin_sessions WHERE hash=? AND expires>?", (_h(tok), time.time())).fetchone()
        if not r:
            raise HTTPException(401, "sessão expirada")
        role = r["role"]
        if role != "owner":  # papel pode ter mudado ou sido removido
            st = c.execute("SELECT role FROM staff WHERE email=?", (r["email"],)).fetchone()
            if not st:
                c.execute("DELETE FROM admin_sessions WHERE hash=?", (_h(tok),))
                raise HTTPException(401, "acesso removido")
            role = st["role"]
    if request.method != "GET" and request.headers.get("x-fidus-admin") != "1":
        raise HTTPException(403, "pedido inválido")  # bloqueia formulários de outros sites
    return Session(email=r["email"], role=role)


def need(screen: str):
    def dep(s: Session = Depends(session)) -> Session:
        if screen not in SCREENS.get(s["role"], set()):
            raise HTTPException(403, "seu papel não vê esta tela")
        return s
    return dep


def manager(s: Session = Depends(session)) -> Session:
    if s["role"] not in ("owner", "admin"):
        raise HTTPException(403, "só administradores")
    return s


# ---------- entrar e sair ----------
class CodeIn(BaseModel):
    code: str


def _ip(request: Request) -> str:
    """IP real do visitante: atrás do Nginx/Docker, o X-Real-IP só vale se quem conecta é a rede interna."""
    import ipaddress
    peer = request.client.host if request.client else "?"
    try:
        a = ipaddress.ip_address(peer)
        trusted = a.is_loopback or a in ipaddress.ip_network("172.16.0.0/12")
    except ValueError:
        trusted = False
    return (request.headers.get("x-real-ip") if trusted else None) or peer


@router.post("/admin/api/login")
def login(body: CodeIn, request: Request):
    ip = _ip(request)
    now = time.time()
    if len(_tries) > 5000:
        for k in [k for k, v in _tries.items() if not v or now - v[-1] > 900]:
            _tries.pop(k, None)
    _tries[ip] = [t for t in _tries.get(ip, []) if now - t < 900]
    if len(_tries[ip]) >= 10:
        raise HTTPException(429, "muitas tentativas, espere 15 minutos")
    code = "".join(ch for ch in body.code.upper() if ch.isalnum())
    with metrics.db() as c:
        r = c.execute("SELECT * FROM panel_codes WHERE hash=? AND used=0 AND expires>?", (_h(code), now)).fetchone()
        if not r or c.execute("UPDATE panel_codes SET used=1 WHERE hash=? AND used=0", (_h(code),)).rowcount != 1:
            _tries[ip].append(now)
            raise HTTPException(400, "código inválido ou expirado")
        tok = secrets.token_urlsafe(32)
        c.execute("INSERT INTO admin_sessions(hash,email,role,expires) VALUES(?,?,?,?)",
                  (_h(tok), r["email"], r["role"], now + SESSION_TTL))
    audit(r["email"], "login", r["role"])
    resp = JSONResponse({"ok": True, "role": r["role"], "email": r["email"]})
    resp.set_cookie("fidus_admin", tok, max_age=SESSION_TTL, httponly=True, samesite="strict",
                    secure=config.PUBLIC_BASE_URL.startswith("https"), path="/admin")
    return resp


@router.post("/admin/api/logout")
def logout(request: Request, s: Session = Depends(session)):
    with metrics.db() as c:
        c.execute("DELETE FROM admin_sessions WHERE hash=?", (_h(request.cookies.get("fidus_admin", "")),))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("fidus_admin", path="/admin")
    return resp


@router.get("/admin/api/me")
def me(s: Session = Depends(session)):
    return {"email": s["email"], "role": s["role"], "screens": sorted(SCREENS.get(s["role"], set()))}


# ---------- dados dos clientes (só números) ----------
def _users() -> list[dict]:
    metrics.flush()
    return [u for u in accounts.list_users() if u["status"] != "apagado"]


def _per_user() -> list[dict]:
    out = []
    month = datetime.now(timezone.utc).date().replace(day=1).isoformat()
    for u in _users():
        with store.as_user(accounts.user_ctx(u)):
            try:
                prof = store.profile()
                plan = plans.current()
                cur = plans.currency_for(prof.get("country"))
                out.append({"id": u["id"], "email": u.get("email") or (config.OWNER_EMAIL if u["id"] == store.OWNER_ID else ""),
                            "name": u.get("name"), "status": u["status"], "created_at": u["created_at"],
                            "last_seen": u.get("last_seen"), "is_owner": u["id"] == store.OWNER_ID, "plan": plan,
                            "plan_name": plans.PLANS[plan]["name"], "currency": cur, "price": plans.price(plan, cur),
                            "google": google_client.is_connected(), "subscription": store.kv_get("subscription") or "",
                            "ai_cost_month": store.usage_cost(month), "language": prof.get("language") or "",
                            "country": prof.get("country") or "",
                            "drafts": {r["status"]: r["n"] for r in store.select(
                                "SELECT status, COUNT(*) n FROM pending_actions GROUP BY status")},
                            "undone": store.select("SELECT COUNT(*) n FROM activities WHERE status='desfeito'")[0]["n"]})
            except Exception:  # noqa: BLE001 - um banco com problema não derruba o painel
                continue
    return out


def _since(days: float) -> float:
    return time.time() - days * 86400


def _pct(a: float, b: float) -> float | None:
    return round(100.0 * a / b, 1) if b else None


def _percentile(vals: list[int], p: float) -> int | None:
    if not vals:
        return None
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(round(p / 100 * (len(vals) - 1))))]


def _days(n: int) -> list[str]:
    today = datetime.now(timezone.utc).date()
    return [(today - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()


@router.get("/admin/api/system")
def system(s: Session = Depends(need("system"))):
    import shutil
    metrics.flush()
    with metrics.db() as c:
        req = c.execute("SELECT ts, kind, status, ms FROM requests WHERE ts>?", (_since(14),)).fetchall()
        errs = c.execute("SELECT ts, path, status, detail FROM errors ORDER BY ts DESC LIMIT 25").fetchall()
        failed = c.execute("SELECT COUNT(*) FROM tasks WHERE ts>? AND ok=0", (_since(1),)).fetchone()[0]
        tasks24 = c.execute("SELECT COUNT(*) FROM tasks WHERE ts>?", (_since(1),)).fetchone()[0]
    last24 = [r for r in req if r["ts"] > _since(1)]
    asks = [r["ms"] for r in last24 if r["kind"] != "outro"]
    series = []
    for d in _days(14):
        day = [r for r in req if _day(r["ts"]) == d]
        series.append({"day": d, "requests": sum(1 for r in day if r["kind"] != "outro"),
                       "errors": sum(1 for r in day if r["status"] >= 500),
                       "p95_ms": _percentile([r["ms"] for r in day if r["kind"] != "outro"], 95)})
    try:
        free = round(shutil.disk_usage(config.DATA_DIR).free / 1e9, 1)
    except OSError:
        free = None
    users = _per_user()
    age = backup.age_hours()
    problems = []
    if age is not None and age > 36:
        problems.append("backup_late")
    if backup.last() and not backup.last().get("ok"):
        problems.append("backup_failed")
    if free is not None and free < 2:
        problems.append("disk_low")
    if last24 and _pct(sum(1 for r in last24 if r["status"] >= 500), len(last24)) > 5:
        problems.append("errors_high")
    if tasks24 >= 10 and _pct(failed, tasks24) > 10:
        problems.append("tasks_failing")
    return {"ok": not problems, "problems": problems, "uptime_s": int(time.time() - metrics.STARTED),
            "version": "0.9.7", "llm": config.LLM_PROVIDER, "model": config.LLM_MODEL,
            "backup": {"age_hours": round(age, 1) if age is not None else None, **backup.last()},
            "disk_free_gb": free, "requests_24h": len(last24), "asks_24h": len(asks),
            "errors_24h": sum(1 for r in last24 if r["status"] >= 500),
            "error_rate_24h": _pct(sum(1 for r in last24 if r["status"] >= 500), len(last24)),
            "p50_ms": _percentile(asks, 50), "p95_ms": _percentile(asks, 95),
            "tasks_failed_24h": failed, "tasks_24h": tasks24,
            "google_connected": sum(1 for u in users if u["google"]), "accounts": len(users),
            "ai_cost_today_usd": round(sum(_today_cost(u["id"]) for u in _users()), 2),
            "series": series,
            "recent_errors": [{"ts": e["ts"], "path": e["path"], "status": e["status"], "detail": e["detail"]} for e in errs]}


def _today_cost(uid: str) -> float:
    u = accounts.get_user(uid)
    with store.as_user(accounts.user_ctx(u)):
        try:
            return store.usage_cost(datetime.now(timezone.utc).date().isoformat())
        except Exception:  # noqa: BLE001
            return 0.0


@router.get("/admin/api/heart")
def heart(s: Session = Depends(need("heart"))):
    users = [u for u in _per_user() if not u["is_owner"]]
    ids = {u["id"] for u in users}
    with metrics.db() as c:
        tasks = [dict(r) for r in c.execute("SELECT ts, user_id, kind, ok FROM tasks WHERE ts>?", (_since(90),)).fetchall()]
        first = {r["user_id"]: r["first"] for r in c.execute("SELECT user_id, MIN(ts) first FROM tasks GROUP BY user_id")}
        counts = {r["user_id"]: r["n"] for r in c.execute("SELECT user_id, COUNT(*) n FROM tasks GROUP BY user_id")}
        fb = c.execute("SELECT value, COUNT(*) n FROM feedback WHERE ts>? GROUP BY value", (_since(30),)).fetchall()
        nps_rows = c.execute("SELECT score, comment, ts FROM nps WHERE ts>? ORDER BY ts DESC", (_since(90),)).fetchall()
    tasks = [t for t in tasks if t["user_id"] in ids]
    up = sum(r["n"] for r in fb if r["value"] > 0)
    down = sum(r["n"] for r in fb if r["value"] < 0)
    scores = [r["score"] for r in nps_rows]
    prom, det = sum(1 for x in scores if x >= 9), sum(1 for x in scores if x <= 6)

    def active(days: float) -> set:
        return {t["user_id"] for t in tasks if t["ts"] > _since(days)}
    now = datetime.now(timezone.utc)

    def created(u):
        try:
            return datetime.fromisoformat(u["created_at"])
        except (TypeError, ValueError):
            return now
    old7 = [u for u in users if now - created(u) >= timedelta(days=7)]
    old30 = [u for u in users if now - created(u) >= timedelta(days=30)]
    a7, a30 = active(7), active(30)
    t30 = [t for t in tasks if t["ts"] > _since(30)]
    by_kind: dict = {}
    for t in t30:
        k = by_kind.setdefault(t["kind"], {"n": 0, "ok": 0})
        k["n"] += 1
        k["ok"] += t["ok"]
    last_task = {}
    for t in tasks:
        last_task[t["user_id"]] = max(last_task.get(t["user_id"], 0), t["ts"])
    at_risk = [{"email": u["email"], "plan": u["plan_name"], "last_task": last_task.get(u["id"])}
               for u in users if u["id"] in first and last_task.get(u["id"], 0) < _since(7)]
    sent = sum(u["drafts"].get("sent", 0) for u in users)
    cancelled = sum(u["drafts"].get("cancelled", 0) for u in users)
    series = []
    for d in _days(30):
        day = [t for t in tasks if _day(t["ts"]) == d]
        series.append({"day": d, "active": len({t["user_id"] for t in day}),
                       "success": _pct(sum(t["ok"] for t in day), len(day))})
    return {
        "happiness": {"thumbs_up": up, "thumbs_down": down, "positive_pct": _pct(up, up + down),
                      "nps": round(100 * (prom - det) / len(scores)) if scores else None, "nps_answers": len(scores),
                      "promoters": prom, "passives": len(scores) - prom - det, "detractors": det,
                      "comments": [{"score": r["score"], "comment": r["comment"], "ts": r["ts"]} for r in nps_rows if r["comment"]][:10]},
        "engagement": {"dau": len(active(1)), "wau": len(a7), "mau": len(a30),
                       "asks_per_active_day": round(len(t30) / max(1, sum(x["active"] for x in series)), 1),
                       "by_kind": by_kind},
        "adoption": {"accounts": len(users), "new_30d": sum(1 for u in users if now - created(u) <= timedelta(days=30)),
                     "google_connected": sum(1 for u in users if u["google"]),
                     "first_ask": sum(1 for u in users if u["id"] in first),
                     "five_asks": sum(1 for u in users if counts.get(u["id"], 0) >= 5)},
        "retention": {"d7_pct": _pct(sum(1 for u in old7 if u["id"] in a7), len(old7)), "d7_base": len(old7),
                      "d30_pct": _pct(sum(1 for u in old30 if u["id"] in a30), len(old30)), "d30_base": len(old30),
                      "at_risk": at_risk[:20]},
        "task_success": {"ok_pct_30d": _pct(sum(t["ok"] for t in t30), len(t30)), "asks_30d": len(t30),
                         "drafts_sent": sent, "drafts_discarded": cancelled,
                         "undone": sum(u["undone"] for u in users)},
        "series": series,
    }


@router.get("/admin/api/business")
def business(s: Session = Depends(need("business"))):
    users = [u for u in _per_user() if not u["is_owner"]]
    mrr: dict = {}
    by_plan: dict = {}
    for u in users:
        by_plan[u["plan"]] = by_plan.get(u["plan"], 0) + 1
        if not u["subscription"].startswith(("expirada",)):
            mrr[u["currency"]] = round(mrr.get(u["currency"], 0) + u["price"], 2)
    subs: dict = {}
    for u in users:
        k = (u["subscription"] or "sem_assinatura").split(":")[0]
        subs[k] = subs.get(k, 0) + 1
    with accounts._db() as c:
        refs = c.execute("SELECT COUNT(*) n, COUNT(paid_at) paid FROM referrals").fetchone()
        deleted = c.execute("SELECT COUNT(*) FROM users WHERE status='apagado'").fetchone()[0]
    rows = []
    for u in users:
        price_usd = u["price"] * FX_TO_USD.get(u["currency"], 1)
        rows.append({"email": u["email"], "plan": u["plan_name"], "price": u["price"], "currency": u["currency"],
                     "ai_cost_month_usd": round(u["ai_cost_month"], 2),
                     "ai_cost_pct": _pct(u["ai_cost_month"], price_usd), "subscription": u["subscription"]})
    rows.sort(key=lambda r: r["ai_cost_month_usd"], reverse=True)
    total_cost = round(sum(u["ai_cost_month"] for u in _per_user()), 2)
    mrr_usd = round(sum(v * FX_TO_USD.get(k, 1) for k, v in mrr.items()), 2)
    return {"mrr_by_currency": mrr, "mrr_usd_estimate": mrr_usd, "plans": by_plan, "subscriptions": subs,
            "ai_cost_month_usd": total_cost, "ai_cost_pct_of_mrr": _pct(total_cost, mrr_usd),
            "referrals": {"invited": refs["n"], "paid": refs["paid"]}, "deleted_accounts": deleted,
            "fair_use_daily_usd": config.FAIR_USE_DAILY_USD, "clients": rows[:50],
            "note": "MRR estimado pelos planos atribuídos até a cobrança pela loja estar ligada; câmbio aproximado."}


@router.get("/admin/api/clients")
def clients(s: Session = Depends(need("clients"))):
    metrics.flush()
    audit(s["email"], "clients.view")
    with metrics.db() as c:
        last = {r["user_id"]: r["last"] for r in c.execute("SELECT user_id, MAX(ts) last FROM tasks GROUP BY user_id")}
        n30 = {r["user_id"]: r["n"] for r in c.execute("SELECT user_id, COUNT(*) n FROM tasks WHERE ts>? GROUP BY user_id",
                                                        (_since(30),))}
    finance = s["role"] in ("owner", "admin", "finance")
    caps = metrics.client_caps()
    out = []
    for u in _per_user():
        flags = []
        if not u["google"]:
            flags.append("no_google")
        if u["id"] in last and last[u["id"]] < _since(7):
            flags.append("inactive_7d")
        sw = accounts.device_switches(u["id"])
        if sw > 2:
            flags.append("device_switching")
        row = {"id": u["id"], "email": u["email"], "name": u["name"], "plan": u["plan"], "plan_name": u["plan_name"],
               "status": u["status"], "created_at": u["created_at"], "last_ask": last.get(u["id"]),
               "asks_30d": n30.get(u["id"], 0), "google": u["google"], "device_switches_30d": sw,
               "language": u["language"], "country": u["country"], "is_owner": u["is_owner"], "flags": flags,
               "app": (caps.get(u["id"]) or {}).get("caps")}
        if finance:
            row.update({"price": u["price"], "currency": u["currency"], "ai_cost_month_usd": round(u["ai_cost_month"], 2),
                        "subscription": u["subscription"]})
        out.append(row)
    return {"clients": out, "can_manage": s["role"] in ("owner", "admin")}


class PlanIn(BaseModel):
    plan: str


@router.post("/admin/api/clients/{uid}/plan")
def set_plan(uid: str, body: PlanIn, s: Session = Depends(manager)):
    if uid == store.OWNER_ID and s["role"] != "owner":
        raise HTTPException(403, "o plano do dono só muda pelo dono")
    u = accounts.get_user(uid)
    if not u or body.plan not in plans.PLANS or u["status"] == "apagado":
        raise HTTPException(400, "cliente ou plano inválido")
    with store.as_user(accounts.user_ctx(u)):
        plans.set_plan(body.plan)
    audit(s["email"], "client.plan", f"{u.get('email')} -> {body.plan}")
    return {"ok": True}


class StatusIn(BaseModel):
    status: str


@router.post("/admin/api/clients/{uid}/status")
def set_status(uid: str, body: StatusIn, s: Session = Depends(manager)):
    if uid == store.OWNER_ID or body.status not in ("ativo", "suspenso"):
        raise HTTPException(400, "inválido")
    u = accounts.get_user(uid)
    if not u or u["status"] == "apagado":
        raise HTTPException(404, "cliente não encontrado")
    accounts.set_status(uid, body.status)
    audit(s["email"], "client.status", f"{u.get('email')} -> {body.status}")
    return {"ok": True}


# ---------- equipe ----------
@router.get("/admin/api/team")
def team(s: Session = Depends(manager)):
    with metrics.db() as c:
        staff = [dict(r) for r in c.execute("SELECT email, role, added_by, created_at FROM staff ORDER BY created_at")]
        log = [dict(r) for r in c.execute("SELECT ts, email, action, target FROM audit ORDER BY ts DESC LIMIT 100")]
    return {"staff": staff, "audit": log, "owner": config.OWNER_EMAIL}


class StaffIn(BaseModel):
    email: str
    role: str


@router.post("/admin/api/team")
def add_staff(body: StaffIn, s: Session = Depends(manager)):
    email = body.email.strip().lower()
    if "@" not in email or body.role not in ROLES:
        raise HTTPException(400, "e-mail ou papel inválido")
    if body.role == "admin" and s["role"] != "owner":
        raise HTTPException(403, "só o dono adiciona administradores")
    if config.OWNER_EMAIL and email == config.OWNER_EMAIL:
        raise HTTPException(400, "o dono já tem acesso total")
    with metrics.db() as c:
        cur = c.execute("SELECT role FROM staff WHERE email=?", (email,)).fetchone()
        if cur and cur["role"] == "admin" and s["role"] != "owner":
            raise HTTPException(403, "só o dono muda o papel de um administrador")
        c.execute("INSERT INTO staff(email,role,added_by,created_at) VALUES(?,?,?,?) "
                  "ON CONFLICT(email) DO UPDATE SET role=excluded.role", (email, body.role, s["email"], store.now()))
    if not accounts.by_email(email):
        accounts.invite(email, "essencial")  # a pessoa entra no app com esse Google para pegar o código do painel
    audit(s["email"], "team.add", f"{email} ({body.role})")
    return {"ok": True}


@router.delete("/admin/api/team/{email}")
def remove_staff(email: str, s: Session = Depends(manager)):
    email = email.strip().lower()
    with metrics.db() as c:
        row = c.execute("SELECT role FROM staff WHERE email=?", (email,)).fetchone()
        if not row:
            raise HTTPException(404, "não está na equipe")
        if row["role"] == "admin" and s["role"] != "owner":
            raise HTTPException(403, "só o dono remove administradores")
        c.execute("DELETE FROM staff WHERE email=?", (email,))
        c.execute("DELETE FROM admin_sessions WHERE email=?", (email,))
    audit(s["email"], "team.remove", email)
    return {"ok": True}


@router.post("/admin/api/backup")
def run_backup(s: Session = Depends(manager)):
    audit(s["email"], "backup.run")
    return backup.run()


# ---------- a página ----------
@router.get("/admin", response_class=HTMLResponse)
def page():
    with open(os.path.join(os.path.dirname(__file__), "admin.html"), encoding="utf-8") as f:
        html = f.read()
    return HTMLResponse(html, headers={
        "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                                   "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})
