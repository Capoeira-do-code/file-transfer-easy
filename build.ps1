$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creando entorno virtual..."
    py -3 -m venv .venv
}

$python = ".\.venv\Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt
& $python -m pip install -r requirements-dev.txt

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
    app.py

Write-Host "Listo: dist\FileTransferEasy.exe"
