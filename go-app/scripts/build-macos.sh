#!/usr/bin/env bash
#
# Builds File Transfer Easy for macOS: a universal .app bundle and a .dmg.
#
#   ./scripts/build-macos.sh            # universal (arm64 + amd64)
#   ARCH=arm64 ./scripts/build-macos.sh # single architecture, much faster
#
# Requires the Xcode command line tools (clang, lipo, iconutil, hdiutil).
# Nothing else: cloudflared is downloaded by the app on first use, so it is
# deliberately not bundled here.
set -euo pipefail

cd "$(dirname "$0")/.."

APP_NAME="File Transfer Easy"
BUNDLE_ID="com.filetransfereasy.desktop"
VERSION="${VERSION:-$(cat VERSION)}"
BINARY="file-transfer-easy"
DIST="dist"
FINAL_APP="$DIST/$APP_NAME.app"
ARCH="${ARCH:-universal}"

# Matching the SDK the toolchain actually targets keeps the linker quiet.
export MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-13.0}"

say() { printf '\033[36m▸\033[0m %s\n' "$1"; }

case "$ARCH" in universal|arm64|amd64) ;; *) echo "ARCH debe ser universal, arm64 o amd64" >&2; exit 1 ;; esac
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "VERSION debe usar el formato numérico X.Y.Z" >&2; exit 1
fi
if [[ ! "$MACOSX_DEPLOYMENT_TARGET" =~ ^[0-9]+\.[0-9]+$ ]]; then
  echo "MACOSX_DEPLOYMENT_TARGET debe usar el formato X.Y" >&2; exit 1
fi
for tool in go clang lipo iconutil hdiutil codesign plutil shasum xattr xcrun; do
  command -v "$tool" >/dev/null || { echo "Falta la herramienta: $tool" >&2; exit 1; }
done
xcrun --find clang >/dev/null
mkdir -p "$DIST"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/fte-build.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT
APP_DIR="$WORK_DIR/$APP_NAME.app"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"

# ---------------------------------------------------------------- the binary

say "Generando iconos…"
go run ./cmd/genicons >/dev/null

build_arch() {
  local arch="$1" out="$2"
  say "Compilando darwin/${arch}…"
  CGO_ENABLED=1 GOOS=darwin GOARCH="$arch" \
    CGO_CFLAGS="-mmacosx-version-min=$MACOSX_DEPLOYMENT_TARGET" \
    CGO_LDFLAGS="-mmacosx-version-min=$MACOSX_DEPLOYMENT_TARGET" \
    go build -tags production -trimpath \
      -ldflags "-s -w -X main.version=$VERSION" \
      -o "$out" .
}

TARGET="$APP_DIR/Contents/MacOS/$BINARY"

if [[ "$ARCH" == "universal" ]]; then
  build_arch arm64 "$WORK_DIR/$BINARY-arm64"
  build_arch amd64 "$WORK_DIR/$BINARY-amd64"
  say "Uniendo en un binario universal…"
  lipo -create -output "$TARGET" "$WORK_DIR/$BINARY-arm64" "$WORK_DIR/$BINARY-amd64"
  rm -f "$WORK_DIR/$BINARY-arm64" "$WORK_DIR/$BINARY-amd64"
else
  build_arch "$ARCH" "$TARGET"
fi

chmod +x "$TARGET"

# ------------------------------------------------------------------ the icon

say "Construyendo el icono del paquete…"
ICONSET="$WORK_DIR/icon.iconset"
mkdir -p "$ICONSET"
cp build/icons/iconset/icon_16.png   "$ICONSET/icon_16x16.png"
cp build/icons/iconset/icon_32.png   "$ICONSET/icon_16x16@2x.png"
cp build/icons/iconset/icon_32.png   "$ICONSET/icon_32x32.png"
cp build/icons/iconset/icon_64.png   "$ICONSET/icon_32x32@2x.png"
cp build/icons/iconset/icon_128.png  "$ICONSET/icon_128x128.png"
cp build/icons/iconset/icon_256.png  "$ICONSET/icon_128x128@2x.png"
cp build/icons/iconset/icon_256.png  "$ICONSET/icon_256x256.png"
cp build/icons/iconset/icon_512.png  "$ICONSET/icon_256x256@2x.png"
cp build/icons/iconset/icon_512.png  "$ICONSET/icon_512x512.png"
cp build/icons/iconset/icon_1024.png "$ICONSET/icon_512x512@2x.png"
iconutil -c icns "$ICONSET" -o "$APP_DIR/Contents/Resources/icon.icns"
rm -rf "$ICONSET"

# ----------------------------------------------------------------- the bundle

say "Escribiendo Info.plist…"
cat > "$APP_DIR/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleExecutable</key><string>$BINARY</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>$MACOSX_DEPLOYMENT_TARGET</string>
  <key>NSHighResolutionCapable</key><true/>
  <!-- Accepting every document type is what lets the Dock icon receive
       dropped files, which is how items get added while the window is hidden. -->
  <key>CFBundleDocumentTypes</key>
  <array>
    <dict>
      <key>CFBundleTypeName</key><string>Cualquier archivo</string>
      <key>CFBundleTypeRole</key><string>Viewer</string>
      <key>LSHandlerRank</key><string>None</string>
      <key>LSItemContentTypes</key>
      <array><string>public.item</string><string>public.folder</string></array>
    </dict>
  </array>
  <!-- The app talks to 127.0.0.1 over plain HTTP for its own window. -->
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
PLIST

# An ad-hoc signature stops Gatekeeper from killing the app outright on the
# machine that built it. A real distribution still needs a Developer ID.
# Extended attributes picked up during the build make codesign refuse the
# bundle outright, so they are stripped first.
say "Firmando de forma ad-hoc…"
xattr -cr "$APP_DIR"
plutil -lint "$APP_DIR/Contents/Info.plist"
codesign --force --sign - "$APP_DIR"
codesign --verify --deep --strict --verbose=2 "$APP_DIR"
if [[ "$ARCH" == "universal" ]]; then
  lipo "$TARGET" -verify_arch arm64
  lipo "$TARGET" -verify_arch x86_64
elif [[ "$ARCH" == "amd64" ]]; then
  lipo "$TARGET" -verify_arch x86_64
else
  lipo "$TARGET" -verify_arch arm64
fi

# -------------------------------------------------------------------- the dmg

say "Creando el .dmg…"
STAGING="$WORK_DIR/dmg"
mkdir -p "$STAGING"
cp -R "$APP_DIR" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
cat > "$STAGING/Instalación.txt" <<INSTALL
File Transfer Easy $VERSION

1. Arrastra File Transfer Easy a Aplicaciones.
2. Abre la app y añade tus archivos o carpetas.
3. Espera a que el enlace esté listo, cópialo y envíalo.

Mantén tu equipo encendido y la app abierta mientras compartes.
Cerrar la ventana mantiene la app en la barra de menús. Usa Salir para detenerla.

Este paquete de prueba tiene firma ad hoc, sin notarización de Apple.
Gatekeeper puede bloquearlo en otros equipos. La distribución pública requiere
Developer ID y notarización; no se modifican las protecciones del sistema.

La primera compartición descarga cloudflared de la fuente oficial de Cloudflare.
INSTALL

DMG="$DIST/FileTransferEasy-$VERSION.dmg"
hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$STAGING" \
  -ov -format UDZO \
  "$DMG" >/dev/null
hdiutil verify "$DMG" >/dev/null
rm -rf "$FINAL_APP"
mv "$APP_DIR" "$FINAL_APP"
xattr -cr "$FINAL_APP"
codesign --verify --deep --strict --verbose=2 "$FINAL_APP"
(cd "$DIST" && shasum -a 256 "$(basename "$DMG")" > "$(basename "$DMG").sha256")

say "Listo:"
echo "    $FINAL_APP"
echo "    $DMG"
echo "    $DMG.sha256"
