"""API do Fidus."""
import html
import os
import tempfile

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

from . import accounts, agent, booking, config, features, google_client, meetings, plans, store, tools

app = FastAPI(title="Fidus API", version="0.7.0", docs_url=None, redoc_url=None, openapi_url=None)  # não expõe o mapa da API
store.init_db()
accounts.init()
if config.APP_TOKEN in ("", "troque-este-token") and not config.PUBLIC_BASE_URL.startswith(("http://localhost", "http://127.0.0.1")):
    raise RuntimeError("Defina FIDUS_APP_TOKEN no .env antes de colocar o Fidus na internet.")


class UserContext:
    """Middleware: descobre o cliente pelo token e abre o banco DELE durante a requisição."""

    def __init__(self, app_):
        self.app = app_

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        auth_h = dict(scope.get("headers") or []).get(b"authorization", b"").decode("latin-1")
        user = accounts.user_for_token(auth_h[7:].strip()) if auth_h.startswith("Bearer ") else None
        tok = store.CURRENT.set(accounts.user_ctx(user)) if user else None
        try:
            await self.app(scope, receive, send)
        finally:
            if tok is not None:
                store.CURRENT.reset(tok)


app.add_middleware(UserContext)


def _resume_all_meetings():
    """Na inicialização: retoma atas pela metade e registra os links de agendamento já existentes."""
    for u in accounts.list_users():
        if u["status"] == "ativo":
            with store.as_user(accounts.user_ctx(u)):
                meetings.resume_unfinished()
                if store.kv_get("booking"):
                    booking.settings()


_resume_all_meetings()


def auth():
    if store.CURRENT.get() is None:
        raise HTTPException(401, "token inválido")


def owner_only():
    u = store.CURRENT.get()
    if not u or not u.get("is_owner"):
        raise HTTPException(403, "só o administrador")


class TextIn(BaseModel):
    text: str
    mode: str = ""  # "voice" = modo conversa (resposta curta para ouvir)


class EditIn(BaseModel):
    body: str


@app.get("/health")
def health():
    return {"ok": True, "google_connected": google_client.is_connected(), "llm": config.LLM_PROVIDER}


# ---------- Login e conexão com o Google ----------
def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="pt"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{margin:0;font-family:system-ui,sans-serif;background:#07090D;color:#F2F5F7;display:flex;min-height:100vh;
align-items:center;justify-content:center}}main{{max-width:420px;padding:32px 24px;text-align:center}}
h1{{font-size:26px;margin:0 0 12px}}p{{color:#B7C0CC;line-height:1.5}}.code{{font:700 34px ui-monospace,monospace;
letter-spacing:.12em;background:#11151C;border:1px solid #222A35;border-radius:14px;padding:18px;margin:20px 0;
user-select:all}}a.b{{display:block;background:#3DDC97;color:#07090D;font-weight:800;text-decoration:none;
padding:16px;border-radius:14px;margin-top:8px}}</style></head><body><main>{body}</main></body></html>""")


def _oauth_sig(uid: str, exp: int) -> str:
    import hashlib
    import hmac
    return hmac.new(config.APP_TOKEN.encode(), f"oauth:{uid}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def _start_google(user_id: str | None, app_challenge: str | None = None) -> RedirectResponse:
    import secrets
    url, state, verifier = google_client.auth_url()
    nonce = secrets.token_urlsafe(24)
    accounts.new_pending(verifier, user_id, state, nonce, app_challenge)
    resp = RedirectResponse(url)
    # o retorno do Google só vale no MESMO navegador que começou (impede alguém mandar o próprio login para a vítima)
    resp.set_cookie("fidus_login", nonce, max_age=900, httponly=True, samesite="lax",
                    secure=config.PUBLIC_BASE_URL.startswith("https"), path="/auth/google")
    return resp


@app.get("/auth/google/login")
def google_login(request: Request, cc: str = ""):
    """Entrar / criar conta com o Google (aberto pelo app, que manda `cc` = hash de um segredo só dele)."""
    import re as _re
    _rate_limit(request, 20, "login")
    return _start_google(None, cc.lower() if _re.fullmatch(r"[0-9a-fA-F]{64}", cc or "") else None)


@app.get("/v1/auth/google/link", dependencies=[Depends(auth)])
def google_link():
    """Link de 10 minutos para reconectar o Google do cliente logado."""
    import time
    uid = store.current()["id"]
    exp = int(time.time()) + 600
    return {"url": f"{config.PUBLIC_BASE_URL.rstrip('/')}/auth/google/start?u={uid}&exp={exp}&sig={_oauth_sig(uid, exp)}"}


@app.get("/auth/google/start")
def google_start(u: str = store.OWNER_ID, exp: int = 0, sig: str = ""):
    import hmac
    import time
    local_first_setup = u == store.OWNER_ID and not google_client.is_connected() \
        and config.PUBLIC_BASE_URL.startswith(("http://localhost", "http://127.0.0.1"))
    if not local_first_setup:
        try:
            ok = exp > time.time() and hmac.compare_digest(_oauth_sig(u, exp), sig)
        except TypeError:
            ok = False
        if not ok or not accounts.use_link_once(sig, exp):
            raise HTTPException(403, "Link expirado ou já usado. Abra de novo pelo app (⋯ > Reconectar Google).")
    return _start_google(u)


@app.get("/auth/google/callback")
def google_callback(request: Request, state: str = "", error: str = ""):
    pending = accounts.take_pending(state, request.cookies.get("fidus_login", ""))
    if not pending:
        raise HTTPException(403, "Conexão não solicitada ou expirada. Comece de novo pelo app.")
    if error:
        return _page("Fidus", "<h1>Conexão cancelada</h1><p>Você pode tentar de novo pelo app.</p>")
    full = str(request.url)
    if config.PUBLIC_BASE_URL.startswith("https"):
        full = full.replace("http://", "https://", 1)
    try:
        creds, who = google_client.exchange(full, state, pending.get("verifier"))
    except Exception as e:  # noqa: BLE001
        return _page("Fidus", f"<h1>Não deu certo</h1><p>O Google recusou a conexão ({html.escape(str(e)[:120])}). Tente de novo pelo app.</p>")
    email = (who.get("email") or "").lower()
    if not email or not who.get("verified"):
        return _page("Fidus", "<h1>E-mail não confirmado</h1><p>Use uma conta Google com e-mail verificado.</p>")
    full_access = google_client.has_required_scopes(creds)
    if pending.get("user_id"):  # reconectar a conta de quem já está logado
        user = accounts.get_user(pending["user_id"])
        expected = (config.OWNER_EMAIL if user and user["id"] == store.OWNER_ID else (user or {}).get("email")) or ""
        if not user or (expected and expected.lower() != email):
            return _page("Fidus", f"<h1>Conta diferente</h1><p>Entre com o mesmo Google da sua conta Fidus ({html.escape(expected)}).</p>")
        if not full_access:
            return _page("Fidus", "<h1>Faltou permissão</h1><p>Para o Fidus cuidar da agenda e dos e-mails, marque todas as caixas na tela do Google. Tente de novo pelo app.</p>")
        with store.as_user(accounts.user_ctx(user)):
            google_client.save_credentials(creds, email)
        return _page("Fidus", "<h1>Google conectado ✓</h1><p>Pode voltar para o app.</p>")
    user = accounts.find_or_create(email, who.get("name"), who.get("sub"))
    if not user:
        return _page("Fidus", f"<h1>Quase lá</h1><p>O Fidus está em acesso antecipado e <b>{html.escape(email)}</b> ainda não "
                              "está na lista. Peça seu convite e tente de novo.</p>")
    with store.as_user(accounts.user_ctx(user)):
        # entrar não troca a conta Google que já está ligada; para trocar, use "Reconectar Google"
        had = store.kv_get("google_creds") is not None
        same = store.kv_get("google_email") == email
        if full_access and (not had or same):
            google_client.save_credentials(creds, email)
    code = accounts.new_login_code(user["id"], pending.get("app_challenge"))
    link = f"{config.APP_SCHEME}://login?code={code}"
    return _page("Fidus", f"""<h1>Pronto, {html.escape((who.get('name') or '').split(' ')[0])}!</h1>
<p>Volte para o app do Fidus. Se ele não abrir sozinho, digite este código na tela de entrada:</p>
<div class="code">{code[:4]}-{code[4:]}</div><a class="b" href="{link}">Abrir o Fidus</a>
<p style="font-size:13px">O código vale 10 minutos e só funciona uma vez.</p>""")


class CodeIn(BaseModel):
    code: str
    verifier: str | None = None


@app.post("/v1/auth/exchange")
def auth_exchange(body: CodeIn, request: Request):
    _rate_check(request, 20, "exchange")  # conta só as tentativas erradas
    token = accounts.redeem_code(body.code, body.verifier)
    if not token:
        _rate_record(request, "exchange")
        raise HTTPException(400, "código inválido ou expirado")
    u = accounts.user_for_token(token)
    return {"token": token, "user": {"id": u["id"], "email": u.get("email"), "name": u.get("name")}}


@app.get("/v1/me", dependencies=[Depends(auth)])
def me():
    u = store.current()
    return {"id": u["id"], "email": u.get("email"), "name": store.user_name(), "is_owner": bool(u.get("is_owner")),
            "plan": plans.current(), "google_connected": google_client.is_connected(), "profile": store.profile()}


@app.post("/v1/auth/logout", dependencies=[Depends(auth)])
def logout(request: Request):
    h = request.headers.get("authorization", "")
    if h.startswith("Bearer fx_"):
        accounts.revoke(h[7:].strip())
    return {"ok": True}


# ---------- Administração (só o dono) ----------
@app.get("/v1/admin/users", dependencies=[Depends(owner_only)])
def admin_users():
    out = []
    for u in accounts.list_users():
        with store.as_user(accounts.user_ctx(u)):
            try:
                stats = features.month_stats()
            except Exception:  # noqa: BLE001
                stats = {"actions_this_month": 0}
            out.append({"id": u["id"], "email": u.get("email"), "name": u.get("name"), "status": u["status"],
                        "created_at": u["created_at"], "last_seen": u.get("last_seen"), "plan": plans.current(),
                        "google_connected": google_client.is_connected(),
                        "actions_this_month": stats.get("actions_this_month", 0), "is_owner": u["id"] == store.OWNER_ID})
    return {"users": out, "invites": accounts.list_invites()}


class InviteIn(BaseModel):
    email: str
    plan: str = "essencial"


@app.post("/v1/admin/invites", dependencies=[Depends(owner_only)])
def admin_invite(body: InviteIn):
    if "@" not in body.email or body.plan not in plans.PLANS:
        raise HTTPException(400, "e-mail ou plano inválido")
    accounts.invite(body.email, body.plan)
    return {"ok": True}


class PlanIn(BaseModel):
    plan: str


@app.post("/v1/admin/users/{uid}/plan", dependencies=[Depends(owner_only)])
def admin_set_plan(uid: str, body: PlanIn):
    u = accounts.get_user(uid)
    if not u or body.plan not in plans.PLANS:
        raise HTTPException(400, "cliente ou plano inválido")
    with store.as_user(accounts.user_ctx(u)):
        plans.set_plan(body.plan)
    return {"ok": True}


class StatusIn(BaseModel):
    status: str


@app.post("/v1/admin/users/{uid}/status", dependencies=[Depends(owner_only)])
def admin_set_status(uid: str, body: StatusIn):
    if uid == store.OWNER_ID or body.status not in ("ativo", "suspenso"):
        raise HTTPException(400, "inválido")
    accounts.set_status(uid, body.status)
    return {"ok": True}


# ---------- Conversa ----------
@app.post("/v1/message", dependencies=[Depends(auth)])
def message(body: TextIn):
    return {"transcript": body.text, **agent.handle(body.text, voice=body.mode == "voice")}


@app.post("/v1/voice", dependencies=[Depends(auth)])
async def voice(audio: UploadFile = File(...)):
    from .transcribe import transcribe

    suffix = os.path.splitext(audio.filename or "")[1] or ".m4a"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(await audio.read())
        path = f.name
    try:
        text = transcribe(path)
    finally:
        os.unlink(path)
    if not text:
        return {"transcript": "", "reply": "Não entendi o áudio. Pode repetir?", "pending_actions": [], "events": []}
    return {"transcript": text, **agent.handle(text)}


class VoiceB64In(BaseModel):
    audio_b64: str
    ext: str = ".m4a"
    mode: str = ""


@app.post("/v1/voice_b64", dependencies=[Depends(auth)])
def voice_b64(body: VoiceB64In):
    """Mesmo que /v1/voice, mas recebe o áudio em base64 (mais compatível com o app)."""
    import base64

    from .transcribe import transcribe

    ext = body.ext if body.ext.startswith(".") and len(body.ext) <= 6 else ".m4a"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(base64.b64decode(body.audio_b64))
        path = f.name
    try:
        text = transcribe(path)
    finally:
        os.unlink(path)
    if not text:
        return {"transcript": "", "reply": "Não entendi o áudio. Pode repetir?", "pending_actions": [], "events": []}
    return {"transcript": text, **agent.handle(text, voice=body.mode == "voice")}


class PhotoIn(BaseModel):
    image_b64: str
    media_type: str = "image/jpeg"
    text: str = ""


@app.post("/v1/photo", dependencies=[Depends(auth)])
def photo(body: PhotoIn):
    """Foto (ex. recibo): guarda a imagem e pede para a IA ler e agir."""
    import base64
    import uuid
    from datetime import datetime

    if body.media_type not in ("image/jpeg", "image/png", "image/webp", "application/pdf"):
        raise HTTPException(400, "formato não suportado (use foto ou PDF)")
    raw = base64.b64decode(body.image_b64)
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(413, "arquivo grande demais (máx. 15 MB)")
    folder = os.path.join(store.receipts_dir(), datetime.now().strftime("%Y-%m"))
    os.makedirs(folder, exist_ok=True)
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}[body.media_type]
    path = os.path.join(folder, f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}{ext}")
    with open(path, "wb") as f:
        f.write(raw)
    text = body.text.strip() or (("PDF enviado." if body.media_type == "application/pdf" else "Foto enviada.") + (" Se for recibo ou nota de compra, lance o gasto. Se for documento "
                                 "(seguro, contrato, carta, MOT, apólice, garantia...), guarde com save_document. "
                                 "Se não der para saber, pergunte."))
    return {"transcript": "", **agent.handle(text, image_b64=body.image_b64, media_type=body.media_type,
                                             receipt_path=path)}


@app.get("/v1/history", dependencies=[Depends(auth)])
def history(limit: int = 60):
    """Últimas mensagens da conversa, para o app mostrar ao abrir."""
    import re

    out = []
    for m in store.recent_messages(limit):
        text = re.sub(r"\n*\[ações executadas:.*\]\s*$", "", m["content"], flags=re.S).strip()
        out.append({"role": m["role"], "text": text})
    return {"messages": out}


# ---------- Ações que exigem autorização do usuário ----------
@app.get("/v1/actions/{pid}", dependencies=[Depends(auth)])
def get_action(pid: str):
    a = store.get_pending(pid)
    if not a:
        raise HTTPException(404, "ação não encontrada")
    return a


@app.post("/v1/actions/{pid}/edit", dependencies=[Depends(auth)])
def edit_action(pid: str, body: EditIn):
    a = store.get_pending(pid)
    if not a or a["status"] != "pending":
        raise HTTPException(409, "ação não está pendente")
    a["payload"]["body"] = body.body
    store.update_pending(pid, "pending", a["payload"])
    return store.get_pending(pid)


@app.post("/v1/actions/{pid}/confirm", dependencies=[Depends(auth)])
def confirm_action(pid: str):
    a = store.get_pending(pid)
    if not a or not store.claim_pending(pid):  # trava atômica: um toque = um envio
        raise HTTPException(409, "ação não está pendente")
    senders = {"send_email": (tools.send_confirmed_email, "email_draft"),
               "calendar_invite": (features.send_confirmed_invite, "invite_draft")}
    if a["kind"] not in senders:
        store.update_pending(pid, "pending")
        raise HTTPException(400, "tipo de ação desconhecido")
    send, act_kind = senders[a["kind"]]
    try:
        result = send(a["payload"])
    except Exception as e:
        store.update_pending(pid, "pending")
        raise HTTPException(502, f"falha ao enviar: {e}")
    store.update_pending(pid, "sent")
    store.update_activity_by_ref(act_kind, pid, "enviado")
    return {"status": "sent", **result}


@app.post("/v1/actions/{pid}/cancel", dependencies=[Depends(auth)])
def cancel_action(pid: str):
    a = store.get_pending(pid)
    if not a or a["status"] != "pending":
        raise HTTPException(409, "ação não está pendente")
    store.update_pending(pid, "cancelled")
    store.update_activity_by_ref("invite_draft" if a["kind"] == "calendar_invite" else "email_draft", pid, "cancelado")
    return {"status": "cancelled"}


# ---------- Aba Atividade ----------
UNDO = {
    "event_created": lambda ref: tools.run_delete_event(ref),
    "reminder_created": lambda ref: tools.run_delete_event(ref),
    "expense_added": lambda ref: tools.run_delete_expense(int(ref)),
    "task_added": lambda ref: features.delete_task(int(ref)),
    "task_done": lambda ref: features.reopen_task(int(ref)),
    "document_saved": lambda ref: features.delete_document(int(ref)),
    "bill_added": lambda ref: features.delete_bill(int(ref)),
    "export_created": lambda ref: features.delete_document(int(ref)),
}


@app.get("/v1/activity", dependencies=[Depends(auth)])
def activity(limit: int = 100):
    items = store.list_activities(limit)
    for a in items:
        a["can_undo"] = a["kind"] in UNDO and a["status"] == "feito" and bool(a["ref"])
    return {"items": items, "stats": features.month_stats()}


@app.post("/v1/activity/{aid}/undo", dependencies=[Depends(auth)])
def undo_activity(aid: int):
    a = store.get_activity(aid)
    if not a:
        raise HTTPException(404, "atividade não encontrada")
    if a["kind"] not in UNDO or a["status"] != "feito" or not a["ref"]:
        raise HTTPException(409, "esta atividade não pode ser desfeita")
    try:
        UNDO[a["kind"]](a["ref"])
    except Exception as e:
        raise HTTPException(502, f"não consegui desfazer: {e}")
    store.set_activity_status(aid, "desfeito")
    return {"status": "desfeito"}


# ---------- Tarefas ----------
@app.get("/v1/tasks", dependencies=[Depends(auth)])
def tasks_list(status: str = "aberta"):
    return features.list_tasks(status)


class TaskIn(BaseModel):
    title: str
    due: str | None = None
    priority: str = "normal"


@app.post("/v1/tasks", dependencies=[Depends(auth)])
def tasks_add(body: TaskIn):
    r = features.add_task(body.title, body.due, body.priority)
    store.add_activity("task_added", body.title, f"prazo {body.due}" if body.due else "sem prazo", "feito",
                       str(r["task_id"]))
    return r


@app.post("/v1/tasks/{tid}/done", dependencies=[Depends(auth)])
def tasks_done(tid: int):
    r = features.complete_task(tid)
    if r.get("error"):
        raise HTTPException(404, r["error"])
    store.add_activity("task_done", r["title"], "concluída", "feito", str(tid))
    return r


@app.post("/v1/tasks/{tid}/reopen", dependencies=[Depends(auth)])
def tasks_reopen(tid: int):
    features.reopen_task(tid)
    return {"ok": True}


@app.delete("/v1/tasks/{tid}", dependencies=[Depends(auth)])
def tasks_delete(tid: int):
    features.delete_task(tid)
    return {"ok": True}


# ---------- Documentos ----------
@app.get("/v1/documents", dependencies=[Depends(auth)])
def documents_list(q: str | None = None):
    docs = features.search_documents(q)["documents"]
    return {"documents": [{**d, "url": features.sign(d["document_id"])} for d in docs]}


@app.get("/v1/documents/{did}/file")
def document_file(did: int, exp: int, sig: str, u: str = store.OWNER_ID):
    """Link assinado e temporário (1 h): o app abre no navegador sem expor o token."""
    if not features.check_sig(did, exp, sig, u):
        raise HTTPException(403, "link expirado")
    user = accounts.get_user(u)
    if not user or user["status"] != "ativo":
        raise HTTPException(404, "documento não encontrado")
    with store.as_user(accounts.user_ctx(user)):
        d = store.get("documents", did)
    if not d or d["deleted"] or not os.path.exists(d["path"]):
        raise HTTPException(404, "documento não encontrado")
    name = os.path.basename(d["path"]) if d["path"].endswith((".zip", ".pdf", ".xlsx")) else None
    return FileResponse(d["path"], filename=name)


# ---------- Bom dia ----------
@app.get("/v1/briefing", dependencies=[Depends(auth)])
def briefing():
    data = features.briefing_data()
    return {"text": features.briefing_text(data), "data": data}


@app.get("/v1/stats", dependencies=[Depends(auth)])
def stats():
    return features.month_stats()


# ---------- Ata de reunião ----------
class MeetingIn(BaseModel):
    audio_b64: str
    ext: str = ".m4a"
    title: str | None = None


@app.post("/v1/meeting_b64", dependencies=[Depends(auth)])
def meeting_upload(body: MeetingIn):
    import base64

    if not plans.allows("meetings_record"):
        return {"locked": True, "upsell": plans.upsell("meetings_record")}

    ext = body.ext if body.ext.startswith(".") and len(body.ext) <= 6 else ".m4a"
    try:
        raw = base64.b64decode(body.audio_b64, validate=True)
    except ValueError:
        raise HTTPException(400, "áudio inválido")
    if len(raw) > 90 * 1024 * 1024:
        raise HTTPException(413, "gravação grande demais (máx. ~3 h)")
    if len(raw) < 1000:
        raise HTTPException(400, "gravação vazia")
    mid = meetings.start(raw, ext, (body.title or "").strip() or None)
    return {"meeting_id": mid, "status": "processando"}


@app.get("/v1/meetings/{mid}", dependencies=[Depends(auth)])
def meeting_status(mid: int):
    r = meetings.status(mid)
    if r.get("error") == "reunião não encontrada":
        raise HTTPException(404, r["error"])
    return r


# ---------- Resumo da semana ----------
@app.get("/v1/weekly", dependencies=[Depends(auth)])
def weekly():
    data = features.weekly_review_data()
    return {"text": features.weekly_text(data), "data": data}


# ---------- Link de agendamento (público, sem token) ----------
_book_hits: dict = {}


def _booking_user(slug: str) -> dict:
    """Dono do link público: abre o banco dele. 404 se o link não existe ou foi desativado."""
    u = accounts.user_for_slug(slug)
    if not u:
        raise HTTPException(404, "link inválido")
    ctx = accounts.user_ctx(u)
    with store.as_user(ctx):
        s = booking.settings()
        if slug != s["slug"] or not s["enabled"]:
            raise HTTPException(404, "link inválido")
    return ctx


def _client_ip(request: Request) -> str:
    import ipaddress
    peer = request.client.host if request.client else "?"
    # o contêiner só escuta em 127.0.0.1 (via Docker): o X-Real-IP vem do Nginx, que sobrescreve o do cliente.
    # Só confiamos no cabeçalho quando quem conecta é o próprio servidor ou a rede interna do Docker.
    try:
        a = ipaddress.ip_address(peer)
        trusted = a.is_loopback or a in ipaddress.ip_network("172.16.0.0/12")
    except ValueError:
        trusted = peer == "testclient"
    return (request.headers.get("x-real-ip") if trusted else None) or peer


def _hits(key: str) -> list:
    import time
    now = time.time()
    if len(_book_hits) > 5000:  # limpa quem não aparece há 1 h
        for k in [k for k, v in _book_hits.items() if not v or now - v[-1] > 3600]:
            _book_hits.pop(k, None)
    return [t for t in _book_hits.get(key, []) if now - t < 3600]


def _rate_check(request: Request, limit: int, bucket: str) -> None:
    if len(_hits(f"{bucket}:{_client_ip(request)}")) >= limit:
        raise HTTPException(429, "muitas tentativas, tente mais tarde")


def _rate_record(request: Request, bucket: str) -> None:
    import time
    key = f"{bucket}:{_client_ip(request)}"
    _book_hits[key] = _hits(key) + [time.time()]


def _rate_limit(request: Request, limit: int = 8, bucket: str = "book"):
    _rate_check(request, limit, bucket)
    _rate_record(request, bucket)


@app.get("/book/{slug}", response_class=HTMLResponse)
def booking_page(slug: str):
    with store.as_user(_booking_user(slug)):
        return HTMLResponse(booking.page(booking.settings()))


@app.get("/book/{slug}/days")
def booking_days(slug: str, type: str):
    with store.as_user(_booking_user(slug)):
        return {"days": booking.days_available(type)}


@app.get("/book/{slug}/slots")
def booking_slots(slug: str, type: str, day: str, request: Request):
    ctx = _booking_user(slug)
    _rate_limit(request, 200, "slots")
    try:
        with store.as_user(ctx):
            return {"slots": booking.slots(type, day)}
    except ValueError:
        raise HTTPException(400, "data inválida")


class BookIn(BaseModel):
    type: str
    day: str
    time: str
    name: str
    email: str
    phone: str = ""
    address: str = ""
    notes: str = ""
    website: str = ""  # armadilha para robôs


@app.post("/book/{slug}")
def booking_create(slug: str, body: BookIn, request: Request):
    ctx = _booking_user(slug)
    if body.website:
        return {"ok": False, "error": "inválido"}
    _rate_limit(request)
    try:
        with store.as_user(ctx):
            return booking.book(body.type, body.day, body.time, body.name, body.email, body.phone, body.address, body.notes)
    except ValueError:
        return {"ok": False, "error": "dados inválidos"}


# ---------- Plano ----------
@app.get("/v1/plan", dependencies=[Depends(auth)])
def plan_info():
    return plans.info()


@app.post("/v1/plan", dependencies=[Depends(owner_only)])
def plan_set(body: PlanIn):
    """Troca de plano do próprio dono (testes). Clientes: /v1/admin/users/{id}/plan, ou o pagamento."""
    try:
        plans.set_plan(body.plan)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return plans.info()
