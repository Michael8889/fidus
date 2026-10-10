"""v0.10: boas-vindas em conversa, dicas por e-mail (leads), parceiros, pt-PT, privacidade/termos, exportar por e-mail."""
import json
import os
import re
import tempfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402

client = TestClient(main.app)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_home_page_languages():
    r = client.get("/", headers={"accept-language": "pt-BR,pt;q=0.9"})
    assert r.status_code == 200 and "Fale. O Fidus resolve." in r.text and "17510962" in r.text
    assert "/privacy?lang=pt" in r.text
    r = client.get("/", headers={"accept-language": "en-GB"})
    assert "Fidus handles it" in r.text and "/terms?lang=en" in r.text


def test_install_script_is_valid_bash_and_never_touches_other_sites():
    import subprocess
    path = os.path.join(ROOT, "server", "deploy", "install.sh")
    assert subprocess.run(["bash", "-n", path]).returncode == 0
    src = open(path).read()
    assert "managed-by-fidus" in src and "nginx -t" in src and "--expand" in src
    assert "rm -rf" not in src


def test_app_points_to_new_domain_and_migrates_old():
    src = open(os.path.join(ROOT, "app", "App.tsx"), encoding="utf-8").read()
    assert 'DEFAULT_SERVER = "https://app.heyfidus.com"' in src
    assert "LEGACY_SERVERS" in src and "fidus.148-230-123-44.sslip.io" in src
    assert 'SUPPORT_EMAIL = "suporte@heyfidus.com"' in src
    assert 'screen === "plan"' in src
