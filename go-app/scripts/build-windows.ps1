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

[CmdletBinding()]
param(
    [string]$Version = "",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Join-Path $PSScriptRoot "..")

if (-not $Version) { $Version = if ($env:VERSION) { $env:VERSION } else { (Get-Content -LiteralPath VERSION -Raw).Trim() } }
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Version debe usar X.Y.Z." }
$Dist = "dist"
$Exe = Join-Path $Dist "FileTransferEasy-$Version-windows-amd64.exe"

function Say($message) { Write-Host "> $message" -ForegroundColor Cyan }

New-Item -ItemType Directory -Path $Dist -Force | Out-Null

Say "Generando iconos..."
go run ./cmd/genicons | Out-Null
if ($LASTEXITCODE -ne 0) { throw "No se pudieron generar los iconos." }

# go-winres turns the .ico and the manifest into a .syso that `go build` picks
# up automatically, which is what gives the .exe its icon and DPI awareness.
Say "Incrustando icono y manifiesto..."
$resource = Join-Path (Get-Location).Path 'rsrc_windows_amd64.syso'
$resourceBackup = $null
if (Test-Path -LiteralPath $resource) {
    $resourceBackup = Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName())
    Copy-Item -LiteralPath $resource -Destination $resourceBackup
}
$previousCGO, $previousOS, $previousArch = $env:CGO_ENABLED, $env:GOOS, $env:GOARCH
try {
    go run github.com/tc-hib/go-winres@v0.3.3 make --in winres/winres.json --arch amd64 --product-version $Version --file-version $Version
    if ($LASTEXITCODE -ne 0) { throw "go-winres falló." }

    Say "Compilando windows/amd64..."
    $env:CGO_ENABLED = "0"
    $env:GOOS = "windows"
    $env:GOARCH = "amd64"
    # -H windowsgui keeps a console window from appearing behind the app.
    go build -tags production -trimpath -ldflags "-s -w -H windowsgui -X main.version=$Version" -o $Exe .
    if ($LASTEXITCODE -ne 0) { throw "La compilación falló." }
} finally {
    $env:CGO_ENABLED, $env:GOOS, $env:GOARCH = $previousCGO, $previousOS, $previousArch
    if ($resourceBackup) {
        Move-Item -LiteralPath $resourceBackup -Destination $resource -Force
    } elseif (Test-Path -LiteralPath $resource) {
        Remove-Item -LiteralPath $resource -Force
    }
}

$hash = (Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $([IO.Path]::GetFileName($Exe))" | Set-Content -LiteralPath "$Exe.sha256" -Encoding ascii

Say "Listo: $Exe"
if ($SkipInstaller) { return }

# ------------------------------------------------------------------ installer

$makensis = Get-Command makensis -ErrorAction SilentlyContinue
if (-not $makensis) {
    Say "NSIS no está instalado; se omite el instalador (el .exe portable ya sirve)."
    exit 0
}

Say "Construyendo el instalador..."
& $makensis.Source "/DVERSION=$Version" "/DSOURCE_EXE=$((Resolve-Path -LiteralPath $Exe).Path)" installer\windows.nsi
if ($LASTEXITCODE -ne 0) { throw "NSIS falló." }

$installer = Join-Path $Dist "FileTransferEasy-Setup-$Version.exe"
$hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $([IO.Path]::GetFileName($installer))" | Set-Content -LiteralPath "$installer.sha256" -Encoding ascii
Say "Listo: $installer"
