"""v0.10: boas-vindas em conversa, dicas por e-mail (leads), parceiros, pt-PT, privacidade/termos, exportar por e-mail."""
import json
import os
import re
import tempfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

from fastapi.testclient import TestClient  # noqa: E402

import pytest  # noqa: E402

from app import actions, payments, plans, store  # noqa: E402


def _clean():
    with store._conn() as c:
        c.execute("DELETE FROM payment_contacts")
        c.execute("UPDATE pending_actions SET status='cancelled' WHERE kind='payment' AND status='pending'")


def test_crc_matches_central_bank_example():
    p = ("00020126580014br.gov.bcb.pix0136123e4567-e12b-12d1-a456-4266554400005204000053039865802BR"
         "5913Fulano de Tal6008BRASILIA62070503***6304")
    assert payments._crc16(p) == "1D3D"


def test_brcode_has_key_amount_and_valid_crc():
    code = payments.brcode("+5511987654321", 350, "João da Silva", "Conserto do secador")
    assert "br.gov.bcb.pix" in code and "+5511987654321" in code and "5406350.00" in code
    assert "JOAO DA SILVA" in code and code[-4:] == payments._crc16(code[:-4])


def test_key_normalization():
    assert payments.normalize_pix_key("(11) 98765-4321", "celular") == "+5511987654321"
    assert payments.normalize_pix_key("123.456.789-09", "cpf") == "12345678909"
    with pytest.raises(ValueError):
        payments.normalize_pix_key("123", "cpf")


def test_first_time_asks_key_then_remembers_and_paid_logs_expense():
    _clean()
    r = payments.prepare("João do secador", 350, description="conserto")
    assert r["needs_key"] and r["pending_action_id"]
    a = payments.set_key(r["pending_action_id"], pix_key="11987654321", pix_key_type="celular")
    assert a["payload"]["pix_code"].startswith("000201") and not a["payload"]["needs_key"]
    assert a["payload"]["currency"] == "BRL"
    # segunda vez: já sabe a chave
    r2 = payments.prepare("joão do secador", 80)
    assert not r2.get("needs_key") and r2["method"] == "pix"
    done = payments.mark_paid(r2["pending_action_id"])
    assert done["status"] == "paid" and done["expense_id"]
    with pytest.raises(ValueError):
        payments.mark_paid(r2["pending_action_id"])  # não lança duas vezes


def test_ambiguous_contact_asks_which():
    _clean()
    payments.save_contact("Pedro caseiro", pix_key="pedro@exemplo.com", pix_key_type="email")
    payments.save_contact("Pedro Costa", iban="PT50000201231234567890154")
    r = payments.prepare("Pedro", 200)
    assert r["ambiguous"] and len(r["options"]) == 2


def test_uk_contact_and_pix_only_in_reais():
    _clean()
    payments.save_contact("Fornecedor", sort_code="04-00-04", account_number="12345678")
    r = payments.prepare("Fornecedor", 120)
    a = store.get_pending(r["pending_action_id"])
    assert a["payload"]["method"] == "uk" and a["payload"]["currency"] == "GBP"
    payments.save_contact("Ana", pix_key="ana@exemplo.com", pix_key_type="email")
    with pytest.raises(ValueError):
        payments.prepare("Ana", 10, currency="EUR")


def test_payment_never_sent_by_envia_command_and_is_premium():
    _clean()
    r = payments.prepare("Alguém Novo", 10)
    assert all(a["kind"] != "payment" for a in actions.waiting(None))
    assert r["pending_action_id"] in [a["id"] for a in payments.waiting()]
    assert not plans.allows("prepare_payment", "negocio") and plans.allows("prepare_payment", "premium")
