@echo off
rem Instalacion desde el codigo fuente (para desarrollo). Los editores deben usar LoClip-Setup.exe de la pagina Releases.
cd /d "%~dp0"
echo Instalando LoClip desde el codigo fuente. El registro queda en %LOCALAPPDATA%\LoClip\install-dev.log
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { Start-Transcript -Path \"$env:LOCALAPPDATA\LoClip\install-dev.log\" -Append | Out-Null; try { & \"%~dp0install.ps1\" } catch { Write-Host $_ -ForegroundColor Red; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }; Stop-Transcript | Out-Null }"
echo.
echo (Esta ventana se queda abierta para que puedas leer cualquier error.)
pause
