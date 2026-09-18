"""Lectura de medios: escaneo de carpetas, metadatos, extracción de frames y miniaturas.

Todo aquí abre los archivos SOLO en modo lectura. Las miniaturas se guardan en la
carpeta de datos de LoClip, nunca junto al material.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np
from PIL import Image, ImageOps

from .config import MEDIA_AUDIO, MEDIA_EXTS, MEDIA_IMAGE, MEDIA_VIDEO, SKIP_DIR_NAMES, thumbs_dir


def kind_of(path: str) -> str | None:
    ext = Path(path).suffix.lower()
    if ext in MEDIA_VIDEO:
        return "video"
    if ext in MEDIA_IMAGE:
        return "image"
    if ext in MEDIA_AUDIO:
        return "audio"
    return None


def scan(root: str) -> Iterator[tuple[str, int, float]]:
    """Recorre una carpeta y devuelve (ruta, tamaño, mtime) de cada archivo de medios."""
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES and not d.startswith(".")]
        for fn in filenames:
            if fn.startswith(".") or fn.startswith("~"):
                continue
            if Path(fn).suffix.lower() not in MEDIA_EXTS:
                continue
            p = os.path.join(dirpath, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            yield p, st.st_size, st.st_mtime


def _bundled(name: str) -> str | None:
    """ffmpeg incluido en la instalación (carpeta `ffmpeg/` junto a `engine/`)."""
    exe = name + (".exe" if os.name == "nt" else "")
    for base in (Path(__file__).resolve().parents[2], Path(sys.executable).resolve().parent.parent):
        p = base / "ffmpeg" / exe
        if p.exists():
            return str(p)
    return None


def _ffprobe_bin() -> str:
    return os.environ.get("LOCLIP_FFPROBE") or _bundled("ffprobe") or shutil.which("ffprobe") or "ffprobe"


def _ffmpeg_bin() -> str:
    return os.environ.get("LOCLIP_FFMPEG") or _bundled("ffmpeg") or shutil.which("ffmpeg") or "ffmpeg"


@dataclass
class Probe:
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""
    has_audio: bool = False
    has_video: bool = False


def probe(path: str) -> Probe:
    """Metadatos con ffprobe (lectura). Si falla, intenta con PyAV."""
    pr = Probe()
    try:
        out = subprocess.run(
            [_ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=60,
        )
        info = json.loads(out.stdout or "{}")
        pr.duration = float(info.get("format", {}).get("duration") or 0)
        for s in info.get("streams", []):
            if s.get("codec_type") == "video" and not pr.has_video:
                # Las portadas de mp3 aparecen como video "attached_pic": ignorarlas.
                if s.get("disposition", {}).get("attached_pic"):
                    continue
                pr.has_video = True
                pr.width = int(s.get("width") or 0)
                pr.height = int(s.get("height") or 0)
                pr.codec = s.get("codec_name", "")
                fr = s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/1"
                try:
                    n, d = fr.split("/")
                    pr.fps = float(n) / float(d) if float(d) else 0.0
                except Exception:
                    pr.fps = 0.0
                if not pr.duration and s.get("duration"):
                    pr.duration = float(s["duration"])
            elif s.get("codec_type") == "audio":
                pr.has_audio = True
        return pr
    except Exception:
        pass
    try:
        import av
        with av.open(path, mode="r") as c:
            pr.duration = float(c.duration / av.time_base) if c.duration else 0.0
            if c.streams.video:
                v = c.streams.video[0]
                pr.has_video, pr.width, pr.height = True, v.width, v.height
                pr.fps = float(v.average_rate or 0)
                pr.codec = v.codec_context.name
            pr.has_audio = bool(c.streams.audio)
    except Exception:
        pass
    return pr


def iter_frames(path: str, sample_fps: float, max_seconds: float = 0) -> Iterator[tuple[float, Image.Image]]:
    """Genera (tiempo_en_segundos, imagen PIL) a `sample_fps` cuadros por segundo.

    Usa ffmpeg en modo lectura para máxima compatibilidad de códecs (ProRes, MXF, H.265…).
    Los frames salen reducidos a 512px de lado largo: suficiente para el modelo y mucho más rápido.
    """
    vf = f"fps={sample_fps},scale='if(gt(iw,ih),512,-2)':'if(gt(iw,ih),-2,512)'"
    cmd = [_ffmpeg_bin(), "-v", "error", "-nostdin", "-threads", "2"]
    if max_seconds:
        cmd += ["-t", str(max_seconds)]
    cmd += ["-i", path, "-vf", vf, "-f", "image2pipe", "-pix_fmt", "rgb24", "-vcodec", "rawvideo", "-"]
    # Necesitamos saber el tamaño de salida: lo calculamos con un probe.
    pr = probe(path)
    if not pr.has_video or not pr.width or not pr.height:
        return
    if pr.width >= pr.height:
        w, h = 512, int(round(pr.height * 512 / pr.width / 2) * 2)
    else:
        h, w = 512, int(round(pr.width * 512 / pr.height / 2) * 2)
    frame_bytes = w * h * 3
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=frame_bytes * 4)
    i = 0
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if not buf or len(buf) < frame_bytes:
                break
            arr = np.frombuffer(buf, dtype=np.uint8).reshape((h, w, 3))
            yield i / sample_fps, Image.fromarray(arr)
            i += 1
    finally:
        try:
            proc.stdout.close()
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            pass


def frame_at(path: str, t: float) -> Image.Image | None:
    """Extrae un solo frame en el segundo t (para 'match frame' desde Premiere)."""
    cmd = [_ffmpeg_bin(), "-v", "error", "-nostdin", "-ss", f"{max(0.0, t):.3f}", "-i", path,
           "-frames:v", "1", "-vf", "scale='if(gt(iw,ih),512,-2)':'if(gt(iw,ih),-2,512)'",
           "-f", "image2pipe", "-vcodec", "png", "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=60)
        if out.stdout:
            import io
            return Image.open(io.BytesIO(out.stdout)).convert("RGB")
    except Exception:
        return None
    return None


def load_image(path: str) -> Image.Image | None:
    try:
        im = Image.open(path)
        im = ImageOps.exif_transpose(im)
        return im.convert("RGB")
    except Exception:
        return None


def thumb_name(file_id: int, t: float) -> str:
    return f"{file_id}_{int(round(t * 1000))}.jpg"


def save_thumb(img: Image.Image, name: str, size: int = 320) -> str:
    p = thumbs_dir() / name
    if not p.exists():
        im = img.copy()
        im.thumbnail((size, size))
        im.save(p, "JPEG", quality=80)
    return name


def extract_audio_wav(path: str, out: Path, max_seconds: float = 0) -> bool:
    """Extrae el audio a WAV 16 kHz mono en la carpeta temporal de LoClip (para whisper)."""
    cmd = [_ffmpeg_bin(), "-v", "error", "-nostdin", "-y", "-i", path]
    if max_seconds:
        cmd += ["-t", str(max_seconds)]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=3600)
        return r.returncode == 0 and out.exists() and out.stat().st_size > 1000
    except Exception:
        return False


def file_key(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8", "surrogateescape")).hexdigest()[:16]
