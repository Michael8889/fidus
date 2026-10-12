"""v0.15: país do pacote (um por plano, três no Global) e pacote Reino Unido."""
import os
import tempfile
from datetime import date

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import countries, main, payments, plans, store, tools, uk  # noqa: E402

client = TestClient(main.app)
H = {"Authorization": "Bearer t"}


@pytest.fixture(autouse=True)
def _keep():
    before = store.kv_get("profile")
    plan = store.kv_get("plan")
    yield
    store.kv_set("profile", before) if before is not None else store.kv_del("profile")
    store.kv_set("plan", plan) if plan is not None else store.kv_del("plan")


def _names(ts):
    return {t["name"] for t in ts}


def test_global_plan_exists_and_prices():
    assert plans.PLANS["global"]["rank"] > plans.PLANS["premium"]["rank"]
    assert plans.PRICES["EUR"]["global"] == 89.90 and plans.PRICES["GBP"]["global"] == 79.90
    assert plans.FEATURE_MIN["multi_country"] == "global"


def test_one_country_per_plan_and_upsell():
    plans.set_plan("premium")
    store.save_profile(countries=[], country="PT", language="pt-PT")
    assert countries.user_countries() == ["PT"]
    r = countries.set_countries(["PT", "GB"])
    assert r["locked"] and r["upsell"]["plan"] == "global"
    assert countries.set_countries(["uk"])["countries"] == ["GB"]
    assert plans.user_currency() == "GBP"


def test_global_gets_three_countries():
    plans.set_plan("global")
    store.save_profile(countries=[], country="BR", language="pt")
    assert countries.user_countries()[0] == "BR" and len(countries.user_countries()) == 3
    assert countries.set_countries(["PT", "GB", "BR"])["ok"]
    plans.set_plan("premium")  # rebaixou: fica só o principal
    assert countries.user_countries() == ["PT"]


def test_tools_follow_the_country():
    plans.set_plan("premium")
    countries.set_countries(["GB"])
    names = _names(tools.available_tools())
    assert "setup_uk_tax_reminders" in names and "setup_tax_reminders" not in names and "set_nif" not in names
    exp = next(t for t in tools.available_tools() if t["name"] == "add_expense")["parameters"]["properties"]
    assert "supplier_vat_number" in exp and "buyer_nif" not in exp
    r = tools.run("set_nif", {"nif": "123456789"})
    assert r["locked"] and r["upsell"]["feature"] == "multi_country"
    countries.set_countries(["PT"])
    names = _names(tools.available_tools())
    assert "setup_tax_reminders" in names and "setup_uk_tax_reminders" not in names
    # a lista completa continua com tudo (Global)
    assert {"setup_tax_reminders", "setup_uk_tax_reminders"} <= _names(tools.TOOLS)


def test_payment_methods_follow_the_country():
    plans.set_plan("premium")
    countries.set_countries(["GB"])
    r = tools.run("save_payment_contact", {"name": "Zé", "mbway_phone": "912345678"})
    assert r["locked"] and "Global" in r["error"]
    r = tools.run("prepare_payment", {"to": "EDP", "amount": 10, "mb_entity": "21312", "mb_reference": "123456789"})
    assert r["locked"]
    ok = tools.run("save_payment_contact", {"name": "Jo Smith", "sort_code": "12-34-56", "account_number": "12345678"})
    assert ok["ok"]
    countries.set_countries(["BR"])
    assert payments.save_contact("Ana Pix", pix_key="ana@ex.com")["method"] == "pix"
    for c in payments.contacts():
        if c["name"] in ("Jo Smith", "Ana Pix"):
            store.update("payment_contacts", c["id"], deleted=1)


def test_wallet_currency_needs_global():
    plans.set_plan("premium")
    countries.set_countries(["PT"])
    r = tools.run("update_profile", {"add_business": "Pessoal UK", "business_currency": "GBP"})
    assert r["locked"]
    plans.set_plan("global")
    countries.set_countries(["PT", "GB"])
    r = tools.run("update_profile", {"add_business": "Pessoal UK", "business_currency": "GBP"})
    assert r["ok"]
    tools.run("update_profile", {"remove_business": "Pessoal UK"})


def test_countries_endpoint_activity_and_undo():
    plans.set_plan("premium")
    countries.set_countries(["PT"])
    me = client.get("/v1/me", headers=H).json()
    assert me["countries"]["countries"] == ["PT"] and me["countries"]["max"] == 1
    r = client.post("/v1/countries", json={"countries": ["GB"]}, headers=H).json()
    assert r["countries"] == ["GB"] and r["currency"] == "GBP"
    acts = client.get("/v1/activity", headers=H).json()
    act = next(a for a in (acts.get("items") if isinstance(acts, dict) else acts) if a["kind"] == "countries_changed")
    assert client.post(f"/v1/activity/{act['id']}/undo", headers=H).status_code == 200
    assert countries.user_countries() == ["PT"]
    assert client.post("/v1/countries", json={"countries": ["PT", "BR"]}, headers=H).json()["locked"]
    assert client.post("/v1/countries", json={"countries": ["XX"]}, headers=H).status_code == 400


def test_uk_vat_number_check():
    assert uk.valid_vat("GB 980 7806 84")  # HMRC example (new series)
    assert not uk.valid_vat("GB123456789")
    plans.set_plan("premium")
    countries.set_countries(["GB"])
    store.save_profile(uk_vat_registered=True)
    r = tools.run("add_expense", {"amount": 12, "currency": "GBP", "vat": 2, "category": "outros",
                                  "business": store.businesses()[0]})
    assert any("VAT number" in a for a in r.get("alerts", []))
    tools.run_delete_expense(r["expense_id"])
    r = tools.run("add_expense", {"amount": 12, "currency": "GBP", "vat": 2, "category": "outros",
                                  "business": store.businesses()[0], "supplier_vat_number": "GB123456789"})
    assert any("doesn't look valid" in a for a in r.get("alerts", []))
    tools.run_delete_expense(r["expense_id"])


def test_uk_tax_reminders_once(monkeypatch):
    plans.set_plan("premium")
    countries.set_countries(["GB"])
    made = []
    monkeypatch.setattr(uk.features, "create_reminder",
                        lambda text, when, recurrence=None, notes=None: made.append((text, when, recurrence)) or {"event_id": str(len(made))})
    store.save_profile(uk_tax_reminders=[])
    r = tools.run("setup_uk_tax_reminders", {"self_employed": True, "payments_on_account": True, "mtd_itsa": True,
                                             "vat_quarter_ends": [3, 6, 9, 12], "company_year_end": 3,
                                             "confirmation_month": 5, "employees": True})
    assert r["ok"] and len(r["created"]) == len(made) == 2 + 1 + 4 + 4 + 3 + 1 + 1
    texts = [m[0] for m in made]
    assert any("31 January" in t for t in texts) and any("PAYE" in t for t in texts)
    vat_june = next(m for m in made if "quarter ending June" in m[0])
    assert date.fromisoformat(vat_june[1][:10]).month == 8  # junho -> 7 de agosto
    ct = next(m for m in made if m[0].startswith("Corporation Tax: payment"))
    assert date.fromisoformat(ct[1][:10]).month == 12  # fim do ano em março -> paga 1 de janeiro
    assert all(m[2] in ("RRULE:FREQ=YEARLY", "RRULE:FREQ=MONTHLY") for m in made)
    assert tools.run("setup_uk_tax_reminders", {"self_employed": True})["already_existed"] == 2
    assert store.profile().get("uk_vat_registered")
