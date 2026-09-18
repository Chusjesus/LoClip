"""LoClip: búsqueda local con IA para tu footage. Motor."""
__version__ = "0.1.0"

# En Windows, las librerías CUDA/cuDNN que instala pip (paquetes nvidia-*) no están en el PATH.
# Las agregamos para que faster-whisper (CTranslate2) pueda usar la GPU.
import os as _os
import sys as _sys


def _add_nvidia_dlls() -> None:
    if _sys.platform != "win32":
        return
    try:
        import site
        roots = list(site.getsitepackages()) + [site.getusersitepackages()]
    except Exception:
        roots = []
    for root in roots:
        tl = _os.path.join(root, "torch", "lib")  # las ruedas CUDA de torch traen cuBLAS/cuDNN aquí
        if _os.path.isdir(tl):
            try:
                _os.add_dll_directory(tl)
            except Exception:
                pass
            _os.environ["PATH"] = tl + _os.pathsep + _os.environ.get("PATH", "")
        nv = _os.path.join(root, "nvidia")
        if not _os.path.isdir(nv):
            continue
        for name in _os.listdir(nv):
            b = _os.path.join(nv, name, "bin")
            if _os.path.isdir(b):
                try:
                    _os.add_dll_directory(b)
                except Exception:
                    pass
                _os.environ["PATH"] = b + _os.pathsep + _os.environ.get("PATH", "")


_add_nvidia_dlls()
