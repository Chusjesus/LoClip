"""Transcripción local con faster-whisper (español, inglés y 90+ idiomas)."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from .config import models_dir


@dataclass
class Segment:
    start: float
    end: float
    text: str
    lang: str = ""
    speaker: str = ""


class SpeechModel:
    def __init__(self, size: str = "small", device: str = "cpu", compute_type: str = "int8"):
        from faster_whisper import WhisperModel

        self.size, self.device, self.compute_type = size, device, compute_type
        self.lock = threading.Lock()
        try:
            self.model = WhisperModel(size, device=device, compute_type=compute_type, download_root=str(models_dir()))
        except Exception:
            # Si CUDA falla (driver viejo, sin cuDNN…), caemos a CPU en vez de morir.
            self.device, self.compute_type = "cpu", "int8"
            self.model = WhisperModel(size, device="cpu", compute_type="int8", download_root=str(models_dir()))

    def transcribe(self, wav: Path, language: str | None = None) -> list[Segment]:
        with self.lock:
            segs, info = self.model.transcribe(
                str(wav), language=language, vad_filter=True, beam_size=1,
                vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=False,
            )
            out = []
            for s in segs:
                text = s.text.strip()
                if not text:
                    continue
                out.append(Segment(float(s.start), float(s.end), text, info.language or ""))
        return out
