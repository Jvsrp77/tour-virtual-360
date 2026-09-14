@echo off
cd /d "%~dp0"
echo.
echo   Iniciando o Tour Virtual...
echo.
python -m pip install -q -r requirements.txt
start "" http://127.0.0.1:5000/entrar
python app.py
pause
