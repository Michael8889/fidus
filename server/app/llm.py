"""Adaptador de IA: o resto do Fidus só fala com `chat()`.

Trocar de provedor = mudar FIDUS_LLM_PROVIDER no .env. Formato interno neutro:
mensagens {role, content} e ferramentas {name, description, parameters (JSON Schema)}.
Resposta: {"text": str, "tool_calls": [{"id", "name", "input"}]}.
"""
import json

from . import config, store


def chat(system: str, messages: list[dict], tools: list[dict], web_search: bool = True) -> dict:
    if config.LLM_PROVIDER == "anthropic":
        return _anthropic(system, messages, tools, web_search)
    if config.LLM_PROVIDER == "openai_compat":
        return _openai_compat(system, messages, tools)
    raise ValueError(f"Provedor desconhecido: {config.LLM_PROVIDER}")


# ---------- Anthropic ----------
def _anthropic(system, messages, tools, web_search=True):
    import anthropic

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
    api_tools = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
    if config.WEB_SEARCH and web_search:
        # busca na web feita pela própria Anthropic (opcional; outros provedores seguem sem ela)
        api_tools.append({"type": "web_search_20250305", "name": "web_search", "max_uses": 3,
                          "user_location": {"type": "approximate", "country": config.WEB_SEARCH_COUNTRY,
                                            "timezone": store.user_tz()}})
    raw: list = []
    for _ in range(3):  # "pause_turn": a busca longa pede para continuar a mesma resposta
        try:
            resp = client.messages.create(model=config.LLM_MODEL, max_tokens=4000, system=system,
                                          messages=msgs, tools=api_tools)
        except anthropic.BadRequestError as e:
            if "web_search" not in str(e) or not config.WEB_SEARCH:
                raise
            config.WEB_SEARCH = False  # busca não liberada nesta conta: segue sem ela
            api_tools = [t for t in api_tools if t.get("name") != "web_search"]
            resp = client.messages.create(model=config.LLM_MODEL, max_tokens=4000, system=system,
                                          messages=msgs, tools=api_tools)
        raw += [b.model_dump(exclude_none=True) for b in resp.content]
        if resp.stop_reason != "pause_turn":
            break
        msgs = msgs + [{"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in resp.content]}]
    blocks = raw
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    calls = [{"id": b["id"], "name": b["name"], "input": b["input"]} for b in blocks if b.get("type") == "tool_use"]
    return {"text": text, "tool_calls": calls, "raw": raw}


# ---------- OpenAI-compatível (OpenAI, Mistral, vLLM, Ollama, etc.) ----------
def _openai_compat(system, messages, tools):
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
    resp = client.chat.completions.create(model=config.LLM_MODEL, messages=msgs, **extra)
    choice = resp.choices[0].message
    calls = [{"id": c.id, "name": c.function.name, "input": json.loads(c.function.arguments or "{}")}
             for c in (choice.tool_calls or [])]
    return {"text": choice.content or "", "tool_calls": calls}
