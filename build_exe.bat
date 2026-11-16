@echo off
REM Genera dist\AlbionBM.exe (un solo archivo). Requiere Python 3.9+.
cd /d "%~dp0"
py -3 -m venv .venv-build || python -m venv .venv-build
.venv-build\Scripts\python -m pip install -r requirements.txt pyinstaller
.venv-build\Scripts\pyinstaller --noconfirm --onefile --windowed --name AlbionBM ^
  --add-data "data;data" --collect-submodules scapy.layers --collect-submodules scapy.arch --collect-data certifi ^
  AlbionBM.pyw
echo.
echo Listo: dist\AlbionBM.exe
pause
