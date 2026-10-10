"""API do Fidus."""
import html
import json
import os
import shutil
import tempfile

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

from . import account_data, accounts, newsletter, partners, actions, admin, agent, backup, booking, metrics, web_tools, config, features, google_client, i18n, mailer, meetings, plans, store, tools

app = FastAPI(title="Fidus API", version="0.9.0", docs_url=None, redoc_url=None, openapi_url=None)  # não expõe o mapa da API
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


app.include_router(admin.router)  # painel da empresa em /admin
app.add_middleware(metrics.Middleware)  # mede tempo e erros (fica por dentro: já sabe quem é o cliente)
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
if (os.getenv("FIDUS_BACKUP_AUTO", "1") or "1") not in ("0", "false", "no"):
    backup.start_daily()  # backup todo dia às 03:30 (UTC)
    newsletter.start_hourly()  # dicas por e-mail: só para quem aceitou


def auth(request: Request):
    if store.CURRENT.get() is None:
        h = request.headers.get("authorization", "")
        # o app mostra "sua conta foi aberta em outro aparelho" quando o motivo é esse
        raise HTTPException(401, accounts.token_problem(h[7:].strip()) or "token inválido")


def owner_only():
    u = store.CURRENT.get()
    if not u or not u.get("is_owner"):
        raise HTTPException(403, "só o administrador")


class TextIn(BaseModel):
    text: str
    mode: str = ""  # "voice" = modo conversa (resposta curta para ouvir)
    drafts: list[str] | None = None  # rascunhos na tela do app (e não em edição): só esses podem sair por "envia"
    request_id: str = ""  # para o botão parar


class EditIn(BaseModel):
    body: str
    to: str | None = None
    subject: str | None = None


@app.get("/health")
def health():
    """Para monitor externo (ex. UptimeRobot): responde 503 se o backup está atrasado ou o disco quase cheio."""
    from fastapi.responses import JSONResponse
    problems = []
    age = backup.age_hours()
    if age is not None and age > 36:
        problems.append(f"backup atrasado ({int(age)} h)")
    if backup.last() and not backup.last().get("ok"):
        problems.append("último backup falhou")
    try:
        free_gb = shutil.disk_usage(config.DATA_DIR).free / 1e9
        if free_gb < 2:
            problems.append(f"disco quase cheio ({free_gb:.1f} GB livres)")
    except OSError:
        free_gb = None
    body = {"ok": not problems, "problems": problems, "google_connected": google_client.is_connected(),
            "llm": config.LLM_PROVIDER, "backup_age_hours": round(age, 1) if age is not None else None,
            "disk_free_gb": round(free_gb, 1) if free_gb is not None else None}
    return JSONResponse(body, status_code=200 if not problems else 503)


# ---------- Login e conexão com o Google ----------
@app.get("/email/sair", response_class=HTMLResponse)
def email_unsub_page(t: str = ""):
    """Link do rodapé: confirma com um botão (alguns leitores de e-mail abrem links sozinhos)."""
    import html as _h
    return _page("Fidus", "<h1>Parar de receber as dicas?</h1><form method='post' action='/email/sair'>"
                          f"<input type='hidden' name='t' value='{_h.escape(t)}'><button>Sim, não quero mais receber</button>"
                          "</form><p>Stop receiving Fidus tips? Press the button above.</p>")


@app.post("/email/sair", response_class=HTMLResponse)
async def email_unsub(request: Request):
    form = await request.form()
    newsletter.unsubscribe(str(form.get("t") or request.query_params.get("t") or ""))  # botão ou "one-click" do Gmail
    return _page("Fidus", "<h1>Pronto ✓</h1><p>Você não vai receber mais as dicas por e-mail. "
                          "You won't receive Fidus tips any more.</p>")


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="pt"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{margin:0;font-family:system-ui,sans-serif;background:#FFFFFF;color:#111111;display:flex;min-height:100vh;
align-items:center;justify-content:center}}main{{max-width:420px;padding:32px 24px;text-align:center}}
h1{{font-size:26px;font-weight:600;margin:0 0 12px}}p{{color:#555;line-height:1.5}}.code{{font:600 34px ui-monospace,monospace;
letter-spacing:.12em;background:#F6F6F5;border:1px solid #E6E6E6;border-radius:14px;padding:18px;margin:20px 0;
user-select:all}}a.b,button{{display:block;width:100%;background:#111;color:#fff;font-weight:600;text-decoration:none;border:0;
font-size:16px;padding:16px;border-radius:999px;margin-top:8px;cursor:pointer}}
@media (prefers-color-scheme: dark){{body{{background:#141414;color:#ECECEC}}p{{color:#AAA}}.code{{background:#1C1C1C;border-color:#2C2C2C}}
a.b,button{{background:#ECECEC;color:#141414}}}}</style></head><body><main>{body}</main></body></html>""")


def _doc(title: str, body: str) -> HTMLResponse:
    """Página de texto longo (privacidade, termos)."""
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{margin:0;font-family:system-ui,sans-serif;background:#FFFFFF;color:#111;line-height:1.6}}
main{{max-width:720px;margin:0 auto;padding:32px 20px 64px}}h1{{font-weight:600;font-size:30px}}h2{{font-weight:600;font-size:19px;margin-top:28px}}
a{{color:#1E5BD8}}.small{{color:#6B6B6B;font-size:14px}}li{{margin:6px 0}}
@media (prefers-color-scheme: dark){{body{{background:#141414;color:#ECECEC}}a{{color:#7DB3FF}}.small{{color:#9A9A9A}}}}</style>
</head><body><main>{body}</main></body></html>""")


HOME_TEXT = {
    "pt": ("Fale. O Fidus resolve.",
           "Seu assessor pessoal por voz: agenda, e-mails, gastos e lembretes, num só lugar.",
           "Em breve na Google Play e na App Store.", "Suporte", "Privacidade", "Termos"),
    "en": ("Just say it. Fidus handles it.",
           "Your voice-first personal assistant: calendar, email, expenses and reminders in one place.",
           "Coming soon to Google Play and the App Store.", "Support", "Privacy", "Terms"),
}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    """Página do domínio (heyfidus.com) até o site completo entrar no ar. Também serve de site da empresa nas lojas."""
    al = (request.headers.get("accept-language") or "").lower()
    lang = "pt" if al.startswith("pt") else "en"
    head, sub, soon, sup, priv, terms_ = HOME_TEXT[lang]
    mail = html.escape(config.SUPPORT_EMAIL or "suporte@heyfidus.com")
    body = (f'<h1 style="font-size:40px;margin-bottom:4px">Fidus</h1><h1>{head}</h1><p>{sub}</p><p><b>{soon}</b></p>'
            f'<p>{sup}: <a href="mailto:{mail}">{mail}</a></p>'
            f'<p><a href="/privacy?lang={lang}">{priv}</a> · <a href="/terms?lang={lang}">{terms_}</a></p>'
            f'<p style="font-size:13px">Fidus Labs Limited · Company no. 17510962 · England &amp; Wales</p>')
    return _page("Fidus", body)


@app.get("/privacy", response_class=HTMLResponse)
def privacy(lang: str = "en"):
    from . import legal
    return _doc("Fidus — Privacy", legal.page("privacy", lang))


@app.get("/terms", response_class=HTMLResponse)
def terms(lang: str = "en"):
    from . import legal
    return _doc("Fidus — Terms", legal.page("terms", lang))


def _oauth_sig(uid: str, exp: int) -> str:
    import hashlib
    import hmac
    return hmac.new(config.APP_TOKEN.encode(), f"oauth:{uid}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def _start_google(user_id: str | None, app_challenge: str | None = None, ref: str | None = None) -> RedirectResponse:
    import secrets
    url, state, verifier = google_client.auth_url()
    nonce = secrets.token_urlsafe(24)
    accounts.new_pending(verifier, user_id, state, nonce, app_challenge, ref)
    resp = RedirectResponse(url)
    # o retorno do Google só vale no MESMO navegador que começou (impede alguém mandar o próprio login para a vítima)
    resp.set_cookie("fidus_login", nonce, max_age=900, httponly=True, samesite="lax",
                    secure=config.PUBLIC_BASE_URL.startswith("https"), path="/auth/google")
    return resp


@app.get("/auth/google/login")
def google_login(request: Request, cc: str = "", ref: str = ""):
    """Entrar / criar conta com o Google (aberto pelo app, que manda `cc` = hash de um segredo só dele
    e, se houver, `ref` = código de convite de um amigo)."""
    import re as _re
    _rate_limit(request, 20, "login")
    ref = ref if _re.fullmatch(r"[A-Za-z0-9-]{3,14}", ref or "") else ""
    return _start_google(None, cc.lower() if _re.fullmatch(r"[0-9a-fA-F]{64}", cc or "") else None, ref or None)


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
    user = accounts.find_or_create(email, who.get("name"), who.get("sub"), pending.get("ref"))
    if user and pending.get("ref"):
        accounts.apply_referral(user["id"], pending["ref"])  # conta nova: liga ao amigo que convidou
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
    device_id: str | None = None
    device_name: str | None = None


@app.post("/v1/auth/exchange")
def auth_exchange(body: CodeIn, request: Request):
    _rate_check(request, 20, "exchange")  # conta só as tentativas erradas
    token = accounts.redeem_code(body.code, body.verifier, body.device_id, body.device_name, _client_ip(request))
    if not token:
        _rate_record(request, "exchange")
        raise HTTPException(400, "código inválido ou expirado")
    u = accounts.user_for_token(token)
    return {"token": token, "user": {"id": u["id"], "email": u.get("email"), "name": u.get("name")}}


# ---------- Entrar com e-mail (código de 6 números) ----------
@app.get("/v1/auth/options")
def auth_options():
    return {"google": True, "email": mailer.enabled()}


class EmailStartIn(BaseModel):
    email: str
    cc: str = ""   # hash do segredo do app (só o app que pediu consegue usar o código)
    ref: str = ""


@app.post("/v1/auth/email/start")
def email_start(body: EmailStartIn, request: Request):
    import re as _re
    if not mailer.enabled():
        raise HTTPException(503, "entrada por e-mail indisponível")
    _rate_limit(request, 8, "emailstart")
    email = body.email.strip().lower()
    if not _re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "e-mail inválido")
    import time as _time
    key = f"emailto:{email}"
    if len(_hits(key)) >= 5:  # ninguém lota a caixa de alguém com códigos
        raise HTTPException(429, "muitos códigos pedidos, tente mais tarde")
    _book_hits[key] = _hits(key) + [_time.time()]
    cc = body.cc.lower() if _re.fullmatch(r"[0-9a-fA-F]{64}", body.cc or "") else None
    what, code = accounts.start_email_login(email, cc, (body.ref or "").strip() or None)
    if what:
        u = accounts.by_email(email)
        lang = "pt"
        if u:
            with store.as_user(accounts.user_ctx(u)):
                lang = store.user_lang()
        elif request.headers.get("accept-language", "").lower()[:2] in ("en", "es"):
            lang = request.headers["accept-language"].lower()[:2]
        # em segundo plano nos dois casos: o tempo de resposta não revela quem é cliente
        if what == "code":
            mailer.send(email, "login_code", lang, code=code)
        else:
            mailer.send(email, "use_google", lang)
    return {"ok": True}  # mesma resposta se o e-mail não tem acesso: não revela quem é cliente


class EmailVerifyIn(BaseModel):
    email: str
    code: str
    verifier: str | None = None
    device_id: str | None = None
    device_name: str | None = None


@app.post("/v1/auth/email/verify")
def email_verify(body: EmailVerifyIn, request: Request):
    _rate_check(request, 20, "emailverify")
    token, u, err = accounts.verify_email_login(body.email, body.code, body.verifier, body.device_id, body.device_name,
                                                _client_ip(request))
    if not token:
        _rate_record(request, "emailverify")
        raise HTTPException(400, err or "código inválido")
    return {"token": token, "user": {"id": u["id"], "email": u.get("email"), "name": u.get("name")}}


# ---------- Meus dados: exportar e apagar a conta ----------
@app.post("/v1/account/export", dependencies=[Depends(auth)])
def account_export(request: Request):
    _rate_limit(request, 5, "export")
    r = account_data.export_zip()
    return {**r, "url": features.sign(r["document_id"])}


class DeleteIn(BaseModel):
    confirm: str


@app.post("/v1/account/delete", dependencies=[Depends(auth)])
def account_delete(body: DeleteIn):
    """Apaga a conta (exigido pela Google Play e pela GDPR). Pede a palavra de confirmação para não ser um toque sem querer."""
    if body.confirm.strip().upper() not in ("APAGAR", "DELETE", "BORRAR", "SUPPRIMER", "LÖSCHEN", "ELIMINA", "PADAM"):
        raise HTTPException(400, "confirmação errada")
    u = store.current()
    lang, name, email = store.user_lang(), store.user_name(), u.get("email")
    r = account_data.delete_account(u["id"])
    newsletter.forget(u["id"])
    if r.get("error"):
        raise HTTPException(400, r["error"])
    if email:
        mailer.send(email, "account_deleted", lang, name=name)
    return r


@app.post("/v1/admin/backup", dependencies=[Depends(owner_only)])
def admin_backup():
    return backup.run()


@app.post("/v1/auth/logout_all", dependencies=[Depends(auth)])
def logout_all():
    return {"ok": True, "closed": accounts.logout_all(store.current()["id"])}


@app.get("/v1/auth/device", dependencies=[Depends(auth)])
def this_device(request: Request):
    return accounts.current_device(request.headers.get("authorization", "")[7:].strip()) or {}


@app.get("/v1/me", dependencies=[Depends(auth)])
def me(request: Request):
    u = store.current()
    metrics.set_client(u["id"], request.headers.get("x-fidus-client", ""))
    return {"id": u["id"], "email": u.get("email"), "name": store.user_name(), "is_owner": bool(u.get("is_owner")),
            "plan": plans.current(), "plan_name": plans.PLANS[plans.current()]["name"],
            "google_connected": google_client.is_connected(), "profile": store.profile(),
            "language": store.user_lang(), "currency": plans.user_currency(),
            "staff_role": admin.role_for({**u, "email": u.get("email")}),
            "nps_due": _nps_due(u), "natural_voice": _tts_on(), "realtime": _rt_on(), "onboarding_pending": _onb_pending(), "voice_gender": store.profile().get("voice_gender") or "female"}


def _onb_pending() -> bool:
    try:
        from . import onboarding
        return onboarding.pending()
    except Exception:  # noqa: BLE001
        return False


def _rt_on() -> bool:
    from . import realtime
    return realtime.enabled()


def _tts_on() -> bool:
    from . import tts
    return tts.enabled()


def _nps_due(u: dict) -> bool:
    try:
        full = accounts.get_user(u["id"]) or {}
        return not u.get("is_owner") and metrics.nps_due(u["id"], full.get("created_at"))
    except Exception:  # noqa: BLE001
        return False


# ---------- Satisfação (painel HEART): 👍/👎 nas respostas e nota de 0 a 10 ----------
class FeedbackIn(BaseModel):
    value: int
    area: str = ""


@app.post("/v1/feedback", dependencies=[Depends(auth)])
def feedback(body: FeedbackIn):
    return {"ok": metrics.add_feedback(store.current()["id"], body.value, body.area)}


class NpsIn(BaseModel):
    score: int
    comment: str = ""


@app.post("/v1/nps", dependencies=[Depends(auth)])
def nps(body: NpsIn):
    if not 0 <= body.score <= 10:
        raise HTTPException(400, "nota de 0 a 10")
    return {"ok": metrics.add_nps(store.current()["id"], body.score, body.comment)}


@app.post("/v1/admin/panel_code", dependencies=[Depends(auth)])
def panel_code():
    """Código de 8 letras para abrir o painel da empresa no computador (só equipe)."""
    return admin.new_panel_code(store.current())


class ProfileIn(BaseModel):
    name: str | None = None
    language: str | None = None
    country: str | None = None
    timezone: str | None = None
    voice_gender: str | None = None  # voz do Fidus: "female" ou "male"
    only_if_empty: bool = False  # o app manda o idioma/país do celular; não sobrescreve o que o usuário escolheu


@app.post("/v1/profile", dependencies=[Depends(auth)])
def profile_update(body: ProfileIn):
    import re
    from zoneinfo import ZoneInfo
    cur = store.profile()
    ch: dict = {}
    if body.language is not None:
        lang = i18n.norm(body.language)
        if not lang:
            raise HTTPException(400, "idioma não suportado")
        ch["language"] = lang
    if body.country is not None:
        cc = body.country.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", cc):
            raise HTTPException(400, "país inválido")
        ch["country"] = cc
    if body.timezone is not None:
        try:
            ZoneInfo(body.timezone)
        except Exception:
            raise HTTPException(400, "fuso inválido")
        ch["timezone"] = body.timezone
    if body.voice_gender is not None:
        if body.voice_gender not in ("female", "male"):
            raise HTTPException(400, "voz inválida")
        ch["voice_gender"] = body.voice_gender
    if body.name is not None and body.name.strip():
        ch["name"] = body.name.strip()[:60]
    if body.only_if_empty:
        tz_default = cur.get("timezone") == config.USER_TIMEZONE and not store.kv_get("tz_set")
        ch = {k: v for k, v in ch.items() if not cur.get(k) or (k == "timezone" and tz_default)}
    if "timezone" in ch:
        store.kv_set("tz_set", "1")
    p = store.save_profile(**ch) if ch else cur
    u = store.current()
    if not u.get("is_owner") and u.get("email") and not store.kv_get("welcome_sent"):
        store.kv_set("welcome_sent", "1")  # boas-vindas uma vez, já no idioma do celular, só para conta nova
        if accounts.is_new_user(u["id"]):
            mailer.send(u["email"], "welcome", store.user_lang(), name=store.user_name() if store.profile().get("name") else "")
    return {"profile": p, "language": store.user_lang(), "currency": plans.user_currency()}


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
        if u["status"] == "apagado":
            continue
        with store.as_user(accounts.user_ctx(u)):
            try:
                stats = features.month_stats()
            except Exception:  # noqa: BLE001
                stats = {"actions_this_month": 0}
            out.append({"id": u["id"], "email": u.get("email"), "name": u.get("name"), "status": u["status"],
                        "created_at": u["created_at"], "last_seen": u.get("last_seen"), "plan": plans.current(),
                        "google_connected": google_client.is_connected(),
                        "actions_this_month": stats.get("actions_this_month", 0), "is_owner": u["id"] == store.OWNER_ID,
                        "device_switches_30d": accounts.device_switches(u["id"]),
                        "ai_cost_month_usd": _safe_cost(),
                        "ips_30d": accounts.distinct_ips(u["id"])})
    return {"users": out, "invites": accounts.list_invites()}


def _safe_cost() -> float:
    try:
        return store.usage_summary(1)["month"]
    except Exception:  # noqa: BLE001
        return 0.0


@app.get("/v1/admin/costs", dependencies=[Depends(owner_only)])
def admin_costs(days: int = 30):
    """Custo de IA por cliente (últimos N dias e mês atual) e o total, para acompanhar a margem."""
    rows = []
    for u in accounts.list_users():
        if u["status"] == "apagado":
            continue
        with store.as_user(accounts.user_ctx(u)):
            try:
                us = store.usage_summary(max(1, min(days, 365)))
            except Exception:  # noqa: BLE001
                continue
            rows.append({"id": u["id"], "email": u.get("email"), "plan": plans.current(), **us})
    rows.sort(key=lambda r: r["month"], reverse=True)
    return {"users": rows, "total_month_usd": round(sum(r["month"] for r in rows), 2),
            "total_period_usd": round(sum(r["cost"] for r in rows), 2), "fair_use_daily_usd": config.FAIR_USE_DAILY_USD}


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
    sent = actions.handle_command(body.text, body.drafts)  # "envia" com rascunho na tela: o próprio usuário autorizou
    if sent:
        metrics.record_task(store.current()["id"], "envio", bool(sent.get("sent_actions")))
        return {"transcript": body.text, **sent}
    return {"transcript": body.text, **agent.handle(body.text, voice=body.mode == "voice", request_id=body.request_id)}


# frases fixas que o app fala (modo conversa); só estas podem ser pedidas avulsas, para ninguém gerar áudio à toa
TTS_PHRASES = {"Pode falar.", "Um instante.", "Deixa eu ver.", "Já vejo isso.", "Até mais!", "Não entendi. Pode repetir?",
               "Perdi a conexão com o servidor. Tente de novo em instantes.", "Feito."}


class TtsIn(BaseModel):
    phrase: str


@app.post("/v1/tts", dependencies=[Depends(auth)])
def tts_phrase(body: TtsIn):
    """Áudio de uma frase fixa no idioma e na voz do cliente (guardado: gera uma vez só)."""
    from . import tts
    if body.phrase not in TTS_PHRASES:
        raise HTTPException(400, "frase desconhecida")
    if not tts.enabled():
        return {"audio": None}
    lang = store.user_lang()
    text = body.phrase if lang == "pt" else (i18n.translate(lang, [body.phrase]).get(body.phrase) or body.phrase)
    return {"audio": tts.synthesize(text, lang, cache=True)}


# ---------- Modo conversa em tempo real ----------
@app.post("/v1/realtime/session", dependencies=[Depends(auth)])
def realtime_session():
    from . import realtime
    if not plans.allows("voice_conversation"):
        raise HTTPException(402, "modo conversa faz parte do plano Negócio")
    r = realtime.session()
    if r.get("error") == "fair_use":
        lang = "pt" if store.user_lang().startswith("pt") else "en"
        raise HTTPException(429, agent.FAIR_USE_MSG[lang])
    if r.get("error"):
        raise HTTPException(503, r["error"])
    return r


class RtToolIn(BaseModel):
    name: str
    arguments: str | dict | None = None
    call_id: str | None = None


@app.post("/v1/realtime/tool", dependencies=[Depends(auth)])
def realtime_tool(body: RtToolIn):
    from . import realtime
    return realtime.run_tool(body.name, body.arguments)


class RtTurnIn(BaseModel):
    user: str = ""
    assistant: str = ""


@app.post("/v1/realtime/turn", dependencies=[Depends(auth)])
def realtime_turn(body: RtTurnIn):
    from . import realtime
    realtime.save_turn(body.user, body.assistant)
    return {"ok": True}


class RtUsageIn(BaseModel):
    usage: dict


@app.post("/v1/realtime/usage", dependencies=[Depends(auth)])
def realtime_usage(body: RtUsageIn):
    from . import realtime
    realtime.record_usage(body.usage)
    return {"ok": True}


class RtCommandIn(BaseModel):
    text: str
    drafts: list[str] | None = None


@app.post("/v1/realtime/command", dependencies=[Depends(auth)])
def realtime_command(body: RtCommandIn):
    """'envia' falado na ligação: só o servidor envia, e só rascunho que está na tela (a IA de voz não envia nada)."""
    sent = actions.handle_command(body.text, body.drafts)
    if not sent:
        return {"handled": False}
    metrics.record_task(store.current()["id"], "envio", bool(sent.get("sent_actions")))
    return {"handled": True, **sent}


class TtsTextIn(BaseModel):
    text: str


@app.post("/v1/tts_text", dependencies=[Depends(auth)])
def tts_text(body: TtsTextIn):
    """Áudio do resto da resposta falada (o app já está tocando a primeira frase)."""
    from . import tts
    text = (body.text or "").strip()
    if not text or len(text) > 700 or not tts.enabled():
        return {"audio": None}
    return {"audio": tts.synthesize(text)}


# ---------- Boas-vindas (setup em conversa) ----------
@app.get("/v1/onboarding", dependencies=[Depends(auth)])
def onboarding_question():
    from . import onboarding
    return onboarding.question()


class OnbIn(BaseModel):
    step: str
    value: str | list[str] | None = None
    skip: bool = False


@app.post("/v1/onboarding/answer", dependencies=[Depends(auth)])
def onboarding_answer(body: OnbIn):
    from . import onboarding
    if isinstance(body.value, str):
        body.value = body.value[:500]
    r = onboarding.answer(body.step, body.value, body.skip)
    if r.get("done") and r.get("messages"):
        for m in r["messages"]:
            store.add_message("assistant", m)
    return r


@app.post("/v1/onboarding/restart", dependencies=[Depends(auth)])
def onboarding_restart():
    from . import onboarding
    return onboarding.restart()


class MarketingIn(BaseModel):
    yes: bool


@app.get("/v1/marketing", dependencies=[Depends(auth)])
def marketing_get():
    return {"yes": newsletter.consent_of(store.current()["id"])}


@app.post("/v1/marketing", dependencies=[Depends(auth)])
def marketing_set(body: MarketingIn):
    store.save_profile(marketing=body.yes)
    newsletter.set_consent(store.current(), body.yes, store.profile(), source="configurações")
    return {"yes": body.yes}


class CancelIn(BaseModel):
    request_id: str


@app.post("/v1/cancel", dependencies=[Depends(auth)])
def cancel_request(body: CancelIn):
    """Botão parar do app: o Fidus para antes do próximo passo e não executa mais nada desse pedido."""
    agent.cancel(body.request_id)
    return {"ok": True}


def _after_transcript(text: str, voice: bool = False, drafts: list[str] | None = None, kind: str = "voz",
                      speak: bool = False, request_id: str | None = None) -> dict:
    if not text:
        return {"transcript": "", "reply": i18n.msg("no_audio"), "pending_actions": [], "events": []}
    sent = actions.handle_command(text, drafts)
    if sent:
        metrics.record_task(store.current()["id"], "envio", bool(sent.get("sent_actions")))
        return {"transcript": text, **sent}
    return {"transcript": text, **agent.handle(text, voice=voice, kind="conversa" if voice else kind, speak=speak,
                                               request_id=request_id)}


@app.post("/v1/voice", dependencies=[Depends(auth)])
async def voice(audio: UploadFile = File(...)):
    from .transcribe import transcribe

    suffix = os.path.splitext(audio.filename or "")[1] or ".m4a"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(await audio.read())
        path = f.name
    from .transcribe import prompt_for
    try:
        text = transcribe(path, prompt_for(store.user_lang()))
    finally:
        os.unlink(path)
    return _after_transcript(text, kind="voz")


class VoiceB64In(BaseModel):
    audio_b64: str
    ext: str = ".m4a"
    mode: str = ""
    drafts: list[str] | None = None
    speak: bool = False  # áudio gravado com "responder em voz alta" ligado: devolve também o texto para falar
    request_id: str = ""  # para o botão parar
    transcribe_only: bool = False


@app.post("/v1/voice_b64", dependencies=[Depends(auth)])
def voice_b64(body: VoiceB64In):
    """Mesmo que /v1/voice, mas recebe o áudio em base64 (mais compatível com o app)."""
    import base64

    from .transcribe import transcribe

    ext = body.ext if body.ext.startswith(".") and len(body.ext) <= 6 else ".m4a"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(base64.b64decode(body.audio_b64))
        path = f.name
    from .transcribe import prompt_for
    try:
        # modo conversa: transcrição mais rápida (busca simples); áudio gravado: busca mais cuidadosa
        import time as _tm
        _t0 = _tm.time()
        text = transcribe(path, prompt_for(store.user_lang()), beam_size=1 if body.mode == "voice" else 5)
        metrics.record_stage("transcricao", int((_tm.time() - _t0) * 1000))
    finally:
        os.unlink(path)
    if body.transcribe_only:  # boas-vindas respondidas por voz: só o texto, sem passar pelo assistente
        return {"transcript": text}
    if agent._cancelled(body.request_id):
        return {"transcript": text, "reply": agent.CANCELLED_MSG["pt" if store.user_lang().startswith("pt") else "en"],
                "cancelled": True, "pending_actions": [], "events": []}
    return _after_transcript(text, voice=body.mode == "voice", drafts=body.drafts, speak=body.speak,
                             request_id=body.request_id)


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
                                             receipt_path=path, kind="pdf" if body.media_type == "application/pdf" else "foto")}


@app.get("/v1/history", dependencies=[Depends(auth)])
def history(limit: int = 60):
    """Últimas mensagens da conversa aberta, para o app mostrar ao abrir."""
    import re

    out = []
    for m in store.recent_messages(min(max(limit, 1), 300)):
        text = re.sub(r"\n*\[ações executadas:.*\]\s*$", "", m["content"], flags=re.S).strip()
        out.append({"role": m["role"], "text": text})
    return {"messages": out, "conversation": store.current_conv()}


# ---------- Conversas (menu) ----------
@app.get("/v1/conversations", dependencies=[Depends(auth)])
def conversations():
    return {"conversations": store.list_conversations(), "current": store.current_conv()}


@app.post("/v1/conversations/new", dependencies=[Depends(auth)])
def conversation_new():
    return {"conversation": store.new_conversation()}


@app.post("/v1/conversations/{cid}/open", dependencies=[Depends(auth)])
def conversation_open(cid: int):
    if not store.open_conversation(cid):
        raise HTTPException(404, "conversa não encontrada")
    return {"conversation": cid}


# ---------- Ações que exigem autorização do usuário ----------
@app.get("/v1/actions", dependencies=[Depends(auth)])
def list_actions():
    """Rascunhos ainda esperando o usuário (o app mostra os cartões de novo ao reabrir)."""
    from . import payments
    return {"actions": actions.waiting(None) + payments.waiting()}


# ---------- Pagar por voz (Premium): o Fidus prepara, o usuário paga no banco ----------
class PayKeyIn(BaseModel):
    pix_key: str | None = None
    pix_key_type: str | None = None
    iban: str | None = None
    sort_code: str | None = None
    account_number: str | None = None


@app.post("/v1/payments/{pid}/key", dependencies=[Depends(auth)])
def payment_key(pid: str, body: PayKeyIn):
    """Primeira vez com esse contato: o usuário informa a chave no cartão (ou escolhe da agenda); o Fidus lembra."""
    from . import payments
    if not plans.allows("prepare_payment"):
        raise HTTPException(402, "pagar por voz faz parte do plano Premium")
    try:
        return payments.set_key(pid, **body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/v1/payments/{pid}/paid", dependencies=[Depends(auth)])
def payment_paid(pid: str):
    """O usuário tocou em 'Já paguei' (pagou no app do banco): lança o gasto na carteira."""
    from . import payments
    try:
        return payments.mark_paid(pid)
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.get("/v1/payments/contacts", dependencies=[Depends(auth)])
def payment_contacts():
    from . import payments
    return {"contacts": [{"id": c["id"], "name": c["name"], "how": payments.mask(c), "wallet": c.get("wallet"),
                          "method": c["method"]} for c in payments.contacts()]}


class PayContactDel(BaseModel):
    id: int


@app.post("/v1/payments/contacts/remove", dependencies=[Depends(auth)])
def payment_contact_remove(body: PayContactDel):
    store.update("payment_contacts", body.id, deleted=1)
    return {"ok": True}


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
    if a["kind"] == "send_email":
        try:
            if body.to is not None:
                a["payload"]["to"] = tools.clean_recipients(body.to)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if body.subject is not None and body.subject.strip():
            a["payload"]["subject"] = body.subject.strip()[:200]
    if not store.update_pending(pid, "pending", a["payload"], only_if="pending"):  # já está sendo enviado
        raise HTTPException(409, "ação não está pendente")
    return store.get_pending(pid)


@app.post("/v1/actions/{pid}/confirm", dependencies=[Depends(auth)])
def confirm_action(pid: str):
    try:
        result = actions.send_pending(pid)  # trava atômica: um toque = um envio
    except actions.SendError as e:
        msg = str(e)
        raise HTTPException(409 if "pendente" in msg else 400 if "desconhecido" in msg else 502, msg)
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
    "sheet_changed": lambda ref: web_tools.undo_sheet(ref),
    "wallet_added": lambda ref: _undo_wallet(ref),
    "wallet_removed": lambda ref: _undo_wallet(ref),
}


def _undo_wallet(ref: str) -> None:
    w = json.loads(ref)
    if w["op"] == "wallet_added":
        if not store.remove_wallet(w["name"]):
            raise ValueError("é a única carteira")
    else:
        store.add_wallet(w["name"], w.get("currency"))


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
    return {"text": i18n.localize(features.briefing_text(data)), "data": data}


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
    return {"text": i18n.localize(features.weekly_text(data)), "data": data}


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


# ---------- Telas do menu ----------
@app.get("/v1/meetings", dependencies=[Depends(auth)])
def meetings_list():
    r = tools.run("list_meetings", {})
    return r if r.get("locked") else {"meetings": r.get("meetings", [])}


def _month_range(month: str | None) -> tuple[str, str, str]:
    import calendar
    import re
    m = month if month and re.fullmatch(r"\d{4}-\d{2}", month) else features._now().strftime("%Y-%m")
    y, mm = int(m[:4]), int(m[5:])
    if not 1 <= mm <= 12 or not 2000 <= y <= 2100:
        raise HTTPException(400, "mês inválido")
    return m, f"{m}-01", f"{m}-{calendar.monthrange(y, mm)[1]:02d}"


@app.get("/v1/expenses/summary", dependencies=[Depends(auth)])
def expenses_summary(month: str | None = None, wallet: str | None = None):
    """Gastos do mês (AAAA-MM; padrão: mês atual), por moeda, carteira e categoria. `wallet` filtra uma carteira."""
    m, d0, d1 = _month_range(month)
    args = {"date_from": d0, "date_to": d1}
    if wallet:
        args["business"] = wallet[:40]
    out = tools.run("summarize_expenses", args)
    # carteiras com o total do mês de cada uma (para os botões de filtro), mesmo quando há filtro
    by_w: dict = {}
    for r in store.query_expenses(d0, d1, limit=10000):
        by_w.setdefault(r["business"], {}).setdefault(r["currency"], 0)
        by_w[r["business"]][r["currency"]] = round(by_w[r["business"]][r["currency"]] + r["amount"], 2)
    names = [w["name"] for w in store.wallets()]
    wallets = [{**w, "totals": by_w.get(w["name"], {})} for w in store.wallets()]
    wallets += [{"name": b, "currency": None, "totals": t, "archived": True} for b, t in by_w.items() if b not in names]
    bills = features.list_bills()["bills"]
    if wallet:
        bills = [b for b in bills if (b.get("business") or "").lower() == wallet.strip().lower()]
    return {"month": m, "wallet": wallet or None, **out, "wallets": wallets, "bills": bills}


class WalletIn(BaseModel):
    name: str
    currency: str | None = None


@app.get("/v1/wallets", dependencies=[Depends(auth)])
def wallets_list():
    return {"wallets": store.wallets(), "can_add": plans.allows("extra_business")}


@app.post("/v1/wallets", dependencies=[Depends(auth)])
def wallets_save(body: WalletIn):
    """Cria uma carteira ou muda a moeda dela (mesmo caminho da conversa, com Atividade e Desfazer)."""
    args = {"add_business": body.name}
    if body.currency:
        args["business_currency"] = body.currency
    r = tools.run("update_profile", args)
    if r.get("locked"):
        return r
    if r.get("error"):
        raise HTTPException(400, r["error"])
    agent._record("update_profile", args, r)
    return {"wallets": store.wallets()}


@app.post("/v1/wallets/remove", dependencies=[Depends(auth)])
def wallets_remove(body: WalletIn):
    args = {"remove_business": body.name}
    r = tools.run("update_profile", args)
    if r.get("error"):
        raise HTTPException(400, r["error"])
    if not r.get("wallet_changes"):
        raise HTTPException(409, "não dá para remover a única carteira")
    agent._record("update_profile", args, r)
    return {"wallets": store.wallets()}


class ExportIn(BaseModel):
    month: str | None = None
    wallet: str | None = None
    email: bool = False  # manda para o e-mail do próprio cliente (ele usa como quiser)


@app.post("/v1/expenses/export", dependencies=[Depends(auth)])
def expenses_export(body: ExportIn):
    """Pacote do contador (planilha + recibos) do mês, de uma carteira ou de todas."""
    m, d0, d1 = _month_range(body.month)
    args = {"date_from": d0, "date_to": d1}
    if body.wallet:
        args["business"] = body.wallet[:40]
    r = tools.run("export_for_accountant", args)
    if r.get("locked"):
        return r
    if r.get("error"):
        raise HTTPException(400, r["error"])
    agent._record("export_for_accountant", args, r)
    out = {"document_id": r["document_id"], "title": r["title"], "url": features.sign(r["document_id"])}
    if body.email:
        out["emailed_to"] = _email_export(r)
    return out


EXPORT_MAIL = {
    "pt": ("Seus gastos: {title}", "<p>Segue em anexo o pacote dos seus gastos (planilha + fotos dos recibos): <b>{title}</b>.</p><p>Use como quiser: guarde, encaminhe ao contador ou abra no Excel.</p>"),
    "en": ("Your expenses: {title}", "<p>Attached is your expenses pack (spreadsheet + receipt photos): <b>{title}</b>.</p><p>Use it however you like: keep it, forward it to your accountant or open it in Excel.</p>"),
    "es": ("Tus gastos: {title}", "<p>Adjunto el paquete de tus gastos (hoja de cálculo + fotos de los recibos): <b>{title}</b>.</p><p>Úsalo como quieras: guárdalo, reenvíalo a tu contable o ábrelo en Excel.</p>"),
}


def _email_export(r: dict) -> str:
    """O pacote vai para o e-mail da PRÓPRIA conta, pelo e-mail do Fidus (nunca para terceiros, nunca pelo Gmail dele)."""
    import base64
    import html as _h
    u = store.current()
    to = u.get("email") if u["id"] != store.OWNER_ID else (config.OWNER_EMAIL or u.get("email"))
    if not mailer.enabled():
        raise HTTPException(503, "os e-mails do Fidus ainda não estão ligados; baixe o arquivo pelo app")
    if not to:
        raise HTTPException(400, "sua conta não tem e-mail")
    doc = store.select("SELECT path, title FROM documents WHERE id=?", (r["document_id"],))
    path = doc[0]["path"] if doc else None
    if not path or not os.path.exists(path):
        raise HTTPException(500, "arquivo não encontrado")
    if os.path.getsize(path) > 20 * 1024 * 1024:
        raise HTTPException(413, "o pacote passou de 20 MB; baixe pelo app ou exporte um período menor")
    with open(path, "rb") as f:
        content = base64.b64encode(f.read()).decode()
    lang = store.user_lang().split("-")[0]
    subj, body = EXPORT_MAIL.get(lang, EXPORT_MAIL["en"])
    title = r["title"]
    mailer.send_raw(to, subj.format(title=title), body.format(title=_h.escape(title)),
                    attachments=[{"filename": os.path.basename(path), "content": content}], wait=True)
    store.add_activity("export_emailed", title, to, "feito")
    return to


@app.get("/v1/booking", dependencies=[Depends(auth)])
def booking_link():
    return tools.run("get_booking_link", {})


# ---------- Idiomas ----------
class I18nIn(BaseModel):
    lang: str
    strings: list[str]


@app.post("/v1/i18n")
def i18n_strings(body: I18nIn, request: Request):
    """Textos do app traduzidos para o idioma do celular (também na tela de login, sem token)."""
    lang = i18n.norm(body.lang)
    if not lang or lang == "pt":
        return {"lang": lang or "pt", "strings": {}}
    if store.CURRENT.get() is None:
        _rate_limit(request, 30, "i18n")
    return {"lang": lang, "strings": i18n.translate(lang, body.strings)}


# ---------- Convide e ganhe ----------
def _invite_link(code: str) -> str:
    return f"{config.PUBLIC_BASE_URL.rstrip('/')}/r/{code}"


@app.get("/v1/referral", dependencies=[Depends(auth)])
def referral():
    uid = store.current()["id"]
    code = accounts.referral_code(uid)
    st = accounts.referral_stats(uid)
    return {"code": code, "link": _invite_link(code), **st}


class RefIn(BaseModel):
    code: str


@app.post("/v1/referral/apply", dependencies=[Depends(auth)])
def referral_apply(body: RefIn, request: Request):
    _rate_limit(request, 10, "refapply")
    r = accounts.apply_referral(store.current()["id"], body.code)
    if r.get("error"):
        raise HTTPException(400, r["error"])
    return r


@app.get("/r/{code}", response_class=HTMLResponse)
def referral_page(code: str, request: Request):
    """Página que o amigo abre pelo link de convite."""
    ref = accounts.referrer_for_code(code)
    if not ref:
        raise HTTPException(404, "convite não encontrado")
    code = accounts.referral_code(ref["id"])
    who = html.escape((ref.get("name") or "").split(" ")[0] or "Um amigo")
    en = not request.headers.get("accept-language", "").lower().startswith("pt")
    days = config.REFERRAL_TRIAL_DAYS
    download = (f'<a class="b" href="{html.escape(config.APP_DOWNLOAD_URL)}">{"Get the app" if en else "Baixar o app"}</a>'
                if config.APP_DOWNLOAD_URL else "")
    open_app = f'<a class="b" style="background:#11151C;color:#F2F5F7;border:1px solid #222A35" href="{config.APP_SCHEME}://invite?code={code}">{"I already have the app" if en else "Já tenho o app"}</a>'
    if en:
        body = (f"<h1>{who} invited you to Fidus</h1><p>Your personal assistant by voice: diary, emails, expenses and "
                f"receipts. You get <b>{days} days free</b>.</p><div class='code'>{code}</div>"
                f"<p>Install the app and, on the sign-in screen, enter this invite code.</p>{download}{open_app}")
    else:
        body = (f"<h1>{who} convidou você para o Fidus</h1><p>Seu assessor pessoal por voz: agenda, e-mails, gastos e "
                f"recibos. Você ganha <b>{days} dias grátis</b>.</p><div class='code'>{code}</div>"
                f"<p>Instale o app e, na tela de entrada, coloque este código de convite.</p>{download}{open_app}")
    return _page("Fidus", body)


# ---------- Assinaturas (Google Play / App Store / Stripe via RevenueCat) ----------
@app.get("/v1/billing", dependencies=[Depends(auth)])
def billing_config():
    """O que o app precisa para abrir a compra na loja: chave pública da RevenueCat e o id do cliente."""
    uid = store.current()["id"]
    on = bool(config.REVENUECAT_ANDROID_KEY or config.REVENUECAT_IOS_KEY)
    from . import partners
    offer = partners.first_month_offer(uid)
    return {"enabled": on, "android_key": config.REVENUECAT_ANDROID_KEY, "ios_key": config.REVENUECAT_IOS_KEY,
            "app_user_id": uid, "referral_trial": accounts.referral_trial(uid) or bool(offer),
            "trial_offer_tag": offer["tag"] if offer else "convite",
            "offer_kind": "partner_discount" if offer else ("referral_trial" if accounts.referral_trial(uid) else None),
            "offer_discount": offer["discount"] if offer else None,
            "subscription": store.kv_get("subscription"), "plan": plans.current()}



@app.post("/billing/revenuecat")
async def billing_webhook(request: Request):
    """Aviso da RevenueCat: assinou, renovou, trocou de plano, cancelou ou expirou.

    O app identifica o cliente na loja pelo id dele no Fidus (app_user_id). A autorização é o segredo
    FIDUS_BILLING_WEBHOOK_SECRET, configurado na RevenueCat como cabeçalho Authorization."""
    import hmac
    secret = config.BILLING_WEBHOOK_SECRET
    got = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not secret or not hmac.compare_digest(got, secret):
        raise HTTPException(401, "não autorizado")
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "json inválido")
    ev = body.get("event") if isinstance(body, dict) else None
    if not isinstance(ev, dict):
        raise HTTPException(400, "evento inválido")
    kind = ev.get("type", "")
    uid = ev.get("app_user_id") or ""
    user = accounts.get_user(uid)
    if not user:
        return {"ok": True, "ignored": "cliente desconhecido"}
    product = (ev.get("new_product_id") or ev.get("product_id") or "").lower()
    plan = next((p for p in ("premium", "negocio", "essencial") if p in product), None)
    mail = None
    with store.as_user(accounts.user_ctx(user)):
        before = plans.current()
        if kind in ("INITIAL_PURCHASE", "RENEWAL", "PRODUCT_CHANGE", "UNCANCELLATION", "NON_RENEWING_PURCHASE") and plan:
            plans.set_plan(plan)
            store.kv_set("subscription", f"ativa:{plan}")
        elif kind in ("CANCELLATION",):
            store.kv_set("subscription", f"cancelada:{plans.current()}")  # vale até o fim do período pago
        elif kind in ("EXPIRATION",):
            store.kv_set("subscription", "expirada")
            plans.set_plan(config.NEW_USER_PLAN)  # acabou o período pago: perde os recursos do plano
        elif kind == "BILLING_ISSUE":
            store.kv_set("subscription", f"problema_pagamento:{plans.current()}")
        mail_kind = {"INITIAL_PURCHASE": "sub_started", "PRODUCT_CHANGE": "sub_started", "RENEWAL": "sub_renewed",
                     "BILLING_ISSUE": "sub_billing_issue", "CANCELLATION": "sub_cancelled", "EXPIRATION": "sub_expired"}.get(kind)
        if mail_kind:
            shown = plans.PLANS[plan or before]["name"]
            mail = (mail_kind, store.user_lang(), store.user_name(), shown)
    to = config.OWNER_EMAIL if uid == store.OWNER_ID else user.get("email")
    if mail:
        mailer.send(to, mail[0], mail[1], name=mail[2], plan=mail[3])
    from . import partners
    if kind == "CANCELLATION" and ev.get("cancel_reason") == "CUSTOMER_SUPPORT":
        accounts.revoke_referral_reward(uid)  # reembolso: o desconto de quem convidou não vale (se ainda não foi usado)
        partners.on_refund(uid)
    paid = (kind == "INITIAL_PURCHASE" and ev.get("period_type") != "TRIAL") or kind == "RENEWAL" \
        or (kind == "NON_RENEWING_PURCHASE")
    if paid:  # cobrança de verdade: comissão do criador parceiro (se o cliente veio dele e está nos 12 meses)
        amount = ev.get("price_in_purchased_currency")
        cur = ev.get("currency") or "USD"
        if amount is None:
            amount, cur = ev.get("price"), "USD"
        try:
            partners.on_payment(uid, str(ev.get("id") or ""), float(amount or 0), cur)
        except (TypeError, ValueError):
            pass
    if kind == "INITIAL_PURCHASE" and ev.get("period_type") != "TRIAL":
        accounts.mark_paid(uid)  # 1º pagamento de verdade: quem convidou ganha o desconto
    elif kind == "RENEWAL" and ev.get("is_trial_conversion"):
        accounts.mark_paid(uid)
    return {"ok": True}
