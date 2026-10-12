"""v0.14: conexões dos clientes (Google, Microsoft) criptografadas no banco; chave fora dos dados e dos backups."""
import os
import tempfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

from app import crypto, store  # noqa: E402


def _raw(k):
    with store._conn() as c:
        r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return r["v"] if r else None


def test_secrets_are_encrypted_at_rest_and_readable():
    store.kv_set("google_creds", '{"refresh_token": "segredo-123"}')
    raw = _raw("google_creds")
    assert raw.startswith("enc1:") and "segredo-123" not in raw
    assert store.kv_get("google_creds") == '{"refresh_token": "segredo-123"}'
    store.kv_set("ms_tokens", '{"access_token": "abc"}')
    assert "abc" not in _raw("ms_tokens") and store.kv_get("ms_tokens") == '{"access_token": "abc"}'
    store.kv_set("plan", "global")  # dado comum continua legível
    assert _raw("plan") == "global"


def test_old_plaintext_is_migrated_on_read():
    with store._conn() as c:
        c.execute("INSERT INTO kv(k,v) VALUES('google_creds','{\"old\": 1}') ON CONFLICT(k) DO UPDATE SET v=excluded.v")
    assert store.kv_get("google_creds") == '{"old": 1}'
    assert _raw("google_creds").startswith("enc1:")
    assert store.kv_get("google_creds") == '{"old": 1}'


def test_key_file_is_private_and_outside_data(tmp_path, monkeypatch):
    path = tmp_path / "keys" / "data.key"
    monkeypatch.setenv("FIDUS_KEY_FILE", str(path))
    monkeypatch.delenv("FIDUS_DATA_KEY", raising=False)
    monkeypatch.setattr(crypto, "_fernet", None)
    token = crypto.encrypt("x")
    assert path.exists() and (os.stat(path).st_mode & 0o777) == 0o600
    monkeypatch.setattr(crypto, "_fernet", None)  # reinício do servidor: mesma chave do arquivo
    assert crypto.decrypt(token) == "x"
    monkeypatch.setattr(crypto, "_fernet", None)
