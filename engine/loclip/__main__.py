"""Arranque: `python -m loclip` levanta el servidor local en http://127.0.0.1:47821"""
from __future__ import annotations

import argparse
import logging
import webbrowser

import uvicorn

from .config import DEFAULT_PORT, data_dir, load_settings


def main() -> None:
    ap = argparse.ArgumentParser("loclip")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--open", action="store_true", help="Abrir la interfaz web en el navegador")
    ap.add_argument("--log", default="info")
    args = ap.parse_args()
    logging.basicConfig(level=args.log.upper(), format="%(asctime)s %(name)s %(levelname)s %(message)s")
    settings = load_settings()
    port = args.port or int(settings.get("port") or DEFAULT_PORT)
    logging.getLogger("loclip").info("Datos en %s", data_dir())
    if args.open:
        import threading
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    uvicorn.run("loclip.server:app", host="127.0.0.1", port=port, log_level=args.log, workers=1)


if __name__ == "__main__":
    main()
