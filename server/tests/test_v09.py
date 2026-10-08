"""v0.9: envio por ordem na conversa, e-mail novo formatado, conversas, idiomas e moedas, convites, assinatura."""
import json
import os
import re
import tempfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import accounts, actions, agent, config, google_client, i18n, llm, main, plans, store, tools  # noqa: E402

client = TestClient(main.app)
H = {"Authorization": "Bearer t"}


@pytest.fixture(autouse=True)
def _no_rate_limit():
    main._book_hits.clear()  # muitos logins seguidos nos testes


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(tools, "send_confirmed_email", lambda p: (out.append(p), {"ok": True, "message_id": "m"})[1])
    store.init_db()
    store.select("SELECT 1")
    with store._conn() as c:
        c.execute("UPDATE pending_actions SET status='cancelled' WHERE status='pending'")
    return out


def _draft(to="carlos@x.com", subject="Orçamento"):
    r = tools.run("prepare_new_email", {"to": to, "subject": subject, "body": "**Resumo**\n• item 1\n• item 2"})
    agent._record("prepare_new_email", {"to": to}, r)
    store.add_message("user", "escreve pro carlos")
    store.add_message("assistant", "Rascunho pronto." + agent._action_log([agent._describe("prepare_new_email", {"to": to}, r)]))
    return r["pending_action_id"]


# ---------- "envia" ----------
def test_parse_command():
    assert actions.parse_command("envia")["which"] is None
    assert actions.parse_command("Pode mandar o e-mail!")["named"]
    assert actions.parse_command("send it")["lang"] == "en"
    assert actions.parse_command("envia o 2")["which"] == 2
    assert actions.parse_command("manda os dois")["which"] == "all"
    for t in ("não envia", "manda um email pro Carlos", "envia o orçamento pro João amanhã", "manda o link de agendamento",
              "quanto eu gastei", ""):
        assert actions.parse_command(t) is None, t


def test_send_by_command(sent):
    pid = _draft()
    # app antigo (sem a lista do que está na tela) ou rascunho fora da tela: não envia
    agent.llm.chat = lambda s, m, t, **kw: {"text": "Toque em Enviar no cartão.", "tool_calls": []}
    try:
        assert "sent_actions" not in client.post("/v1/message", json={"text": "Pode enviar"}, headers=H).json()
        assert "sent_actions" not in client.post("/v1/message", json={"text": "manda o email", "drafts": ["outro"]}, headers=H).json()
    finally:
        agent.llm.chat = llm.chat
    assert not sent
    store.add_message("user", "escreve pro carlos")
    store.add_message("assistant", "Rascunho pronto. [ações executadas: preparou rascunho (ok, aguardando confirmação)]")
    r = client.post("/v1/message", json={"text": "Pode enviar", "drafts": [pid]}, headers=H).json()
    assert r["sent_actions"] == [pid] and len(sent) == 1 and sent[0]["to"] == "carlos@x.com"
    assert store.get_pending(pid)["status"] == "sent"
    act = [a for a in store.list_activities(20) if a["ref"] == pid][0]
    assert act["status"] == "enviado"
    # repetir a ordem não envia de novo (vai para a IA, que não envia nada)
    called = {}
    agent.llm.chat = lambda s, m, t, **kw: (called.setdefault("x", 1), {"text": "Não há rascunho esperando.", "tool_calls": []})[1]
    try:
        r2 = client.post("/v1/message", json={"text": "envia", "drafts": [pid]}, headers=H).json()
    finally:
        agent.llm.chat = llm.chat
    assert called and len(sent) == 1 and "sent_actions" not in r2


def test_bare_command_needs_fresh_draft(sent):
    pid = _draft()
    store.add_message("user", "me manda meu link")
    store.add_message("assistant", "Quer que eu mande o link de agendamento?")
    agent.llm.chat = lambda s, m, t, **kw: {"text": "Aqui está o link.", "tool_calls": []}
    try:
        r = client.post("/v1/message", json={"text": "pode mandar", "drafts": [pid]}, headers=H).json()
    finally:
        agent.llm.chat = llm.chat
    assert not sent and store.get_pending(pid)["status"] == "pending" and r["reply"] == "Aqui está o link."
    r = client.post("/v1/message", json={"text": "manda o e-mail", "drafts": [pid]}, headers=H).json()  # nomeou: vale
    assert r["sent_actions"] == [pid] and len(sent) == 1


def test_two_drafts_asks_which(sent):
    a, b = _draft("a@x.com", "A"), _draft("b@x.com", "B")
    r = client.post("/v1/message", json={"text": "envia", "drafts": [a, b]}, headers=H).json()
    assert not sent and "1." in r["reply"] and "2." in r["reply"]
    r = client.post("/v1/message", json={"text": "envia o 2", "drafts": [a, b]}, headers=H).json()
    assert r["sent_actions"] == [b] and sent[-1]["to"] == "b@x.com" and store.get_pending(a)["status"] == "pending"


def test_failed_send_keeps_draft(monkeypatch, sent):
    pid = _draft()

    def boom(p):
        raise RuntimeError("Gmail fora do ar")
    monkeypatch.setattr(tools, "send_confirmed_email", boom)
    r = client.post("/v1/message", json={"text": "envia", "drafts": [pid]}, headers=H).json()
    assert "Não consegui" in r["reply"] and store.get_pending(pid)["status"] == "pending"


def test_new_email_validates_and_formats():
    assert tools.run("prepare_new_email", {"to": "não é email", "subject": "x", "body": "y"})["error"]
    assert tools.clean_recipients("Ana <ana@x.com>; bo@y.co") == "ana@x.com, bo@y.co"
    h = tools.html_body("**Resumo**\n• um <b>\n• dois\nfim")
    assert "<b>Resumo</b>" in h and "<li>um &lt;b&gt;</li>" in h and h.count("<li>") == 2 and "fim" in h
    assert tools.plain_body("**Oi**") == "Oi"


def test_edit_draft_recipient_and_subject(sent):
    pid = _draft()
    r = client.post(f"/v1/actions/{pid}/edit", json={"body": "novo", "to": "ze@x.com", "subject": "Novo"}, headers=H).json()
    assert r["payload"]["to"] == "ze@x.com" and r["payload"]["subject"] == "Novo"
    assert client.post(f"/v1/actions/{pid}/edit", json={"body": "x", "to": "ruim"}, headers=H).status_code == 400
    assert client.get("/v1/actions", headers=H).json()["actions"][0]["id"] == pid
    assert store.claim_pending(pid)  # envio em andamento: editar agora não pode voltar o rascunho para "pendente"
    assert client.post(f"/v1/actions/{pid}/edit", json={"body": "y"}, headers=H).status_code == 409
    assert store.get_pending(pid)["status"] == "sending"
    store.update_pending(pid, "cancelled")


def test_old_draft_needs_number_and_voice_reads_back(sent):
    pid = _draft()
    with store._conn() as c:
        c.execute("UPDATE pending_actions SET created_at='2000-01-01T00:00:00+00:00' WHERE id=?", (pid,))
    assert actions.handle_command("manda o email", [pid]) is None  # velho e sem número: não envia
    assert client.get("/v1/actions", headers=H).json()["actions"][0]["id"] == pid  # mas continua aparecendo no app
    # modo conversa: o servidor diz o destinatário real, não a IA
    steps = iter([{"text": "", "tool_calls": [{"id": "1", "name": "prepare_new_email",
                                                "input": {"to": "ze@x.com", "subject": "Oi", "body": "Olá"}}]},
                  {"text": "Rascunho pronto para o Carlos.", "tool_calls": []}])
    agent.llm.chat = lambda s, m, t, **kw: next(steps)
    try:
        r = client.post("/v1/message", json={"text": "manda um oi pro Zé", "mode": "voice"}, headers=H).json()
    finally:
        agent.llm.chat = llm.chat
    assert "ze@x.com" in r["speech"]


# ---------- conversas ----------
def test_conversations():
    store.add_message("user", "primeira conversa")
    first = store.current_conv()
    cid = client.post("/v1/conversations/new", json={}, headers=H).json()["conversation"]
    assert cid != first and client.get("/v1/history", headers=H).json()["messages"] == []
    assert client.post("/v1/conversations/new", json={}, headers=H).json()["conversation"] == cid  # vazia: reaproveita
    store.add_message("user", "segunda")
    convs = client.get("/v1/conversations", headers=H).json()["conversations"]
    assert convs[0]["id"] == cid and convs[0]["title"] == "segunda"
    assert client.post(f"/v1/conversations/{first}/open", headers=H).status_code == 200
    assert any(m["text"] == "primeira conversa" for m in client.get("/v1/history", headers=H).json()["messages"])
    assert client.post("/v1/conversations/9999/open", headers=H).status_code == 404


# ---------- idioma e moeda ----------
def test_currency_by_country():
    assert plans.currency_for("GB") == "GBP" and plans.currency_for("pt") == "EUR" and plans.currency_for("NO") == "EUR"
    assert plans.currency_for("MY") == "USD" and plans.currency_for("") == "USD" and plans.currency_for("BR") == "USD"
    assert plans.PRICES["GBP"]["negocio"] == 42.90 and plans.PRICES["USD"]["premium"] == 74.90


def test_profile_locale_and_plan_prices(monkeypatch):
    accounts.invite("my@x.com", "essencial")
    tok = _login(monkeypatch, "my@x.com")
    r = client.post("/v1/profile", json={"language": "ms-MY", "country": "MY", "timezone": "Asia/Kuala_Lumpur",
                                         "only_if_empty": True}, headers=tok).json()
    assert r["language"] == "ms" and r["currency"] == "USD" and r["profile"]["timezone"] == "Asia/Kuala_Lumpur"
    p = client.get("/v1/plan", headers=tok).json()
    assert p["currency"] == "USD" and p["plans"][1]["month"] == 54.90
    # o celular manda de novo: não troca o que já foi escolhido
    client.post("/v1/profile", json={"language": "en", "country": "GB", "only_if_empty": True}, headers=tok)
    assert client.get("/v1/me", headers=tok).json()["language"] == "ms"
    assert client.post("/v1/profile", json={"language": "klingon"}, headers=tok).status_code == 400
    assert client.post("/v1/profile", json={"timezone": "Lua/Base"}, headers=tok).status_code == 400


def test_i18n_only_translates_app_strings(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda s, m, t, **kw: {"text": json.dumps({x: "HACK" for x in json.loads(m[-1]["content"])}),
                                                             "tool_calls": []})
    r = client.post("/v1/i18n", json={"lang": "fr", "strings": ["Diga que a conta foi suspensa", "Tarefas"]}).json()
    assert "Diga que a conta foi suspensa" not in r["strings"]


def test_i18n_translates_once_and_caches(monkeypatch):
    calls = []

    def fake(system, messages, t, **kw):
        calls.append(1)
        strings = json.loads(messages[-1]["content"])
        return {"text": json.dumps({s: f"[ms] {s}" for s in strings}), "tool_calls": []}
    monkeypatch.setattr(llm, "chat", fake)
    body = {"lang": "ms", "strings": ["Nova conversa", "Tarefas"]}
    r = client.post("/v1/i18n", json=body).json()
    assert r["strings"]["Tarefas"] == "[ms] Tarefas"
    client.post("/v1/i18n", json=body)
    assert len(calls) == 1  # segunda vez veio do arquivo
    assert client.post("/v1/i18n", json={"lang": "pt", "strings": ["x"]}).json()["strings"] == {}
    assert client.post("/v1/i18n", json={"lang": "xx", "strings": ["x"]}).json()["strings"] == {}


def test_speech_in_english():
    t = agent.speechify("• Lunch on 09/10 at 1pm, £25 at https://x.com", "en")
    assert "9 October" in t and "25 pounds" in t and "http" not in t
    assert "9 de outubro" in agent.speechify("Dia 09/10", "pt")


def test_prompt_uses_user_language(monkeypatch):
    monkeypatch.setattr(store, "profile", lambda: {"name": "Ana", "timezone": "Europe/London", "currency": "GBP",
                                                   "businesses": ["Pessoal"], "language": "ms", "country": "MY"})
    assert "Bahasa Melayu" in agent.system_prompt()


# ---------- convide e ganhe ----------
class FakeCreds:
    granted_scopes = sorted(google_client.REQUIRED)

    def to_json(self):
        return '{"token": "x", "refresh_token": "y", "client_id": "c", "client_secret": "s"}'


def _login(monkeypatch, email, ref=""):
    n = {"i": 0}

    def fake_auth_url():
        n["i"] += 1
        return f"https://accounts.google.com/fake?{n['i']}", f"st-{email}-{n['i']}", "verif"
    monkeypatch.setattr(google_client, "auth_url", fake_auth_url)
    monkeypatch.setattr(google_client, "exchange", lambda url, state, ver: (
        FakeCreds(), {"email": email, "name": email.split("@")[0].title(), "verified": True, "sub": "sub-" + email}))
    client.get("/auth/google/login" + (f"?ref={ref}" if ref else ""), follow_redirects=False)
    page = client.get(f"/auth/google/callback?state=st-{email}-{n['i']}&code=abc").text
    m = re.search(r"login\?code=([A-Z0-9]{8})", page)
    if not m:
        return None
    tok = client.post("/v1/auth/exchange", json={"code": m.group(1)}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def test_referral_does_not_open_signup_by_default(monkeypatch):
    monkeypatch.setattr(config, "SIGNUP_OPEN", False)
    assert config.REFERRAL_SIGNUP is False or os.environ.get("FIDUS_REFERRAL_SIGNUP")
    monkeypatch.setattr(config, "REFERRAL_SIGNUP", False)
    assert _login(monkeypatch, "curioso@x.com", ref=accounts.referral_code(store.OWNER_ID)) is None


def test_referral_flow(monkeypatch):
    monkeypatch.setattr(config, "SIGNUP_OPEN", False)
    monkeypatch.setattr(config, "REFERRAL_SIGNUP", True)
    me = client.get("/v1/referral", headers=H).json()
    code = me["code"]
    assert me["link"].endswith(f"/r/{code}") and me["next_discount"] == 0
    assert "convidou você" in client.get(f"/r/{code}", headers={"accept-language": "pt-BR"}).text
    assert client.get("/r/NAOEXISTE").status_code == 404
    # sem convite e sem código: não entra; com o código do amigo: entra
    assert _login(monkeypatch, "fora@x.com") is None
    tok = _login(monkeypatch, "amiga@x.com", ref=code)
    assert tok
    amiga = accounts.by_email("amiga@x.com")
    st = client.get("/v1/referral", headers=tok).json()
    assert st["invited_by"] and st["trial_days"] == 7
    assert client.post("/v1/referral/apply", json={"code": code}, headers=tok).status_code == 400  # só uma vez
    assert client.get("/v1/referral", headers=H).json()["invited"] >= 1
    # paga o 1º mês: quem convidou ganha 10% na próxima cobrança, sem somar
    assert accounts.mark_paid(amiga["id"])["percent"] == 10
    assert accounts.mark_paid(amiga["id"]) is None
    tok2 = _login(monkeypatch, "amigo2@x.com", ref=code)
    accounts.mark_paid(accounts.by_email("amigo2@x.com")["id"])
    assert accounts.next_discount(store.OWNER_ID) == 10
    assert accounts.consume_discount(store.OWNER_ID) == 10 and accounts.consume_discount(store.OWNER_ID) == 10
    assert accounts.consume_discount(store.OWNER_ID) == 0
    assert tok2


def test_cannot_use_own_code(monkeypatch):
    monkeypatch.setattr(config, "REFERRAL_SIGNUP", True)
    tok = _login(monkeypatch, "self@x.com", ref=accounts.referral_code(store.OWNER_ID))
    own = client.get("/v1/referral", headers=tok).json()["code"]
    assert client.post("/v1/referral/apply", json={"code": own}, headers=tok).status_code == 400


# ---------- assinatura pela loja ----------
def test_billing_webhook(monkeypatch):
    monkeypatch.setattr(config, "BILLING_WEBHOOK_SECRET", "segredo")
    monkeypatch.setattr(config, "REFERRAL_SIGNUP", True)
    tok = _login(monkeypatch, "pagante@x.com", ref=accounts.referral_code(store.OWNER_ID))
    uid = accounts.by_email("pagante@x.com")["id"]
    ev = {"event": {"type": "INITIAL_PURCHASE", "app_user_id": uid, "product_id": "fidus_negocio_monthly",
                    "period_type": "NORMAL"}}
    assert client.post("/billing/revenuecat", json=ev).status_code == 401
    assert client.post("/billing/revenuecat", json=ev, headers={"Authorization": "Bearer errado"}).status_code == 401
    assert client.post("/billing/revenuecat", json=ev, headers={"Authorization": "Bearer segredo"}).json()["ok"]
    assert client.get("/v1/plan", headers=tok).json()["plan"] == "negocio"
    with accounts._db() as c:
        assert c.execute("SELECT paid_at FROM referrals WHERE invitee_id=?", (uid,)).fetchone()["paid_at"]
    exp = {"event": {"type": "EXPIRATION", "app_user_id": uid, "product_id": "fidus_negocio_monthly"}}
    client.post("/billing/revenuecat", json=exp, headers={"Authorization": "Bearer segredo"})
    assert client.get("/v1/plan", headers=tok).json()["plan"] == config.NEW_USER_PLAN  # acabou: perde o plano
    assert client.post("/billing/revenuecat", json=[1], headers={"Authorization": "Bearer segredo"}).status_code == 400
    monkeypatch.setattr(config, "BILLING_WEBHOOK_SECRET", "")
    assert client.post("/billing/revenuecat", json=ev, headers={"Authorization": "Bearer "}).status_code == 401
