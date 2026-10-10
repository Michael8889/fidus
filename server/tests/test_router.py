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
