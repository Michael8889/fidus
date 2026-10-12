"""Portal do contabilista (/contabilista): despesas, faturas e exportação dos clientes que lhe deram acesso.

Só leitura. Entra com código de 6 números por e-mail; a sessão fica num cookie só deste caminho. Cada pedido confere
de novo se o cliente ainda dá acesso e se o plano dele ainda inclui o recurso.
"""
import calendar
import os
import shutil
import tempfile
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from . import accounts, config, plans, portugal, site_forms, store, team

router = APIRouter()
COOKIE = "fidus_cont"


def _secure() -> bool:
    return (config.PUBLIC_BASE_URL or "").startswith("https")


def _email(request: Request) -> str:
    e = team.session_email(request.cookies.get(COOKIE, ""))
    if not e:
        raise HTTPException(401, "sessão expirada")
    return e


def _csrf(request: Request) -> None:
    if request.headers.get("x-fidus-cont") != "1":
        raise HTTPException(403, "pedido inválido")


def _client(request: Request, gid: int) -> tuple[dict, dict]:
    email = _email(request)
    g = team.grant(gid, email)
    if not g:
        raise HTTPException(404, "sem acesso a este cliente")
    owner = accounts.get_user(g["owner_id"])
    ctx = accounts.user_ctx(owner)
    with store.as_user(ctx):
        if not plans.allows("accountant_access"):
            raise HTTPException(403, "o plano deste cliente já não inclui o acesso do contabilista")
    team.touch(gid)
    return g, ctx


def _period(month: str = "", date_from: str = "", date_to: str = "") -> tuple[str, str]:
    try:
        if date_from and date_to:
            d0, d1 = date.fromisoformat(date_from), date.fromisoformat(date_to)
        else:
            y, m = (int(x) for x in (month or date.today().strftime("%Y-%m")).split("-"))
            d0, d1 = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
    except ValueError:
        raise HTTPException(400, "período inválido") from None
    if d1 < d0 or (d1 - d0).days > 400:
        raise HTTPException(400, "período inválido")
    return d0.isoformat(), d1.isoformat()


class StartIn(BaseModel):
    email: str


class LoginIn(BaseModel):
    email: str
    code: str


@router.post("/contabilista/api/start")
def start(body: StartIn, request: Request):
    _csrf(request)
    ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "?")
    if site_forms.limited("cont", ip, 10):
        raise HTTPException(429, "muitas tentativas")
    team.start_login(body.email)
    return {"ok": True}  # igual para todos: não revela quem tem acesso


@router.post("/contabilista/api/login")
def login(body: LoginIn, request: Request):
    _csrf(request)
    token = team.verify_login(body.email, body.code)
    if not token:
        raise HTTPException(400, "código inválido ou expirado")
    resp = JSONResponse({"ok": True})
    resp.set_cookie(COOKIE, token, max_age=team.SESSION_TTL, httponly=True, samesite="strict", secure=_secure(),
                    path="/contabilista")
    return resp


@router.post("/contabilista/api/logout")
def logout(request: Request):
    _csrf(request)
    team.end_session(request.cookies.get(COOKIE, ""))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/contabilista")
    return resp


@router.get("/contabilista/api/me")
def me(request: Request):
    email = _email(request)
    return {"email": email, "clients": [{"id": g["id"], "name": g["name"] or g["email"], "email": g["email"],
                                         "since": g["created_at"]} for g in team.grants_for(email)]}


@router.get("/contabilista/api/c/{gid}/expenses")
def expenses(gid: int, request: Request, month: str = "", date_from: str = "", date_to: str = "", wallet: str = ""):
    g, ctx = _client(request, gid)
    d0, d1 = _period(month, date_from, date_to)
    with store.as_user(ctx):
        rows = store.query_expenses(d0, d1, business=wallet[:40] or None, limit=10000)
        rows = sorted(rows, key=lambda r: (r["date"], r["id"]))
        pt = portugal.is_portugal()
        wallets = [{"name": w["name"], "currency": w.get("currency")} for w in store.wallets()]
    totals: dict = {}
    vat: dict = {}
    by_cat: dict = {}
    by_irs: dict = {}
    no_nif = 0
    out = []
    for r in rows:
        cur = r["currency"]
        totals[cur] = round(totals.get(cur, 0) + r["amount"], 2)
        vat[cur] = round(vat.get(cur, 0) + (r["vat"] or 0), 2)
        by_cat.setdefault(r["category"], {}).setdefault(cur, 0)
        by_cat[r["category"]][cur] = round(by_cat[r["category"]][cur] + r["amount"], 2)
        if pt and cur == "EUR":
            k = r.get("irs_category") or "sem_categoria"
            by_irs[k] = round(by_irs.get(k, 0) + r["amount"], 2)
            if not r.get("buyer_nif"):
                no_nif += 1
        out.append({"id": r["id"], "date": r["date"], "merchant": r["merchant"] or "", "category": r["category"],
                    "wallet": r["business"], "amount": r["amount"], "currency": cur, "vat": r["vat"],
                    "supplier_nif": r.get("supplier_nif") or "", "buyer_nif": r.get("buyer_nif") or "",
                    "irs_category": portugal.IRS_CATEGORIES.get(r.get("irs_category") or "", ""),
                    "note": r["note"] or "", "receipt": bool(r.get("receipt_path") and os.path.exists(r["receipt_path"]))})
    return {"client": {"id": g["id"], "name": g["name"] or g["email"]}, "from": d0, "to": d1, "wallet": wallet or None,
            "wallets": wallets, "count": len(out), "totals": totals, "vat": vat, "by_category": by_cat,
            "portugal": pt, "by_irs": {portugal.IRS_CATEGORIES.get(k, "Sem categoria do e-Fatura"): v for k, v in by_irs.items()},
            "invoices_without_nif": no_nif, "expenses": out}


@router.get("/contabilista/api/c/{gid}/receipt/{eid}")
def receipt(gid: int, eid: int, request: Request):
    _g, ctx = _client(request, gid)
    with store.as_user(ctx):
        r = store.select("SELECT receipt_path FROM expenses WHERE id=? AND deleted=0", (int(eid),))
    path = r[0]["receipt_path"] if r else None
    root = os.path.realpath(ctx["receipts"])
    if not path or not os.path.realpath(path).startswith(root + os.sep) or not os.path.exists(path):
        raise HTTPException(404, "recibo não encontrado")
    return FileResponse(path, headers={"Cache-Control": "private, no-store"})


@router.get("/contabilista/api/c/{gid}/export")
def export(gid: int, request: Request, month: str = "", date_from: str = "", date_to: str = "", wallet: str = ""):
    from . import features
    _g, ctx = _client(request, gid)
    d0, d1 = _period(month, date_from, date_to)
    tmp = tempfile.mkdtemp(prefix="fidus-cont-")
    with store.as_user(ctx):
        r = features.build_export(d0, d1, wallet[:40] or None, folder=tmp)
    if not r.get("ok"):
        shutil.rmtree(tmp, ignore_errors=True)
        raise HTTPException(400, r.get("error") or "sem dados")
    return FileResponse(r["path"], filename=r["name"], media_type="application/zip",
                        background=BackgroundTask(shutil.rmtree, tmp, True))


@router.get("/contabilista", response_class=HTMLResponse)
def page():
    with open(os.path.join(os.path.dirname(__file__), "accountant.html"), encoding="utf-8") as f:
        html = f.read()
    return HTMLResponse(html, headers={
        "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                                   "img-src 'self' data: blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})
