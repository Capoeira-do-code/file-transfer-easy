$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creando entorno virtual..."
    py -3 -m venv .venv
}

$python = ".\.venv\Scripts\python.exe"
& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "No se pudo actualizar pip." }
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias runtime." }
& $python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias de build." }

Write-Host "Generando dist\FileTransferEasy.exe..."
& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onefile `
    --name FileTransferEasy `
    --hidden-import flask `
    --hidden-import waitress `
    --hidden-import waitress.server `
    --hidden-import jinja2 `
    --hidden-import werkzeug `
    --hidden-import PySide6.QtCore `
    --hidden-import PySide6.QtWidgets `
    --hidden-import PySide6.QtWebEngineWidgets `
    --hidden-import PySide6.QtWebEngineCore `
    app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller no pudo generar el ejecutable." }

Write-Host "Listo: dist\FileTransferEasy.exe"
