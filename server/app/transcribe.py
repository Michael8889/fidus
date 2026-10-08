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


def duration_seconds(path: str) -> float:
    return _load_audio(path).size / SAMPLE_RATE
