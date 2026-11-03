"""Fidus legível para buscadores e assistentes de IA, sem JavaScript."""
import json
import os
import re
import tempfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

from fastapi.testclient import TestClient  # noqa: E402

from app import main, plans  # noqa: E402

client = TestClient(main.app)


def test_robots_allows_ai_bots_and_points_to_sitemap():
    r = client.get("/robots.txt").text
    for bot in ("GPTBot", "OAI-SearchBot", "ClaudeBot", "Claude-SearchBot", "PerplexityBot"):
        assert f"User-agent: {bot}\nAllow: /" in r
    assert "Sitemap: https://heyfidus.com/sitemap.xml" in r and "Disallow: /v1/" in r


def test_sitemap_and_llms():
    sm = client.get("/sitemap.xml")
    assert sm.status_code == 200 and "https://heyfidus.com/about" in sm.text
    t = client.get("/llms.txt").text
    assert t.startswith("# Fidus") and "Fidus Labs Limited" in t and "17510962" in t
    assert f"{plans.PRICES['GBP']['essencial']:.2f}" in t  # preço igual ao do app


def test_about_pages_are_plain_text():
    for path, word in (("/sobre", "assistente pessoal por voz"), ("/about", "voice-first personal assistant")):
        r = client.get(path)
        assert r.status_code == 200 and word in r.text and "{{" not in r.text
        for blob in re.findall(r'<script type="application/ld\+json">(.*?)</script>', r.text, flags=re.S):
            json.loads(blob)  # JSON-LD válido


def test_home_has_noscript_and_structured_data():
    r = client.get("/")
    assert r.status_code == 200
    if "<noscript>" in r.text:  # só quando o site gerado existe
        assert "Fidus: assistente pessoal por voz" in r.text and 'application/ld+json' in r.text
