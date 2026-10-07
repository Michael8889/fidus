"""API do Fidus."""
import os
import tempfile

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

from . import agent, booking, config, features, google_client, meetings, plans, store, tools

app = FastAPI(title="Fidus API", version="0.5.0")
store.init_db()
if config.APP_TOKEN in ("", "troque-este-token") and not config.PUBLIC_BASE_URL.startswith(("http://localhost", "http://127.0.0.1")):
    raise RuntimeError("Defina FIDUS_APP_TOKEN no .env antes de colocar o Fidus na internet.")
meetings.resume_unfinished()


def auth(authorization: str = Header(default="")):
    if authorization != f"Bearer {config.APP_TOKEN}":
        raise HTTPException(401, "token inválido")


class TextIn(BaseModel):
    text: str


class EditIn(BaseModel):
    body: str


@app.get("/health")
def health():
    return {"ok": True, "google_connected": google_client.is_connected(), "llm": config.LLM_PROVIDER}


# ---------- Conexão com o Google ----------
def _oauth_sig(exp: int) -> str:
    import hashlib
    import hmac
    return hmac.new(config.APP_TOKEN.encode(), f"oauth:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


@app.get("/v1/auth/google/link", dependencies=[Depends(auth)])
def google_link():
    """Link de 10 minutos para (re)conectar o Google. Só quem tem o token do app consegue gerar."""
    import time
    exp = int(time.time()) + 600
    return {"url": f"{config.PUBLIC_BASE_URL.rstrip('/')}/auth/google/start?exp={exp}&sig={_oauth_sig(exp)}"}


@app.get("/auth/google/start")
def google_start(exp: int = 0, sig: str = ""):
    import hmac
    import time
    local_first_setup = config.PUBLIC_BASE_URL.startswith(("http://localhost", "http://127.0.0.1")) \
        and not google_client.is_connected()
    if not local_first_setup:
        try:
            ok = exp > time.time() and hmac.compare_digest(_oauth_sig(exp), sig)
        except TypeError:
            ok = False
        if not ok:
            raise HTTPException(403, "Abra este link pelo app do Fidus (⋯ > Reconectar Google).")
    store.kv_set("google_oauth_pending", str(int(time.time()) + 600))
    return RedirectResponse(google_client.auth_url())


@app.get("/auth/google/callback")
def google_callback(request: Request):
    import time
    pending = store.kv_get("google_oauth_pending")
    if not pending or int(pending) < time.time():
        raise HTTPException(403, "Conexão não solicitada ou expirada. Comece de novo pelo app.")
    store.kv_set("google_oauth_pending", "0")
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    google_client.handle_callback(str(request.url).replace("http://", "https://", 1)
                                  if config.PUBLIC_BASE_URL.startswith("https") else str(request.url))
    return HTMLResponse("<h2>Fidus conectado ao Google ✓</h2><p>Pode fechar esta página.</p>")


# ---------- Conversa ----------
@app.post("/v1/message", dependencies=[Depends(auth)])
def message(body: TextIn):
    return {"transcript": body.text, **agent.handle(body.text)}


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
    return {"transcript": text, **agent.handle(text)}


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
    folder = os.path.join(config.RECEIPTS_DIR, datetime.now().strftime("%Y-%m"))
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
def document_file(did: int, exp: int, sig: str):
    """Link assinado e temporário (1 h): o app abre no navegador sem expor o token."""
    if not features.check_sig(did, exp, sig):
        raise HTTPException(403, "link expirado")
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


def _booking_or_404(slug: str) -> dict:
    s = booking.settings()
    if slug != s["slug"] or not s["enabled"]:
        raise HTTPException(404, "link inválido")
    return s


def _rate_limit(request: Request, limit: int = 8, bucket: str = "book"):
    import time

    peer = request.client.host if request.client else "?"
    # o contêiner só escuta em 127.0.0.1: o X-Real-IP vem do Nginx, que sobrescreve o do cliente
    proxied = peer.startswith(("127.", "172.", "10.", "192.168.")) or peer in ("::1", "testclient")
    ip = (request.headers.get("x-real-ip") if proxied else None) or peer
    key = f"{bucket}:{ip}"
    now = time.time()
    hits = [t for t in _book_hits.get(key, []) if now - t < 3600]
    if len(hits) >= limit:
        raise HTTPException(429, "muitas tentativas, tente mais tarde")
    _book_hits[key] = hits + [now]


@app.get("/book/{slug}", response_class=HTMLResponse)
def booking_page(slug: str):
    return HTMLResponse(booking.page(_booking_or_404(slug)))


@app.get("/book/{slug}/days")
def booking_days(slug: str, type: str):
    _booking_or_404(slug)
    return {"days": booking.days_available(type)}


@app.get("/book/{slug}/slots")
def booking_slots(slug: str, type: str, day: str, request: Request):
    _booking_or_404(slug)
    _rate_limit(request, 200, "slots")
    try:
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
    _booking_or_404(slug)
    if body.website:
        return {"ok": False, "error": "inválido"}
    _rate_limit(request)
    try:
        return booking.book(body.type, body.day, body.time, body.name, body.email, body.phone, body.address, body.notes)
    except ValueError:
        return {"ok": False, "error": "dados inválidos"}


# ---------- Plano ----------
@app.get("/v1/plan", dependencies=[Depends(auth)])
def plan_info():
    return plans.info()


class PlanIn(BaseModel):
    plan: str


@app.post("/v1/plan", dependencies=[Depends(auth)])
def plan_set(body: PlanIn):
    """Troca de plano manual (testes). Com o pagamento ligado, quem chama isto é a confirmação do Stripe."""
    try:
        plans.set_plan(body.plan)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return plans.info()
