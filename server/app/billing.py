"""Assinatura pelo site com o Stripe Checkout (cartão, Apple Pay, Google Pay).

O app do beta é instalado fora da Google Play, por isso a assinatura é feita numa página segura do Stripe:
- POST /v1/billing/checkout → link do Stripe para o plano escolhido (mensal ou anual), no preço da moeda do cliente.
  Quem ainda está nos dias grátis não perde os dias que faltam: a 1.ª cobrança fica para o fim do teste.
- POST /billing/stripe → aviso assinado do Stripe (assinou, renovou, falhou, cancelou); o plano muda sozinho.
- POST /v1/billing/portal → página do Stripe para trocar o cartão ou cancelar.
Os preços vêm de plans.PRICES (não é preciso criar produtos no painel do Stripe). As chaves ficam só no .env.
"""
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

import requests

from . import accounts, config, countries, mailer, plans, store

API = "https://api.stripe.com/v1"
TOLERANCE = 300  # segundos de diferença aceites na assinatura do aviso


def enabled() -> bool:
    return bool(config.STRIPE_SECRET_KEY)


def _call(method: str, path: str, data: dict | None = None) -> dict:
    r = requests.request(method, API + path, data=data, auth=(config.STRIPE_SECRET_KEY, ""), timeout=20,
                         headers={"Stripe-Version": config.STRIPE_API_VERSION})  # mesma versão do webhook
    out = r.json()
    if r.status_code >= 400:
        raise RuntimeError((out.get("error") or {}).get("message") or f"Stripe {r.status_code}")
    return out


def _flat(prefix: str, value, out: dict) -> dict:
    """{'a': {'b': 1}} → {'a[b]': 1}, como a API do Stripe espera (form)."""
    if isinstance(value, dict):
        for k, v in value.items():
            _flat(f"{prefix}[{k}]" if prefix else k, v, out)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _flat(f"{prefix}[{i}]", v, out)
    elif value is not None:
        out[prefix] = "true" if value is True else "false" if value is False else str(value)
    return out


def _base() -> str:
    return (config.PUBLIC_BASE_URL or "").rstrip("/")


def _owner_email(u: dict) -> str:
    return (config.OWNER_EMAIL if u["id"] == store.OWNER_ID else u.get("email")) or ""


def checkout(plan: str, period: str = "month") -> dict:
    """Link do Stripe Checkout para o cliente atual assinar `plan`."""
    if not enabled():
        raise ValueError("pagamento ainda não está ligado")
    if plan not in plans.PLANS:
        raise ValueError("plano desconhecido")
    if period not in ("month", "year"):
        raise ValueError("período inválido")
    u = store.current()
    if u.get("member_id"):
        raise PermissionError("só o titular da conta pode assinar")
    cur = plans.user_currency()
    month = plans.price(plan, cur)
    amount = plans.year_price(month) if period == "year" else month
    sub = {"metadata": {"fidus_user": u["id"], "plan": plan}}
    end = plans.trial_ends()
    if plans.access() == "trial" and end:  # não perde os dias grátis que faltam
        ts = int(datetime.fromisoformat(end).timestamp())
        if ts - time.time() > 49 * 3600:  # o Stripe pede pelo menos 48 h
            sub["trial_end"] = ts
    data = {
        "mode": "subscription",
        "client_reference_id": u["id"],
        "customer_email": _owner_email(u) or None,
        "locale": "pt" if store.user_lang().startswith("pt") else "en",
        "allow_promotion_codes": True,
        "line_items": [{"quantity": 1, "price_data": {
            "currency": cur.lower(), "unit_amount": int(round(amount * 100)),
            "recurring": {"interval": period},
            "tax_behavior": "inclusive",  # os preços do site já incluem o IVA
            "product_data": {"name": f"Fidus {plans.PLANS[plan]['name']}", "tax_code": config.STRIPE_TAX_CODE}}}],
        "subscription_data": sub,
        "metadata": {"fidus_user": u["id"], "plan": plan},
        "success_url": f"{_base()}/assinatura/ok",
        "cancel_url": f"{_base()}/assinatura/cancelada",
    }
    if config.STRIPE_MANAGED:
        data["managed_payments"] = {"enabled": True}
    cust = store.kv_get("stripe_customer")
    if cust:
        data.pop("customer_email")
        data["customer"] = cust
    s = _call("POST", "/checkout/sessions", _flat("", data, {}))
    return {"url": s["url"], "plan": plan, "period": period, "amount": amount, "currency": cur}


def portal() -> dict:
    if not enabled():
        raise ValueError("pagamento ainda não está ligado")
    cust = store.kv_get("stripe_customer")
    if not cust:
        raise ValueError("ainda não há assinatura nesta conta")
    s = _call("POST", "/billing_portal/sessions", {"customer": cust, "return_url": f"{_base()}/assinatura/ok"})
    return {"url": s["url"]}


# ---------- aviso do Stripe ----------
def verify(payload: bytes, header: str) -> dict:
    """Confere a assinatura Stripe-Signature (t=..., v1=...). Erro = aviso falso ou velho."""
    secret = config.STRIPE_WEBHOOK_SECRET
    if not secret:
        raise ValueError("segredo do aviso não configurado")
    parts = dict(p.split("=", 1) for p in (header or "").split(",") if "=" in p)
    sigs = [p.split("=", 1)[1] for p in (header or "").split(",") if p.startswith("v1=")]
    ts = parts.get("t", "")
    if not ts.isdigit() or abs(time.time() - int(ts)) > TOLERANCE:
        raise ValueError("aviso fora do prazo")
    want = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(want, s) for s in sigs):
        raise ValueError("assinatura inválida")
    return json.loads(payload)


def _user_for(obj: dict) -> dict | None:
    meta = obj.get("metadata") or {}
    uid = meta.get("fidus_user") or obj.get("client_reference_id")
    if not uid and obj.get("customer"):
        uid = _customer_owner(obj["customer"])
    u = accounts.get_user(uid) if uid else None
    return u if u and u["status"] == "ativo" else None


def _customer_owner(cust: str) -> str | None:
    with accounts._db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS stripe_customers (customer TEXT PRIMARY KEY, user_id TEXT NOT NULL)")
        r = c.execute("SELECT user_id FROM stripe_customers WHERE customer=?", (cust,)).fetchone()
    return r["user_id"] if r else None


def _remember_customer(cust: str, uid: str) -> None:
    with accounts._db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS stripe_customers (customer TEXT PRIMARY KEY, user_id TEXT NOT NULL)")
        c.execute("INSERT OR REPLACE INTO stripe_customers(customer,user_id) VALUES(?,?)", (cust, uid))


def _mail(u: dict, kind: str, plan: str) -> None:
    to = _owner_email(u)
    if to:
        mailer.send(to, kind, store.user_lang(), name=store.user_name(), plan=plans.PLANS[plan]["name"])


def handle(event: dict) -> dict:
    """Aplica um aviso do Stripe. Repetir o mesmo aviso não muda nada (o Stripe pode reenviar)."""
    kind = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    u = _user_for(obj)
    if not u:
        return {"ignored": "cliente desconhecido"}
    with store.as_user(accounts.user_ctx(u)):
        seen = set((store.kv_get("stripe_events") or "").split(","))
        if event.get("id") in seen:
            return {"ignored": "repetido"}
        store.kv_set("stripe_events", ",".join(list(seen - {""})[-50:] + [event.get("id") or ""]))
        plan = (obj.get("metadata") or {}).get("plan")
        if kind == "checkout.session.completed" and obj.get("mode") == "subscription":
            if obj.get("customer"):
                store.kv_set("stripe_customer", obj["customer"])
                _remember_customer(obj["customer"], u["id"])
            if plan in plans.PLANS:
                plans.set_plan(plan)
                store.kv_set("subscription", f"ativa:{plan}")
                countries.freeze()  # o país do plano fica fixo (no Global, os três)
                store.add_activity("subscription", f"Assinatura do plano {plans.PLANS[plan]['name']}", "Stripe", "feito")
                _mail(u, "sub_started", plan)
                from . import ads
                total = (obj.get("amount_total") or 0) / 100 or plans.price(plan, plans.user_currency())
                ads.send("Subscribe", _owner_email(u), f"sub-{obj.get('id') or u['id']}", value=total,
                         currency=(obj.get("currency") or plans.user_currency()))
            return {"ok": True, "plan": plan}
        if kind in ("customer.subscription.updated", "customer.subscription.created"):
            st = obj.get("status")
            p = plan if plan in plans.PLANS else plans.current()
            if st in ("active", "trialing"):
                plans.set_plan(p)
                store.kv_set("subscription", f"{'cancelada' if obj.get('cancel_at_period_end') else 'ativa'}:{p}")
            elif st in ("past_due", "unpaid", "incomplete"):
                store.kv_set("subscription", f"problema_pagamento:{p}")
                _mail(u, "sub_billing_issue", p)
            return {"ok": True, "status": st}
        if kind == "customer.subscription.deleted":
            store.kv_set("subscription", "expirada")
            p = plans.current()
            plans.start_trial(0)
            store.kv_set("trial_ends", datetime.now(timezone.utc).isoformat())  # acabou: volta a pedir assinatura
            _mail(u, "sub_expired", p)
            return {"ok": True, "status": "expirada"}
        if kind == "invoice.paid" and (obj.get("amount_paid") or 0) > 0:
            from . import partners
            accounts.mark_paid(u["id"])  # 1.ª cobrança de verdade: quem convidou ganha o desconto
            try:
                partners.on_payment(u["id"], str(obj.get("id") or ""), obj["amount_paid"] / 100,
                                    (obj.get("currency") or "eur").upper())
            except (TypeError, ValueError, KeyError):
                pass
            return {"ok": True, "paid": obj["amount_paid"] / 100}
    return {"ignored": kind}
