@echo off
REM Gera dist\bio-pdv\bio-pdv.exe
REM Rode UMA vez numa maquina Windows com Python 3.10+ instalado.
REM O .exe resultante roda em qualquer Windows sem Python.

setlocal
cd /d "%~dp0"

echo.
echo === bio-pdv: build para Windows ===
echo.

rem Procura o Python. Quando o instalador nao marca "Add Python to PATH", o
rem comando 'python' nao existe mas o lancador 'py' costuma existir.
set "PYEXE="
where python >nul 2>&1
if not errorlevel 1 set "PYEXE=python"
if defined PYEXE goto :achou_python
where py >nul 2>&1
if not errorlevel 1 set "PYEXE=py"
:achou_python

if not defined PYEXE (
    echo [ERRO] Python nao encontrado.
    echo.
    echo Nem 'python' nem 'py' respondem neste terminal.
    echo Instale de https://python.org e MARQUE "Add Python to PATH"
    echo na primeira tela do instalador.
    pause
    exit /b 1
)
echo Usando: %PYEXE%

echo [1/4] Criando ambiente virtual...
if not exist .venv-build (
    %PYEXE% -m venv .venv-build || goto :erro
)

echo [2/4] Instalando dependencias...
call .venv-build\Scripts\activate.bat
python -m pip install --upgrade pip --quiet || goto :erro
python -m pip install -r requirements.txt --quiet || goto :erro
python -m pip install pyinstaller --quiet || goto :erro

echo [3/4] Gerando o executavel (leva alguns minutos)...
pyinstaller bio-pdv.spec --noconfirm --clean || goto :erro

echo [4/4] Pronto.
echo.
echo Executavel: %CD%\dist\bio-pdv\bio-pdv.exe
echo.
echo Para gerar o INSTALADOR, abra instalador.iss no Inno Setup
echo (https://jrsoftware.org/isdl.php) e clique em Compile.
echo.
pause
exit /b 0

:erro
echo.
echo [ERRO] Falhou. Veja as mensagens acima.
pause
exit /b 1
