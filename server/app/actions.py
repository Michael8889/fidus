"""Ações que falam pelo usuário (e-mail, convite, ata): envio só com a autorização dele.

Duas formas de autorizar, as duas vindas do próprio usuário:
- tocar em Enviar no cartão do rascunho (/v1/actions/{id}/confirm);
- mandar a ordem na conversa ("envia", "pode mandar", "send it"), por texto ou voz.

A ordem é reconhecida aqui, por regra fixa, só no texto que o usuário mandou. A IA nunca envia nada:
nenhuma ferramenta dela chega a este módulo, e texto de e-mails lidos não passa por aqui.
"""
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from . import features, store, tools

KINDS = {"send_email": (lambda p: tools.send_confirmed_email(p), "email_draft"),
         "calendar_invite": (lambda p: features.send_confirmed_invite(p), "invite_draft")}

COMMAND_WINDOW = timedelta(hours=3)  # rascunhos mais velhos que isso precisam do toque no cartão


class SendError(Exception):
    pass


def send_pending(pid: str) -> dict:
    """Envia uma ação pendente (trava atômica: um pedido = um envio). Erro → a ação volta a ficar pendente."""
    a = store.get_pending(pid)
    if not a or not store.claim_pending(pid):
        raise SendError("ação não está pendente")
    if a["kind"] not in KINDS:
        store.update_pending(pid, "pending")
        raise SendError("tipo de ação desconhecido")
    send, act_kind = KINDS[a["kind"]]
    try:
        result = send(a["payload"])
    except Exception as e:
        store.update_pending(pid, "pending")
        raise SendError(f"falha ao enviar: {e}") from e
    store.update_pending(pid, "sent")
    store.update_activity_by_ref(act_kind, pid, "enviado")
    return result


# ---------- "envia" na conversa ----------
_VERBS = {"envia", "enviar", "envie", "enviaa", "manda", "mandar", "mande", "dispara", "disparar", "send", "sendit",
          "envoie", "envoyer", "invia", "senden", "schick", "verstuur", "wyslij"}
_FILLER = {"ok", "okay", "oki", "sim", "isso", "pode", "podes", "beleza", "blz", "perfeito", "otimo", "show", "certo",
           "ta", "esta", "bom", "boa", "yes", "yeah", "yep", "sure", "please", "pls", "por", "favor", "pf", "agora",
           "ja", "entao", "ai", "the", "it", "this", "that", "go", "ahead", "now", "o", "os", "as", "esse", "essa",
           "este", "esta", "esses", "essas", "isso", "ele", "ela", "eles", "elas", "la", "lo", "de", "do", "da", "pra",
           "para", "por", "fidus", "vai", "pode", "mesmo", "assim", "aquele", "aquela", "and", "e", "y", "si",
           "por", "favor", "le", "lui", "es", "bitte", "jetzt"}
_NOUNS = {"email", "emails", "mail", "rascunho", "rascunhos", "convite", "convites", "resposta", "respostas", "draft",
          "drafts", "invite", "invites", "invitation", "mensagem", "ata", "correo"}
_ALL = {"todos", "todas", "tudo", "dois", "duas", "both", "all", "everything", "ambos"}
_ORD = {"primeiro": 1, "primeira": 1, "first": 1, "segundo": 2, "segunda": 2, "second": 2, "terceiro": 3,
        "terceira": 3, "third": 3, "quarto": 4, "quarta": 4, "fourth": 4}
_NOT = {"nao", "no", "not", "dont", "nunca", "never", "cancela", "cancelar", "espera", "wait", "nem"}


def _tokens(text: str) -> list[str]:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.replace("e-mail", "email").replace("send it", "sendit")
    return re.findall(r"[a-z]+|\d+", t)


def parse_command(text: str) -> dict | None:
    """Reconhece uma ordem curta de envio. Devolve {"which": None | número | "all", "lang": "pt"|"en"} ou None."""
    if not text or len(text) > 80:
        return None
    toks = _tokens(text)
    if not toks or len(toks) > 10 or any(t in _NOT for t in toks):
        return None
    if not any(t in _VERBS for t in toks):
        return None
    which: int | str | None = None
    named = any(t in _NOUNS for t in toks)
    for t in toks:
        if t in _VERBS or t in _FILLER or t in _NOUNS:
            continue
        if t in _ALL:
            which = "all"
        elif t in _ORD:
            which = _ORD[t]
        elif t.isdigit() and 1 <= int(t) <= 9:
            which = int(t)
        else:
            return None  # palavra que não faz parte de uma ordem simples ("manda um e-mail pro Carlos")
    lang = "en" if any(t in ("send", "sendit", "please", "go") for t in toks) else "pt"
    return {"which": which, "lang": lang, "named": named}


FRESH = timedelta(minutes=15)  # ordem sem número ("envia") só vale para rascunho recente


def _age(a: dict) -> timedelta:
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(a["created_at"])
    except (TypeError, ValueError):
        return timedelta.max


def waiting(window: timedelta | None = COMMAND_WINDOW) -> list[dict]:
    """Rascunhos aguardando o usuário, do mais antigo para o mais novo (window=None: todos)."""
    rows = store.select("SELECT id FROM pending_actions WHERE status='pending' AND kind IN ('send_email','calendar_invite') "
                        "ORDER BY created_at")
    out = [store.get_pending(r["id"]) for r in rows]
    return [a for a in out if window is None or _age(a) <= window]


def describe(a: dict, lang: str = "pt") -> str:
    p = a["payload"]
    if a["kind"] == "calendar_invite":
        who = ", ".join(p.get("emails") or [])
        return (f"invite '{p.get('title', '')}' to {who}" if lang == "en" else f"convite '{p.get('title', '')}' para {who}")
    return (f"email to {p.get('to', '')} ({p.get('subject', '')})" if lang == "en"
            else f"e-mail para {p.get('to', '')} ({p.get('subject', '')})")


def readback(a: dict, lang: str = "pt") -> str:
    """Frase montada pelo servidor (não pela IA) com o destinatário e o assunto reais, para o modo conversa."""
    if lang == "en":
        return f"Draft ready: {describe(a, 'en')}. Say “send it” to send it, or check it in the app."
    return f"Rascunho pronto: {describe(a)}. Diga “envia” para mandar ou confira no app."


def _remember_list(items: list[dict]) -> None:
    store.kv_set("draft_list", json.dumps({"ids": [a["id"] for a in items], "at": store.now()}))


def _listed() -> list[str]:
    try:
        d = json.loads(store.kv_get("draft_list") or "{}")
        if datetime.now(timezone.utc) - datetime.fromisoformat(d["at"]) <= FRESH:
            return d["ids"]
    except (KeyError, TypeError, ValueError):
        pass
    return []


def handle_command(text: str, visible: list[str] | None = None) -> dict | None:
    """Se o texto for uma ordem de envio, envia o rascunho que o usuário está vendo e responde.

    Só vale para rascunhos que o app diz estarem na tela (`visible`) e que não estão sendo editados: assim a
    ordem nunca manda um rascunho que o usuário não viu. Sem essa lista (app antigo), só o toque envia.
    Fora disso devolve None e o pedido segue para a IA, que não envia nada."""
    cmd = parse_command(text)
    if not cmd or visible is None:
        return None
    vis = set(visible)
    items = [a for a in waiting() if a["id"] in vis]
    if not items:
        return None
    en = cmd["lang"] == "en"
    which = cmd["which"]
    if isinstance(which, int):
        listed = _listed()
        pool = listed or [a["id"] for a in items]
        if which > len(pool):
            reply = (f"There are only {len(pool)} drafts waiting." if en else f"Só tenho {len(pool)} rascunho(s) esperando.")
            return _answer(text, reply, [], [])
        pick = next((a for a in items if a["id"] == pool[which - 1]), None)
        if not pick:
            reply = "That draft is no longer waiting." if en else "Esse rascunho não está mais esperando."
            return _answer(text, reply, [], [])
        chosen = [pick]
    elif which == "all":
        chosen = items
    else:
        # "pode mandar" solto só vale logo depois do rascunho (senão pode ser resposta a outra pergunta do Fidus);
        # "manda o e-mail" vale para rascunho recente na tela.
        fresh = [a for a in items if _age(a) <= FRESH]
        if not fresh or (not cmd["named"] and not _just_drafted()):
            return None
        if len(fresh) > 1:
            _remember_list(fresh)
            lines = "\n".join(f"{i}. {describe(a, cmd['lang'])}" for i, a in enumerate(fresh, 1))
            reply = (f"You have {len(fresh)} drafts waiting:\n{lines}\nSay \"send 1\", \"send 2\" or \"send all\"."
                     if en else f"Tenho {len(fresh)} rascunhos esperando:\n{lines}\nDiga \"envia o 1\", \"envia o 2\" ou \"envia todos\".")
            return _answer(text, reply, [], [])
        chosen = fresh[:1]
    sent, failed = [], []
    for a in chosen:
        try:
            send_pending(a["id"])
            sent.append(a)
        except SendError as e:
            failed.append((a, str(e)))
    parts = []
    if sent:
        what = "; ".join(describe(a, cmd["lang"]) for a in sent)
        parts.append(f"Done, sent: {what}." if en else f"Pronto, enviei: {what}.")
    for a, err in failed:
        parts.append(f"Couldn't send the {describe(a, 'en')}: {err}" if en
                     else f"Não consegui enviar o {describe(a)}: {err}")
    log = [f"enviou {describe(a)} por ordem do usuário" for a in sent]
    return _answer(text, " ".join(parts), [a["id"] for a in sent], log)


def _just_drafted() -> bool:
    last = [m for m in store.recent_messages(4) if m["role"] == "assistant"]
    return bool(last) and ("aguardando confirmação" in last[-1]["content"] or "rascunhos esperando" in last[-1]["content"]
                           or "drafts waiting" in last[-1]["content"])


def _answer(user_text: str, reply: str, sent_ids: list[str], log: list[str]) -> dict:
    store.add_message("user", user_text)
    store.add_message("assistant", reply + (f"\n\n[ações executadas: {'; '.join(log)}]" if log else ""))
    return {"reply": reply, "speech": reply.replace("\n", ". "), "pending_actions": [], "events": [], "documents": [],
            "upsell": None, "sent_actions": sent_ids}
