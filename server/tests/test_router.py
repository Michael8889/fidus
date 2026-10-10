"""v0.10: boas-vindas em conversa, dicas por e-mail (leads), parceiros, pt-PT, privacidade/termos, exportar por e-mail."""
import json
import os
import re
import tempfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

from fastapi.testclient import TestClient  # noqa: E402

from app import agent, config, llm, store  # noqa: E402


def _on(monkeypatch):
    import importlib
    importlib.reload(llm)  # outros testes trocam llm.chat sem devolver
    monkeypatch.setattr(config, "LLM_MODEL_CHEAP", "gemini:gemini-2.5-flash")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "x")


def test_split_spec():
    assert llm.split_spec("gemini:gemini-2.5-flash") == ("gemini", "gemini-2.5-flash")
    assert llm.split_spec("claude-haiku-4-5-20251001") == ("anthropic", "claude-haiku-4-5-20251001")
    assert llm.split_spec("openai:gpt-5-mini") == ("openai_compat", "gpt-5-mini")


def test_router_off_without_cheap_model(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL_CHEAP", None)
    assert agent.route("marca dentista amanhã às 10") == "smart"


def test_router_simple_vs_complex(monkeypatch):
    _on(monkeypatch)
    monkeypatch.setattr(store, "recent_pending", lambda hours=2: 0)
    assert agent.route("marca dentista amanhã às 10") == "cheap"
    assert agent.route("paguei 45 euros de gasolina") == "cheap"
    assert agent.route("me lembra de pagar a luz dia 5") == "cheap"
    assert agent.route("o que tenho amanhã?") == "cheap"
    assert agent.route("manda um e-mail pro João dizendo que atraso") == "smart"
    assert agent.route("responde o cliente da proposta") == "smart"
    assert agent.route("marca reunião e depois avisa o Pedro") == "smart"
    assert agent.route("pesquisa o preço do voo para Lisboa") == "smart"
    assert agent.route("anota esse recibo", image=True) == "smart"
    assert agent.route("x" * 300) == "smart"


def test_router_keeps_smart_with_fresh_draft(monkeypatch):
    _on(monkeypatch)
    import sqlite3  # noqa: F401
    with store._conn() as c:  # rascunhos de outros testes não contam aqui
        c.execute("UPDATE pending_actions SET status='cancelled' WHERE status='pending'")
    pid = store.create_pending("email", {"to": "a@b.c", "subject": "s", "body": "b"})
    try:
        assert agent.route("ok") == "smart"
    finally:
        store.update_pending(pid, "cancelled")
    assert agent.route("marca dentista amanhã") == "cheap"


def test_fallback_when_main_model_fails(monkeypatch):
    _on(monkeypatch)
    calls = []

    def fake(spec, system, messages, tools, web_search):
        calls.append(spec)
        if spec == config.LLM_MODEL:
            raise RuntimeError("credit balance is too low")
        return {"text": "ok", "tool_calls": [], "usage": {"model": spec, "calls": 1}}
    monkeypatch.setattr(llm, "_call", fake)
    out = llm.chat("sys", [{"role": "user", "content": "oi"}], [])
    assert out["text"] == "ok" and out["fallback"] == "gemini:gemini-2.5-flash"
    assert calls == [config.LLM_MODEL, "gemini:gemini-2.5-flash"]


def test_gemini_price_known():
    assert llm.cost_usd({"model": "gemini-2.5-flash", "input": 1_000_000, "output": 0}) == 0.25
    assert llm.cost_usd({"model": "gemini-2.5-flash-lite", "input": 1_000_000, "output": 0}) == 0.10


def test_cheap_model_that_claims_without_tool_is_redone_by_smart(monkeypatch):
    _on(monkeypatch)
    monkeypatch.setattr(store, "recent_pending", lambda hours=2: 0)
    seen = []

    def fake_chat(system, messages, tools_, web_search=True, model=None):
        seen.append(model)
        if len(seen) == 1:
            return {"text": "Pronto, marquei na sua agenda.", "tool_calls": [], "usage": {}}
        return {"text": "Não marquei nada ainda: qual horário?", "tool_calls": [], "usage": {}}
    monkeypatch.setattr(agent.llm, "chat", fake_chat)
    out = agent.handle("marca dentista amanhã")
    assert seen == ["gemini:gemini-2.5-flash", None]
    assert "horário" in out["reply"]


def test_split_speech_first_sentence():
    first, rest = agent.split_speech("Pronto, marquei o dentista amanhã às dez da manhã na clínica. "
                                     "Também deixei um lembrete uma hora antes para você não esquecer de sair cedo.")
    assert first.endswith("clínica.") and rest.startswith("Também")
    assert agent.split_speech("Feito.") == ("Feito.", "")


def test_voice_parts_sends_rest_only_with_audio(monkeypatch):
    long = ("Pronto, marquei o dentista amanhã às dez da manhã na clínica. "
            "Também deixei um lembrete uma hora antes para você não esquecer de sair cedo.")
    monkeypatch.setattr(agent, "_voice", lambda s: "MP3:" + s[:10])
    out = agent._voice_parts(long)
    assert out["speech_audio"] == "MP3:Pronto, ma" and out["speech_rest"].startswith("Também")
    monkeypatch.setattr(agent, "_voice", lambda s: None)
    assert agent._voice_parts(long) == {"speech_audio": None}


def test_gemini_extra_fields_round_trip(monkeypatch):
    import importlib
    import types
    importlib.reload(llm)
    sent = []

    class TC:
        id = "abc"
        function = types.SimpleNamespace(name="add_expense", arguments='{"amount": 1}')
        model_extra = {"extra_content": {"google": {"thought_signature": "SIG"}}}

    class Client:
        def __init__(self, **kw):
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))

        def create(self, **kw):
            sent.append(kw)
            msg = types.SimpleNamespace(content="", tool_calls=[TC()])
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=None)
    import openai
    monkeypatch.setattr(openai, "OpenAI", Client)
    out = llm._openai_compat("sys", [{"role": "user", "content": "x"}], [], "gemini-3.8-flash", "u", "k")
    assert out["tool_calls"][0]["extra"]["extra_content"]["google"]["thought_signature"] == "SIG"
    llm._openai_compat("sys", [{"role": "user", "content": "x"},
                               {"role": "assistant", "content": "", "tool_calls": out["tool_calls"]},
                               {"role": "tool", "tool_call_id": "abc", "content": "{}"}], [], "gemini-3.8-flash", "u", "k")
    back = sent[1]["messages"][2]["tool_calls"][0]
    assert back["extra_content"]["google"]["thought_signature"] == "SIG" and back["id"] == "abc"


def test_route_distance_with_mocked_maps(monkeypatch):
    import requests
    from app import tools

    class R:
        def __init__(self, j):
            self.j = j

        def raise_for_status(self):
            pass

        def json(self):
            return self.j

    def fake_get(url, params=None, timeout=None, headers=None):
        if "nominatim" in url:
            return R([{"lat": "40.2", "lon": "-8.26", "display_name": params["q"]}])
        return R({"routes": [{"distance": 2512000, "duration": 88200}]})
    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda s: None)
    out = tools._route_distance("Vila Nova de Poiares", "Roma")
    assert out["km"] == 2512 and out["drive_time"] == "24 h 30 min" and "google.com/maps/dir" in out["maps_link"]


def test_partial_text_and_status_while_answering(monkeypatch):
    importlib = __import__("importlib")
    importlib.reload(llm)
    monkeypatch.setattr(config, "LLM_MODEL_CHEAP", None)
    monkeypatch.setattr(store, "recent_pending", lambda hours=2: 0)
    seen_status = []
    calls = {"n": 0}

    def fake_chat(system, messages, tools_, web_search=True, model=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"text": "", "tool_calls": [{"id": "t1", "name": "list_calendar_events",
                                               "input": {"time_min": "a", "time_max": "b"}}], "usage": {}}
        llm._emit("Amanhã você ")
        llm._emit("tem dentista às 10.")
        return {"text": "Amanhã você tem dentista às 10.", "tool_calls": [], "usage": {}}

    def fake_run(name, args):
        seen_status.append(agent.partial("rq1")["status"])
        return {"events": []}
    monkeypatch.setattr(agent.llm, "chat", fake_chat)
    monkeypatch.setattr(agent.tools, "run", fake_run)
    out = agent.handle("o que tenho amanhã?", request_id="rq1")
    p = agent.partial("rq1")
    assert seen_status == ["Vendo sua agenda…"]
    assert p["done"] and p["text"] == "Amanhã você tem dentista às 10." and out["reply"].startswith("Amanhã")
    assert agent.partial("nao-existe") == {"text": "", "status": "", "done": False}


def test_openai_stream_assembles_text_and_tool_calls(monkeypatch):
    import importlib
    import types
    importlib.reload(llm)
    got = []
    tok = llm.STREAM.set(lambda p: got.append(p))
    NS = types.SimpleNamespace

    def ch(content=None, tcs=None, usage=None):
        return NS(usage=usage, choices=[NS(delta=NS(content=content, tool_calls=tcs))] if (content or tcs) else [])
    chunks = [ch("Vou "), ch("ver."),
              ch(tcs=[NS(index=0, id="c1", function=NS(name="add_", arguments='{"amo'), model_extra={"extra_content": {"g": 1}})]),
              ch(tcs=[NS(index=0, id=None, function=NS(name="expense", arguments='unt": 5}'), model_extra=None)]),
              ch(usage=NS(prompt_tokens=10, completion_tokens=3))]

    class Client:
        chat = NS(completions=NS(create=lambda **kw: iter(chunks)))
    try:
        out = llm._openai_stream(Client(), "gemini-3.8-flash", [], {})
    finally:
        llm.STREAM.reset(tok)
    assert out["text"] == "Vou ver." and got == ["Vou ", "ver."]
    assert out["tool_calls"][0]["name"] == "add_expense" and out["tool_calls"][0]["input"] == {"amount": 5}
    assert out["tool_calls"][0]["extra"] == {"extra_content": {"g": 1}} and out["usage"]["input"] == 10
