"""v0.15: pacote Portugal — NIF, e-Fatura, calendário fiscal, MB Way/Multibanco, textos em pt-PT."""
import os
import tempfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

import pytest  # noqa: E402

from app import mailer, payments, plans, portugal, site_forms, store, tools  # noqa: E402


@pytest.fixture(autouse=True)
def _keep_profile():
    """Estes testes mudam o país/idioma do perfil; os outros testes esperam o perfil de antes."""
    before = store.kv_get("profile")
    yield
    if before is None:
        store.kv_del("profile")
    else:
        store.kv_set("profile", before)


def _pt():
    store.save_profile(country="PT", language="pt-PT", nifs={})


def test_nif_check_digit():
    assert portugal.valid_nif("123456789")
    assert not portugal.valid_nif("123456788") and not portugal.valid_nif("12345") and not portugal.valid_nif("")
    assert portugal.clean_nif("PT 351123456789") == "123456789"


def test_set_nif_rejects_invalid_and_keeps_per_wallet():
    _pt()
    with pytest.raises(ValueError):
        portugal.set_nif("123456788")
    assert portugal.set_nif("123456789")["nif"] == "123456789"
    assert portugal.user_nif() == "123456789"


def test_invoice_without_nif_alerts_and_saves_category():
    _pt()
    portugal.set_nif("123456789")
    r = tools.run("add_expense", {"amount": 23.8, "category": "alimentacao", "business": "Pessoal", "currency": "EUR",
                                  "merchant": "Tasca", "irs_category": "restauracao_alojamento"})
    assert r["ok"] and any("não tem NIF" in a for a in r.get("alerts", []))
    ok = tools.run("add_expense", {"amount": 12, "category": "alimentacao", "business": "Pessoal", "currency": "EUR",
                                   "buyer_nif": "123 456 789", "irs_category": "restauracao_alojamento"})
    assert not any("não tem NIF" in a for a in ok.get("alerts", [])) and any("IVA" in a for a in ok.get("alerts", []))
    other = tools.run("add_expense", {"amount": 5, "category": "outros", "business": "Pessoal", "currency": "EUR",
                                      "buyer_nif": "999999990"})
    assert any("não é o desta carteira" in a for a in other.get("alerts", []))
    s = portugal.irs_summary()
    assert s["by_category"]["restauracao_alojamento"]["faturas"] >= 2 and s["invoices_without_nif"] >= 1


def test_no_nif_alerts_outside_portugal():
    store.save_profile(country="GB", language="en", nifs={}, countries=["GB"])
    r = tools.run("add_expense", {"amount": 10, "category": "outros", "business": "Pessoal", "currency": "EUR"})
    assert not any("NIF" in a for a in r.get("alerts", []))


def test_tax_reminders_created_once(monkeypatch):
    _pt()
    made = []
    monkeypatch.setattr(portugal.features, "create_reminder",
                        lambda text, when, recurrence=None, notes=None: made.append((text, when, recurrence)) or {"ok": True, "event_id": str(len(made))})
    store.save_profile(pt_tax_reminders=[])
    r = portugal.setup_tax_reminders(iva="trimestral", self_employed=True, iuc_months=[3])
    texts = [m[0] for m in made]
    assert sum("IVA do" in t for t in texts) == 4 and sum("declaração trimestral" in t for t in texts) == 4
    assert any("IUC" in t for t in texts) and all(m[2] and m[2].startswith("RRULE:FREQ=") for m in made)
    assert r["created"] and portugal.setup_tax_reminders(iva="trimestral", self_employed=True, iuc_months=[3])["already_existed"] == len(made)


def test_mbway_and_multibanco_payments():
    store.save_profile(country="PT", currency="EUR", businesses=["Pessoal"])
    with store._conn() as c:
        c.execute("DELETE FROM payment_contacts")
    assert payments.normalize_pt_phone("912 345 678") == "+351912345678"
    with pytest.raises(ValueError):
        payments.normalize_pt_phone("212345678")
    c = payments.save_contact("Ana Silva", mbway_phone="+351 912 345 678")
    assert c["method"] == "mbway" and payments.mask(c).endswith("678")
    r = payments.prepare("Ana Silva", 30)
    p = store.get_pending(r["pending_action_id"])["payload"]
    assert p["method"] == "mbway" and p["currency"] == "EUR" and p["mbway_phone"] == "+351912345678"
    m = payments.prepare("EDP", 54.2, mb_entity="21 312", mb_reference="123456789")
    mp = store.get_pending(m["pending_action_id"])["payload"]
    assert mp["method"] == "multibanco" and mp["mb_reference"] == "123 456 789" and not mp["needs_key"]
    with pytest.raises(ValueError):
        payments.prepare("EDP", 10, mb_entity="12", mb_reference="1")


def test_price_and_pt_pt_texts():
    assert plans.PRICES["EUR"]["essencial"] == 16.90
    assert "O seu código" in mailer.render("login_code", "pt-PT", code="1")[0]
    assert "Seu código" in mailer.render("login_code", "pt-BR", code="1")[0]
    assert site_forms._lang("pt-PT") == "pt-pt" and "Está na lista" in site_forms.WAIT_MAIL["pt-pt"][0]
    assert "Fale-nos" in site_forms.partner_page("pt-pt")


def test_pt_pt_translation_uses_portugal_vocabulary(monkeypatch):
    from app import i18n
    seen = {}

    def fake_chat(system, messages, tools_, **kw):
        seen["system"] = system
        return {"text": "{}"}
    monkeypatch.setattr(i18n.llm, "chat", fake_chat)
    i18n._ask("pt-pt", ["Salvar"])
    assert "telemóvel" in seen["system"] and "ecrã" in seen["system"] and "definições" in seen["system"]
    assert i18n._path("pt-pt").endswith("pt-pt.v2.json") and i18n._path("es").endswith("es.json")
    i18n._ask("es", ["Salvar"])
    assert "telemóvel" not in seen["system"]


def test_ready_translations_always_served_even_when_rate_limited(monkeypatch):
    from fastapi.testclient import TestClient
    from app import i18n, main
    c = TestClient(main.app)
    key = next(iter(i18n._allowed()))
    cache = i18n._load("de")
    cache[key] = "ÜBERSETZT"
    with open(i18n._path("de"), "w", encoding="utf-8") as f:
        import json
        json.dump(cache, f)
    monkeypatch.setattr(i18n.llm, "chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError("não devia gerar")))
    main._rate_hits.clear() if hasattr(main, "_rate_hits") else None
    for _ in range(35):  # passa do limite de quem ainda não entrou: os textos prontos continuam a vir
        r = c.post("/v1/i18n", json={"lang": "de", "strings": [key]}, headers={"x-real-ip": "10.8.8.8"})
        assert r.status_code == 200 and r.json()["strings"].get(key) == "ÜBERSETZT"


def test_translation_answers_at_once_even_if_ai_hangs(monkeypatch, tmp_path):
    import time
    from app import i18n
    keys = ["Pronto", "Guardar"]
    monkeypatch.setattr(i18n, "_allowed", lambda: set(keys))
    monkeypatch.setattr(i18n, "_path", lambda lang: str(tmp_path / f"{lang}.json"))
    (tmp_path / "fi.json").write_text('{"Pronto": "Valmis"}', encoding="utf-8")
    monkeypatch.setattr(i18n, "_ask", lambda lang, chunk: time.sleep(3) or {})
    t0 = time.time()
    out = i18n.translate("fi", keys)
    assert out == {"Pronto": "Valmis"} and time.time() - t0 < 1  # não espera a IA travada


def test_whatsapp_message_comes_as_a_card_and_is_never_sent(monkeypatch):
    from app import agent
    r = tools.run("draft_message", {"text": "Olá Ana, confirmo amanhã às 10h.", "channel": "whatsapp", "to": "Ana",
                                    "phone": "+351 912 345 678"})
    assert r["draft"]["phone"] == "351912345678" and r["draft"]["channel"] == "whatsapp"
    assert tools.run("draft_message", {"text": "  "})["error"]
    steps = iter([
        {"text": "", "tool_calls": [{"id": "1", "name": "draft_message",
                                      "input": {"text": "Olá Ana, confirmo amanhã às 10h.", "channel": "whatsapp", "to": "Ana"}}]},
        {"text": "Aqui está a mensagem para a Ana.", "tool_calls": []},
    ])
    monkeypatch.setattr(agent.llm, "chat", lambda s, m, t, **kw: next(steps))
    out = agent.handle("escreve uma mensagem de whatsapp para a Ana a confirmar amanhã às 10")
    assert out["message_drafts"][0]["text"].startswith("Olá Ana") and not out["pending_actions"]


def test_tips_email_is_designed_and_follows_the_country(monkeypatch):
    from app import newsletter, accounts
    s, page = newsletter.preview(0, "pt-pt")
    assert s.startswith("Notas do Mike #1: porque criei") and "Porque criei o Fidus" in page
    assert "DICA DE HOJE" not in page and "Dica de hoje" in page and "Ao fim do dia" in page  # dica em destaque
    assert "Fundador do Fidus" in page and "Não quero receber mais" in page and "'Segoe" not in page
    s_en, page_en = newsletter.preview(0, "en")
    assert "why I built Fidus" in s_en and "Founder, Fidus" in page_en
    # idioma de hoje: perfil em pt-PT → texto de Portugal; sem idioma, o país do plano decide
    store.save_profile(language="pt-PT", country="PT")
    assert newsletter.current_lang({"user_id": store.OWNER_ID, "lang": "en"}) == "pt-pt"
    import json as _j
    from app import config as _c
    monkeypatch.setattr(_c, "OWNER_LANGUAGE", "")
    raw = _j.loads(store.kv_get("profile") or "{}")
    raw.pop("language", None)
    store.kv_set("profile", _j.dumps(raw))
    store.save_profile(countries=["GB"], country="GB")
    assert newsletter.current_lang({"user_id": store.OWNER_ID, "lang": "pt"}) == "en"


def test_admin_sends_designed_tip_preview(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    sent = []
    monkeypatch.setattr(mailer, "enabled", lambda: True)
    monkeypatch.setattr(mailer, "send_raw", lambda to, subject, body, **k: sent.append((to, subject, k.get("page_html"))) or True)
    c = TestClient(main.app)
    code = c.post("/v1/admin/panel_code", headers={"Authorization": "Bearer t"}).json()["code"]
    b = TestClient(main.app, base_url="https://testserver")
    b.post("/admin/api/login", json={"code": code})
    r = b.post("/admin/api/newsletter/preview", json={"step": 1, "lang": "pt-pt"}, headers={"X-Fidus-Admin": "1"}).json()
    assert r["ok"] and sent[-1][1].startswith("[teste] Notas do Mike #2") and "<table" in sent[-1][2]
