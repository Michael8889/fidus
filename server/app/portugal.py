"""Pacote Portugal: NIF nas faturas, categorias do e-Fatura/IRS e calendário fiscal com lembretes.

Fontes das datas (calendário fiscal 2026): Vendus, "Trabalhadores Independentes: calendário fiscal para 2026" e
"Calendário fiscal das empresas 2026". Prazo que cai em fim de semana ou feriado passa para o dia útil seguinte; os
lembretes saem alguns dias ANTES, por isso valem todos os anos. Nada aqui substitui o contabilista certificado.
"""
from datetime import date, datetime, timedelta

from . import features, store

# ---------- NIF ----------
NIF_FIRST = set("1235689") | {"45", "70", "71", "72", "74", "75", "77", "78", "79", "90", "91", "98", "99"}


def valid_nif(nif: str | None) -> bool:
    """NIF português: 9 dígitos com dígito de controlo (módulo 11)."""
    d = "".join(ch for ch in (nif or "") if ch.isdigit())
    if len(d) != 9 or not (d[0] in NIF_FIRST or d[:2] in NIF_FIRST):
        return False
    total = sum(int(d[i]) * (9 - i) for i in range(8))
    check = 11 - total % 11
    return (0 if check >= 10 else check) == int(d[8])


def clean_nif(nif: str | None) -> str | None:
    d = "".join(ch for ch in (nif or "") if ch.isdigit())
    if d.startswith("351") and len(d) == 12:
        d = d[3:]
    return d or None


# ---------- e-Fatura / IRS ----------
# deduções à coleta e benefício do IVA por exigência de fatura (com o NIF do contribuinte)
IRS_CATEGORIES = {
    "despesas_gerais": "Despesas gerais familiares",
    "saude": "Saúde",
    "educacao": "Educação",
    "habitacao": "Habitação (rendas)",
    "lares": "Lares",
    "restauracao_alojamento": "Restauração e alojamento (benefício do IVA)",
    "reparacao_automoveis": "Reparação de automóveis e motociclos (benefício do IVA)",
    "cabeleireiros": "Cabeleireiros e institutos de beleza (benefício do IVA)",
    "veterinario": "Veterinário (benefício do IVA)",
    "ginasios": "Ginásios e clubes desportivos (benefício do IVA)",
    "passes_transportes": "Passes e transportes públicos (benefício do IVA)",
    "jornais_revistas": "Jornais e revistas (benefício do IVA)",
    "cultura": "Cultura: livros, espetáculos, museus (benefício do IVA)",
    "atividade": "Despesa da atividade (empresa / trabalho independente)",
}


def user_nif(wallet: str | None = None) -> str | None:
    nifs = store.profile().get("nifs") or {}
    if wallet and (store.match_business(wallet) or wallet) in nifs:
        return nifs[store.match_business(wallet) or wallet]
    return nifs.get("*")


def set_nif(nif: str, wallet: str | None = None) -> dict:
    n = clean_nif(nif)
    if not valid_nif(n):
        raise ValueError("NIF inválido: são 9 dígitos e o último é de controlo; confira o número")
    nifs = dict(store.profile().get("nifs") or {})
    key = (store.match_business(wallet) or wallet.strip()) if wallet else "*"
    nifs[key] = n
    store.save_profile(nifs=nifs)
    return {"wallet": None if key == "*" else key, "nif": n}


def is_portugal() -> bool:
    from . import countries
    return countries.enabled("PT")


def check_invoice(wallet: str, buyer_nif: str | None, supplier_nif: str | None, irs_category: str | None,
                  currency: str) -> list[str]:
    """Avisos sobre a fatura portuguesa acabada de lançar (só em euros e para quem está em Portugal)."""
    if currency != "EUR" or not is_portugal():
        return []
    out = []
    mine = user_nif(wallet)
    b = clean_nif(buyer_nif)
    if supplier_nif and not valid_nif(clean_nif(supplier_nif)):
        out.append("o NIF do vendedor na foto não é válido; confira se a fatura está bem lida")
    if not b:
        out.append("esta fatura não tem NIF de cliente: não conta para o IRS (nem para o IVA da empresa). "
                   "Na próxima, peça fatura com o seu NIF" + (f" ({mine})" if mine else ""))
    elif not valid_nif(b):
        out.append(f"o NIF de cliente na fatura ({b}) não é válido; confira a foto")
    elif mine and b != mine:
        out.append(f"o NIF na fatura ({b}) não é o desta carteira ({mine}): vai contar para outro contribuinte")
    if irs_category and IRS_CATEGORIES.get(irs_category, "").endswith("(benefício do IVA)") and b:
        out.append("dá dedução de parte do IVA no IRS (se o NIF for o seu); valide no e-Fatura até ao início de março")
    return out


def irs_summary(year: int | None = None) -> dict:
    y = int(year or date.today().year)
    rows = store.query_expenses(f"{y}-01-01", f"{y}-12-31", limit=10000)
    rows = [r for r in rows if r["currency"] == "EUR"]
    by: dict = {}
    without_nif = 0
    for r in rows:
        k = r.get("irs_category") or "sem_categoria"
        by.setdefault(k, {"label": IRS_CATEGORIES.get(k, "Sem categoria do e-Fatura"), "total": 0.0, "faturas": 0})
        by[k]["total"] = round(by[k]["total"] + r["amount"], 2)
        by[k]["faturas"] += 1
        if not r.get("buyer_nif"):
            without_nif += 1
    return {"year": y, "by_category": by, "invoices_without_nif": without_nif,
            "note": "totais lançados no Fidus, em euros. O que conta é o que está no e-Fatura: valide lá as faturas "
                    "pendentes até ao início de março. Limites e percentagens: confirme com o contabilista."}


# ---------- Calendário fiscal ----------
def _next(month: int, day: int) -> date:
    today = date.today()
    d = date(today.year, month, day)
    return d if d >= today else date(today.year + 1, month, day)


def _next_monthly(day: int) -> date:
    today = date.today()
    d = today.replace(day=day)
    if d < today:
        d = (today.replace(day=1) + timedelta(days=32)).replace(day=day)
    return d


def _plan(iva: str, self_employed: bool, company: bool, payments_on_account: bool, iuc_months: list[int],
          employees: bool) -> list[tuple[str, date, str | None, str]]:
    """(texto, primeira data, RRULE, nota)."""
    items: list = []
    if iva == "trimestral":
        for m, q in ((2, "4.º trimestre"), (5, "1.º trimestre"), (9, "2.º trimestre"), (11, "3.º trimestre")):
            items.append((f"IVA do {q}: declaração até dia 20, pagamento até dia 25", _next(m, 15),
                          "RRULE:FREQ=YEARLY", "Regime trimestral. Se o prazo cair ao fim de semana, passa para o dia útil seguinte."))
    elif iva == "mensal":
        items.append(("IVA do mês: declaração até dia 20, pagamento até dia 25", _next_monthly(15),
                      "RRULE:FREQ=MONTHLY", "Regime mensal: declaração do mês de há dois meses."))
    if self_employed:
        for m, per in ((1, "outubro a dezembro"), (4, "janeiro a março"), (7, "abril a junho"), (10, "julho a setembro")):
            items.append((f"Segurança Social: declaração trimestral ({per}) até ao fim do mês", _next(m, 20),
                          "RRULE:FREQ=YEARLY", "Trabalhador independente: rendimentos do trimestre anterior."))
        items.append(("Segurança Social: pagar a contribuição (entre dia 10 e 20)", _next_monthly(12),
                      "RRULE:FREQ=MONTHLY", "Em agosto o prazo vai até dia 31."))
    if payments_on_account:
        for m in (7, 9, 12):
            items.append(("IRS: pagamento por conta até dia 20", _next(m, 15), "RRULE:FREQ=YEARLY",
                          "Só se a AT lhe notificou pagamentos por conta."))
    items.append(("e-Fatura: validar as faturas pendentes (prazo no início de março)", _next(2, 20),
                  "RRULE:FREQ=YEARLY", "Faturas por validar podem não contar para as deduções do IRS."))
    items.append(("IRS: abre a entrega (1 de abril a 30 de junho)", _next(4, 1), "RRULE:FREQ=YEARLY", None))
    items.append(("IRS: último mês para entregar (até 30 de junho)", _next(6, 1), "RRULE:FREQ=YEARLY", None))
    if company:
        items.append(("Empresa: Modelo 22 (IRC) e IES — confirmar prazos com o contabilista certificado", _next(5, 2),
                      "RRULE:FREQ=YEARLY", "IES até 15 de julho; pagamentos por conta de IRC em julho, setembro e dezembro."))
    if employees:
        items.append(("Funcionários: declarações de remunerações (AT e Segurança Social) até dia 10", _next_monthly(7),
                      "RRULE:FREQ=MONTHLY", None))
        items.append(("Funcionários: pagar retenções na fonte até dia 20", _next_monthly(17), "RRULE:FREQ=MONTHLY", None))
    for m in iuc_months:
        items.append(("IUC: pagar este mês (mês da matrícula do carro)", _next(int(m), 1), "RRULE:FREQ=YEARLY", None))
    return items


def setup_tax_reminders(iva: str = "isento", self_employed: bool = False, company: bool = False,
                        payments_on_account: bool = False, iuc_months: list | None = None,
                        employees: bool = False) -> dict:
    if iva not in ("trimestral", "mensal", "isento"):
        raise ValueError("IVA: trimestral, mensal ou isento")
    months = [int(m) for m in (iuc_months or []) if str(m).isdigit() and 1 <= int(m) <= 12]
    done = store.profile().get("pt_tax_reminders") or []
    created, skipped = [], 0
    for text, first, rrule, note in _plan(iva, self_employed, company, payments_on_account, months, employees):
        key = f"{text}|{first.month}"
        if key in done:
            skipped += 1
            continue
        when = datetime(first.year, first.month, first.day, 9, 0).isoformat()
        r = features.create_reminder(text, when, rrule, note)
        created.append({"text": text, "first": first.isoformat(), "event_id": r.get("event_id")})
        done.append(key)
    store.save_profile(pt_tax_reminders=done)
    return {"ok": True, "created": created, "already_existed": skipped,
            "note": "Lembretes alguns dias antes de cada prazo, todos os anos. Datas de referência do calendário fiscal; "
                    "confirme os seus prazos com o contabilista certificado."}


TOOLS = [
    {
        "name": "setup_tax_reminders",
        "description": "PORTUGAL: cria lembretes recorrentes do calendário fiscal (IVA, Segurança Social, IRS, e-Fatura, "
                       "IUC, IRC). Antes, pergunte: regime de IVA (trimestral/mensal/isento), se é trabalhador "
                       "independente, se tem empresa, se tem funcionários, se tem pagamentos por conta e o mês da "
                       "matrícula do(s) carro(s) para o IUC. Não duplica se já foram criados.",
        "parameters": {"type": "object", "properties": {
            "iva": {"type": "string", "enum": ["trimestral", "mensal", "isento"]},
            "self_employed": {"type": "boolean", "description": "trabalhador independente (recibos verdes)"},
            "company": {"type": "boolean", "description": "tem empresa (sociedade)"},
            "employees": {"type": "boolean"},
            "payments_on_account": {"type": "boolean", "description": "a AT notificou pagamentos por conta de IRS"},
            "iuc_months": {"type": "array", "items": {"type": "integer"}, "description": "mês da matrícula de cada carro"},
        }, "required": ["iva"]},
    },
    {
        "name": "set_nif",
        "description": "PORTUGAL: guarda o NIF do usuário (ou o de uma carteira/empresa) para conferir as faturas. "
                       "Valida o dígito de controlo.",
        "parameters": {"type": "object", "properties": {
            "nif": {"type": "string"}, "wallet": {"type": "string", "description": "carteira/empresa; vazio = pessoal"},
        }, "required": ["nif"]},
    },
    {
        "name": "irs_summary",
        "description": "PORTUGAL: totais do ano por categoria do e-Fatura/IRS e quantas faturas ficaram sem NIF.",
        "parameters": {"type": "object", "properties": {"year": {"type": "integer"}}},
    },
]

DISPATCH = {"setup_tax_reminders": setup_tax_reminders, "set_nif": set_nif, "irs_summary": irs_summary}
