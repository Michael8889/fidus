"""Voz natural do Fidus (texto -> áudio MP3) com as vozes do Google Cloud.

Por que Google: o plano grátis cobre 4 milhões de letras por mês nas vozes WaveNet (umas 16 mil respostas faladas)
e depois custa US$ 4 por milhão. Sem a chave FIDUS_GOOGLE_TTS_KEY no .env, nada muda: o app usa a voz do celular.

FIDUS_TTS_TIER escolhe a qualidade: wavenet (padrão, mais barata), neural2 (US$ 16/milhão) ou chirp3 (a mais
natural, US$ 30/milhão; 1 milhão grátis por mês). O nome exato da voz é escolhido pela lista do próprio Google.
"""
import base64
import hashlib
import logging
import os
import threading

import requests

from . import config, store

log = logging.getLogger("fidus.tts")
API = "https://texttospeech.googleapis.com/v1"
MAX_CHARS = 1200          # resposta falada longa demais: corta (o texto completo continua na tela)
TIER_TAG = {"wavenet": "Wavenet", "neural2": "Neural2", "chirp3": "Chirp3-HD", "standard": "Standard"}
# idioma do Fidus -> idioma da voz (sotaque)
LOCALE = {"pt": "pt-BR", "en": "en-GB", "es": "es-ES", "fr": "fr-FR", "de": "de-DE", "it": "it-IT", "nl": "nl-NL",
          "pl": "pl-PL", "sv": "sv-SE", "da": "da-DK", "nb": "nb-NO", "fi": "fi-FI", "cs": "cs-CZ", "ro": "ro-RO",
          "tr": "tr-TR", "el": "el-GR", "hu": "hu-HU", "uk": "uk-UA", "ru": "ru-RU", "ja": "ja-JP", "ko": "ko-KR",
          "zh": "cmn-CN", "hi": "hi-IN", "id": "id-ID", "ms": "ms-MY", "vi": "vi-VN", "th": "th-TH", "ar": "ar-XA"}
_voices: dict = {}
_lock = threading.Lock()


def enabled() -> bool:
    return bool((config.GOOGLE_TTS_KEY or "").strip())


def tier() -> str:
    t = (config.TTS_TIER or "wavenet").strip().lower()
    return t if t in TIER_TAG else "wavenet"


def _key() -> str:
    return (config.GOOGLE_TTS_KEY or "").strip()


def _pick_voice(locale: str, gender: str) -> str | None:
    """Melhor voz do Google para o idioma, a qualidade escolhida e o gênero (guarda a lista na memória)."""
    ck = (locale, tier(), gender)
    if ck in _voices:
        return _voices[ck]
    with _lock:
        if ck in _voices:
            return _voices[ck]
        try:
            r = requests.get(f"{API}/voices", params={"languageCode": locale, "key": _key()}, timeout=10)
            r.raise_for_status()
            voices = r.json().get("voices", [])
        except Exception as e:  # noqa: BLE001
            log.warning("lista de vozes falhou: %s", e)
            return None
        want = TIER_TAG[tier()]
        g = "FEMALE" if gender != "male" else "MALE"
        order = [want, "Neural2", "Wavenet", "Standard"]
        pick = None
        for tag in order:
            same = [v for v in voices if f"-{tag}-" in v.get("name", "") and locale in v.get("languageCodes", [])]
            pick = next((v for v in same if v.get("ssmlGender") == g), None) or (same[0] if same else None)
            if pick:
                break
        _voices[ck] = pick["name"] if pick else None
        return _voices[ck]


def _cache_dir() -> str:
    d = os.path.join(config.DATA_DIR, "tts-cache")
    os.makedirs(d, exist_ok=True)
    return d


def synthesize(text: str, lang: str | None = None, gender: str | None = None, cache: bool = False) -> str | None:
    """Devolve o MP3 em base64, ou None (sem chave, erro ou texto vazio: o app fala com a voz do celular)."""
    text = (text or "").strip()[:MAX_CHARS]
    if not text or not enabled():
        return None
    lang = (lang or store.user_lang() or "pt").split("-")[0]
    locale = LOCALE.get(lang, "en-GB")
    gender = gender or voice_gender()
    voice = _pick_voice(locale, gender)
    if not voice:
        return None
    path = None
    if cache:  # frases fixas ("Pode falar.", "Um instante."): uma vez só, para todo mundo
        h = hashlib.sha256(f"{voice}|{text}".encode()).hexdigest()[:32]
        path = os.path.join(_cache_dir(), h + ".mp3")
        if os.path.exists(path):
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode()
    cfg = {"audioEncoding": "MP3"}
    if "Chirp3" not in voice:  # as vozes Chirp 3 HD não aceitam mudar a velocidade
        cfg["speakingRate"] = 1.05
    try:
        r = requests.post(f"{API}/text:synthesize", params={"key": _key()}, timeout=20,
                          json={"input": {"text": text}, "voice": {"languageCode": locale, "name": voice},
                                "audioConfig": cfg})
        r.raise_for_status()
        audio = r.json().get("audioContent")
    except Exception as e:  # noqa: BLE001
        log.warning("voz do Google falhou: %s", e)
        return None
    if not audio:
        return None
    try:  # custo por cliente (entra no uso justo e no painel, como a IA)
        store.add_usage({"model": f"tts-google-{tier()}", "calls": 1, "input": len(text)})
    except Exception:  # noqa: BLE001
        pass
    if path:
        try:
            with open(path, "wb") as f:
                f.write(base64.b64decode(audio))
        except OSError:
            pass
    return audio


def voice_gender() -> str:
    g = (store.profile().get("voice_gender") or "female").lower()
    return "male" if g == "male" else "female"
