"""Entrar com a Apple (exigido pela App Store quando o app tem "Entrar com o Google").

O app (iPhone) recebe da Apple um identity token (JWT assinado pela Apple) e manda para o servidor junto com o
nonce que ele mesmo criou. Aqui conferimos a assinatura com as chaves públicas da Apple, o emissor, o
destinatário (o bundle id do app), a validade e o nonce. Não precisa de chave secreta nem de .env.
"""
import base64
import hashlib
import json
import time

from . import config

ISSUER = "https://appleid.apple.com"
KEYS_URL = "https://appleid.apple.com/auth/keys"
_keys_cache: dict = {"at": 0.0, "keys": {}}


def _b64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _fetch_keys() -> dict:
    import requests
    r = requests.get(KEYS_URL, timeout=10)
    r.raise_for_status()
    return {k["kid"]: k for k in r.json().get("keys", []) if k.get("kty") == "RSA"}


def _key(kid: str) -> dict | None:
    """Chaves da Apple em cache por 1 hora; chave nova (a Apple troca às vezes) força buscar de novo."""
    if kid not in _keys_cache["keys"] or time.time() - _keys_cache["at"] > 3600:
        try:
            _keys_cache["keys"], _keys_cache["at"] = _fetch_keys(), time.time()
        except Exception:  # noqa: BLE001 — sem rede: usa o que já tinha
            pass
    return _keys_cache["keys"].get(kid)


def _verify_rs256(jwk: dict, signed: bytes, sig: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    pub = rsa.RSAPublicNumbers(int.from_bytes(_b64(jwk["e"]), "big"), int.from_bytes(_b64(jwk["n"]), "big")).public_key()
    try:
        pub.verify(sig, signed, padding.PKCS1v15(), hashes.SHA256())
        return True
    except InvalidSignature:
        return False


def verify(identity_token: str, raw_nonce: str | None) -> dict | None:
    """Claims do token se tudo confere; None se não. O nonce do token é o SHA-256 (hex) do nonce cru do app."""
    try:
        h64, p64, s64 = (identity_token or "").split(".")
        header, claims = json.loads(_b64(h64)), json.loads(_b64(p64))
    except (ValueError, TypeError):
        return None
    if header.get("alg") != "RS256":
        return None
    jwk = _key(header.get("kid", ""))
    if not jwk or not _verify_rs256(jwk, f"{h64}.{p64}".encode(), _b64(s64)):
        return None
    now = time.time()
    if claims.get("iss") != ISSUER or claims.get("aud") not in config.APPLE_AUDIENCES:
        return None
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] < now - 60:
        return None
    if not raw_nonce or claims.get("nonce") != hashlib.sha256(raw_nonce.encode()).hexdigest():
        return None  # o token só vale para o pedido que o próprio app começou
    if not claims.get("sub"):
        return None
    return claims


def is_true(v) -> bool:
    """A Apple manda alguns campos como texto ("true") e outros como booleano."""
    return v is True or str(v).lower() == "true"
