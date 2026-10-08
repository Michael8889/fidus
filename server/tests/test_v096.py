"""v0.9.6: voz natural do Google (com custo medido) e frases fixas."""
import base64
import os
import tempfile

os.environ.setdefault("FIDUS_DB_PATH", tempfile.mktemp(suffix=".db"))
os.environ.setdefault("FIDUS_APP_TOKEN", "t")

from fastapi.testclient import TestClient  # noqa: E402

from app import agent, config, main, store, tts  # noqa: E402

client = TestClient(main.app)
H = {"Authorization": "Bearer t"}
MP3 = base64.b64encode(b"ID3fake").decode()


class Resp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def fake_google(monkeypatch, calls):
    voices = {"voices": [
        {"name": "pt-BR-Standard-A", "ssmlGender": "FEMALE", "languageCodes": ["pt-BR"]},
        {"name": "pt-BR-Wavenet-B", "ssmlGender": "MALE", "languageCodes": ["pt-BR"]},
        {"name": "pt-BR-Wavenet-C", "ssmlGender": "FEMALE", "languageCodes": ["pt-BR"]},
        {"name": "en-GB-Wavenet-A", "ssmlGender": "FEMALE", "languageCodes": ["en-GB"]},
    ]}
    monkeypatch.setattr(tts.requests, "get", lambda url, params=None, timeout=0: Resp(voices))

    def post(url, params=None, json=None, timeout=0):
        calls.append(json)
        return Resp({"audioContent": MP3})
    monkeypatch.setattr(tts.requests, "post", post)
    monkeypatch.setattr(config, "GOOGLE_TTS_KEY", "k")
    monkeypatch.setattr(config, "TTS_TIER", "wavenet")
    tts._voices.clear()


def test_no_key_means_phone_voice(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_TTS_KEY", "")
    assert tts.synthesize("olá") is None
    assert client.post("/v1/tts", json={"phrase": "Pode falar."}, headers=H).json() == {"audio": None}
    assert client.get("/v1/me", headers=H).json()["natural_voice"] is False


def test_voice_reply_comes_with_natural_audio_and_cost(monkeypatch):
    calls = []
    fake_google(monkeypatch, calls)
    monkeypatch.setattr(agent.llm, "chat", lambda s, m, t, **kw: {"text": "Tudo certo por aqui.", "tool_calls": []})
    r = client.post("/v1/message", json={"text": "como está?", "mode": "voice"}, headers=H).json()
    assert r["speech_audio"] == MP3
    assert calls[-1]["voice"]["name"] == "pt-BR-Wavenet-C"  # feminina, WaveNet
    with store._conn() as c:
        row = c.execute("SELECT * FROM usage WHERE model='tts-google-wavenet'").fetchone()
    assert row and row["input"] >= len("Tudo certo por aqui.") and row["cost"] > 0
    # texto sem modo voz: sem áudio (não gasta)
    r2 = client.post("/v1/message", json={"text": "como está?"}, headers=H).json()
    assert not r2.get("speech_audio")


def test_male_voice_and_fixed_phrases_cached(monkeypatch):
    calls = []
    fake_google(monkeypatch, calls)
    assert client.post("/v1/profile", json={"voice_gender": "male"}, headers=H).status_code == 200
    assert tts.synthesize("oi")
    assert calls[-1]["voice"]["name"] == "pt-BR-Wavenet-B"
    n = len(calls)
    a1 = client.post("/v1/tts", json={"phrase": "Um instante."}, headers=H).json()["audio"]
    a2 = client.post("/v1/tts", json={"phrase": "Um instante."}, headers=H).json()["audio"]
    assert a1 == a2 == MP3 and len(calls) == n + 1  # a segunda vem do arquivo guardado
    assert client.post("/v1/tts", json={"phrase": "qualquer texto"}, headers=H).status_code == 400
    assert client.post("/v1/profile", json={"voice_gender": "robo"}, headers=H).status_code == 400
    client.post("/v1/profile", json={"voice_gender": "female"}, headers=H)


def test_app_reports_what_it_has():
    from app import metrics
    client.get("/v1/me", headers={**H, "X-Fidus-Client": "sr=1,speech=1,player=1,js=0.9.7,ota=abc<script>"})
    metrics.flush()
    caps = metrics.client_caps()[store.OWNER_ID]["caps"]
    assert caps.startswith("sr=1,speech=1") and "<" not in caps
