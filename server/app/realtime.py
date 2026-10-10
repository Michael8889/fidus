"""Modo conversa em tempo real (como o ChatGPT): a IA de voz da OpenAI ouve e fala direto pelo app (WebRTC).

O servidor só faz três coisas, sempre no banco do cliente:
1. cria a sessão (chave temporária de 10 min) com as regras do Fidus, o contexto e as ferramentas;
2. executa as ferramentas que a IA pede (as MESMAS do chat: nada envia sozinho, e-mail vira rascunho para confirmar);
3. guarda o que foi dito na conversa e o custo (para o histórico, a aba Atividade e o uso justo).

O "envia" falado nunca passa pela IA: o app manda o texto para /v1/realtime/command, que usa actions.handle_command
(só envia rascunho que está na tela), igual ao chat.
"""
import hashlib
import json
import logging
import threading

import requests

from . import agent, config, store, tools

log = logging.getLogger("fidus.realtime")
API = "https://api.openai.com/v1"
_ACTIONS: dict[str, list[str]] = {}  # ações feitas na ligação desde a última fala guardada (por cliente)
_lock = threading.Lock()

RT_RULES = """
LIGAÇÃO POR VOZ EM TEMPO REAL (o usuário está falando com você agora, talvez dirigindo):
- Fale de forma natural, calorosa e curta, como numa ligação: no máximo 2 frases por vez. Nada de listas ou símbolos.
- Responda no idioma em que o usuário falar.
- Para agir (agenda, gasto, lembrete, tarefa, rascunho), use as ferramentas. Nunca diga que fez algo sem a ferramenta
  ter confirmado. Enquanto a ferramenta roda, pode dizer algo curto como "deixa eu ver".
- Rascunho de e-mail ou convite: diga para quem é e o assunto em uma frase, e que ele pode dizer "envia".
- Quando o usuário mandar enviar ("envia", "pode mandar", "send it"), NÃO diga que enviou e não chame ferramenta:
  diga só "só um segundo". O app envia e te avisa o resultado logo em seguida.
- Se o usuário te interromper, pare e escute.
"""


def enabled() -> bool:
    return bool((config.OPENAI_API_KEY or "").strip()) and config.REALTIME_ON


def _uid() -> str:
    return (store.CURRENT.get() or {}).get("id") or store.OWNER_ID


def tool_specs() -> list[dict]:
    return [{"type": "function", "name": t["name"], "description": t["description"], "parameters": t["parameters"]}
            for t in tools.TOOLS]


def instructions() -> str:
    fixed, ctx = agent.system_parts(True)
    return f"{fixed}\n{RT_RULES}\n{ctx}"


def session() -> dict:
    """Chave temporária para o app abrir a ligação direto com a OpenAI (a chave da empresa nunca sai do servidor)."""
    if not enabled():
        return {"error": "tempo real desligado"}
    if agent.over_fair_use():
        return {"error": "fair_use"}
    lang = (store.user_lang() or "pt").split("-")[0]
    body = {
        "expires_after": {"anchor": "created_at", "seconds": 600},
        "session": {
            "type": "realtime", "model": config.REALTIME_MODEL, "instructions": instructions(),
            "tools": tool_specs(), "tool_choice": "auto",
            "audio": {
                "input": {"transcription": {"model": "gpt-4o-mini-transcribe", "language": lang},
                          "turn_detection": {"type": "semantic_vad", "eagerness": "auto"},
                          "noise_reduction": {"type": "near_field"}},
                "output": {"voice": config.REALTIME_VOICE},
            },
        },
    }
    safety = hashlib.sha256(f"fidus:{_uid()}".encode()).hexdigest()[:32]
    try:
        r = requests.post(f"{API}/realtime/client_secrets", json=body, timeout=15,
                          headers={"Authorization": f"Bearer {config.OPENAI_API_KEY.strip()}",
                                   "OpenAI-Safety-Identifier": safety})
        if r.status_code >= 400:
            log.warning("sessão tempo real recusada: %s %s", r.status_code, r.text[:300])
            return {"error": f"openai {r.status_code}"}
        j = r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("sessão tempo real falhou: %s", e)
        return {"error": "sem conexão com a OpenAI"}
    value = j.get("value") or (j.get("client_secret") or {}).get("value")
    if not value:
        return {"error": "resposta inesperada da OpenAI"}
    with _lock:
        _ACTIONS[_uid()] = []
    return {"client_secret": value, "model": config.REALTIME_MODEL, "expires_at": j.get("expires_at"),
            "calls_url": f"{API}/realtime/calls"}


def run_tool(name: str, arguments: str | dict | None) -> dict:
    """Executa uma ferramenta pedida na ligação, com as mesmas regras do chat (plano, rascunho, Atividade)."""
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
    except ValueError:
        args = {}
    if name not in {t["name"] for t in tools.TOOLS}:
        result = {"error": f"ferramenta desconhecida: {name}"}
    else:
        try:
            tools.web_tools.begin("")
        except Exception:  # noqa: BLE001
            pass
        result = tools.run(name, args)
        agent._record(name, args, result)
    with _lock:
        _ACTIONS.setdefault(_uid(), []).append(agent._describe(name, args, result))
    out: dict = {"output": tools.dumps(result)[:8000], "pending_actions": [], "events": []}
    pid = result.get("pending_action_id") if isinstance(result, dict) else None
    if pid:
        pa = store.get_pending(pid)
        if pa:
            out["pending_actions"].append(pa)
    if name == "create_calendar_event" and result.get("ok"):
        out["events"].append(result)
    if result.get("upsell"):
        out["upsell"] = result["upsell"]
    return out


def save_turn(user: str, assistant: str) -> None:
    """Guarda a fala e a resposta no histórico (o chat e as próximas conversas sabem o que foi dito)."""
    user, assistant = (user or "").strip()[:4000], (assistant or "").strip()[:4000]
    with _lock:
        acts = _ACTIONS.pop(_uid(), [])
        _ACTIONS[_uid()] = []
    if not user and not assistant and not acts:
        return
    if user:
        store.add_message("user", user)
    store.add_message("assistant", (assistant or "…") + agent._action_log(acts))
    try:
        from . import metrics
        metrics.record_task(_uid(), "tempo_real", True, len(acts), sum("(erro" in a for a in acts), 0)
    except Exception:  # noqa: BLE001
        pass


def record_usage(u: dict) -> None:
    """Custo da ligação (o app repassa o 'usage' de cada resposta da OpenAI)."""
    def n(x) -> int:
        try:
            return max(0, min(int(x or 0), 500_000))
        except (TypeError, ValueError):
            return 0
    cached = n((u.get("input_token_details") or {}).get("cached_tokens"))
    inp, out = n(u.get("input_tokens")), n(u.get("output_tokens"))
    store.add_usage({"model": f"realtime-{config.REALTIME_MODEL}", "calls": 1, "input": max(0, inp - cached),
                     "output": out, "cache_read": cached})
