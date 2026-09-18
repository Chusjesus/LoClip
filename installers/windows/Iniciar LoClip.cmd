@echo off
rem Abre la versión web de LoClip (el panel de Premiere arranca el motor solo; esto es opcional)
cd /d "%~dp0engine"
start "" "%~dp0python\pythonw.exe" -m loclip --open
