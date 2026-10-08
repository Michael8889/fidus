"""v0.9.5: carteiras nos gastos, resposta falada aos áudios, modelo leve para cumprimentos, tradução em blocos."""
import os
import tempfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

from fastapi.testclient import TestClient  # noqa: E402

from app import agent, config, i18n, main, store, tools  # noqa: E402

client = TestClient(main.app)
H = {"Authorization": "Bearer t"}


# ---------- carteiras ----------
def test_wallet_currency_filter_and_undo():
    r = client.post("/v1/wallets", json={"name": "Pessoal BR 95", "currency": "brl"}, headers=H)
    assert r.status_code == 200, r.text
    ws = {w["name"]: w["currency"] for w in r.json()["wallets"]}
    assert ws["Pessoal BR 95"] == "BRL"

    # gasto sem moeda dita entra na moeda da carteira
    client.post("/v1/wallets", json={"name": "HomB UK 95", "currency": "GBP"}, headers=H)
    month = "2026-03"
    out = tools.run("add_expense", {"amount": 50, "category": config.CATEGORIES[0], "business": "pessoal br 95",
                                    "date": f"{month}-10"})
    assert out["ok"] and out["currency"] == "BRL" and out["business"] == "Pessoal BR 95"
    out2 = tools.run("add_expense", {"amount": 20, "category": config.CATEGORIES[0], "business": "HomB UK 95",
                                     "date": f"{month}-11"})
    assert out2["currency"] == "GBP"

    all_ = client.get(f"/v1/expenses/summary?month={month}", headers=H).json()
    tot = {w["name"]: w["totals"] for w in all_["wallets"]}
    assert tot["Pessoal BR 95"] == {"BRL": 50.0} and tot["HomB UK 95"] == {"GBP": 20.0}
    one = client.get(f"/v1/expenses/summary?month={month}&wallet=Pessoal%20BR%2095", headers=H).json()
    assert one["wallet"] == "Pessoal BR 95" and one["totals_by_currency"] == {"BRL": 50.0}
    assert {w["name"] for w in one["wallets"]} >= {"Pessoal BR 95", "HomB UK 95"}  # botões continuam todos

    # criar carteira aparece na Atividade e pode ser desfeito
    acts = client.get("/v1/activity", headers=H).json()["items"]
    a = next(x for x in acts if x["kind"] == "wallet_added" and "Pessoal BR 95" in x["title"])
    assert a["can_undo"]
    assert client.post(f"/v1/activity/{a['id']}/undo", headers=H).json()["status"] == "desfeito"
    names = [w["name"] for w in client.get("/v1/wallets", headers=H).json()["wallets"]]
    assert "Pessoal BR 95" not in names
    # o gasto continua guardado e aparece como carteira antiga
    again = client.get(f"/v1/expenses/summary?month={month}", headers=H).json()
    old = next(w for w in again["wallets"] if w["name"] == "Pessoal BR 95")
    assert old.get("archived") and old["totals"] == {"BRL": 50.0}

    # remover e desfazer a remoção traz de volta com a moeda
    assert client.post("/v1/wallets/remove", json={"name": "HomB UK 95"}, headers=H).status_code == 200
    acts = client.get("/v1/activity", headers=H).json()["items"]
    rm = next(x for x in acts if x["kind"] == "wallet_removed" and "HomB UK 95" in x["title"])
    client.post(f"/v1/activity/{rm['id']}/undo", headers=H)
    assert {"name": "HomB UK 95", "currency": "GBP"} in client.get("/v1/wallets", headers=H).json()["wallets"]


def test_wallet_bad_currency_and_last_wallet():
    assert client.post("/v1/wallets", json={"name": "X95", "currency": "reais"}, headers=H).status_code == 400
    ws = [w["name"] for w in client.get("/v1/wallets", headers=H).json()["wallets"]]
    for n in ws[1:]:
        client.post("/v1/wallets/remove", json={"name": n}, headers=H)
    assert client.post("/v1/wallets/remove", json={"name": ws[0]}, headers=H).status_code == 409
    for n in ws[1:]:  # devolve as carteiras para os outros testes
        client.post("/v1/wallets", json={"name": n}, headers=H)


def test_context_lists_wallets_with_currency():
    client.post("/v1/wallets", json={"name": "Business PT 95", "currency": "EUR"}, headers=H)
    assert "Business PT 95 (EUR)" in agent._context()


def test_export_wallet_month():
    month = "2026-03"
    r = client.post("/v1/expenses/export", json={"month": month, "wallet": "HomB UK 95"}, headers=H).json()
    assert r.get("locked") or (r["url"] and "HomB UK 95" in r["title"])


# ---------- voz ----------
def test_light_model_only_for_greetings(monkeypatch):
    seen = []

    def fake(system, messages, tools_, **kw):
        seen.append(kw.get("model"))
        return {"text": "Olá!", "tool_calls": []}
    monkeypatch.setattr(agent.llm, "chat", fake)
    client.post("/v1/message", json={"text": "Oi Fidus!"}, headers=H)
    client.post("/v1/message", json={"text": "ok"}, headers=H)  # pode ser confirmação: modelo principal
    client.post("/v1/message", json={"text": "obrigado"}, headers=H)
    assert seen == [config.LLM_MODEL_LIGHT, None, config.LLM_MODEL_LIGHT]


def test_recorded_audio_can_get_spoken_reply(monkeypatch):
    monkeypatch.setattr(agent.llm, "chat", lambda s, m, t, **kw: {"text": "**Tudo certo** por aqui.", "tool_calls": []})
    assert agent.handle("lista", kind="voz")["speech"] is None
    spoken = agent.handle("lista", kind="voz", speak=True)["speech"]
    assert spoken and "*" not in spoken


# ---------- tradução ----------
def test_translation_retries_in_smaller_blocks(monkeypatch, tmp_path):
    keys = [f"Texto número {i}" for i in range(60)]
    monkeypatch.setattr(i18n, "_allowed", lambda: set(keys))
    monkeypatch.setattr(i18n, "_path", lambda lang: str(tmp_path / f"{lang}.json"))
    calls = []

    def ask(lang, chunk):
        calls.append(len(chunk))
        if len(chunk) > 10:
            return {}  # bloco grande: a IA "estoura" e não devolve nada
        return {k: k.replace("Texto número", "Text number") for k in chunk}
    monkeypatch.setattr(i18n, "_ask", ask)
    out = i18n.translate("en", keys)
    assert len(out) == 60 and out["Texto número 7"] == "Text number 7"
    assert max(calls) <= i18n.CHUNK


# ---------- botão parar ----------
def test_cancel_stops_before_running_tools(monkeypatch):
    ran = []
    monkeypatch.setattr(tools, "run", lambda name, args: ran.append(name) or {"ok": True})

    def fake(system, messages, tools_, **kw):
        agent.cancel("req-95")  # a pessoa toca em parar enquanto a IA pensa
        return {"text": "", "tool_calls": [{"id": "c1", "name": "add_task", "input": {"title": "x"}}]}
    monkeypatch.setattr(agent.llm, "chat", fake)
    r = client.post("/v1/message", json={"text": "cria tarefa x", "request_id": "req-95"}, headers=H).json()
    assert r["cancelled"] and ran == []


def test_cancel_endpoint_marks_request():
    assert client.post("/v1/cancel", json={"request_id": "abc95"}, headers=H).json()["ok"]
    assert agent._cancelled("abc95") and not agent._cancelled("other")
