"""Testa o fluxo sem Google nem IA reais (tudo simulado)."""
import os
import tempfile

os.environ["FIDUS_DB_PATH"] = tempfile.mktemp(suffix=".db")
os.environ["FIDUS_APP_TOKEN"] = "t"

from fastapi.testclient import TestClient  # noqa: E402

from app import agent, llm, main, tools  # noqa: E402

H = {"Authorization": "Bearer t"}
client = TestClient(main.app)
sent: list[dict] = []


def fake_run(name, args):
    if name == "search_emails":
        return {"emails": [{"id": "m1", "from": "Carlos <c@x.com>", "subject": "Orçamento"}]}
    if name == "prepare_email_reply":
        pid = tools.store.create_pending("send_email", {"to": "c@x.com", "subject": "Re: Orçamento", "body": args["body"]})
        return {"ok": True, "pending_action_id": pid}
    if name == "create_calendar_event":
        return {"ok": True, "event_id": "e1", "title": args["title"], "start": args["start"]}
    return {}


def script(steps):
    it = iter(steps)
    return lambda system, messages, t: next(it)


_ORIG = {}


def setup_module():
    _ORIG.update(run=tools.run, send=tools.send_confirmed_email, chat=llm.chat)
    tools.run = fake_run
    agent.tools.run = fake_run
    tools.send_confirmed_email = lambda p: (sent.append(p), {"ok": True, "message_id": "s1"})[1]
    main.tools.send_confirmed_email = tools.send_confirmed_email


def teardown_module():
    tools.run = _ORIG["run"]
    tools.send_confirmed_email = _ORIG["send"]
    llm.chat = _ORIG["chat"]


def test_requires_token():
    assert client.post("/v1/message", json={"text": "oi"}).status_code == 401


def test_calendar_event_created():
    agent.llm.chat = script([
        {"text": "", "tool_calls": [{"id": "1", "name": "create_calendar_event",
                                      "input": {"title": "Visita técnica", "start": "2026-10-12T16:00:00",
                                                "end": "2026-10-12T17:00:00"}}]},
        {"text": "Marcado: visita técnica, 12/10 às 16h.", "tool_calls": []},
    ])
    r = client.post("/v1/message", json={"text": "marca visita técnica dia 12 às 4pm"}, headers=H).json()
    assert r["events"][0]["title"] == "Visita técnica"
    assert "16h" in r["reply"]


def test_email_only_sent_after_confirm():
    agent.llm.chat = script([
        {"text": "", "tool_calls": [{"id": "1", "name": "search_emails", "input": {"query": "from:carlos"}}]},
        {"text": "", "tool_calls": [{"id": "2", "name": "prepare_email_reply",
                                      "input": {"message_id": "m1", "body": "Aceito, pagamento em 30 dias."}}]},
        {"text": "Rascunho pronto para revisar.", "tool_calls": []},
    ])
    r = client.post("/v1/message", json={"text": "responde o Carlos aceitando"}, headers=H).json()
    pid = r["pending_actions"][0]["id"]
    assert sent == []  # nada enviado ainda

    client.post(f"/v1/actions/{pid}/edit", json={"body": "Aceito. Pagamento em 30 dias, ok?"}, headers=H)
    ok = client.post(f"/v1/actions/{pid}/confirm", headers=H).json()
    assert ok["status"] == "sent"
    assert sent[0]["body"] == "Aceito. Pagamento em 30 dias, ok?"

    # não pode enviar duas vezes
    assert client.post(f"/v1/actions/{pid}/confirm", headers=H).status_code == 409


def test_cancel():
    pid = tools.store.create_pending("send_email", {"to": "a", "subject": "b", "body": "c"})
    assert client.post(f"/v1/actions/{pid}/cancel", headers=H).json()["status"] == "cancelled"
    assert client.post(f"/v1/actions/{pid}/confirm", headers=H).status_code == 409


def test_activity_and_undo():
    deleted = []
    tools.run_delete_event = lambda eid: deleted.append(eid)
    main.tools.run_delete_event = tools.run_delete_event
    agent.llm.chat = script([
        {"text": "", "tool_calls": [{"id": "1", "name": "create_calendar_event",
                                      "input": {"title": "Dentista", "start": "2026-10-15T09:00:00",
                                                "end": "2026-10-15T10:00:00"}}]},
        {"text": "Marcado.", "tool_calls": []},
    ])
    client.post("/v1/message", json={"text": "marca dentista"}, headers=H)
    items = client.get("/v1/activity", headers=H).json()["items"]
    ev = [i for i in items if i["kind"] == "event_created" and i["title"] == "Dentista"][0]
    assert ev["can_undo"] and ev["ref"] == "e1"
    assert client.post(f"/v1/activity/{ev['id']}/undo", headers=H).json()["status"] == "desfeito"
    assert deleted == ["e1"]
    assert client.post(f"/v1/activity/{ev['id']}/undo", headers=H).status_code == 409


def test_expense_flow_and_undo():
    import app.tools as T  # funções reais de gastos; agenda continua simulada
    orig = fake_run

    def run_with_expenses(name, args):
        if name in ("add_expense", "summarize_expenses", "delete_expense"):
            fn = {"add_expense": T._add_expense, "summarize_expenses": T._summarize_expenses,
                  "delete_expense": T._delete_expense}[name]
            return fn(**args)
        return orig(name, args)

    agent.tools.run = run_with_expenses
    agent.llm.chat = script([
        {"text": "", "tool_calls": [{"id": "1", "name": "add_expense",
                                      "input": {"amount": 60, "currency": "gbp", "category": "combustível",
                                                "business": "HomB", "merchant": "Shell", "date": "2026-10-06"}}]},
        {"text": "Lançado.", "tool_calls": []},
    ])
    client.post("/v1/message", json={"text": "paguei 60 libras de gasolina homb"}, headers=H)
    s = T._summarize_expenses("2026-10-01", "2026-10-31")
    assert s["totals_by_currency"] == {"GBP": 60.0} and s["by_business"]["HomB"]["GBP"] == 60.0

    items = client.get("/v1/activity", headers=H).json()["items"]
    ex = [i for i in items if i["kind"] == "expense_added"][0]
    assert ex["can_undo"] and "60.00 GBP" in ex["title"]
    assert client.post(f"/v1/activity/{ex['id']}/undo", headers=H).json()["status"] == "desfeito"
    assert T._summarize_expenses("2026-10-01", "2026-10-31")["count"] == 0


def test_summary_never_mixes_currencies():
    import app.tools as T
    T._add_expense(10, "alimentação", "Pessoal", currency="EUR", date="2026-09-02")
    T._add_expense(20, "alimentação", "Pessoal", currency="GBP", date="2026-09-03")
    s = T._summarize_expenses("2026-09-01", "2026-09-30", category="alimentação")
    assert s["totals_by_currency"] == {"EUR": 10.0, "GBP": 20.0}


def test_photo_receipt_saved_and_linked(tmp_path):
    import base64
    import app.tools as T
    from app import config
    config.RECEIPTS_DIR = str(tmp_path)
    seen = {}

    def chat(system, messages, t):
        if not seen:
            seen["content"] = messages[-1]["content"]
            return {"text": "", "tool_calls": [{"id": "1", "name": "add_expense", "input": {
                "amount": 12.5, "currency": "GBP", "category": "alimentação", "business": "Pessoal",
                "merchant": "Pret", "attach_receipt": True}}]}
        return {"text": "Lançado 12,50 GBP no Pret.", "tool_calls": []}

    agent.llm.chat = chat
    agent.tools.run = lambda n, a: T._add_expense(**a) if n == "add_expense" else {}
    img = base64.b64encode(b"\xff\xd8fakejpeg").decode()
    r = client.post("/v1/photo", json={"image_b64": img}, headers=H).json()
    assert "12,50" in r["reply"]
    assert seen["content"][0]["type"] == "image"
    rows = T.store.query_expenses("2000-01-01", "2100-01-01", business="Pessoal")
    pret = [x for x in rows if x["merchant"] == "Pret"][0]
    assert pret["receipt_path"] and os.path.exists(pret["receipt_path"])
