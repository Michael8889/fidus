"""Ambiente isolado para os testes: bancos e pastas temporários."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="fidus-test-")
os.environ.setdefault("FIDUS_ACCOUNTS_DB", os.path.join(_tmp, "accounts.db"))
os.environ.setdefault("FIDUS_DATA_DIR", _tmp)
os.environ.setdefault("FIDUS_RECEIPTS_DIR", os.path.join(_tmp, "receipts"))
os.environ.setdefault("FIDUS_DB_PATH", os.path.join(_tmp, "fidus.db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")
