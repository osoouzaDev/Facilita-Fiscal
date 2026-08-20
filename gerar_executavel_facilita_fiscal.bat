@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Ambiente Python nao encontrado em .venv.
    echo Crie o ambiente e instale requirements.txt e pyinstaller.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean FacilitaFiscal.spec
if errorlevel 1 (
    echo.
    echo Nao foi possivel gerar o executavel.
    pause
    exit /b 1
)

echo.
echo Executavel criado em dist\FacilitaFiscal.exe
pause
