#!/usr/bin/env bash
#
# Cross-builds the Windows executable from macOS or Linux.
#
#   ./scripts/build-windows.sh
#   VERSION=1.2.0 ./scripts/build-windows.sh
#
# Wails v3 drives WebView2 through pure-Go bindings, so no cgo and no Windows
# machine are needed for the .exe itself. Only the NSIS installer has to be
# built on Windows (scripts/build-windows.ps1 or the GitHub Actions workflow).
set -euo pipefail

cd "$(dirname "$0")/.."

VERSION="${VERSION:-1.0.0}"
DIST="dist"
EXE="$DIST/FileTransferEasy.exe"

say() { printf '\033[36m▸\033[0m %s\n' "$1"; }

mkdir -p "$DIST"

say "Generando iconos…"
go run ./cmd/genicons >/dev/null

# go-winres writes rsrc_windows_amd64.syso next to main.go, which `go build`
# links in automatically. That is what gives the .exe its icon, its version
# information and its per-monitor DPI awareness.
say "Incrustando icono y manifiesto…"
go run github.com/tc-hib/go-winres@v0.3.3 make \
  --in winres/winres.json \
  --arch amd64 \
  --product-version "$VERSION" \
  --file-version "$VERSION"

cleanup() { rm -f rsrc_windows_*.syso; }
trap cleanup EXIT

say "Compilando windows/amd64…"
# -H windowsgui stops a console window from opening behind the app.
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 \
  go build -trimpath \
    -ldflags "-s -w -H windowsgui -X main.version=$VERSION" \
    -o "$EXE" .

say "Listo:"
echo "    $EXE"
echo
echo "El instalador NSIS se genera en Windows con scripts\\build-windows.ps1,"
echo "o automáticamente al publicar un tag mediante GitHub Actions."
