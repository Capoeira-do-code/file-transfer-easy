@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creando entorno virtual...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo No se pudo crear el entorno virtual. Comprueba que Python esta instalado.
        pause
        exit /b 1
    )
)

echo Instalando dependencias...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo No se pudieron instalar las dependencias.
    pause
    exit /b 1
)

echo Abriendo File Transfer Easy...
start "" ".venv\Scripts\pythonw.exe" "%~dp0app.py"
endlocal
