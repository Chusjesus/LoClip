# LoClip — instalador para Windows
# Uso: clic derecho > "Ejecutar con PowerShell", o en una terminal:  powershell -ExecutionPolicy Bypass -File installers\install.ps1
# Qué hace: instala Python (si falta), crea un entorno aislado, instala el motor (con CUDA si hay GPU NVIDIA),
# descarga ffmpeg y los modelos, registra el panel en Premiere y crea el acceso directo "Iniciar LoClip".
# No modifica nada en tus carpetas de footage.

$ErrorActionPreference = "Stop"
$Repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$Engine = Join-Path $Repo "engine"
$Panel = Join-Path $Repo "panel"
$Data = Join-Path $env:LOCALAPPDATA "LoClip"
$Venv = Join-Path $Data "venv"
New-Item -ItemType Directory -Force -Path $Data | Out-Null

function Say($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "  ! $m" -ForegroundColor Yellow }

# ---------------------------------------------------------------- Python
Say "Buscando Python 3.11/3.12…"
$py = $null
foreach ($v in @("3.12", "3.11")) {
  try { $out = & py -$v -c "import sys;print(sys.executable)" 2>$null; if ($LASTEXITCODE -eq 0 -and $out) { $py = $out.Trim(); break } } catch {}
}
if (-not $py) {
  Say "Python no encontrado. Instalando Python 3.12 con winget…"
  try { winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements --silent | Out-Null } catch { Warn "winget falló: $_" }
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
  try { $out = & py -3.12 -c "import sys;print(sys.executable)"; if ($LASTEXITCODE -eq 0) { $py = $out.Trim() } } catch {}
  if (-not $py) { throw "No se pudo instalar Python. Instálalo desde https://www.python.org/downloads/ (marca 'Add to PATH') y vuelve a ejecutar este instalador." }
}
Write-Host "  Python: $py"

# ---------------------------------------------------------------- venv
Say "Creando entorno de LoClip en $Venv"
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) { & $py -m venv $Venv }
$VPy = Join-Path $Venv "Scripts\python.exe"
& $VPy -m pip install --upgrade pip wheel --quiet

# ---------------------------------------------------------------- GPU
$hasNvidia = $false
try { & nvidia-smi 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { $hasNvidia = $true } } catch {}
if ($hasNvidia) {
  Say "GPU NVIDIA detectada: instalando PyTorch con CUDA (descarga grande, ~3 GB; ten paciencia)"
  & $VPy -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128 --quiet
  & $VPy -m pip install nvidia-cudnn-cu12 nvidia-cublas-cu12 --quiet
} else {
  Say "Sin GPU NVIDIA: instalando PyTorch para CPU (el análisis será más lento, la búsqueda igual de rápida)"
  & $VPy -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu --quiet
}

Say "Instalando el motor de LoClip…"
& $VPy -m pip install -r (Join-Path $Engine "requirements.txt") --quiet

# ---------------------------------------------------------------- ffmpeg
Say "Verificando ffmpeg…"
$ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
$FFDir = Join-Path $Data "ffmpeg"
if (-not $ff -and -not (Test-Path (Join-Path $FFDir "ffmpeg.exe"))) {
  Say "Descargando ffmpeg (build estático de gyan.dev)…"
  $zip = Join-Path $Data "ffmpeg.zip"
  Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $zip
  $tmp = Join-Path $Data "ffmpeg_tmp"
  if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
  Expand-Archive -Path $zip -DestinationPath $tmp
  New-Item -ItemType Directory -Force -Path $FFDir | Out-Null
  Get-ChildItem -Recurse -Path $tmp -Include ffmpeg.exe, ffprobe.exe | ForEach-Object { Copy-Item $_.FullName $FFDir -Force }
  Remove-Item -Recurse -Force $tmp; Remove-Item -Force $zip
}
$ffmpegExe = if ($ff) { $ff.Source } else { Join-Path $FFDir "ffmpeg.exe" }
$ffprobeExe = if ($ff) { (Get-Command ffprobe).Source } else { Join-Path $FFDir "ffprobe.exe" }

# ---------------------------------------------------------------- lanzador
Say "Creando lanzador…"
$VPyw = Join-Path $Venv "Scripts\pythonw.exe"
$Start = Join-Path $Data "Iniciar LoClip.cmd"
@"
@echo off
set LOCLIP_FFMPEG=$ffmpegExe
set LOCLIP_FFPROBE=$ffprobeExe
cd /d "$Engine"
start "" "$VPyw" -m loclip --open
"@ | Set-Content -Path $Start -Encoding ASCII
$StopS = Join-Path $Data "Detener LoClip.cmd"
"@echo off`r`ncurl -s -X POST http://127.0.0.1:47821/api/shutdown >nul 2>&1`r`ntaskkill /F /FI `"WINDOWTITLE eq loclip`" >nul 2>&1" | Set-Content -Path $StopS -Encoding ASCII
$ws = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath("Desktop"), (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))) {
  $lnk = $ws.CreateShortcut((Join-Path $dir "Iniciar LoClip.lnk")); $lnk.TargetPath = $Start; $lnk.IconLocation = (Join-Path $Panel "icons\icon-256.png"); $lnk.Save()
}

# ---------------------------------------------------------------- panel de Premiere
Say "Instalando el panel en Premiere Pro…"
$CepDir = Join-Path $env:APPDATA "Adobe\CEP\extensions\com.loclip.panel"
if (Test-Path $CepDir) { Remove-Item -Recurse -Force $CepDir }
New-Item -ItemType Directory -Force -Path (Split-Path $CepDir) | Out-Null
Copy-Item -Recurse $Panel $CepDir
@{ cmd = $VPyw; args = @("-m", "loclip"); cwd = $Engine; env = @{ LOCLIP_FFMPEG = $ffmpegExe; LOCLIP_FFPROBE = $ffprobeExe } } | ConvertTo-Json | Set-Content -Path (Join-Path $CepDir "engine.json") -Encoding UTF8
# Permitir paneles sin firma (necesario para paneles internos; es un ajuste estándar de Adobe)
foreach ($v in 9..13) {
  $k = "HKCU:\Software\Adobe\CSXS.$v"
  if (-not (Test-Path $k)) { New-Item -Path $k -Force | Out-Null }
  Set-ItemProperty -Path $k -Name PlayerDebugMode -Value "1" -Type String
}
# El lanzador del panel necesita las variables de ffmpeg: las guardamos también a nivel de usuario.
[Environment]::SetEnvironmentVariable("LOCLIP_FFMPEG", $ffmpegExe, "User")
[Environment]::SetEnvironmentVariable("LOCLIP_FFPROBE", $ffprobeExe, "User")

# ---------------------------------------------------------------- modelos
Say "Descargando modelos de IA (una sola vez; ~0.5–2 GB según tu equipo)…"
Push-Location $Engine
& $VPy -m loclip.setup_models
Pop-Location

Say "¡Listo!"
Write-Host @"

  1. Abre Premiere Pro (reinícialo si estaba abierto).
  2. Menú Ventana > Extensiones > LoClip   (en inglés: Window > Extensions > LoClip)
  3. El panel arranca el motor solo. También puedes usar "Iniciar LoClip" del escritorio para la versión web.
  4. En "Fuentes" agrega la carpeta de footage. LoClip solo lee; nunca escribe en tus carpetas.

  Datos de LoClip (índice, miniaturas, modelos): $Data
"@
