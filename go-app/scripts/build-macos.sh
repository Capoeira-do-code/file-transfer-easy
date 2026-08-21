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
VERSION="${VERSION:-1.0.0}"
BINARY="file-transfer-easy"
DIST="dist"
APP_DIR="$DIST/$APP_NAME.app"

# Matching the SDK the toolchain actually targets keeps the linker quiet.
export MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-13.0}"

say() { printf '\033[36m▸\033[0m %s\n' "$1"; }

rm -rf "$DIST"
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
    go build -trimpath \
      -ldflags "-s -w -X main.version=$VERSION" \
      -o "$out" . 2> >(grep -v 'ld: warning' >&2 || true)
}

TARGET="$APP_DIR/Contents/MacOS/$BINARY"

if [[ "${ARCH:-universal}" == "universal" ]]; then
  build_arch arm64 "$DIST/$BINARY-arm64"
  build_arch amd64 "$DIST/$BINARY-amd64"
  say "Uniendo en un binario universal…"
  lipo -create -output "$TARGET" "$DIST/$BINARY-arm64" "$DIST/$BINARY-amd64"
  rm -f "$DIST/$BINARY-arm64" "$DIST/$BINARY-amd64"
else
  build_arch "$ARCH" "$TARGET"
fi

chmod +x "$TARGET"

# ------------------------------------------------------------------ the icon

say "Construyendo el icono del paquete…"
ICONSET="$DIST/icon.iconset"
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
xattr -cr "$APP_DIR" 2>/dev/null || true
codesign --force --deep --sign - "$APP_DIR" || \
  say "No se pudo firmar (se puede abrir igualmente con clic derecho › Abrir)"

# -------------------------------------------------------------------- the dmg

say "Creando el .dmg…"
STAGING="$DIST/dmg"
mkdir -p "$STAGING"
cp -R "$APP_DIR" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

DMG="$DIST/FileTransferEasy-$VERSION.dmg"
hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$STAGING" \
  -ov -format UDZO \
  "$DMG" >/dev/null
rm -rf "$STAGING"

say "Listo:"
echo "    $APP_DIR"
echo "    $DMG"
