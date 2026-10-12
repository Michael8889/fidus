"""País do pacote: cada plano vale para UM país (e a moeda dele); o plano Global vale para os três.

O Fidus só oferece ao cliente o que é do país dele: ferramentas fiscais (Portugal: NIF, e-Fatura, calendário fiscal;
Reino Unido: Self Assessment, VAT, Companies House), formas de pagamento (MB Way/Multibanco, conta UK, Pix) e as
regras no texto para a IA. Menos ferramentas por pedido = respostas mais rápidas e mais baratas.
"""
from . import plans, store

COUNTRIES = {
    "PT": {"currency": "EUR", "name": "Portugal", "flag": "🇵🇹"},
    "GB": {"currency": "GBP", "name": "Reino Unido", "flag": "🇬🇧"},
    "BR": {"currency": "BRL", "name": "Brasil", "flag": "🇧🇷"},
}
# ferramentas que só existem num país
TOOL_COUNTRY = {
    "setup_tax_reminders": "PT", "set_nif": "PT", "irs_summary": "PT",
    "setup_uk_tax_reminders": "GB", "set_uk_tax_profile": "GB",
}
# forma de pagamento -> países onde aparece
METHOD_COUNTRIES = {"mbway": {"PT"}, "multibanco": {"PT"}, "iban": {"PT", "GB"}, "uk": {"GB"}, "pix": {"BR"}}


class CountryLocked(ValueError):
    """Pedido de outro país fora do pacote do cliente: vira a oferta do plano Global."""


def _guess() -> str:
    """Sem escolha feita: o país do celular; senão o idioma (pt-PT = Portugal, pt = Brasil); senão Reino Unido."""
    p = store.profile()
    cc = (p.get("country") or "").upper()
    cc = "GB" if cc == "UK" else cc
    if cc in COUNTRIES:
        return cc
    lang = (p.get("language") or "").lower()
    if lang.startswith("pt-pt"):
        return "PT"
    if lang.startswith("pt"):
        return "BR"
    return "GB"


def max_countries(plan: str | None = None) -> int:
    return 3 if (plan or plans.current()) == "global" else 1


def user_countries() -> list[str]:
    """Países do pacote do cliente, o principal primeiro."""
    p = store.profile()
    chosen = [c for c in (p.get("countries") or []) if c in COUNTRIES]
    if not chosen:  # sem escolha: o país do celular; no Global, os três (o do celular primeiro)
        g = _guess()
        chosen = [g] + [c for c in COUNTRIES if c != g] if max_countries() > 1 else [g]
    return chosen[:max_countries()]


def primary() -> str:
    return user_countries()[0]


def enabled(cc: str) -> bool:
    return cc in user_countries()


def currencies() -> set[str]:
    return {COUNTRIES[c]["currency"] for c in user_countries()}


def locked_in() -> bool:
    """O país fica fixo depois da primeira escolha (ou da assinatura). Trocar de país = mudar para o Global."""
    return bool(store.profile().get("countries")) and max_countries() == 1


def freeze() -> list[str]:
    """Na assinatura: grava o país atual (o do celular, se nunca escolheu) e ele passa a ser o do plano."""
    cs = user_countries()
    store.save_profile(countries=cs, country=cs[0])
    return cs


def set_countries(codes: list[str]) -> dict:
    codes = [("GB" if c.upper() == "UK" else c.upper()) for c in codes if c]
    codes = list(dict.fromkeys(c for c in codes if c in COUNTRIES))
    if not codes:
        raise ValueError("escolha Portugal, Reino Unido ou Brasil")
    if len(codes) > max_countries():
        return plans.locked("multi_country")
    if locked_in() and codes != user_countries():
        out = plans.locked("multi_country")
        out["error"] = (f"o plano vale só para {COUNTRIES[primary()]['name']} e o país não muda. Para usar outro "
                        "país: plano Global (os três países). " + out["error"])
        return out
    store.save_profile(countries=codes, country=codes[0])
    return {"ok": True, "countries": codes, "currencies": sorted(currencies())}


def tool_allowed(name: str) -> bool:
    cc = TOOL_COUNTRY.get(name)
    return not cc or enabled(cc)


def method_allowed(method: str) -> bool:
    return bool(METHOD_COUNTRIES.get(method, set()) & set(user_countries()))


def require_method(method: str) -> None:
    if method and not method_allowed(method):
        names = " / ".join(COUNTRIES[c]["name"] for c in sorted(METHOD_COUNTRIES.get(method, ())))
        raise CountryLocked(f"essa forma de pagamento é de {names}, fora do país do pacote "
                            f"({COUNTRIES[primary()]['name']}). Para usar mais de um país: plano Global")


def require_currency(currency: str | None) -> None:
    """Carteiras só nas moedas dos países do pacote (gastos avulsos em viagem continuam livres)."""
    cur = (currency or "").upper()
    if cur and cur in {c["currency"] for c in COUNTRIES.values()} and cur not in currencies():
        raise CountryLocked(f"carteira em {cur} é de outro país do pacote. Para usar mais de um país: plano Global")


def info() -> dict:
    return {"countries": user_countries(), "max": max_countries(), "chosen": bool(store.profile().get("countries")), "locked": locked_in(),
            "options": [{"code": k, **v} for k, v in COUNTRIES.items()]}
