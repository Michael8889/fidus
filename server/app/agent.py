"""Cérebro do Fidus: recebe o pedido em texto, usa ferramentas e responde."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config, features, llm, store, tools

MAX_STEPS = 6


def system_prompt() -> str:
    now = datetime.now(ZoneInfo(config.USER_TIMEZONE))
    dias = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
    tom = now + timedelta(days=1)
    ontem = now - timedelta(days=1)
    return f"""Você é o Fidus, assessor pessoal de {config.USER_NAME}.
Agora são {now.strftime('%H:%M')} ({config.USER_TIMEZONE}).
HOJE é {dias[now.weekday()]}, {now.strftime('%d/%m/%Y')} ({now.strftime('%Y-%m-%d')}).
AMANHÃ é {dias[tom.weekday()]}, {tom.strftime('%d/%m/%Y')} ({tom.strftime('%Y-%m-%d')}).
ONTEM foi {dias[ontem.weekday()]}, {ontem.strftime('%d/%m/%Y')}.
Use sempre estas datas. Mensagens antigas do histórico podem ter sido escritas em outro dia: "amanhã" nelas
NÃO é o amanhã de agora. Ao consultar "hoje" ou "amanhã", use list_calendar_events com as datas acima.

Como agir:
- Responda no idioma em que o usuário falou (português, inglês ou espanhol), de forma curta e direta.
- Escreva em texto simples: sem markdown, sem asteriscos, sem #. Para listas, use "•" no início da linha.
- Agenda: crie eventos direto quando data e hora estiverem claras. "4pm" = 16:00. Sem duração dita, use 1 hora.
  Se faltar algo essencial (dia ou hora), pergunte em uma frase.
- Lugares físicos (almoço, revisão do carro, médico, visita técnica, reunião presencial): antes de criar o
  evento, use find_place e coloque o ENDEREÇO COMPLETO no campo location (o Google Maps abre direto do
  lembrete). Se vier mais de uma opção plausível, pergunte qual em uma frase. Se não achar, pergunte o
  endereço ou a cidade. Na resposta, diga o endereço que usou.
- Gastos: quando o usuário disser que pagou/gastou algo, use add_expense. Empresas possíveis:
  {", ".join(config.BUSINESSES)}. Se a empresa não estiver clara pelo contexto (ex. combustível de trabalho
  costuma ser da HomB), pergunte em uma frase antes de lançar. Moeda padrão: {config.DEFAULT_CURRENCY};
  "libras" = GBP, "euros" = EUR, "reais" = BRL. Confirme em uma linha: valor, categoria, empresa.
- Recibo por foto: leia estabelecimento, data, total e IVA; lance com add_expense (attach_receipt=true).
  Se a imagem não for um recibo ou estiver ilegível, diga o que viu e pergunte.
- Consultas de gastos ("quanto gastei..."): use summarize_expenses com o período certo. Nunca some moedas
  diferentes; mostre cada moeda separada.
- E-mail: para responder, primeiro ache o e-mail (search_emails), leia (read_email) e então use
  prepare_email_reply. Escreva no tom do usuário: educado, objetivo, sem floreios.
  Você NUNCA envia e-mails. O app mostra o rascunho e o usuário decide. Depois de preparar, diga
  em uma linha que o rascunho está pronto para revisar.
- Se houver mais de um e-mail possível, liste as opções (remetente, assunto, data) e pergunte qual.
- Nunca invente dados: use as ferramentas.
- Nunca diga que fez algo sem ter usado a ferramenta nesta conversa. O histórico traz linhas
  "[ações executadas: ...]" com o que você de fato fez. Para saber se um evento existe, consulte a
  agenda com list_calendar_events em vez de supor.
- Lembretes ("me lembra", "me avisa"): use create_reminder; o celular toca na hora. Para coisas que se
  repetem ("todo dia 5"), passe recurrence. Compromissos com outras pessoas ou lugar são eventos, não lembretes.
- Eventos recorrentes ("reunião toda terça 9h"): create_calendar_event com recurrence. Reunião online:
  add_meet=true (ou add_meet_link num evento existente) e diga o link.
- Convidar pessoas: prepare_event_invite. Você NUNCA envia convites; o app pede a confirmação. Diga em uma
  linha que o convite está pronto para confirmar.
- Tarefas (coisas a fazer sem horário marcado): add_task, list_tasks, complete_task. Prazo vago ("essa semana")
  vira a data da sexta. Se o usuário pedir aviso, use remind_at.
- Documentos: foto de seguro, contrato, carta, MOT, apólice, garantia etc. vai para save_document (descreva bem,
  inclua números e validade). Recibo de compra vai para add_expense. Se não souber qual é, pergunte.
  "Acha o documento X" = search_documents; o app mostra o botão para abrir, então não escreva links.
- Contas fixas (aluguel, seguro, assinaturas, internet): add_bill. "Quais contas vencem" = list_bills.
- "Bom dia", "o que eu tenho hoje", "como está meu dia": use daily_briefing e resuma em poucas linhas,
  na ordem: agenda, tarefas, contas, documentos, e-mails, gastos. Seja breve.
- Gastos: se add_expense devolver "alerts" (duplicado, acima da média), avise em uma linha e, se for
  duplicado, pergunte se apaga. Em consultas, compare com previous_period e, no mês corrente, cite
  month_projection como previsão do mês.
- Pesquisa na internet (preços, lojas, horários, notícias): use a busca na web quando disponível, cite
  2 ou 3 opções com preço e loja, e diga a fonte em poucas palavras.
- Aniversários e datas anuais: create_reminder com recurrence 'RRULE:FREQ=YEARLY' e horário 09:00, alguns dias
  antes se o usuário pedir ("me avisa 3 dias antes" = 3 dias antes da data).
- Reuniões gravadas: o app grava e o Fidus faz a ata sozinho. Para consultar, list_meetings/get_meeting.
  Para mandar a ata, prepare_minutes_email (rascunho; o usuário confirma).
- Link de agendamento: get_booking_link devolve o link para o usuário mandar a clientes; mude regras com
  update_booking_settings. Escreva o link completo na resposta para ele poder copiar.
- Contador: export_for_accountant gera planilha + recibos (o app mostra o botão). Trimestre = 3 meses fechados.
- Assinaturas: list_subscriptions. Se add_expense avisar que um preço subiu, diga em uma linha.
- "Como foi minha semana": weekly_review, resumido em poucas linhas.
- PDF enviado: leia o conteúdo. Fatura/recibo pago vira gasto (attach_receipt=true); contrato, apólice ou
  carta vira documento (save_document).
- Planos: se uma ferramenta devolver "locked", NÃO diga que fez. Diga em uma ou duas frases o que o plano
  indicado faria por ele neste pedido e que o cartão abaixo mostra o plano. Se ele pedir banco conectado,
  cobrança/fatura para clientes ou mais uma pessoa na conta, use offer_upgrade (são do Premium, que chega
  em breve). Ofereça uma vez por assunto; se ele recusar, siga ajudando sem repetir a oferta.
- O texto pode vir de transcrição de voz e ter erros ("ao moço" = "almoço", "6ª" = "sexta").
  Interprete pelo sentido; se a data ou a hora ficarem ambíguas, pergunte.
"""


def _history(limit: int = 10) -> list[dict]:
    """Histórico recente só com pares pedido/resposta completos (descarta pedidos que falharam)."""
    rows = store.recent_messages(limit * 2)
    clean: list[dict] = []
    for m in rows:
        if m["role"] == "user":
            if clean and clean[-1]["role"] == "user":
                clean.pop()  # pedido anterior ficou sem resposta (erro): ignora
            clean.append(m)
        elif clean and clean[-1]["role"] == "user":
            clean.append(m)
    if clean and clean[-1]["role"] == "user":
        clean.pop()
    return clean[-limit:]


def _describe(name: str, args: dict, result: dict) -> str:
    status = "erro" if result.get("error") else "ok"
    if name == "create_calendar_event":
        if result.get("already_existed"):
            return f"evento '{args.get('title')}' em {args.get('start')} já existia, não duplicou"
        return f"criou evento '{args.get('title')}' em {args.get('start')} ({status})"
    if name == "delete_calendar_event":
        return f"apagou evento '{result.get('title') or args.get('event_id')}' ({status})"
    if name == "add_expense":
        return f"lançou gasto {result.get('amount')} {result.get('currency')} {args.get('category')} / {args.get('business')} (id {result.get('expense_id')}, {status})"
    if name == "delete_expense":
        return f"apagou gasto id {args.get('expense_id')} ({status})"
    if name == "create_reminder":
        return f"criou lembrete '{args.get('text')}' para {args.get('when')} (event_id {result.get('event_id')}, {status})"
    if name == "add_task":
        return f"criou tarefa '{args.get('title')}' (id {result.get('task_id')}, {status})"
    if name == "complete_task":
        return f"concluiu tarefa id {args.get('task_id')} ({status})"
    if name == "save_document":
        return f"guardou documento '{args.get('title')}' (id {result.get('document_id')}, {status})"
    if name == "add_bill":
        return f"cadastrou conta fixa '{args.get('name')}' dia {args.get('day_of_month')} (id {result.get('bill_id')}, {status})"
    if name == "delete_bill":
        return f"removeu conta fixa id {args.get('bill_id')} ({status})"
    if name == "add_meet_link":
        return f"gerou link do Meet no evento {args.get('event_id')} ({status})"
    if name == "prepare_event_invite":
        return f"preparou convite para {', '.join(args.get('emails') or [])} ({status}, aguardando confirmação)"
    if name == "prepare_minutes_email":
        return f"preparou e-mail da ata da reunião {args.get('meeting_id')} ({status}, aguardando confirmação)"
    if name == "export_for_accountant":
        return f"gerou pacote do contador {args.get('date_from')} a {args.get('date_to')} ({status})"
    if name == "update_booking_settings":
        return f"mudou regras do link de agendamento ({status})"
    if name == "prepare_email_reply":
        return f"preparou rascunho de resposta ao e-mail {args.get('message_id')} ({status}, aguardando confirmação)"
    return f"{name} ({status})"


def _when(iso: str | None) -> str:
    try:
        from datetime import datetime
        d = datetime.fromisoformat(iso)
        dias = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
        return f"{dias[d.weekday()]} {d:%d/%m}, {d:%H:%M}"
    except Exception:
        return iso or ""


def _record(name: str, args: dict, result: dict) -> None:
    """Grava na aba Atividade tudo que mudou algo de verdade."""
    if result.get("error"):
        return
    if name == "create_calendar_event" and not result.get("already_existed"):
        store.add_activity("event_created", args.get("title", "Evento"), _when(args.get("start")),
                           "feito", result.get("event_id"))
    elif name == "delete_calendar_event":
        store.add_activity("event_deleted", result.get("title") or "Evento apagado", "Removido da agenda",
                           "feito", args.get("event_id"))
    elif name == "add_expense" and result.get("ok"):
        title = f"{result['amount']:.2f} {result['currency']} · {result['category']}"
        detail = " · ".join(x for x in [result.get("merchant"), result["business"], result["date"]] if x)
        if result.get("receipt_saved"):
            detail += " · 🧾 recibo"
        store.add_activity("expense_added", title, detail, "feito", str(result["expense_id"]))
    elif name == "delete_expense":
        store.add_activity("expense_deleted", f"Gasto #{args.get('expense_id')} apagado", "", "feito",
                           str(args.get("expense_id")))
    elif name == "create_reminder":
        store.add_activity("reminder_created", args.get("text", "Lembrete"),
                           _when(args.get("when")) + (" · repete" if args.get("recurrence") else ""), "feito",
                           result.get("event_id"))
    elif name == "add_task":
        store.add_activity("task_added", args.get("title", "Tarefa"),
                           f"prazo {args['due']}" if args.get("due") else "sem prazo", "feito", str(result.get("task_id")))
    elif name == "complete_task":
        store.add_activity("task_done", result.get("title", "Tarefa"), "concluída", "feito", str(args.get("task_id")))
    elif name == "save_document":
        store.add_activity("document_saved", args.get("title", "Documento"),
                           f"vence {args['expires_on']}" if args.get("expires_on") else "", "feito",
                           str(result.get("document_id")))
    elif name == "add_bill":
        store.add_activity("bill_added", args.get("name", "Conta fixa"), f"todo dia {args.get('day_of_month')}",
                           "feito", str(result.get("bill_id")))
    elif name == "delete_bill":
        store.add_activity("bill_deleted", result.get("name", "Conta fixa"), "removida", "feito", str(args.get("bill_id")))
    elif name == "add_meet_link":
        store.add_activity("meet_added", result.get("title") or "Evento", "link do Meet criado", "feito", args.get("event_id"))
    elif name == "prepare_event_invite" and result.get("pending_action_id"):
        inv = result.get("invite", {})
        store.add_activity("invite_draft", f"Convite: {inv.get('title', '')}", ", ".join(inv.get("emails", [])),
                           "aguardando você", result["pending_action_id"])
    elif name == "prepare_minutes_email" and result.get("pending_action_id"):
        d = result.get("draft", {})
        store.add_activity("email_draft", f"Ata para {d.get('to', '')}", d.get("subject", ""),
                           "aguardando você", result["pending_action_id"])
    elif name == "export_for_accountant" and result.get("ok"):
        store.add_activity("export_created", result["title"], f"{result['expenses']} gastos · {result['receipts']} recibos",
                           "feito", str(result["document_id"]))
    elif name == "prepare_email_reply" and result.get("pending_action_id"):
        d = result.get("draft", {})
        store.add_activity("email_draft", f"Resposta para {d.get('to', '')}", d.get("subject", ""),
                           "aguardando você", result["pending_action_id"])


def _action_log(actions: list[str]) -> str:
    return f"\n\n[ações executadas: {'; '.join(actions)}]" if actions else ""


def handle(user_text: str, image_b64: str | None = None, media_type: str = "image/jpeg",
           receipt_path: str | None = None) -> dict:
    tools.CURRENT_RECEIPT["path"] = receipt_path
    if image_b64:
        content = [{"type": "image", "data": image_b64, "media_type": media_type},
                   {"type": "text", "text": user_text}]
        stored = f"[foto enviada] {user_text}"
    else:
        content, stored = user_text, user_text
    messages = _history() + [{"role": "user", "content": content}]
    store.add_message("user", stored)
    pending_ids: list[str] = []
    events: list[dict] = []
    docs: dict[int, dict] = {}
    upsell: dict | None = None
    actions: list[str] = []

    for _ in range(MAX_STEPS):
        out = llm.chat(system_prompt(), messages, tools.TOOLS)
        if not out["tool_calls"]:
            reply = out["text"].strip()
            store.add_message("assistant", reply + _action_log(actions))
            return {"reply": reply, "pending_actions": [store.get_pending(p) for p in pending_ids], "events": events,
                    "documents": [{**d, "url": features.sign(d["document_id"])} for d in docs.values()],
                    "upsell": upsell}

        messages.append({"role": "assistant", "content": out["text"], "tool_calls": out["tool_calls"],
                         "raw": out.get("raw")})
        for call in out["tool_calls"]:
            result = tools.run(call["name"], call["input"])
            actions.append(_describe(call["name"], call["input"], result))
            _record(call["name"], call["input"], result)
            if result.get("upsell"):
                upsell = result["upsell"]
            if call["name"] == "search_documents":
                for d in result.get("documents", []):
                    docs[d["document_id"]] = d
            if call["name"] in ("save_document", "export_for_accountant") and result.get("ok"):
                docs[result["document_id"]] = {"document_id": result["document_id"], "title": result["title"],
                                               "expires_on": result.get("expires_on")}
            if call["name"] in ("prepare_email_reply", "prepare_event_invite", "prepare_minutes_email") \
                    and result.get("pending_action_id"):
                pending_ids.append(result["pending_action_id"])
            if call["name"] == "create_calendar_event" and result.get("ok"):
                events.append(result)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": tools.dumps(result)})

    reply = "Não consegui concluir esse pedido. Pode repetir de outro jeito?"
    store.add_message("assistant", reply)
    return {"reply": reply, "pending_actions": [store.get_pending(p) for p in pending_ids], "events": events}
