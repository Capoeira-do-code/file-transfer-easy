# Builds File Transfer Easy for Windows: a portable FileTransferEasy.exe and,
# when NSIS is available, an installer alongside it.
#
#   .\scripts\build-windows.ps1
#   $env:VERSION = "1.2.0"; .\scripts\build-windows.ps1
#
# Wails v3 talks to WebView2 through pure-Go bindings, so no C toolchain is
# needed. cloudflared is not bundled: the app downloads it on first use.
#
# To build only the .exe, scripts/build-windows.sh cross-compiles it from
# macOS or Linux. This script exists for the NSIS installer, which does need
# to run on Windows.

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Join-Path $PSScriptRoot "..")

$Version = if ($env:VERSION) { $env:VERSION } else { "1.0.0" }
$Dist = "dist"
$Exe = Join-Path $Dist "FileTransferEasy.exe"

function Say($message) { Write-Host "> $message" -ForegroundColor Cyan }

if (Test-Path $Dist) { Remove-Item -Recurse -Force $Dist }
New-Item -ItemType Directory -Path $Dist | Out-Null

Say "Generando iconos..."
go run ./cmd/genicons | Out-Null
if ($LASTEXITCODE -ne 0) { throw "No se pudieron generar los iconos." }

# go-winres turns the .ico and the manifest into a .syso that `go build` picks
# up automatically, which is what gives the .exe its icon and DPI awareness.
Say "Incrustando icono y manifiesto..."
go run github.com/tc-hib/go-winres@v0.3.3 make --in winres/winres.json --arch amd64 --product-version $Version --file-version $Version
if ($LASTEXITCODE -ne 0) { throw "go-winres falló." }

Say "Compilando windows/amd64..."
$env:CGO_ENABLED = "0"
$env:GOOS = "windows"
$env:GOARCH = "amd64"
# -H windowsgui keeps a console window from appearing behind the app.
go build -trimpath -ldflags "-s -w -H windowsgui -X main.version=$Version" -o $Exe .
if ($LASTEXITCODE -ne 0) { throw "La compilación falló." }

# The .syso would otherwise get picked up by unrelated builds on this machine.
Get-ChildItem -Filter "rsrc_windows_*.syso" | Remove-Item -Force -ErrorAction SilentlyContinue

Say "Listo: $Exe"

# ------------------------------------------------------------------ installer

$makensis = Get-Command makensis -ErrorAction SilentlyContinue
if (-not $makensis) {
    Say "NSIS no está instalado; se omite el instalador (el .exe portable ya sirve)."
    exit 0
}

Say "Construyendo el instalador..."
& $makensis.Source /DVERSION=$Version installer\windows.nsi
if ($LASTEXITCODE -ne 0) { throw "NSIS falló." }

Say "Listo: $(Join-Path $Dist "FileTransferEasy-Setup-$Version.exe")"
