"""v0.10: boas-vindas em conversa, dicas por e-mail (leads), parceiros, pt-PT, privacidade/termos, exportar por e-mail."""
import json
import os
import re
import tempfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

from fastapi.testclient import TestClient  # noqa: E402

from app import config, main, realtime, store, tools  # noqa: E402

client = TestClient(main.app)


def _key(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(config, "REALTIME_ON", True)


def test_disabled_without_key(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", None)
    assert not realtime.enabled()
    assert realtime.session()["error"]


def test_session_sends_rules_tools_and_hides_company_key(monkeypatch):
    _key(monkeypatch)
    sent = {}

    class R:
        status_code = 200
        text = ""

        def json(self):
            return {"value": "ek_temp", "expires_at": 123}

    def fake_post(url, json=None, timeout=None, headers=None):
        sent.update(url=url, body=json, headers=headers)
        return R()
    monkeypatch.setattr(realtime.requests, "post", fake_post)
    out = realtime.session()
    assert out["client_secret"] == "ek_temp" and "sk-test" not in str(out)
    s = sent["body"]["session"]
    assert sent["url"].endswith("/realtime/client_secrets")
    assert s["model"] == config.REALTIME_MODEL and "TEMPO REAL" in s["instructions"]
    names = {t["name"] for t in s["tools"]}
    assert "add_expense" in names and all(t["type"] == "function" for t in s["tools"])
    # nenhuma ferramenta da IA envia e-mail (CLAUDE.md): só prepara rascunho
    assert not any(n.startswith("send") for n in names)
    assert "sk-test" in sent["headers"]["Authorization"] and sent["headers"]["OpenAI-Safety-Identifier"]


def test_tool_runs_and_turn_is_saved_with_actions(monkeypatch):
    _key(monkeypatch)
    monkeypatch.setattr(tools, "run", lambda name, args: {"ok": True, "expense_id": 1, "amount": 45.0, "currency": "EUR",
                                                         "category": "combustível", "business": "Pessoal", "date": "2026-10-10"})
    out = realtime.run_tool("add_expense", '{"amount": 45, "currency": "EUR", "category": "combustível"}')
    assert '"ok": true' in out["output"]
    realtime.save_turn("paguei 45 de gasolina", "Anotei 45 euros de gasolina.")
    last = store.recent_messages(2)
    assert last[-2]["content"] == "paguei 45 de gasolina"
    assert "Anotei" in last[-1]["content"] and "ações executadas" in last[-1]["content"]


def test_unknown_tool_is_refused(monkeypatch):
    _key(monkeypatch)
    out = realtime.run_tool("send_email_now", "{}")
    assert "desconhecida" in out["output"]


def test_usage_recorded_with_bounds(monkeypatch):
    calls = []
    monkeypatch.setattr(store, "add_usage", lambda u: calls.append(u))
    realtime.record_usage({"input_tokens": 1000, "output_tokens": 500, "input_token_details": {"cached_tokens": 200}})
    realtime.record_usage({"input_tokens": "x", "output_tokens": 10**9})
    assert calls[0]["input"] == 800 and calls[0]["cache_read"] == 200 and calls[0]["output"] == 500
    assert calls[1]["input"] == 0 and calls[1]["output"] == 500_000
