"""Ata de reunião: o app grava, o servidor transcreve (Whisper local) e a IA resume.

Roda em segundo plano porque uma reunião de 1 h leva alguns minutos para transcrever.
O e-mail da ata nunca sai sozinho: vira rascunho pendente, como as respostas de e-mail.
"""
import json
import os
import re
import threading
import traceback
from datetime import datetime

from . import config, features, llm, store

_lock = threading.Lock()  # uma reunião por vez para não travar o servidor

TOOLS = [
    {
        "name": "list_meetings",
        "description": "Lista as reuniões gravadas (mais recentes primeiro), com status e título.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_meeting",
        "description": "Detalhes de uma reunião gravada: resumo, decisões, próximos passos e trecho da transcrição. "
                       "Use para 'o que ficou decidido na reunião com X'.",
        "parameters": {"type": "object", "properties": {"meeting_id": {"type": "integer"}}, "required": ["meeting_id"]},
    },
    {
        "name": "prepare_minutes_email",
        "description": "Prepara o e-mail com a ata de uma reunião para os participantes. NÃO envia: o usuário "
                       "revisa e confirma no app. Peça os e-mails se não souber.",
        "parameters": {
            "type": "object",
            "properties": {
                "meeting_id": {"type": "integer"},
                "emails": {"type": "array", "items": {"type": "string"}},
                "note": {"type": "string", "description": "frase de abertura opcional"},
            },
            "required": ["meeting_id", "emails"],
        },
    },
]

SUMMARY_PROMPT = """Você recebe a transcrição automática de uma reunião (pode ter erros de transcrição).
O dono do Fidus se chama {name}; na transcrição ele pode aparecer como "eu".
Hoje é {today}. Devolva SOMENTE um JSON válido, sem texto antes ou depois, neste formato:
{{"title": "título curto da reunião",
  "summary": "resumo em 3 a 6 frases curtas",
  "decisions": ["decisão 1", "..."],
  "action_items": [{{"owner": "nome da pessoa ou 'eu' se for {name}", "task": "o que fazer", "due": "AAAA-MM-DD ou null"}}],
  "open_questions": ["pendências sem dono", "..."]}}
Escreva no idioma principal da reunião. Não invente nada que não esteja na transcrição."""


def _dir() -> str:
    d = os.path.join(config.DATA_DIR, "meetings", datetime.now().strftime("%Y-%m"))
    os.makedirs(d, exist_ok=True)
    return d


def start(audio_bytes: bytes, ext: str, title: str | None = None) -> int:
    path = os.path.join(_dir(), f"{datetime.now():%Y%m%d-%H%M%S}{ext}")
    with open(path, "wb") as f:
        f.write(audio_bytes)
    mid = store.insert("meetings", title=title, status="processando", audio_path=path)
    threading.Thread(target=process, args=(mid,), daemon=True).start()
    return mid


def _parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("a IA não devolveu o resumo no formato esperado")
    return json.loads(m.group(0))


def _is_me(owner: str | None) -> bool:
    o = (owner or "").strip().lower()
    mine = {"eu", "me", "mim", "i", "você", "voce"}
    if config.USER_NAME.strip():
        mine.add(config.USER_NAME.strip().lower())
    return o in mine


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _drop_audio(path: str | None) -> None:
    try:
        if path:
            os.remove(path)  # privacidade: guarda só o texto
    except OSError:
        pass


def resume_unfinished() -> None:
    """Na inicialização: reuniões que ficaram no meio (servidor reiniciou) voltam para a fila."""
    try:
        for m in store.select("SELECT id, audio_path FROM meetings WHERE status='processando'"):
            if m["audio_path"] and os.path.exists(m["audio_path"]):
                threading.Thread(target=process, args=(m["id"],), daemon=True).start()
            else:
                store.update("meetings", m["id"], status="erro", error="o servidor reiniciou e o áudio se perdeu")
    except Exception:  # noqa: BLE001
        traceback.print_exc()


def process(mid: int) -> None:
    from .transcribe import MEETING_PROMPT, transcribe

    m = store.get("meetings", mid)
    with _lock:
        try:
            transcript = transcribe(m["audio_path"], MEETING_PROMPT, beam_size=1)
            if not transcript:
                raise ValueError("não consegui ouvir nada na gravação")
            store.update("meetings", mid, transcript=transcript)
            out = llm.chat(SUMMARY_PROMPT.format(name=config.USER_NAME, today=features._now().date().isoformat()),
                           [{"role": "user", "content": transcript[:120000]}], [], web_search=False)
            data = _parse_json(out["text"])
            title = m["title"] or data.get("title") or "Reunião"
            created = []
            for it in data.get("action_items") or []:
                if _is_me(it.get("owner")) and it.get("task"):
                    due = it.get("due") if DATE_RE.match(str(it.get("due") or "")) else None
                    t = features.add_task(it["task"], due=due, notes=f"Da reunião: {title}")
                    created.append(t["task_id"])
            data["tasks_created"] = created
            store.update("meetings", mid, title=title, summary=json.dumps(data, ensure_ascii=False))
            _drop_audio(m["audio_path"])
            store.add_activity("meeting_summarized", title,
                               f"{len(data.get('decisions') or [])} decisões · {len(created)} tarefas suas", "feito", str(mid))
            store.add_message("assistant", minutes_text(mid))
            store.update("meetings", mid, status="pronta")  # por último: o app só vê "pronta" com tudo feito
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            _drop_audio(m["audio_path"])
            store.update("meetings", mid, status="erro", error=str(e))
            store.add_message("assistant", f"Não consegui processar a gravação da reunião: {e}")


def minutes_text(mid: int) -> str:
    m = store.get("meetings", mid)
    d = json.loads(m["summary"] or "{}")
    lines = [f"Ata pronta: {m['title']}", "", d.get("summary", "")]
    if d.get("decisions"):
        lines += ["", "Decisões:"] + [f"• {x}" for x in d["decisions"]]
    if d.get("action_items"):
        lines += ["", "Próximos passos:"]
        for it in d["action_items"]:
            due = f" (até {it['due'][8:10]}/{it['due'][5:7]})" if DATE_RE.match(str(it.get("due") or "")) else ""
            lines.append(f"• {it.get('owner') or '?'}: {it.get('task')}{due}")
    if d.get("open_questions"):
        lines += ["", "Em aberto:"] + [f"• {x}" for x in d["open_questions"]]
    if d.get("tasks_created"):
        lines += ["", f"Coloquei {len(d['tasks_created'])} tarefa(s) suas na aba Tarefas."]
    lines += ["", "Quer que eu prepare o e-mail da ata para os participantes?"]
    return "\n".join(lines).strip()


def status(mid: int) -> dict:
    m = store.get("meetings", mid)
    if not m:
        return {"error": "reunião não encontrada"}
    out = {"meeting_id": mid, "status": m["status"], "title": m["title"]}
    if m["status"] == "pronta":
        out["text"] = minutes_text(mid)
    if m["status"] == "erro":
        out["error"] = m["error"]
    return out


# ---------- ferramentas ----------
def list_meetings():
    rows = store.select("SELECT id, title, status, created_at FROM meetings ORDER BY id DESC LIMIT 20")
    return {"meetings": [{"meeting_id": r["id"], "title": r["title"], "status": r["status"],
                          "date": r["created_at"][:10]} for r in rows]}


def get_meeting(meeting_id):
    m = store.get("meetings", int(meeting_id))
    if not m:
        return {"error": "reunião não encontrada"}
    return {"meeting_id": m["id"], "title": m["title"], "status": m["status"], "date": m["created_at"][:10],
            "summary": json.loads(m["summary"] or "{}"), "transcript_excerpt": (m["transcript"] or "")[:4000]}


def prepare_minutes_email(meeting_id, emails, note=None):
    m = store.get("meetings", int(meeting_id))
    if not m or m["status"] != "pronta":
        return {"error": "a ata dessa reunião ainda não está pronta"}
    emails = [e.strip() for e in emails if e and "@" in e]
    if not emails:
        return {"error": "nenhum e-mail válido. Pergunte o e-mail dos participantes."}
    d = json.loads(m["summary"])
    body = [note or "Olá, segue o resumo da nossa reunião.", "", d.get("summary", "")]
    if d.get("decisions"):
        body += ["", "Decisões:"] + [f"- {x}" for x in d["decisions"]]
    if d.get("action_items"):
        body += ["", "Próximos passos:"]
        for it in d["action_items"]:
            owner = config.USER_NAME if _is_me(it.get("owner")) else it.get("owner")
            due = f" (até {it['due']})" if DATE_RE.match(str(it.get("due") or "")) else ""
            body.append(f"- {owner}: {it.get('task')}{due}")
    body += ["", "Abraço,", config.USER_NAME]
    payload = {"to": ", ".join(emails), "subject": f"Ata: {m['title']}", "body": "\n".join(body)}
    pid = store.create_pending("send_email", payload)
    return {"ok": True, "pending_action_id": pid, "status": "aguardando confirmação do usuário", "draft": payload}


DISPATCH = {"list_meetings": list_meetings, "get_meeting": get_meeting, "prepare_minutes_email": prepare_minutes_email}
