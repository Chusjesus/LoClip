"""Detección de hardware y elección automática de modelos.

LoClip elige los modelos según la máquina para que la misma herramienta
funcione en una PC con GPU NVIDIA, en una PC sin GPU y en una Mac.
El usuario siempre puede forzar un modelo desde Ajustes.

IMPORTANTE para equipos: el índice visual solo es compatible entre máquinas
que usen el MISMO modelo visual. Por eso el modelo visual por defecto es el
mismo en todas las máquinas ("base") y los modelos más grandes son opt-in.
"""
from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, asdict


@dataclass
class HardwareInfo:
    os: str
    arch: str
    python: str
    torch: str = ""
    device: str = "cpu"          # cuda | mps | cpu
    gpu_name: str = ""
    vram_gb: float = 0.0
    ram_gb: float = 0.0
    cpu_count: int = 0

    def to_dict(self):
        return asdict(self)


# Modelos visuales (open_clip). Todos con licencia Apache 2.0 y multilingües (SigLIP 2).
VISUAL_MODELS = {
    "base":    {"name": "ViT-B-16-SigLIP2-256",      "pretrained": "webli", "dim": 768,  "size_mb": 375,  "min_vram_gb": 0},
    "large":   {"name": "ViT-L-16-SigLIP2-256",      "pretrained": "webli", "dim": 1024, "size_mb": 1500, "min_vram_gb": 6},
    "quality": {"name": "ViT-SO400M-16-SigLIP2-256", "pretrained": "webli", "dim": 1152, "size_mb": 4500, "min_vram_gb": 10},
}
DEFAULT_VISUAL_TIER = "base"

# Modelos de voz (faster-whisper). Licencia MIT.
SPEECH_MODELS = ["tiny", "base", "small", "medium", "large-v3-turbo", "large-v3"]


def detect() -> HardwareInfo:
    info = HardwareInfo(os=platform.system(), arch=platform.machine(), python=sys.version.split()[0])
    try:
        import os
        info.cpu_count = os.cpu_count() or 0
    except Exception:
        pass
    try:
        import psutil  # opcional
        info.ram_gb = round(psutil.virtual_memory().total / 1e9, 1)
    except Exception:
        pass
    try:
        import torch
        info.torch = torch.__version__
        if torch.cuda.is_available():
            info.device = "cuda"
            props = torch.cuda.get_device_properties(0)
            info.gpu_name = props.name
            info.vram_gb = round(props.total_memory / 1e9, 1)
        elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            info.device = "mps"
            info.gpu_name = "Apple Silicon (MPS)"
    except Exception:
        pass
    return info


def recommend(info: HardwareInfo) -> dict:
    """Devuelve la recomendación de modelos para esta máquina."""
    # Visual: por compatibilidad de índices el default siempre es "base".
    visual_tier = DEFAULT_VISUAL_TIER
    if info.device == "cuda":
        visual_options = [t for t, m in VISUAL_MODELS.items() if info.vram_gb >= m["min_vram_gb"]]
    elif info.device == "mps":
        visual_options = ["base", "large"]
    else:
        visual_options = ["base"]

    # Voz: aquí sí conviene el mejor que aguante la máquina (la transcripción es texto; siempre compatible).
    if info.device == "cuda" and info.vram_gb >= 6:
        speech = "large-v3-turbo"
        compute = "float16"
    elif info.device == "cuda":
        speech = "small"
        compute = "int8_float16"
    elif info.device == "mps":
        speech = "small"      # faster-whisper corre en CPU en Mac; small es buen balance
        compute = "int8"
    else:
        speech = "base" if info.cpu_count < 8 else "small"
        compute = "int8"

    return {
        "device": info.device,
        "visual_tier": visual_tier,
        "visual_options": visual_options,
        "speech_model": speech,
        "speech_compute": compute,
        "speech_device": "cuda" if info.device == "cuda" else "cpu",
        "notes": _notes(info),
    }


def _notes(info: HardwareInfo) -> list[str]:
    n = []
    if info.device == "cuda":
        n.append(f"GPU NVIDIA detectada ({info.gpu_name}, {info.vram_gb} GB). Análisis acelerado con CUDA.")
    elif info.device == "mps":
        n.append("Apple Silicon detectado. El análisis visual usa la GPU (MPS); la transcripción usa CPU.")
    else:
        n.append("Sin GPU compatible: el análisis será más lento (CPU). Las búsquedas siguen siendo instantáneas.")
    return n
