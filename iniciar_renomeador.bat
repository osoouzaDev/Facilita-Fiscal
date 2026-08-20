@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" renomeador_pdfs.py
) else (
    py renomeador_pdfs.py
)
if errorlevel 1 (
    echo.
    echo Nao foi possivel iniciar o programa.
    echo Consulte as instrucoes do arquivo README.md.
    pause
)
