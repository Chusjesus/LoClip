#!/bin/bash
# LoClip — instalador para macOS (Apple Silicon o Intel) y Linux
# Uso:  bash installers/install.sh
# Instala el motor en un entorno aislado, descarga ffmpeg y los modelos y registra el panel en Premiere.
# No modifica nada en tus carpetas de footage.
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE="$REPO/engine"
PANEL="$REPO/panel"
if [ "$(uname)" = "Darwin" ]; then DATA="$HOME/Library/Application Support/LoClip"; else DATA="${XDG_DATA_HOME:-$HOME/.local/share}/LoClip"; fi
VENV="$DATA/venv"
mkdir -p "$DATA"
say() { printf "\n\033[36m==> %s\033[0m\n" "$1"; }

say "Buscando Python 3.11/3.12…"
PY=""
for c in python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    v=$("$c" -c 'import sys;print("%d.%d"%sys.version_info[:2])')
    case "$v" in 3.11|3.12) PY="$(command -v $c)"; break;; esac
  fi
done
if [ -z "$PY" ]; then
  if command -v brew >/dev/null 2>&1; then say "Instalando Python 3.12 con Homebrew…"; brew install python@3.12; PY="$(brew --prefix)/bin/python3.12";
  else echo "Instala Python 3.12 desde https://www.python.org/downloads/ y vuelve a ejecutar."; exit 1; fi
fi
echo "  Python: $PY"

say "Creando entorno en $VENV"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
VPY="$VENV/bin/python"
"$VPY" -m pip install --upgrade pip wheel --quiet

say "Instalando PyTorch…"
if [ "$(uname)" = "Darwin" ]; then "$VPY" -m pip install torch torchvision --quiet
elif command -v nvidia-smi >/dev/null 2>&1; then "$VPY" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128 --quiet
else "$VPY" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu --quiet; fi

say "Instalando el motor de LoClip…"
"$VPY" -m pip install -r "$ENGINE/requirements.txt" --quiet

say "Verificando ffmpeg…"
FFMPEG="$(command -v ffmpeg || true)"; FFPROBE="$(command -v ffprobe || true)"
if [ -z "$FFMPEG" ]; then
  if command -v brew >/dev/null 2>&1; then brew install ffmpeg; FFMPEG="$(command -v ffmpeg)"; FFPROBE="$(command -v ffprobe)";
  elif [ "$(uname)" = "Darwin" ]; then
    mkdir -p "$DATA/ffmpeg"; cd "$DATA/ffmpeg"
    curl -L -o ffmpeg.zip https://evermeet.cx/ffmpeg/getrelease/zip && unzip -o -q ffmpeg.zip && rm ffmpeg.zip
    curl -L -o ffprobe.zip https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip && unzip -o -q ffprobe.zip && rm ffprobe.zip
    chmod +x ffmpeg ffprobe; xattr -d com.apple.quarantine ffmpeg ffprobe 2>/dev/null || true
    FFMPEG="$DATA/ffmpeg/ffmpeg"; FFPROBE="$DATA/ffmpeg/ffprobe"; cd "$REPO"
  else echo "Instala ffmpeg (sudo apt install ffmpeg) y vuelve a ejecutar."; exit 1; fi
fi

say "Creando lanzador…"
cat > "$DATA/Iniciar LoClip.command" <<EOF
#!/bin/bash
export LOCLIP_FFMPEG="$FFMPEG"
export LOCLIP_FFPROBE="$FFPROBE"
cd "$ENGINE"
exec "$VPY" -m loclip --open
EOF
chmod +x "$DATA/Iniciar LoClip.command"
[ "$(uname)" = "Darwin" ] && ln -sf "$DATA/Iniciar LoClip.command" "$HOME/Desktop/Iniciar LoClip.command" || true

if [ "$(uname)" = "Darwin" ]; then
  say "Instalando el panel en Premiere Pro…"
  CEP="$HOME/Library/Application Support/Adobe/CEP/extensions/com.loclip.panel"
  rm -rf "$CEP"; mkdir -p "$(dirname "$CEP")"; cp -R "$PANEL" "$CEP"
  cat > "$CEP/engine.json" <<EOF
{"cmd": "$VPY", "args": ["-m", "loclip"], "cwd": "$ENGINE", "env": {"LOCLIP_FFMPEG": "$FFMPEG", "LOCLIP_FFPROBE": "$FFPROBE"}}
EOF
  for v in 9 10 11 12 13; do defaults write "com.adobe.CSXS.$v" PlayerDebugMode 1; done
  killall cfprefsd 2>/dev/null || true
fi

say "Descargando modelos de IA (una sola vez)…"
cd "$ENGINE" && "$VPY" -m loclip.setup_models

say "¡Listo!"
cat <<EOF

  1. Abre Premiere Pro (reinícialo si estaba abierto).
  2. Menú Ventana > Extensiones > LoClip   (Window > Extensions > LoClip)
  3. El panel arranca el motor solo. También: "Iniciar LoClip.command" en el Escritorio abre la versión web.
  4. En "Fuentes" agrega la carpeta de footage (p. ej. /Volumes/Vault). LoClip solo lee; nunca escribe ahí.

  Datos de LoClip: $DATA
EOF
