"""Adaptador Anthropic: busca na web incluída, e desligada sozinha se a conta não tiver."""
import anthropic
import httpx

from app import config, llm


class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none=True):
        return dict(self.__dict__)


class Resp:
    def __init__(self, content, stop="end_turn"):
        self.content, self.stop_reason = content, stop


def fake_client(calls, fail_web=False):
    class C:
        def __init__(self, **kw):
            self.messages = self

        def create(self, **kw):
            calls.append(kw)
            if fail_web and any(t.get("name") == "web_search" for t in kw.get("tools", [])):
                req = httpx.Request("POST", "https://x")
                raise anthropic.BadRequestError("web_search is not enabled", response=httpx.Response(400, request=req), body=None)
            if len(calls) == 1 and not fail_web:
                return Resp([Block(type="server_tool_use", id="s1", name="web_search", input={"query": "pneu"})], "pause_turn")
            return Resp([Block(type="text", text="Achei 3 lojas.")])
    return C


def test_web_search_and_pause_turn(monkeypatch):
    calls = []
    monkeypatch.setattr(anthropic, "Anthropic", fake_client(calls))
    monkeypatch.setattr(config, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(config, "WEB_SEARCH", True)
    out = llm._anthropic("sys", [{"role": "user", "content": "preço pneu"}], [])
    assert out["text"] == "Achei 3 lojas." and len(calls) == 2
    assert any(t.get("type") == "web_search_20250305" for t in calls[0]["tools"])


def test_web_search_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(anthropic, "Anthropic", fake_client(calls, fail_web=True))
    monkeypatch.setattr(config, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(config, "WEB_SEARCH", True)
    out = llm._anthropic("sys", [{"role": "user", "content": "oi"}], [])
    assert out["text"] == "Achei 3 lojas." and config.WEB_SEARCH is False


def test_cache_marks_fixed_prompt_and_usage_cost(monkeypatch):
    calls = []

    class U:
        input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens = 1000, 200, 0, 9000
        server_tool_use = None

    class C:
        def __init__(self, **kw):
            self.messages = self

        def create(self, **kw):
            calls.append(kw)
            r = Resp([Block(type="text", text="ok")])
            r.usage = U()
            return r
    monkeypatch.setattr(anthropic, "Anthropic", C)
    monkeypatch.setattr(config, "WEB_SEARCH", False)
    out = llm._anthropic(("regras fixas", "hoje é quinta"), [{"role": "user", "content": "oi"}], [], model="claude-sonnet-5-5")
    sysblocks = calls[0]["system"]
    assert sysblocks[0]["cache_control"] and sysblocks[0]["text"] == "regras fixas" and "cache_control" not in sysblocks[1]
    assert calls[0]["messages"][-1]["content"][-1]["cache_control"]
    u = out["usage"]
    assert u["cache_read"] == 9000 and u["calls"] == 1
    # 1000*2 + 200*10 + 9000*0.2 = 5800 por milhão
    assert abs(llm.cost_usd(u) - 0.0058) < 1e-9
