"""Entrar com a Apple (iPhone): token conferido com a chave da Apple, nonce, conta presa ao ID da Apple."""
import base64
import hashlib
import json
import os
import tempfile
import time

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402,F401
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import accounts, apple_auth, config, main, plans, store  # noqa: E402

client = TestClient(main.app)
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _jwk(key, kid="k1"):
    n = key.public_key().public_numbers()
    return {"kty": "RSA", "kid": kid, "alg": "RS256", "use": "sig",
            "n": _b64(n.n.to_bytes((n.n.bit_length() + 7) // 8, "big")), "e": _b64(n.e.to_bytes(3, "big"))}


def make_token(sub="apple-1", email="ana@privaterelay.appleid.com", nonce="raw-nonce", aud="com.fidus.app",
               iss="https://appleid.apple.com", exp_in=600, key=KEY, verified="true"):
    header = {"alg": "RS256", "kid": "k1"}
    claims = {"iss": iss, "aud": aud, "exp": int(time.time()) + exp_in, "iat": int(time.time()), "sub": sub,
              "nonce": hashlib.sha256(nonce.encode()).hexdigest(), "email_verified": verified}
    if email:
        claims["email"] = email
    signed = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"
    sig = key.sign(signed.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signed}.{_b64(sig)}"


def setup_keys(monkeypatch):
    monkeypatch.setattr(apple_auth, "_fetch_keys", lambda: {"k1": _jwk(KEY)})
    monkeypatch.setattr(apple_auth, "_keys_cache", {"at": 0.0, "keys": {}})
    main._book_hits.clear()


def test_token_checks(monkeypatch):
    setup_keys(monkeypatch)
    assert apple_auth.verify(make_token(), "raw-nonce")["sub"] == "apple-1"
    assert apple_auth.verify(make_token(), "outro-nonce") is None          # token de outro pedido
    assert apple_auth.verify(make_token(), None) is None
    assert apple_auth.verify(make_token(aud="com.outro.app"), "raw-nonce") is None
    assert apple_auth.verify(make_token(iss="https://evil.example"), "raw-nonce") is None
    assert apple_auth.verify(make_token(exp_in=-600), "raw-nonce") is None  # vencido
    assert apple_auth.verify(make_token(key=OTHER), "raw-nonce") is None    # assinatura falsa
    assert apple_auth.verify("lixo", "raw-nonce") is None


def test_uninvited_apple_user_cannot_enter(monkeypatch):
    setup_keys(monkeypatch)
    monkeypatch.setattr(config, "SIGNUP_OPEN", False)
    r = client.post("/v1/auth/apple", json={"identity_token": make_token(sub="a-x", email="x@privaterelay.appleid.com"),
                                            "nonce": "raw-nonce"})
    assert r.status_code == 403
    assert accounts.by_email("x@privaterelay.appleid.com") is None


def test_invited_apple_login_and_same_account_later(monkeypatch):
    setup_keys(monkeypatch)
    monkeypatch.setattr(config, "SIGNUP_OPEN", False)
    accounts.invite("apple-bia@x.com", "negocio")
    r = client.post("/v1/auth/apple", json={"identity_token": make_token(sub="a-bia", email="apple-bia@x.com"),
                                            "nonce": "raw-nonce", "name": "Bia Lima", "device_id": "d1"})
    assert r.status_code == 200, r.text
    uid = r.json()["user"]["id"]
    assert accounts.get_user(uid)["apple_sub"] == "a-bia"
    with store.as_user(accounts.user_ctx(accounts.get_user(uid))):
        assert plans.current() == "negocio"
    # a Apple não manda e-mail de novo: entra pelo ID permanente
    r2 = client.post("/v1/auth/apple", json={"identity_token": make_token(sub="a-bia", email=None), "nonce": "raw-nonce"})
    assert r2.status_code == 200 and r2.json()["user"]["id"] == uid


def test_review_code_opens_signup_for_hidden_email(monkeypatch):
    setup_keys(monkeypatch)
    monkeypatch.setattr(config, "SIGNUP_OPEN", False)
    monkeypatch.setattr(config, "REVIEW_CODE", "GREVIEW26")
    r = client.post("/v1/auth/apple", json={"identity_token": make_token(sub="a-rev", email="rev@privaterelay.appleid.com"),
                                            "nonce": "raw-nonce", "ref": "greview26"})
    assert r.status_code == 200, r.text
    u = accounts.get_user(r.json()["user"]["id"])
    with store.as_user(accounts.user_ctx(u)):
        assert plans.current() == config.BETA_PLAN


def test_google_account_is_not_taken_over(monkeypatch):
    setup_keys(monkeypatch)
    accounts.invite("apple-gui@x.com", "essencial")
    u = accounts.find_or_create("apple-gui@x.com", "Gui", "google-sub-gui")
    r = client.post("/v1/auth/apple", json={"identity_token": make_token(sub="a-gui", email="apple-gui@x.com"), "nonce": "raw-nonce"})
    assert r.status_code == 403
    assert accounts.get_user(u["id"]).get("apple_sub") is None


def test_unverified_email_is_refused(monkeypatch):
    setup_keys(monkeypatch)
    monkeypatch.setattr(config, "SIGNUP_OPEN", True)
    r = client.post("/v1/auth/apple", json={"identity_token": make_token(sub="a-nv", email="apple-nv@x.com", verified="false"),
                                            "nonce": "raw-nonce"})
    assert r.status_code == 403


def test_bad_token_is_rejected(monkeypatch):
    setup_keys(monkeypatch)
    r = client.post("/v1/auth/apple", json={"identity_token": make_token(key=OTHER), "nonce": "raw-nonce"})
    assert r.status_code == 400


def test_deleted_account_forgets_apple_id(monkeypatch):
    setup_keys(monkeypatch)
    accounts.invite("apple-del@x.com", "essencial")
    r = client.post("/v1/auth/apple", json={"identity_token": make_token(sub="a-del", email="apple-del@x.com"), "nonce": "raw-nonce"})
    uid = r.json()["user"]["id"]
    accounts.forget_user(uid, "apple-del@x.com")
    assert accounts.get_user(uid)["apple_sub"] is None
