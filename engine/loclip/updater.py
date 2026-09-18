"""Actualización desde el propio panel: consulta la última versión publicada en GitHub Releases,
descarga el instalador y lo ejecuta en modo silencioso. Funciona solo en Windows (el .exe) y
requiere que el repositorio sea público (o un token en LOCLIP_GITHUB_TOKEN)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import urllib.request

from .config import data_dir

REPO = os.environ.get("LOCLIP_REPO", "Chusjesus/LoClip")
state = {"checking": False, "latest": None, "url": None, "notes": "", "error": "", "downloading": False, "progress": 0.0, "launched": False}


def _ver_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def check(current: str) -> dict:
    state.update(checking=True, error="")
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest", headers={"Accept": "application/vnd.github+json", "User-Agent": "LoClip"})
        tok = os.environ.get("LOCLIP_GITHUB_TOKEN")
        if tok:
            req.add_header("Authorization", f"Bearer {tok}")
        with urllib.request.urlopen(req, timeout=10) as r:
            rel = json.load(r)
        tag = rel.get("tag_name", "")
        asset = next((a for a in rel.get("assets", []) if a["name"].lower().endswith(".exe")), None)
        state.update(latest=tag.lstrip("v"), url=asset["browser_download_url"] if asset else None, notes=(rel.get("body") or "")[:2000])
    except Exception as e:  # noqa: BLE001
        state.update(error=str(e))
    finally:
        state["checking"] = False
    return status(current)


def status(current: str) -> dict:
    latest = state["latest"]
    available = bool(latest and _ver_tuple(latest) > _ver_tuple(current) and state["url"] and sys.platform == "win32")
    return {"current": current, "latest": latest, "available": available, "url": state["url"], "notes": state["notes"],
            "error": state["error"], "downloading": state["downloading"], "progress": state["progress"], "launched": state["launched"]}


def apply(on_ready) -> dict:
    """Descarga el instalador y lo lanza. `on_ready` se llama justo antes de lanzar (para apagar el motor)."""
    if not state["url"] or sys.platform != "win32":
        return {"ok": False, "error": "No hay instalador disponible para esta plataforma"}
    if state["downloading"]:
        return {"ok": True, "already": True}

    def worker():
        state.update(downloading=True, progress=0.0, error="")
        try:
            dest = data_dir() / "updates"
            dest.mkdir(exist_ok=True)
            path = dest / f"LoClip-Setup-{state['latest']}.exe"
            req = urllib.request.Request(state["url"], headers={"User-Agent": "LoClip"})
            with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        state["progress"] = done / total
            state["progress"] = 1.0
            on_ready()
            # /SILENT muestra solo la barra de progreso; el bootstrap final abre su ventana de consola.
            subprocess.Popen([str(path), "/SILENT", "/NORESTART", "/SUPPRESSMSGBOXES"], close_fds=True,
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            state["launched"] = True
            threading.Timer(1.5, lambda: os._exit(0)).start()
        except Exception as e:  # noqa: BLE001
            state["error"] = str(e)
        finally:
            state["downloading"] = False

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True}
