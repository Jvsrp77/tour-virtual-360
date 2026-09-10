@echo off
cd /d "%~dp0"
echo.
echo   Iniciando o Tour Virtual...
echo.
python -m pip install -q -r requirements.txt
start "" http://localhost:5000/painel
python app.py
pause
