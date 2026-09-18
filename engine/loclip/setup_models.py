"""Descarga los modelos recomendados para esta máquina (se ejecuta una vez desde el instalador).

    python -m loclip.setup_models
"""
from __future__ import annotations

import sys

from . import hardware
from .config import load_settings


def main() -> None:
    info = hardware.detect()
    rec = hardware.recommend(info)
    s = load_settings()
    print("Equipo:", info.os, info.arch, "| device:", info.device, info.gpu_name, f"{info.vram_gb} GB" if info.vram_gb else "")
    for n in rec["notes"]:
        print(" ·", n)
    vt = s.get("visual_model", "auto")
    vt = rec["visual_tier"] if vt == "auto" else vt
    print(f"Descargando modelo visual ({vt})…")
    from .embeddings import VisualModel
    VisualModel(vt, "cpu")  # solo descarga/valida; se carga en CPU para no exigir GPU aquí
    if s.get("transcribe", True):
        sm = s.get("speech_model", "auto")
        sm = rec["speech_model"] if sm == "auto" else sm
        print(f"Descargando modelo de voz ({sm})…")
        from faster_whisper import WhisperModel
        from .config import models_dir
        WhisperModel(sm, device="cpu", compute_type="int8", download_root=str(models_dir()))
    print("Listo.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("ERROR:", e)
        sys.exit(1)
