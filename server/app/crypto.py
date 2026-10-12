"""Criptografia dos segredos dos clientes guardados no servidor (conexões com Google e Microsoft).

As chaves de acesso que o Google e a Microsoft entregam ficam no banco de cada cliente CRIPTOGRAFADAS (Fernet:
AES-128 + HMAC). A chave mestra NÃO fica nos bancos nem nos backups:
- FIDUS_DATA_KEY no ambiente, se existir; senão
- o arquivo FIDUS_KEY_FILE (no servidor: /keys/data.key, pasta separada de /data e fora do backup), criado sozinho
  na primeira vez com permissão só do dono.
Perder a chave = os clientes precisam reconectar Google/Outlook (nada mais se perde).
"""
import base64
import logging
import os
import threading

from . import config

log = logging.getLogger("fidus.crypto")
PREFIX = "enc1:"
_lock = threading.Lock()
_fernet = None


def _key_file() -> str:
    path = (os.environ.get("FIDUS_KEY_FILE") or "").strip()
    if path:
        return path
    if os.path.isdir("/keys"):
        return "/keys/data.key"
    return os.path.join(os.path.dirname(os.path.abspath(config.DATA_DIR)), "keys", "data.key")


def _load():
    global _fernet
    if _fernet is not None:
        return _fernet
    from cryptography.fernet import Fernet
    with _lock:
        if _fernet is not None:
            return _fernet
        raw = (os.environ.get("FIDUS_DATA_KEY") or "").strip()
        if not raw:
            path = _key_file()
            if os.path.isfile(path):
                raw = open(path, encoding="ascii").read().strip()
            else:
                raw = Fernet.generate_key().decode()
                os.makedirs(os.path.dirname(path), exist_ok=True)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(raw)
                log.warning("chave de criptografia criada em %s (guarde uma cópia fora do servidor)", path)
        if len(raw) != 44:  # texto livre em FIDUS_DATA_KEY: vira uma chave válida (SHA-256)
            import hashlib
            raw = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest()).decode()
        _fernet = Fernet(raw.encode())
        return _fernet


def encrypt(text: str) -> str:
    return PREFIX + _load().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(value: str) -> str:
    """Valor criptografado -> texto. Valor antigo (sem o prefixo) volta como está (migração automática)."""
    if not value or not value.startswith(PREFIX):
        return value
    return _load().decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)
