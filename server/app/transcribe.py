"""Transcrição 100% local com faster-whisper (sem enviar áudio a terceiros).

O áudio é convertido pelo FFmpeg (16 kHz, mono) e entregue ao Whisper como números,
sem depender da biblioteca PyAV, cujas versões novas quebram o faster-whisper.
"""
import shutil
import subprocess
from functools import lru_cache

import numpy as np

from . import config

SAMPLE_RATE = 16000


@lru_cache(maxsize=1)
def _model():
    from faster_whisper import WhisperModel

    return WhisperModel(config.WHISPER_MODEL, device="auto", compute_type="int8")


def _load_audio(path: str) -> np.ndarray:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg não encontrado. Feche e abra o PowerShell e ligue o servidor de novo.")
    out = subprocess.run(
        [ffmpeg, "-nostdin", "-loglevel", "error", "-i", path,
         "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(out, np.int16).astype(np.float32) / 32768.0


COMMAND_PROMPT = ("Pedidos ao assessor Fidus em português, às vezes em inglês: "
                  "marca almoço com o contador sexta à uma da tarde; "
                  "responde o e-mail do Carlos; quanto gastei de gasolina este mês.")
PROMPTS = {
    "pt": COMMAND_PROMPT,
    "en": "Requests to the Fidus assistant in English: book lunch with the accountant Friday at 1pm; "
          "reply to Carlos's email; how much did I spend on fuel this month.",
    "es": "Pedidos al asistente Fidus en español: agenda almuerzo con el contador el viernes a la una; "
          "responde el correo de Carlos; cuánto gasté en gasolina este mes.",
}


def prompt_for(lang: str | None) -> str | None:
    """Dica de contexto no idioma do usuário. Outros idiomas: sem dica (o Whisper detecta sozinho)."""
    return PROMPTS.get((lang or "pt").split("-")[0].lower())


MEETING_PROMPT = "Reunião de trabalho em português ou inglês, com nomes, valores, prazos e próximos passos."


def transcribe(path: str, initial_prompt: str | None = COMMAND_PROMPT, beam_size: int = 5) -> str:
    audio = _load_audio(path)
    if audio.size == 0:
        return ""
    # dica de contexto: melhora nomes, horários e palavras comuns
    segments, _info = _model().transcribe(audio, vad_filter=True, beam_size=beam_size, initial_prompt=initial_prompt)
    return " ".join(s.text.strip() for s in segments).strip()


def _openai_ok() -> bool:
    return config.TRANSCRIBE != "local" and bool((getattr(config, "OPENAI_API_KEY", "") or "").strip())


def transcribe_fast(path: str, lang: str | None = None, initial_prompt: str | None = COMMAND_PROMPT) -> str:
    """Pedido falado (segundos de áudio): OpenAI quando configurada (~1 s, entende melhor nomes e sotaque);
    se falhar ou não houver chave, o Whisper local de sempre."""
    import logging
    import os
    if _openai_ok() and os.path.getsize(path) < 24 * 1024 * 1024:
        try:
            import requests

            from . import store
            code = (lang or "").split("-")[0].lower()
            data = {"model": config.TRANSCRIBE_MODEL, "response_format": "json"}
            if code in ("pt", "en", "es", "fr", "de", "it", "ms"):
                data["language"] = code
            if initial_prompt:
                data["prompt"] = initial_prompt
            with open(path, "rb") as f:
                r = requests.post("https://api.openai.com/v1/audio/transcriptions", data=data, timeout=20,
                                  files={"file": (os.path.basename(path), f)},
                                  headers={"Authorization": f"Bearer {config.OPENAI_API_KEY.strip()}"})
            r.raise_for_status()
            j = r.json()
            u = j.get("usage") or {}
            try:
                store.add_usage({"model": config.TRANSCRIBE_MODEL, "calls": 1, "input": int(u.get("input_tokens") or 0),
                                 "output": int(u.get("output_tokens") or 0)})
            except Exception:  # noqa: BLE001
                pass
            return (j.get("text") or "").strip()
        except Exception as e:  # noqa: BLE001
            logging.getLogger("fidus.transcribe").warning("transcrição OpenAI falhou (%s); usando a local", str(e)[:160])
    return transcribe(path, initial_prompt, beam_size=1)


def duration_seconds(path: str) -> float:
    return _load_audio(path).size / SAMPLE_RATE
