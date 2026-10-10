"""Planos do Fidus e oferta de upgrade na hora certa.

Regra de produto: o que cria o hábito diário (voz, agenda, lembretes, gastos, e-mail, documentos,
tarefas) existe em todos os planos e nunca tem limite de uso. O que separa os planos é o valor para o
negócio. Quando o usuário pede algo de um plano acima, o Fidus explica o que faria e oferece o upgrade
uma vez, sem insistir.
"""
from . import config, store

PLANS = {
    "essencial": {
        "rank": 1, "name": "Essencial", "month": 29.90,
        "highlights": ["Voz e texto sem limite", "Agenda, lembretes e bom dia", "E-mail com aprovação",
                       "Gastos e recibos de 1 carteira", "Documentos com validade", "Tarefas"],
    },
    "negocio": {
        "rank": 2, "name": "Negócio", "month": 49.90,
        "highlights": ["Modo conversa: fale com o Fidus como numa ligação", "Empresas e moedas ilimitadas",
                       "Link de agendamento para clientes",
                       "Ata de reunião automática", "Pacote do contador", "Alerta de assinaturas",
                       "Resumo da semana"],
    },
    "premium": {
        "rank": 3, "name": "Premium", "month": 69.90,
        "highlights": ["Pagar por voz: Pix e transferências preparados para você", "Cobrança e fatura para clientes",
                       "Mais 1 pessoa na conta + acesso do contador", "Atas sem limite e suporte prioritário"],
    },
}

# Preço por moeda (valores redondos fixos, como nas lojas de apps). Libra no Reino Unido, euro na Europa,
# dólar no resto do mundo. A cobrança de verdade segue o país do cartão.
PRICES = {
    "EUR": {"essencial": 29.90, "negocio": 49.90, "premium": 69.90},
    "GBP": {"essencial": 24.90, "negocio": 42.90, "premium": 59.90},
    "USD": {"essencial": 32.90, "negocio": 54.90, "premium": 74.90},
}
SYMBOL = {"EUR": "€", "GBP": "£", "USD": "$"}
EUROPE = set("AD AL AT AX BA BE BG BY CH CY CZ DE DK EE ES FI FO FR GG GI GR HR HU IE IM IS IT JE LI LT LU LV MC MD "
             "ME MK MT NL NO PL PT RO RS SE SI SJ SK SM UA VA XK".split())


def currency_for(country: str | None) -> str:
    cc = (country or "").strip().upper()
    if cc in ("GB", "UK"):
        return "GBP"
    return "EUR" if cc in EUROPE else "USD"


def user_currency() -> str:
    return currency_for(store.profile().get("country"))


def price(plan: str, cur: str | None = None) -> float:
    return PRICES[cur or user_currency()][plan]


def fmt(amount: float, cur: str) -> str:
    return f"{SYMBOL[cur]}{amount:.2f}"


# ferramenta/recurso -> plano mínimo
FEATURE_MIN = {
    "get_booking_link": "negocio",
    "update_booking_settings": "negocio",
    "list_meetings": "negocio",
    "get_meeting": "negocio",
    "prepare_minutes_email": "negocio",
    "meetings_record": "negocio",
    "export_for_accountant": "negocio",
    "list_subscriptions": "negocio",
    "weekly_review": "negocio",
    "extra_business": "negocio",
    "voice_conversation": "negocio",
    "bank_connection": "premium",
    "prepare_payment": "premium",
    "save_payment_contact": "premium",
    "client_invoices": "premium",
    "extra_user": "premium",
}

FEATURE_LABEL = {
    "get_booking_link": "link de agendamento", "update_booking_settings": "link de agendamento",
    "list_meetings": "atas de reunião", "get_meeting": "atas de reunião", "prepare_minutes_email": "atas de reunião",
    "meetings_record": "gravar reuniões e gerar a ata", "export_for_accountant": "pacote do contador",
    "list_subscriptions": "alerta de assinaturas", "weekly_review": "resumo da semana",
    "extra_business": "gastos de mais de uma empresa",
    "voice_conversation": "modo conversa por voz", "bank_connection": "banco conectado",
    "prepare_payment": "pagar por voz", "save_payment_contact": "pagar por voz",
    "client_invoices": "cobrança e fatura para clientes", "extra_user": "mais uma pessoa na conta",
}

UPSELL_TOOL = {
    "name": "offer_upgrade",
    "description": "Mostra no app o cartão do plano que libera um recurso que o usuário pediu e o plano atual não tem "
                   "(ou que ainda vai chegar no Premium: banco conectado, cobrança/fatura para clientes, mais uma "
                   "pessoa na conta). Use no máximo uma vez por assunto; se ele recusar, não insista.",
    "parameters": {"type": "object", "properties": {"feature": {"type": "string", "enum": sorted(FEATURE_MIN)}},
                   "required": ["feature"]},
}


def current() -> str:
    default = (config.DEFAULT_PLAN or "premium") if store.current().get("is_owner") else config.NEW_USER_PLAN
    p = (store.kv_get("plan") or default).strip().lower()
    return p if p in PLANS else "essencial"  # valor estranho nunca libera o plano mais caro


def set_plan(plan: str) -> str:
    if plan not in PLANS:
        raise ValueError("plano desconhecido")
    store.kv_set("plan", plan)
    return plan


def allows(feature: str, plan: str | None = None) -> bool:
    need = FEATURE_MIN.get(feature)
    return not need or PLANS[plan or current()]["rank"] >= PLANS[need]["rank"]


def year_price(month: float) -> float:
    return round(month * 10, 2)  # anual: 2 meses grátis


def upsell(feature: str) -> dict:
    need = FEATURE_MIN.get(feature, "negocio")
    p = PLANS[need]
    cur = user_currency()
    m = price(need, cur)
    return {"feature": feature, "feature_label": FEATURE_LABEL.get(feature, feature), "plan": need, "name": p["name"],
            "month": m, "year": year_price(m), "currency": cur, "symbol": SYMBOL[cur], "highlights": p["highlights"],
            "current_plan": PLANS[current()]["name"], "url": config.UPGRADE_URL}


def locked(feature: str) -> dict:
    u = upsell(feature)
    return {"error": f"'{u['feature_label']}' faz parte do plano {u['name']} ({fmt(u['month'], u['currency'])}/mês). "
                     f"O usuário está no plano {u['current_plan']}. Explique o benefício para o pedido dele em "
                     f"uma ou duas frases e diga que o cartão abaixo mostra o plano. Não diga que fez a ação.",
            "locked": True, "upsell": u}


def primary_business() -> str:
    """No Essencial, a carteira é a primeira usada (ou 'Pessoal')."""
    b = store.kv_get("primary_business")
    if not b:
        row = store.select("SELECT business FROM expenses WHERE deleted=0 ORDER BY id LIMIT 1")
        b = row[0]["business"] if row else store.businesses()[0]
        store.kv_set("primary_business", b)
    return b


def gate(tool: str, args: dict) -> dict | None:
    """Devolve o bloqueio com a oferta, ou None se o plano permite."""
    if tool == "offer_upgrade":
        return None
    if not allows(tool):
        return locked(tool)
    if tool in ("add_expense", "add_bill") and args.get("business") and not allows("extra_business"):
        if args["business"].strip().lower() != primary_business().lower():
            return locked("extra_business")
    return None


def info() -> dict:
    cur = current()
    money = user_currency()
    return {"plan": cur, "name": PLANS[cur]["name"], "url": config.UPGRADE_URL, "currency": money,
            "symbol": SYMBOL[money], "locked_features": sorted(f for f in FEATURE_MIN if not allows(f, cur)),
            "plans": [{"id": k, "name": v["name"], "month": price(k, money), "year": year_price(price(k, money)),
                       "highlights": v["highlights"]} for k, v in PLANS.items()]}
