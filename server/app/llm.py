"""Adaptador de IA: o resto do Fidus só fala com `chat()`.

Trocar de provedor = mudar FIDUS_LLM_PROVIDER no .env. Formato interno neutro:
mensagens {role, content} e ferramentas {name, description, parameters (JSON Schema)}.
Resposta: {"text": str, "tool_calls": [{"id", "name", "input"}], "usage": {...}}.

`system` pode ser texto ou (parte_fixa, parte_que_muda): a parte fixa (regras + ferramentas) fica em cache na
Anthropic e custa 10% nas chamadas seguintes; a que muda (data, hora, perfil) vai depois.
Cada chamada grava tokens e custo no banco do cliente (store.add_usage), para medir o custo por cliente.
"""
import json

from . import config, store


def chat(system, messages: list[dict], tools: list[dict], web_search: bool = True, model: str | None = None) -> dict:
    if config.LLM_PROVIDER == "anthropic":
        out = _anthropic(system, messages, tools, web_search, model or config.LLM_MODEL)
    elif config.LLM_PROVIDER == "openai_compat":
        sys_text = "\n\n".join(system) if isinstance(system, (tuple, list)) else system
        out = _openai_compat(sys_text, messages, tools, model or config.LLM_MODEL)
    else:
        raise ValueError(f"Provedor desconhecido: {config.LLM_PROVIDER}")
    try:
        store.add_usage(out.get("usage") or {})
    except Exception:  # noqa: BLE001 - medir nunca derruba a resposta
        pass
    return out


# Preço por milhão de tokens: (entrada, saída, gravar cache 5 min, ler cache). Fonte: tabela de preços da Anthropic
# (out/2026). Modelos fora da lista usam FIDUS_PRICE_* ou o preço do Sonnet.
PRICES = {"claude-sonnet-5-5": (2.0, 10.0, 2.5, 0.2), "claude-haiku-4-5": (1.0, 5.0, 1.25, 0.1)}
SEARCH_PRICE = 10.0 / 1000  # busca na web: US$ 10 por mil


def cost_usd(u: dict) -> float:
    model = u.get("model") or ""
    p = next((v for k, v in PRICES.items() if model.startswith(k)), None) or config.CUSTOM_PRICES or PRICES["claude-sonnet-5-5"]
    return round((u.get("input", 0) * p[0] + u.get("output", 0) * p[1] + u.get("cache_write", 0) * p[2]
                  + u.get("cache_read", 0) * p[3]) / 1_000_000 + u.get("searches", 0) * SEARCH_PRICE, 6)


# ---------- Anthropic ----------
def _anthropic(system, messages, tools, web_search=True, model=None):
    import anthropic

    model = model or config.LLM_MODEL
    headers = {"anthropic-workspace-id": config.ANTHROPIC_WORKSPACE_ID} if config.ANTHROPIC_WORKSPACE_ID else None
    client = anthropic.Anthropic(api_key=(config.ANTHROPIC_API_KEY or "").strip(), default_headers=headers)
    msgs = []
    for m in messages:
        if m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            # vários resultados de ferramenta seguidos vão juntos numa só mensagem
            if msgs and msgs[-1]["role"] == "user" and isinstance(msgs[-1]["content"], list) \
                    and msgs[-1]["content"] and msgs[-1]["content"][0].get("type") == "tool_result":
                msgs[-1]["content"].append(block)
            else:
                msgs.append({"role": "user", "content": [block]})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            if m.get("raw"):
                # devolve a resposta original completa (inclui o raciocínio do modelo)
                blocks = m["raw"]
            else:
                blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                blocks += [{"type": "tool_use", "id": t["id"], "name": t["name"], "input": t["input"]}
                           for t in m["tool_calls"]]
            msgs.append({"role": "assistant", "content": blocks})
        elif isinstance(m["content"], list):  # texto + imagem
            blocks = []
            for b in m["content"]:
                if b["type"] == "image" and b["media_type"] == "application/pdf":
                    blocks.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                                  "data": b["data"]}})
                elif b["type"] == "image":
                    blocks.append({"type": "image", "source": {"type": "base64", "media_type": b["media_type"],
                                                               "data": b["data"]}})
                else:
                    blocks.append({"type": "text", "text": b["text"]})
            msgs.append({"role": m["role"], "content": blocks})
        else:
            msgs.append({"role": m["role"], "content": m["content"]})
    # cache: regras + ferramentas (parte fixa) e a conversa até aqui (as voltas seguintes do mesmo pedido reaproveitam)
    if isinstance(system, (tuple, list)):
        fixed, dynamic = system[0], "\n\n".join(system[1:])
        system = [{"type": "text", "text": fixed, "cache_control": {"type": "ephemeral"}}] + \
                 ([{"type": "text", "text": dynamic}] if dynamic else [])
    if msgs and msgs[-1]["role"] == "user":
        last = msgs[-1]
        content = last["content"] if isinstance(last["content"], list) else [{"type": "text", "text": last["content"]}]
        if content and isinstance(content[-1], dict) and content[-1].get("type") in ("text", "tool_result", "image", "document"):
            content = content[:-1] + [{**content[-1], "cache_control": {"type": "ephemeral"}}]
            msgs[-1] = {**last, "content": content}
    api_tools = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
    if config.WEB_SEARCH and web_search:
        # busca na web feita pela própria Anthropic (opcional; outros provedores seguem sem ela)
        api_tools.append({"type": "web_search_20250305", "name": "web_search", "max_uses": 3,
                          "user_location": {"type": "approximate", "country": config.WEB_SEARCH_COUNTRY,
                                            "timezone": store.user_tz()}})
    raw: list = []
    usage = {"model": model, "calls": 0, "input": 0, "output": 0, "cache_write": 0, "cache_read": 0, "searches": 0}
    extra = {"tools": api_tools} if api_tools else {}
    for _ in range(3):  # "pause_turn": a busca longa pede para continuar a mesma resposta
        try:
            resp = client.messages.create(model=model, max_tokens=4000, system=system, messages=msgs, **extra)
        except anthropic.BadRequestError as e:
            if "web_search" not in str(e) or not config.WEB_SEARCH:
                raise
            config.WEB_SEARCH = False  # busca não liberada nesta conta: segue sem ela
            api_tools = [t for t in api_tools if t.get("name") != "web_search"]
            extra = {"tools": api_tools} if api_tools else {}
            resp = client.messages.create(model=model, max_tokens=4000, system=system, messages=msgs, **extra)
        u = getattr(resp, "usage", None)
        if u is not None:
            usage["calls"] += 1
            usage["input"] += getattr(u, "input_tokens", 0) or 0
            usage["output"] += getattr(u, "output_tokens", 0) or 0
            usage["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
            usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
            stu = getattr(u, "server_tool_use", None)
            usage["searches"] += (getattr(stu, "web_search_requests", 0) or 0) if stu else 0
        raw += [b.model_dump(exclude_none=True) for b in resp.content]
        if resp.stop_reason != "pause_turn":
            break
        msgs = msgs + [{"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in resp.content]}]
    blocks = raw
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    calls = [{"id": b["id"], "name": b["name"], "input": b["input"]} for b in blocks if b.get("type") == "tool_use"]
    return {"text": text, "tool_calls": calls, "raw": raw, "usage": usage}


# ---------- OpenAI-compatível (OpenAI, Mistral, vLLM, Ollama, etc.) ----------
def _openai_compat(system, messages, tools, model=None):
    from openai import OpenAI

    client = OpenAI(base_url=config.OPENAI_COMPAT_BASE_URL, api_key=config.OPENAI_COMPAT_API_KEY or "none")
    msgs = [{"role": "system", "content": system}]
    for m in messages:
        if m["role"] == "tool":
            msgs.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            msgs.append({"role": "assistant", "content": m.get("content") or None, "tool_calls": [
                {"id": t["id"], "type": "function",
                 "function": {"name": t["name"], "arguments": json.dumps(t["input"])}} for t in m["tool_calls"]]})
        elif isinstance(m["content"], list):
            msgs.append({"role": m["role"], "content": [
                ({"type": "text", "text": "[PDF anexado: este provedor de IA não lê PDF; peça uma foto]"}
                 if b["media_type"] == "application/pdf" else
                 {"type": "image_url", "image_url": {"url": f"data:{b['media_type']};base64,{b['data']}"}})
                if b["type"] == "image" else {"type": "text", "text": b["text"]} for b in m["content"]]})
        else:
            msgs.append({"role": m["role"], "content": m["content"]})
    extra = {"tools": [{"type": "function", "function": t} for t in tools]} if tools else {}
    resp = client.chat.completions.create(model=model or config.LLM_MODEL, messages=msgs, **extra)
    choice = resp.choices[0].message
    calls = [{"id": c.id, "name": c.function.name, "input": json.loads(c.function.arguments or "{}")}
             for c in (choice.tool_calls or [])]
    u = getattr(resp, "usage", None)
    usage = {"model": model, "calls": 1, "input": getattr(u, "prompt_tokens", 0) or 0,
             "output": getattr(u, "completion_tokens", 0) or 0}
    return {"text": choice.content or "", "tool_calls": calls, "usage": usage}
