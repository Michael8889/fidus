"""v0.13.2: velocidade — Gemini pensando o mínimo, status ao vivo também na voz, transcrição rápida com reserva local."""
import os
import tempfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

from app import agent, config, llm, store, transcribe  # noqa: E402


def test_gemini_uses_minimal_thinking_and_falls_back(monkeypatch):
    import importlib
    importlib.reload(llm)
    seen = []

    class Comp:
        def create(self, **kw):
            seen.append(kw.get("reasoning_effort"))
            if kw.get("reasoning_effort") == "minimal":
                raise RuntimeError("Invalid reasoning_effort for this model")

            class M:
                content, tool_calls = "ok", None

            class C:
                message = M()

            class R:
                choices, usage = [C()], None
            return R()

    class Client:
        def __init__(self, **_):
            self.chat = type("X", (), {"completions": Comp()})()
    import openai
    monkeypatch.setattr(openai, "OpenAI", Client)
    out = llm._openai_compat("sys", [{"role": "user", "content": "oi"}], [], "gemini-3.8-flash", "u", "k", gemini=True)
    assert out["text"] == "ok" and seen == ["minimal", "low"]
    llm._openai_compat("sys", [{"role": "user", "content": "oi"}], [], "gemini-3.8-flash", "u", "k", gemini=True)
    assert seen[-1] == "low"  # lembra o nível que funcionou
    llm._openai_compat("sys", [{"role": "user", "content": "oi"}], [], "gpt-5-mini", "u", "k")
    assert seen[-1] is None  # outros provedores: sem o parâmetro


def test_partial_shows_listening_then_transcript_then_tool_status():
    agent.partial_set("r-voz", "_listen")
    assert agent.partial("r-voz")["status"] == "Ouvindo seu áudio…"
    agent.partial_set("r-voz", "_", transcript="marca o contador sexta")
    buf, cb = agent._partial_start("r-voz")
    assert agent.partial("r-voz")["transcript"] == "marca o contador sexta"
    cb({"status": "web_search"})
    assert agent.partial("r-voz")["status"] == "Pesquisando na web…"
    cb("Achei ")
    assert agent.partial("r-voz")["text"] == "Achei " and agent.partial("r-voz")["status"] == ""


def test_fast_transcription_falls_back_to_local(monkeypatch, tmp_path):
    f = tmp_path / "a.m4a"
    f.write_bytes(b"x" * 100)
    monkeypatch.setattr(config, "OPENAI_API_KEY", "k")
    monkeypatch.setattr(config, "TRANSCRIBE", "auto")
    import requests

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"text": " marca o contador ", "usage": {"input_tokens": 50, "output_tokens": 5}}
    calls = []
    monkeypatch.setattr(requests, "post", lambda url, **kw: calls.append(kw["data"]) or R())
    assert transcribe.transcribe_fast(str(f), "pt-BR") == "marca o contador"
    assert calls[0]["language"] == "pt" and calls[0]["model"] == config.TRANSCRIBE_MODEL

    def boom(url, **kw):
        raise requests.HTTPError("429 sem crédito")
    monkeypatch.setattr(requests, "post", boom)
    monkeypatch.setattr(transcribe, "transcribe", lambda path, prompt=None, beam_size=5: "local ok")
    assert transcribe.transcribe_fast(str(f), "pt") == "local ok"
    monkeypatch.setattr(config, "TRANSCRIBE", "local")
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("não devia chamar")))
    assert transcribe.transcribe_fast(str(f), "pt") == "local ok"
