@echo off
REM Lanza Albion BM desde el codigo fuente (requiere Python 3.9+ y Npcap).
cd /d "%~dp0"
if not exist .venv (
  echo Creando entorno de Python...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
start "" .venv\Scripts\pythonw.exe AlbionBM.pyw
