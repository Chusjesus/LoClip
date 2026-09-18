"""Paso final del instalador de Windows (lo ejecuta LoClip-Setup.exe con el Python incluido).

1. Cierra un motor de LoClip que esté corriendo.
2. Si hay GPU NVIDIA, cambia PyTorch a la versión con CUDA (descarga ~3 GB). Si no, se queda con la de CPU ya incluida.
3. Instala el panel en Premiere (carpeta CEP del usuario) y escribe engine.json con las rutas reales.
4. Descarga los modelos de IA para que el primer arranque sea inmediato.
Si algo falla, LoClip sigue funcionando en modo CPU y descarga los modelos al primer uso.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

APP = os.path.dirname(os.path.abspath(sys.executable))          # …\LoClip\python
ROOT = os.path.dirname(APP)                                      # …\LoClip
ENGINE = os.path.join(ROOT, "engine")
PANEL_SRC = os.path.join(ROOT, "panel")
PY = sys.executable
PYW = os.path.join(APP, "pythonw.exe")
CEP_DIR = os.path.join(os.environ.get("APPDATA", ""), "Adobe", "CEP", "extensions", "com.loclip.panel")
LOG = os.path.join(os.environ.get("LOCALAPPDATA", ROOT), "LoClip", "install.log")


def say(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run(cmd: list[str]) -> int:
    say("> " + " ".join(cmd))
    return subprocess.call(cmd)


def stop_engine() -> None:
    try:
        urllib.request.urlopen("http://127.0.0.1:47821/api/shutdown", data=b"", timeout=2)
        time.sleep(1)
    except Exception:
        pass


def has_nvidia() -> bool:
    try:
        return subprocess.call(["nvidia-smi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
    except Exception:
        return False


def torch_is_cuda() -> bool:
    try:
        out = subprocess.check_output([PY, "-c", "import torch;print(torch.version.cuda or '')"], text=True, timeout=120)
        return bool(out.strip())
    except Exception:
        return False


def install_cuda_torch() -> None:
    say("GPU NVIDIA detectada. Descargando PyTorch con CUDA (~3 GB). Esto puede tardar varios minutos…")
    rc = run([PY, "-m", "pip", "install", "--no-warn-script-location", "torch", "torchvision",
              "--index-url", "https://download.pytorch.org/whl/cu128", "--upgrade", "--force-reinstall", "--no-deps"])
    if rc == 0:
        run([PY, "-m", "pip", "install", "--no-warn-script-location", "nvidia-cudnn-cu12", "nvidia-cublas-cu12"])
        say("PyTorch CUDA instalado.")
    else:
        say("No se pudo instalar la versión CUDA; LoClip usará CPU (más lento al analizar, igual de rápido al buscar).")


def install_panel() -> None:
    say("Instalando el panel en Premiere Pro…")
    if os.path.isdir(CEP_DIR):
        shutil.rmtree(CEP_DIR, ignore_errors=True)
    os.makedirs(os.path.dirname(CEP_DIR), exist_ok=True)
    shutil.copytree(PANEL_SRC, CEP_DIR)
    cfg = {"cmd": PYW, "args": ["-m", "loclip"], "cwd": ENGINE, "env": {}}
    with open(os.path.join(CEP_DIR, "engine.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    # Permitir paneles sin firma de Adobe (ajuste estándar para paneles internos)
    try:
        import winreg
        for v in range(9, 14):
            k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Adobe\CSXS.{v}")
            winreg.SetValueEx(k, "PlayerDebugMode", 0, winreg.REG_SZ, "1")
            winreg.CloseKey(k)
    except Exception as e:  # noqa: BLE001
        say(f"Aviso: no se pudo escribir el registro de Adobe ({e}).")
    say("Panel instalado en " + CEP_DIR)


def download_models() -> None:
    say("Descargando modelos de IA (una sola vez)…")
    rc = subprocess.call([PY, "-m", "loclip.setup_models"], cwd=ENGINE)
    say("Modelos listos." if rc == 0 else "Los modelos se descargarán en el primer arranque.")


def main() -> int:
    say("=== LoClip: configuración final ===")
    stop_engine()
    if has_nvidia() and not torch_is_cuda():
        install_cuda_torch()
    else:
        say("Sin GPU NVIDIA (o CUDA ya instalado): se usa la configuración actual.")
    install_panel()
    download_models()
    say("=== Listo. Abre Premiere: Ventana > Extensiones > LoClip ===")
    time.sleep(2)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        say(f"ERROR: {e}")
        print("\nPuedes cerrar esta ventana. LoClip intentará completar la configuración al primer arranque.")
        time.sleep(15)
        sys.exit(0)
