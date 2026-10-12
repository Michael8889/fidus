"""Pagar por voz (Premium), fase 1: o Fidus prepara o pagamento e quem paga é o usuário, no app do banco.

- Contatos de pagamento que o Fidus aprende sozinho: na primeira vez ele pergunta a chave Pix (ou os dados do banco)
  no próprio cartão, ou o usuário escolhe na agenda do celular; depois lembra. Nada de cadastrar duas vezes.
- Pix: gera o "Pix copia e cola" (BR Code do Banco Central) com chave, valor e descrição. O usuário copia, cola no
  app do banco e confirma lá: o banco mostra o nome do dono da chave antes de pagar.
- Reino Unido / IBAN: o cartão mostra os dados para copiar.
- Portugal: MB Way (número do telemóvel do contacto) e Multibanco (entidade + referência de uma fatura, lidas da
  foto ou ditas pelo usuário). O usuário copia e paga na app do banco ou do MB Way.
- "Já paguei": lança o gasto na carteira certa (com Desfazer na Atividade).

O Fidus nunca move dinheiro sozinho: não há ferramenta da IA que pague, e o cartão só muda com o toque do usuário.
"""
import re
import unicodedata
import uuid

from . import countries, store

KEY_TYPES = ["celular", "cpf", "cnpj", "email", "aleatoria"]
METHOD_CURRENCY = {"pix": "BRL", "uk": "GBP", "iban": "EUR", "mbway": "EUR", "multibanco": "EUR"}


def normalize_pt_phone(phone: str) -> str:
    """Telemóvel português para o MB Way: 912 345 678 / +351 912345678 -> +351912345678."""
    d = re.sub(r"\D", "", phone or "")
    if d.startswith("00351"):
        d = d[2:]
    if len(d) == 9 and d.startswith("9"):
        return "+351" + d
    if len(d) == 12 and d.startswith("3519"):
        return "+" + d
    raise ValueError("número do MB Way inválido: use um telemóvel português (9 dígitos, começa por 9)")


def multibanco(entity: str, reference: str) -> tuple[str, str]:
    """Pagamento de serviços: entidade (5 dígitos) e referência (9 dígitos), formatada como no talão."""
    e, r = re.sub(r"\D", "", entity or ""), re.sub(r"\D", "", reference or "")
    if len(e) != 5 or len(r) != 9:
        raise ValueError("Multibanco: a entidade tem 5 dígitos e a referência 9")
    return e, f"{r[:3]} {r[3:6]} {r[6:]}"


# ---------- Contatos ----------
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def contacts() -> list[dict]:
    return store.select("SELECT * FROM payment_contacts WHERE deleted=0 ORDER BY name")


def find(name: str) -> list[dict]:
    """Contatos que batem com o nome dito ("João", "joão do secador")."""
    q = _norm(name)
    if not q:
        return []
    rows = contacts()
    exact = [r for r in rows if _norm(r["name"]) == q]
    if exact:
        return exact
    words = [w for w in q.split() if len(w) > 2 and w not in ("pro", "pra", "para", "the", "for")]
    return [r for r in rows if words and all(w in _norm(r["name"] + " " + (r.get("note") or "")) for w in words)] \
        or [r for r in rows if words and words[0] in _norm(r["name"]).split()]


def normalize_pix_key(key: str, key_type: str) -> str:
    k = (key or "").strip()
    digits = re.sub(r"\D", "", k)
    if key_type == "celular":
        if digits.startswith("55") and len(digits) in (12, 13):
            return "+" + digits
        if len(digits) in (10, 11):
            return "+55" + digits
        raise ValueError("celular inválido: use DDD + número")
    if key_type == "cpf":
        if len(digits) != 11:
            raise ValueError("CPF precisa de 11 dígitos")
        return digits
    if key_type == "cnpj":
        if len(digits) != 14:
            raise ValueError("CNPJ precisa de 14 dígitos")
        return digits
    if key_type == "email":
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", k):
            raise ValueError("e-mail inválido")
        return k.lower()
    if key_type == "aleatoria":
        try:
            return str(uuid.UUID(k))
        except ValueError:
            raise ValueError("chave aleatória inválida") from None
    raise ValueError("tipo de chave desconhecido")


def _iban_ok(iban: str) -> bool:
    s = re.sub(r"\s", "", iban or "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", s):
        return False
    num = "".join(str(int(ch, 36)) for ch in s[4:] + s[:4])
    return int(num) % 97 == 1


def save_contact(name: str, pix_key: str | None = None, pix_key_type: str | None = None, iban: str | None = None,
                 sort_code: str | None = None, account_number: str | None = None, wallet: str | None = None,
                 category: str | None = None, note: str | None = None, mbway_phone: str | None = None) -> dict:
    name = (name or "").strip()[:60]
    if not name:
        raise ValueError("diga o nome do contato")
    data: dict = {}
    if mbway_phone:
        data.update(method="mbway", mbway_phone=normalize_pt_phone(mbway_phone))
    elif pix_key:
        kt = (pix_key_type or "").lower() or ("email" if "@" in pix_key else "")
        if kt not in KEY_TYPES:
            raise ValueError("diga o tipo da chave Pix: celular, CPF, CNPJ, e-mail ou aleatória")
        data.update(method="pix", pix_key=normalize_pix_key(pix_key, kt), pix_key_type=kt)
    elif iban:
        if not _iban_ok(iban):
            raise ValueError("IBAN inválido")
        data.update(method="iban", iban=re.sub(r"\s", "", iban).upper())
    elif sort_code or account_number:
        sc, acc = re.sub(r"\D", "", sort_code or ""), re.sub(r"\D", "", account_number or "")
        if len(sc) != 6 or len(acc) != 8:
            raise ValueError("sort code tem 6 dígitos e a conta 8")
        data.update(method="uk", sort_code=f"{sc[:2]}-{sc[2:4]}-{sc[4:]}", account_number=acc)
    else:
        raise ValueError("falta o MB Way, a chave Pix ou os dados do banco")
    countries.require_method(data["method"])
    if wallet:
        data["wallet"] = store.match_business(wallet) or wallet.strip()[:40]
    if category:
        data["category"] = category
    if note:
        data["note"] = note.strip()[:80]
    existing = next((r for r in contacts() if _norm(r["name"]) == _norm(name)), None)
    if existing:
        store.update("payment_contacts", existing["id"], **data)
        cid = existing["id"]
    else:
        cid = store.insert("payment_contacts", name=name, deleted=0, **data)
    return store.get("payment_contacts", cid)


# ---------- Pix copia e cola (BR Code estático, padrão do Banco Central) ----------
def _f(tag: str, value: str) -> str:
    return f"{tag}{len(value):02d}{value}"


def _crc16(data: str) -> str:
    crc = 0xFFFF
    for b in data.encode():
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def _ascii(s: str, n: int) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9 .,/-]", "", s).strip()[:n] or "PIX"


def brcode(key: str, amount: float, name: str, description: str = "", city: str = "BRASIL") -> str:
    gui = _f("00", "br.gov.bcb.pix") + _f("01", key)
    desc = _ascii(description, 72) if description else ""
    room = 99 - len(gui) - 4
    if desc and room > 0:
        gui += _f("02", desc[:room])
    payload = (_f("00", "01") + _f("26", gui) + _f("52", "0000") + _f("53", "986") + _f("54", f"{amount:.2f}")
               + _f("58", "BR") + _f("59", _ascii(name, 25).upper()) + _f("60", _ascii(city, 15).upper())
               + _f("62", _f("05", "***")) + "6304")
    return payload + _crc16(payload)


def mask(c: dict) -> str:
    if c.get("method") == "pix":
        k, kt = c.get("pix_key") or "", c.get("pix_key_type")
        if kt == "email":
            u, _, d = k.partition("@")
            return f"{u[:2]}•••@{d}"
        if kt == "aleatoria":
            return k[:8] + "…"
        return "•••" + k[-4:]
    if c.get("method") == "uk":
        return f"{c.get('sort_code')} · •••{(c.get('account_number') or '')[-4:]}"
    if c.get("method") == "mbway":
        return "MB Way •••" + (c.get("mbway_phone") or "")[-3:]
    if c.get("method") == "iban":
        return f"{(c.get('iban') or '')[:4]} ••• {(c.get('iban') or '')[-4:]}"
    return ""


# ---------- Pagamento preparado (cartão no app) ----------
def _wallet_for(contact: dict | None, currency: str | None, wallet: str | None) -> str:
    if wallet and store.match_business(wallet):
        return store.match_business(wallet)
    if contact and contact.get("wallet"):
        return store.match_business(contact["wallet"]) or contact["wallet"]
    if currency:
        for w in store.wallets():
            if (w.get("currency") or "").upper() == currency.upper():
                return w["name"]
    return store.businesses()[0]


def _build(payload: dict, contact: dict | None) -> dict:
    """Completa o cartão com o contato (ou marca que falta a chave)."""
    if not contact:
        payload.update(needs_key=True, method=None)
        return payload
    method = contact["method"]
    countries.require_method(method)
    cur = (payload.get("currency") or "").upper() or METHOD_CURRENCY[method]
    if method == "pix" and cur != "BRL":
        raise ValueError("Pix é só em reais (BRL)")
    if method == "mbway" and cur != "EUR":
        raise ValueError("MB Way é só em euros")
    wallet = _wallet_for(contact, cur, payload.get("wallet_asked"))
    payload.update(needs_key=False, method=method, currency=cur, contact_id=contact["id"], to=contact["name"],
                   masked=mask(contact), wallet=wallet, category=contact.get("category") or payload.get("category"))
    if method == "pix":
        payload["pix_code"] = brcode(contact["pix_key"], payload["amount"], contact["name"], payload.get("description", ""))
    elif method == "mbway":
        payload["mbway_phone"] = contact["mbway_phone"]
    elif method == "uk":
        payload.update(sort_code=contact["sort_code"], account_number=contact["account_number"])
    else:
        payload["iban"] = contact["iban"]
    return payload


def prepare(to: str, amount: float, currency: str | None = None, description: str | None = None,
            wallet: str | None = None, category: str | None = None, mb_entity: str | None = None,
            mb_reference: str | None = None) -> dict:
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        raise ValueError("valor inválido") from None
    if not 0 < amount < 1_000_000:
        raise ValueError("valor inválido")
    if mb_entity or mb_reference:  # fatura com referência Multibanco: não precisa de contacto
        countries.require_method("multibanco")
        ent, ref = multibanco(mb_entity or "", mb_reference or "")
        payload = {"to": (to or "").strip()[:60] or f"Entidade {ent}", "amount": amount, "currency": "EUR",
                   "description": (description or "").strip()[:72], "needs_key": False, "method": "multibanco",
                   "mb_entity": ent, "mb_reference": ref, "masked": f"Ent. {ent} · Ref. {ref}",
                   "wallet": _wallet_for(None, "EUR", wallet), "category": category}
        pid = store.create_pending("payment", payload)
        store.add_activity("payment_prepared", f"Pagamento para {payload['to']}", f"{amount:.2f} EUR", "aguardando", pid)
        return {"ok": True, "pending_action_id": pid, "to": payload["to"], "amount": amount, "currency": "EUR",
                "from_wallet": payload["wallet"], "method": "multibanco",
                "status": "aguardando o usuário pagar (Pagamento de Serviços) e tocar em 'Já paguei'"}
    found = find(to)
    if len(found) > 1:
        return {"ambiguous": True, "options": [{"name": c["name"], "how": mask(c), "wallet": c.get("wallet"),
                                                "currency": METHOD_CURRENCY.get(c["method"])} for c in found[:5]],
                "instruction": "Pergunte ao usuário qual destes, sem preparar nada ainda."}
    payload = {"to": (to or "").strip()[:60], "amount": amount, "currency": (currency or "").upper() or None,
               "description": (description or "").strip()[:72], "wallet_asked": wallet, "category": category}
    payload = _build(payload, found[0] if found else None)
    pid = store.create_pending("payment", payload)
    store.add_activity("payment_prepared", f"Pagamento para {payload['to']}",
                       f"{amount:.2f} {payload.get('currency') or ''}".strip(), "aguardando", pid)
    if payload["needs_key"]:
        return {"ok": True, "pending_action_id": pid, "needs_key": True,
                "status": f"aguardando o MB Way, a chave Pix ou os dados do banco de {payload['to']} no cartão (só nesta primeira vez)"}
    return {"ok": True, "pending_action_id": pid, "to": payload["to"], "amount": amount, "currency": payload["currency"],
            "from_wallet": payload["wallet"], "method": payload["method"],
            "status": "aguardando o usuário pagar no app do banco e tocar em 'Já paguei'"}


def set_key(pid: str, pix_key: str | None = None, pix_key_type: str | None = None, iban: str | None = None,
            sort_code: str | None = None, account_number: str | None = None, mbway_phone: str | None = None) -> dict:
    a = store.get_pending(pid)
    if not a or a["kind"] != "payment" or a["status"] != "pending":
        raise ValueError("pagamento não está pendente")
    p = a["payload"]
    contact = save_contact(p["to"], pix_key=pix_key, pix_key_type=pix_key_type, iban=iban, sort_code=sort_code,
                           account_number=account_number, wallet=p.get("wallet_asked"), mbway_phone=mbway_phone)
    p = _build(p, contact)
    store.update_pending(pid, "pending", p, only_if="pending")
    return store.get_pending(pid)


def mark_paid(pid: str) -> dict:
    a = store.get_pending(pid)
    if not a or a["kind"] != "payment" or a["status"] != "pending" or a["payload"].get("needs_key"):
        raise ValueError("pagamento não está pronto")
    p = a["payload"]
    if not store.update_pending(pid, "paid", only_if="pending"):
        raise ValueError("pagamento já foi marcado")
    from . import features
    eid = store.add_expense(features._now().date().isoformat(), p["amount"], p["currency"],
                            p.get("category") or "outros", p["wallet"], p["to"],
                            ("Pago pelo Fidus" + (f": {p['description']}" if p.get("description") else ""))[:200])
    store.update_activity_by_ref("payment_prepared", pid, "pago")
    store.add_activity("expense_added", f"{p['amount']:.2f} {p['currency']} · {p['to']}",
                       f"Pagamento · {p['wallet']}", "feito", str(eid))
    return {**store.get_pending(pid), "expense_id": eid}


def waiting() -> list[dict]:
    rows = store.select("SELECT id FROM pending_actions WHERE status='pending' AND kind='payment' ORDER BY created_at")
    return [store.get_pending(r["id"]) for r in rows]


# ---------- Ferramentas da IA (nenhuma paga: só preparam) ----------
TOOLS = [
    {
        "name": "prepare_payment",
        "description": "Prepara um pagamento por voz (Pix no Brasil; MB Way, Multibanco ou IBAN em Portugal; "
                       "transferência no Reino Unido) e mostra um cartão. NÃO paga: o usuário paga na app do banco e "
                       "toca em 'Já paguei'. Use para 'faz um Pix de 50 pro João', 'manda 30 euros por MB Way à Ana', "
                       "'paga 120 libras ao fornecedor'. Fatura portuguesa com referência Multibanco (foto ou dita): "
                       "passe mb_entity e mb_reference. Se vier ambiguous, pergunte qual contato. "
                       "Se vier needs_key, diga que na primeira vez ele informa a chave no cartão (ou escolhe da "
                       "agenda) ou fala a chave agora. Nunca diga que pagou.",
        "parameters": {"type": "object", "properties": {
            "to": {"type": "string", "description": "nome do contato como o usuário disse"},
            "amount": {"type": "number"},
            "currency": {"type": "string", "description": "BRL, GBP, EUR; vazio = a moeda do contato"},
            "description": {"type": "string", "description": "referência curta, ex. 'conserto do secador'"},
            "wallet": {"type": "string", "description": "carteira/conta de onde sai, se o usuário disse"},
            "category": {"type": "string", "description": "categoria do gasto, se óbvia"},
            "mb_entity": {"type": "string", "description": "Multibanco: entidade (5 dígitos) da fatura"},
            "mb_reference": {"type": "string", "description": "Multibanco: referência (9 dígitos) da fatura"},
        }, "required": ["to", "amount"]},
    },
    {
        "name": "save_payment_contact",
        "description": "Guarda (ou atualiza) um contato de pagamento quando o usuário fala o número do MB Way, a "
                       "chave Pix ou os dados do banco. Diga o tipo da chave Pix (celular, cpf, cnpj, email, aleatoria).",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
            "mbway_phone": {"type": "string", "description": "telemóvel português do MB Way"},
            "pix_key": {"type": "string"},
            "pix_key_type": {"type": "string", "enum": KEY_TYPES},
            "iban": {"type": "string"},
            "sort_code": {"type": "string"},
            "account_number": {"type": "string"},
            "wallet": {"type": "string", "description": "carteira de onde costuma sair o pagamento"},
            "note": {"type": "string", "description": "apelido/função, ex. 'secador', 'contador'"},
        }, "required": ["name"]},
    },
]


def _tool_save(**a) -> dict:
    c = save_contact(**a)
    return {"ok": True, "contact": c["name"], "how": mask(c), "wallet": c.get("wallet")}


DISPATCH = {"prepare_payment": lambda **a: prepare(**a), "save_payment_contact": _tool_save}
