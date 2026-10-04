#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${VERSION:-1.0.1}"
ARCH="${ARCH:-$(go env GOARCH)}"
case "$ARCH" in amd64|arm64) ;; *) echo "ARCH debe ser amd64 o arm64" >&2; exit 1 ;; esac
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "VERSION debe usar X.Y.Z" >&2; exit 1; }
for tool in go python3; do command -v "$tool" >/dev/null || { echo "Falta $tool" >&2; exit 1; }; done
PKG_CONFIG="${PKG_CONFIG:-pkg-config}"
command -v "$PKG_CONFIG" >/dev/null || { echo "Falta pkg-config" >&2; exit 1; }
"$PKG_CONFIG" --exists gtk+-3.0 webkit2gtk-4.1 gdk-3.0 x11 || {
  echo "Faltan GTK3 y WebKitGTK 4.1. En Debian/Ubuntu: sudo apt install build-essential pkg-config libgtk-3-dev libwebkit2gtk-4.1-dev libx11-dev" >&2
  exit 1
}
if [[ "$(uname -s)" != "Linux" && -z "${CC:-}" ]]; then
  echo "Desde macOS usa python3 scripts/build-linux-cross.py, o configura CC y un sysroot Linux." >&2
  exit 1
fi
work="$(mktemp -d "${TMPDIR:-/tmp}/fte-linux.XXXXXX")"
trap 'rm -rf "$work"' EXIT
go run ./cmd/genicons
CGO_ENABLED=1 GOOS=linux GOARCH="$ARCH" PKG_CONFIG="$PKG_CONFIG" \
  go build -tags gtk3 -trimpath -ldflags "-s -w -X main.version=$VERSION" -o "$work/file-transfer-easy" .
python3 scripts/package-linux.py "$work/file-transfer-easy" "$VERSION" "$ARCH"
