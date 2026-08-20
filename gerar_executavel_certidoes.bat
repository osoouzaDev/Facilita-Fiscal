@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Criando o ambiente de compilacao...
    py -m venv .venv
    if errorlevel 1 goto :erro
)

echo Instalando as dependencias...
".venv\Scripts\python.exe" -m pip install -r requirements.txt -r requirements-build.txt
if errorlevel 1 goto :erro

echo Gerando o executavel...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean RenomeadorCertidoesEstaduais.spec
if errorlevel 1 goto :erro

echo.
echo Executavel criado em:
echo %CD%\dist\RenomeadorCertidoesEstaduais.exe
pause
exit /b 0

:erro
echo.
echo Nao foi possivel gerar o executavel.
pause
exit /b 1
