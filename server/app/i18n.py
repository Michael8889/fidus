"""Idiomas: tradução dos textos do app e de textos fixos do servidor.

O app é escrito em português. Para outro idioma, o app manda a lista de textos e o servidor devolve a tradução,
feita pela IA uma única vez e guardada em arquivo (vale para todos os clientes daquele idioma). Só idiomas da lista
abaixo, com teto de textos por idioma, para ninguém usar isso para gastar IA à toa.
"""
import json
import os
import re
import threading

from . import config, llm, store

LANGS = {
    "pt": "português", "en": "English", "es": "español", "fr": "français", "de": "Deutsch", "it": "italiano",
    "nl": "Nederlands", "pl": "polski", "ro": "română", "sv": "svenska", "da": "dansk", "nb": "norsk bokmål",
    "fi": "suomi", "cs": "čeština", "sk": "slovenčina", "hu": "magyar", "el": "ελληνικά", "bg": "български",
    "hr": "hrvatski", "sl": "slovenščina", "lt": "lietuvių", "lv": "latviešu", "et": "eesti", "uk": "українська",
    "ru": "русский", "tr": "Türkçe", "ar": "العربية", "he": "עברית", "hi": "हिन्दी", "bn": "বাংলা", "ur": "اردو",
    "ms": "Bahasa Melayu", "id": "Bahasa Indonesia", "tl": "Filipino", "vi": "Tiếng Việt", "th": "ไทย",
    "zh": "中文", "ja": "日本語", "ko": "한국어", "sw": "Kiswahili", "af": "Afrikaans", "ca": "català",
    "ga": "Gaeilge", "is": "íslenska", "mt": "Malti", "sq": "shqip", "sr": "српски", "mk": "македонски",
}
MAX_PER_LANG = 2500
# Só os textos de verdade do app são traduzidos (lista gerada por app/i18n-keys.py). Texto que não está na lista
# é ignorado: ninguém consegue gravar uma "tradução" falsa no cache nem gastar IA com textos aleatórios.
_KEYS_FILE = os.path.join(os.path.dirname(__file__), "i18n_keys.json")


def _allowed() -> set:
    try:
        with open(_KEYS_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()
MAX_PER_REQUEST = 500
_locks: dict = {}
_guard = threading.Lock()


def norm(lang: str | None) -> str:
    code = (lang or "").strip().lower().replace("_", "-").split("-")[0]
    if code == "no":
        code = "nb"
    return code if code in LANGS else ""


def name(lang: str) -> str:
    return LANGS.get(norm(lang) or "pt", "português")


def _path(lang: str) -> str:
    d = os.path.join(config.DATA_DIR, "i18n")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{lang}.json")


def _load(lang: str) -> dict:
    try:
        with open(_path(lang), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _lock(lang: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(lang, threading.Lock())


def _ask(lang: str, strings: list[str]) -> dict:
    system = (f"You translate the user interface of Fidus, a personal assistant app, from Brazilian Portuguese to "
              f"{LANGS[lang]}. Keep it short and natural for a phone app. Keep emojis, numbers, punctuation, line "
              "breaks, the name Fidus and placeholders like {0} or {name} exactly. Reply ONLY with a JSON object "
              "mapping each original string to its translation.")
    out = llm.chat(system, [{"role": "user", "content": json.dumps(strings, ensure_ascii=False)}], [],
                   web_search=False)
    text = out.get("text") or ""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and k in strings and v.strip()}


def translate(lang: str, strings: list[str]) -> dict:
    """{texto_em_português: tradução}. Português ou idioma desconhecido → {} (o app usa o original)."""
    lang = norm(lang)
    if not lang or lang == "pt":
        return {}
    ok = _allowed()
    want = list(dict.fromkeys(s for s in strings[:MAX_PER_REQUEST] if isinstance(s, str) and s in ok))
    cache = _load(lang)
    missing = [s for s in want if s not in cache]
    if missing and len(cache) < MAX_PER_LANG:
        with _lock(lang):
            cache = _load(lang)
            missing = [s for s in want if s not in cache][: MAX_PER_LANG - len(cache)]
            from concurrent.futures import ThreadPoolExecutor
            chunks = [missing[i:i + 80] for i in range(0, len(missing), 80)]

            def safe(chunk):
                try:
                    return _ask(lang, chunk)
                except Exception:  # noqa: BLE001 - sem tradução, o app mostra o português
                    return {}
            with ThreadPoolExecutor(max_workers=4) as pool:
                for part in pool.map(safe, chunks):
                    cache.update(part)
            tmp = _path(lang) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
            os.replace(tmp, _path(lang))
    return {s: cache[s] for s in want if s in cache}


def localize(text: str) -> str:
    """Texto fixo gerado em português (bom dia, semana) no idioma do usuário."""
    lang = store.user_lang()
    if not text or lang == "pt" or lang not in LANGS:
        return text
    try:
        out = llm.chat(f"Translate the message to {LANGS[lang]}. Keep the layout, emojis, numbers, names and line "
                       "breaks. Reply only with the translated message.", [{"role": "user", "content": text}], [],
                       web_search=False)
        return (out.get("text") or "").strip() or text
    except Exception:  # noqa: BLE001
        return text


# Frases curtas do próprio servidor
_MSG = {
    "no_audio": {"pt": "Não entendi o áudio. Pode repetir?", "en": "I couldn't understand the audio. Could you say it again?",
                 "es": "No entendí el audio. ¿Puedes repetirlo?", "fr": "Je n'ai pas compris l'audio. Tu peux répéter ?",
                 "de": "Ich habe die Aufnahme nicht verstanden. Kannst du das wiederholen?",
                 "it": "Non ho capito l'audio. Puoi ripetere?"},
}


def msg(key: str) -> str:
    lang = store.user_lang()
    d = _MSG[key]
    return d.get(lang) or d["en" if lang != "pt" else "pt"]
