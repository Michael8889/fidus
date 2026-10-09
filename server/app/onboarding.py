"""Boas-vindas: o Fidus se ajusta à pessoa em 2 minutos, numa conversa curta (cada pergunta pode ser pulada).

As perguntas são ADAPTADAS a cada idioma (exemplos locais, moeda do país, tratamento certo), não traduzidas ao pé
da letra: pt (Brasil), pt-pt (Portugal), en (Reino Unido) e es estão escritas à mão; os outros idiomas usam o inglês
traduzido pela IA uma vez e guardado. As respostas viram perfil, carteiras, estilo e o horário do "bom dia".
A última pergunta é o consentimento para dicas por e-mail (newsletter.py): desmarcado por padrão, sempre opcional.
"""
import json
import os
import re
from zoneinfo import ZoneInfo

from . import config, i18n, llm, plans, store

STEPS = ["name", "work", "wallets", "city", "priorities", "style", "briefing", "emails"]

# moeda sugerida pelo país do celular (para as carteiras)
COUNTRY_CURRENCY = {"GB": "GBP", "UK": "GBP", "BR": "BRL", "US": "USD", "PT": "EUR", "ES": "EUR", "FR": "EUR", "DE": "EUR",
                    "IT": "EUR", "IE": "EUR", "NL": "EUR", "BE": "EUR", "AT": "EUR", "FI": "EUR", "GR": "EUR",
                    "CH": "CHF", "PL": "PLN", "SE": "SEK", "NO": "NOK", "DK": "DKK", "CZ": "CZK", "RO": "RON", "HU": "HUF",
                    "CA": "CAD", "AU": "AUD", "MX": "MXN", "AR": "ARS", "CO": "COP", "CL": "CLP", "IN": "INR", "MY": "MYR"}

T = {
    "pt": {
        "intro": "Oi! Eu sou o Fidus, seu assessor. Em 2 minutos eu me ajusto a você. Pode responder falando ou escrevendo, e pular o que quiser.",
        "name": ("Como você quer que eu te chame?", "Ex.: Mike"),
        "work": ("Você trabalha por conta própria, tem empresa, ou os dois?", None),
        "work_opts": {"self": "Por conta própria", "company": "Tenho empresa", "both": "Os dois"},
        "wallets": ("Quais empresas ou contas eu devo separar nos seus gastos? E em qual moeda cada uma?",
                    "Ex.: “Minha empresa em reais e o pessoal em reais”"),
        "city": ("Em que cidade você está hoje? (É para os lembretes chegarem na hora certa.)", "Ex.: São Paulo"),
        "priorities": ("Em que você quer que eu te ajude primeiro? Escolha até 3.", None),
        "prio_opts": {"agenda": "Agenda", "email": "E-mails", "expenses": "Gastos e recibos", "tasks": "Tarefas",
                      "meetings": "Reuniões e atas", "booking": "Agendamento de clientes"},
        "style": ("Prefere respostas curtas e diretas, ou mais detalhadas?", None),
        "style_opts": {"short": "Curtas e diretas", "detailed": "Mais detalhadas"},
        "briefing": ("Quer um resumo do seu dia toda manhã? Que horas?", None),
        "briefing_opts": {"07:00": "7h", "08:00": "8h", "09:00": "9h", "off": "Não, obrigado"},
        "emails": ("Por último: quer receber por e-mail dicas de gestão e novidades do Fidus? (Dá para mudar depois nas Configurações.)", None),
        "emails_opts": {"yes": "Sim, quero", "no": "Agora não"},
        "continue": "Continuar", "skip": "Pular",
        "wallet_limit": "Criei a carteira “{first}”. Mais de uma carteira faz parte do plano Negócio.",
        "done": ["Pronto, {name}! Antes de começar, três combinados:\n1. Eu nunca envio nada em seu nome (e-mail, convite, ata) sem você aprovar.\n2. Tudo que eu faço aparece em Atividade, com Desfazer.\n3. Seus dados são seus: não uso para propaganda, e você pode exportar ou apagar tudo quando quiser.\n\nAh, eu também erro às vezes. Se algo sair errado, é só me dizer.",
                 "Vamos testar? Me diga algo como “paguei 30 reais de gasolina”, “marca dentista quinta às 10” ou mande a foto de um recibo."],
    },
    "pt-pt": {
        "intro": "Olá! Sou o Fidus, o seu assistente. Em 2 minutos fico ajustado a si. Pode responder a falar ou a escrever, e saltar o que quiser.",
        "name": ("Como quer que o trate?", "Ex.: Mike"),
        "work": ("Trabalha por conta própria, tem empresa, ou as duas coisas?", None),
        "work_opts": {"self": "Por conta própria", "company": "Tenho empresa", "both": "As duas"},
        "wallets": ("Que empresas ou contas devo separar nas suas despesas? E em que moeda está cada uma?",
                    "Ex.: “A minha empresa em euros e o pessoal em euros”"),
        "city": ("Em que cidade está hoje? (É para os lembretes chegarem à hora certa.)", "Ex.: Lisboa"),
        "priorities": ("Em que quer que o ajude primeiro? Escolha até 3.", None),
        "prio_opts": {"agenda": "Agenda", "email": "E-mails", "expenses": "Despesas e recibos", "tasks": "Tarefas",
                      "meetings": "Reuniões e atas", "booking": "Marcações de clientes"},
        "style": ("Prefere respostas curtas e diretas, ou mais detalhadas?", None),
        "style_opts": {"short": "Curtas e diretas", "detailed": "Mais detalhadas"},
        "briefing": ("Quer um resumo do seu dia todas as manhãs? A que horas?", None),
        "briefing_opts": {"07:00": "7h", "08:00": "8h", "09:00": "9h", "off": "Não, obrigado"},
        "emails": ("Por último: quer receber por e-mail dicas de gestão e novidades do Fidus? (Pode alterar depois nas Definições.)", None),
        "emails_opts": {"yes": "Sim, quero", "no": "Agora não"},
        "continue": "Continuar", "skip": "Saltar",
        "wallet_limit": "Criei a carteira “{first}”. Mais do que uma carteira faz parte do plano Negócio.",
        "done": ["Pronto, {name}! Antes de começar, três combinados:\n1. Nunca envio nada em seu nome (e-mail, convite, ata) sem a sua aprovação.\n2. Tudo o que faço aparece em Atividade, com Anular.\n3. Os seus dados são seus: não os uso para publicidade e pode exportar ou apagar tudo quando quiser.\n\nAh, e também me engano às vezes. Se algo correr mal, é só dizer-me.",
                 "Vamos experimentar? Diga-me algo como “paguei 40 euros de combustível”, “marca o dentista quinta às 10” ou envie a foto de um recibo."],
    },
    "en": {
        "intro": "Hi! I'm Fidus, your assistant. Give me 2 minutes and I'll fit around you. Answer by voice or text, and skip anything you like.",
        "name": ("What should I call you?", "e.g. Mike"),
        "work": ("Are you self-employed, do you run a company, or both?", None),
        "work_opts": {"self": "Self-employed", "company": "I run a company", "both": "Both"},
        "wallets": ("Which businesses or accounts should I keep separate for your spending? And in which currency is each one?",
                    "e.g. “My business in pounds and personal in pounds”"),
        "city": ("Which city are you in today? (So reminders arrive at the right time.)", "e.g. London"),
        "priorities": ("What would you like help with first? Pick up to 3.", None),
        "prio_opts": {"agenda": "Diary", "email": "Emails", "expenses": "Expenses & receipts", "tasks": "Tasks",
                      "meetings": "Meetings & notes", "booking": "Client bookings"},
        "style": ("Do you prefer short, to-the-point answers, or more detail?", None),
        "style_opts": {"short": "Short and direct", "detailed": "More detail"},
        "briefing": ("Would you like a summary of your day every morning? What time?", None),
        "briefing_opts": {"07:00": "7am", "08:00": "8am", "09:00": "9am", "off": "No, thanks"},
        "emails": ("Last one: would you like management tips and Fidus news by email? (You can change this later in Settings.)", None),
        "emails_opts": {"yes": "Yes, please", "no": "Not now"},
        "continue": "Continue", "skip": "Skip",
        "wallet_limit": "I've created the “{first}” wallet. More than one wallet is part of the Business plan.",
        "done": ["All set, {name}! Before we start, three promises:\n1. I never send anything in your name (email, invite, minutes) without your approval.\n2. Everything I do shows up in Activity, with Undo.\n3. Your data is yours: I don't use it for advertising, and you can export or delete everything whenever you like.\n\nOh, and I get things wrong sometimes. If something's off, just tell me.",
                 "Shall we try? Say something like “I paid £30 for petrol”, “book the dentist Thursday at 10” or send me a photo of a receipt."],
    },
    "es": {
        "intro": "¡Hola! Soy Fidus, tu asistente. En 2 minutos me adapto a ti. Puedes responder hablando o escribiendo, y saltarte lo que quieras.",
        "name": ("¿Cómo quieres que te llame?", "Ej.: Mike"),
        "work": ("¿Trabajas por tu cuenta, tienes empresa, o las dos cosas?", None),
        "work_opts": {"self": "Por mi cuenta", "company": "Tengo empresa", "both": "Las dos"},
        "wallets": ("¿Qué empresas o cuentas separo en tus gastos? ¿Y en qué moneda está cada una?",
                    "Ej.: “Mi empresa en euros y lo personal en euros”"),
        "city": ("¿En qué ciudad estás hoy? (Para que los recordatorios lleguen a su hora.)", "Ej.: Madrid"),
        "priorities": ("¿En qué quieres que te ayude primero? Elige hasta 3.", None),
        "prio_opts": {"agenda": "Agenda", "email": "Correos", "expenses": "Gastos y recibos", "tasks": "Tareas",
                      "meetings": "Reuniones y actas", "booking": "Citas de clientes"},
        "style": ("¿Prefieres respuestas cortas y directas, o más detalladas?", None),
        "style_opts": {"short": "Cortas y directas", "detailed": "Más detalladas"},
        "briefing": ("¿Quieres un resumen de tu día cada mañana? ¿A qué hora?", None),
        "briefing_opts": {"07:00": "7:00", "08:00": "8:00", "09:00": "9:00", "off": "No, gracias"},
        "emails": ("Por último: ¿quieres recibir por correo consejos de gestión y novedades de Fidus? (Puedes cambiarlo luego en Ajustes.)", None),
        "emails_opts": {"yes": "Sí, quiero", "no": "Ahora no"},
        "continue": "Continuar", "skip": "Saltar",
        "wallet_limit": "He creado la cartera “{first}”. Más de una cartera forma parte del plan Negocio.",
        "done": ["¡Listo, {name}! Antes de empezar, tres compromisos:\n1. Nunca envío nada en tu nombre (correo, invitación, acta) sin tu aprobación.\n2. Todo lo que hago aparece en Actividad, con Deshacer.\n3. Tus datos son tuyos: no los uso para publicidad y puedes exportar o borrar todo cuando quieras.\n\nAh, y a veces me equivoco. Si algo sale mal, dímelo.",
                 "¿Probamos? Dime algo como “he pagado 40 euros de gasolina”, “pon el dentista el jueves a las 10” o mándame la foto de un recibo."],
    },
}


def _lang() -> str:
    lang = store.user_lang()
    return lang if lang in T else ("pt" if lang.startswith("pt") else lang)


def _texts(lang: str) -> dict:
    """Idiomas sem texto escrito à mão: o inglês adaptado pela IA, uma vez por idioma, guardado em arquivo."""
    if lang in T:
        return T[lang]
    path = os.path.join(config.DATA_DIR, "i18n", f"onboarding-{lang}.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        pass
    if lang not in i18n.LANGS:
        return T["en"]
    try:
        out = llm.chat("Adapt this onboarding script of a personal assistant app from British English to "
                       f"{i18n.LANGS[lang]}. Adapt naturally for that country (local currency, everyday examples, "
                       "polite form usual in apps), do not translate word by word. Keep the JSON structure and keys, "
                       "keep {name} and {first} placeholders. Reply ONLY with the JSON.",
                       [{"role": "user", "content": json.dumps(T["en"], ensure_ascii=False)}], [],
                       web_search=False, model=config.LLM_MODEL_LIGHT)
        data = json.loads(re.search(r"\{.*\}", out.get("text") or "", re.S).group(0))
        assert set(T["en"]) <= set(data)
    except Exception:  # noqa: BLE001 - sem tradução, fica em inglês
        return T["en"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return data


# ---------- estado ----------
def _state() -> dict:
    try:
        return json.loads(store.kv_get("onboarding") or "{}")
    except ValueError:
        return {}


def _save(st: dict) -> None:
    store.kv_set("onboarding", json.dumps(st))


def pending() -> bool:
    """Conta nova que ainda não passou pelas boas-vindas (contas antigas: só se pedirem para refazer)."""
    st = _state()
    if st.get("done"):
        return False
    if st.get("started"):
        return True
    u = store.current()
    if u.get("is_owner"):
        return False
    with store._conn() as c:
        had = c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    return had == 0


def restart() -> dict:
    _save({"started": True, "step": 0})
    return question()


def question() -> dict:
    st = _state()
    if not st.get("started"):
        st = {"started": True, "step": 0}
        _save(st)
    if st.get("done"):
        return {"done": True}
    lang = _lang()
    tx = _texts(lang)
    step = STEPS[st.get("step", 0)]
    text, hint = tx[step]
    out = {"step": step, "index": STEPS.index(step) + 1, "total": len(STEPS), "text": text, "hint": hint,
           "kind": "text", "options": [], "skip": tx["skip"], "continue": tx["continue"]}
    if st.get("step", 0) == 0:
        out["intro"] = tx["intro"]
    opts = {"work": "work_opts", "priorities": "prio_opts", "style": "style_opts", "briefing": "briefing_opts",
            "emails": "emails_opts"}.get(step)
    if opts:
        out["kind"] = "multi" if step == "priorities" else "choice"
        out["options"] = [{"id": k, "label": v} for k, v in tx[opts].items()]
        if step == "priorities":
            out["max"] = 3
    if step == "wallets":
        cur = COUNTRY_CURRENCY.get((store.profile().get("country") or "").upper())
        if cur:
            out["suggested_currency"] = cur
    return out


# ---------- respostas ----------
def _extract(kind: str, text: str) -> dict:
    """Entende a resposta livre (voz ou texto) com o modelo leve. Nunca inventa: na dúvida, devolve vazio."""
    prompts = {
        "name": 'From the reply, extract the name the person wants to be called. JSON {"name": "..."} or {"name": ""}.',
        "wallets": ('From the reply, list the businesses/accounts to track spending separately, with ISO currency '
                    'codes (reais=BRL, libras/pounds=GBP, euros=EUR, dólares=USD). JSON {"wallets": [{"name": "...", '
                    '"currency": "XXX"}]} (max 6; currency "" if not said).'),
        "city": 'From the reply, give the city and its IANA time zone. JSON {"city": "...", "timezone": "Area/City"} or empty strings.',
    }
    try:
        out = llm.chat(prompts[kind] + " Reply ONLY with JSON.", [{"role": "user", "content": text[:500]}], [],
                       web_search=False, model=config.LLM_MODEL_LIGHT)
        return json.loads(re.search(r"\{.*\}", out.get("text") or "", re.S).group(0))
    except Exception:  # noqa: BLE001
        return {}


def answer(step: str, value=None, skip: bool = False) -> dict:
    """Aplica a resposta da pergunta atual e devolve a próxima (ou o fecho)."""
    st = _state()
    if not st.get("started") or st.get("done"):
        return {"done": True}
    cur = STEPS[st.get("step", 0)]
    if step != cur:
        return {"error": "pergunta fora de ordem", **question()}
    tx = _texts(_lang())
    notes: list[str] = []
    if not skip and value not in (None, "", []):
        notes += _apply(cur, value, tx) or []
    st["step"] = st.get("step", 0) + 1
    if st["step"] >= len(STEPS):
        st["done"] = True
        _save(st)
        name = store.profile().get("name") or ""
        closing = [m.replace("{name}", name).replace(", !", "!").replace(" ,", ",") for m in tx["done"]]
        if not name:
            closing[0] = re.sub(r",\s*!", "!", closing[0])
        return {"done": True, "notes": notes, "messages": closing}
    _save(st)
    return {**question(), "notes": notes}


def _apply(step: str, value, tx: dict) -> list[str]:
    p = store.profile()
    if step == "name":
        text = str(value).strip()
        name = text if len(text) <= 30 and len(text.split()) <= 3 else (_extract("name", text).get("name") or "")
        name = re.sub(r"^(me chama de|me chame de|pode me chamar de|call me|i'?m|eu sou o|eu sou a|sou o|sou a)\s+",
                      "", name, flags=re.I).strip(" .!")
        if name:
            store.save_profile(name=name[:40])
    elif step == "work" and value in tx["work_opts"]:
        store.save_profile(work_type=value)
    elif step == "wallets":
        found = _extract("wallets", str(value)).get("wallets") or []
        found = [w for w in found if isinstance(w, dict) and (w.get("name") or "").strip()][:6]
        if not found:
            return []
        if not plans.allows("extra_business"):
            first = found[0]
            _set_wallets([first])
            return [tx["wallet_limit"].replace("{first}", first["name"].strip()[:40])] if len(found) > 1 else []
        _set_wallets(found)
    elif step == "city":
        got = _extract("city", str(value))
        tz = (got.get("timezone") or "").strip()
        try:
            ZoneInfo(tz)
        except Exception:  # noqa: BLE001
            tz = ""
        ch = {"city": (got.get("city") or str(value))[:60]}
        if tz:
            ch["timezone"] = tz
            store.kv_set("tz_set", "1")
        store.save_profile(**ch)
    elif step == "priorities":
        vals = [v for v in (value if isinstance(value, list) else [value]) if v in tx["prio_opts"]][:3]
        if vals:
            store.save_profile(priorities=vals)
    elif step == "style" and value in tx["style_opts"]:
        store.save_profile(reply_style=value)
    elif step == "briefing" and value in tx["briefing_opts"]:
        store.save_profile(briefing_time=value)
    elif step == "emails" and value in ("yes", "no"):
        from . import newsletter
        store.save_profile(marketing=value == "yes")
        newsletter.set_consent(store.current(), value == "yes", store.profile())
    _ = p
    return []


def _set_wallets(found: list[dict]) -> None:
    """Troca a carteira padrão ("Pessoal", sem gastos ainda) pelas que a pessoa disse; mantém as que já têm uso."""
    p = store.profile()
    current = p.get("businesses") or []
    with store._conn() as c:
        used = {r[0] for r in c.execute("SELECT DISTINCT business FROM expenses WHERE deleted=0")}
    keep = [b for b in current if b in used]
    names: list[str] = []
    wc = dict(p.get("wallet_currency") or {})
    for w in found:
        name = re.sub(r"\s+", " ", w["name"].strip())[:40]
        if name.lower() in (n.lower() for n in names + keep):
            continue
        names.append(name)
        cur = (w.get("currency") or "").strip().upper()
        if re.fullmatch(r"[A-Z]{3}", cur):
            wc[name] = cur
    store.save_profile(businesses=keep + names, wallet_currency=wc)
    currencies = {wc.get(n) for n in names if wc.get(n)}
    if len(currencies) == 1:
        store.save_profile(currency=currencies.pop())
