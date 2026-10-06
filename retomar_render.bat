@echo off
REM Retoma o render das plantas defasadas de onde parou.
REM Pode fechar e reabrir a vontade: um ponto so conta como pronto quando tem
REM A FOTO E O MAPA de profundidade, entao ponto interrompido no meio e refeito.
cd /d "%~dp0"
"C:\Users\jrpin\AppData\Local\Programs\Python\Python311\python.exe" -u cena_apartamento.py apto_padrao apto_compacto cobertura mansao pavilhao
echo.
echo Terminou. Falta publicar com:  python publicar.py mansao ...
pause
