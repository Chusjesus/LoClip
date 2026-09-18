"""Rutas y configuración de LoClip.

Regla de oro: LoClip NUNCA escribe junto al material. Todo (base de datos,
miniaturas, modelos, logs) vive en la carpeta de datos del usuario.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

APP_NAME = "LoClip"
DEFAULT_PORT = 47821

MEDIA_VIDEO = {".mp4", ".mov", ".mxf", ".avi", ".mkv", ".m4v", ".webm", ".mts", ".m2ts", ".mpg", ".mpeg", ".wmv", ".braw", ".r3d", ".prores", ".dv", ".3gp", ".ts"}
MEDIA_IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".heic", ".gif", ".dng", ".psd"}
MEDIA_AUDIO = {".wav", ".mp3", ".aac", ".m4a", ".flac", ".aif", ".aiff", ".ogg", ".wma"}
MEDIA_EXTS = MEDIA_VIDEO | MEDIA_IMAGE | MEDIA_AUDIO

# Carpetas que nunca se indexan (caches de Premiere, previews, etc.)
SKIP_DIR_NAMES = {
    "Adobe Premiere Pro Video Previews", "Adobe Premiere Pro Audio Previews",
    "Media Cache", "Media Cache Files", "Peak Files", "Auto-Save", "Adobe Premiere Pro Auto-Save",
    "node_modules", ".git", "$RECYCLE.BIN", "System Volume Information", ".Trash", ".Trashes",
    "__MACOSX", ".lucid", ".DS_Store", "Proxies", "Proxy",
}


def data_dir() -> Path:
    env = os.environ.get("LOCLIP_DATA")
    if env:
        p = Path(env)
    elif sys.platform == "win32":
        p = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        p = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def thumbs_dir() -> Path:
    p = data_dir() / "thumbs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def models_dir() -> Path:
    p = data_dir() / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / "loclip.sqlite3"


DEFAULT_SETTINGS: dict[str, Any] = {
    "language": "auto",            # "auto" | "es" | "en"  (idioma de la interfaz)
    "port": DEFAULT_PORT,
    "visual_model": "auto",        # "auto" | nombre de open_clip
    "speech_model": "auto",        # "auto" | tamaño de faster-whisper
    "device": "auto",              # "auto" | "cuda" | "cpu" | "mps"
    "sample_fps": 1.0,             # frames analizados por segundo de video
    "moment_similarity": 0.90,     # frames consecutivos más parecidos que esto se agrupan en un "momento"
    "transcribe": True,
    "transcribe_languages": ["es", "en"],
    "max_video_seconds": 0,        # 0 = sin límite
    "thumb_size": 320,
}


def load_settings() -> dict[str, Any]:
    p = data_dir() / "settings.json"
    s = dict(DEFAULT_SETTINGS)
    if p.exists():
        try:
            s.update(json.loads(p.read_text("utf-8")))
        except Exception:
            pass
    return s


def save_settings(s: dict[str, Any]) -> None:
    p = data_dir() / "settings.json"
    p.write_text(json.dumps(s, indent=2, ensure_ascii=False), "utf-8")
