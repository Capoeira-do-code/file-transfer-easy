#!/usr/bin/env python3
"""Package an ELF executable without requiring dpkg on the build host."""
import gzip
import hashlib
import io
import re
import struct
import sys
import tarfile
from pathlib import Path

binary, version, arch = sys.argv[1:]
if arch not in ("amd64", "arm64") or not re.fullmatch(r"\d+\.\d+\.\d+", version):
    raise SystemExit("Versión o arquitectura no válida")
payload = Path(binary).read_bytes()
if payload[:5] != b"\x7fELF\x02" or payload[5] != 1 or struct.unpack_from("<H", payload, 18)[0] != {"amd64": 62, "arm64": 183}[arch]:
    raise SystemExit("El ejecutable no es ELF de 64 bits para la arquitectura solicitada")

desktop = b"""[Desktop Entry]
Type=Application
Name=File Transfer Easy
Comment=Compartir archivos mediante un enlace
Exec=file-transfer-easy %F
Icon=com.filetransfereasy.desktop
Terminal=false
Categories=Network;FileTransfer;
MimeType=application/octet-stream;inode/directory;
StartupWMClass=file_transfer_easy
StartupNotify=true
"""
root = Path(__file__).resolve().parent.parent
icon = (root / "build/icons/iconset/icon_256.png").read_bytes()
readme = """File Transfer Easy

Instalación .deb (Debian 12+ / Ubuntu 24.04+):
  sudo apt install ./FileTransferEasy-VERSION-linux-ARCH.deb

Instalación sin administrador del .tar.gz:
  Extrae el archivo y ejecuta ./install.sh.
  Instala previamente GTK3, WebKitGTK 4.1, xdg-utils y Python 3.

Añade archivos o carpetas en la ventana. También puedes abrirlos con la app
desde el gestor de archivos. La bandeja depende del entorno de escritorio;
si no aparece, abre otra vez la app desde el lanzador para recuperar la ventana.

El enlace se crea al añadir contenido. Mantén el equipo encendido y la app
abierta durante las descargas. La primera sesión descarga cloudflared.
""".replace("VERSION", version).replace("ARCH", arch).encode()

def archive(files):
    result = io.BytesIO()
    with gzip.GzipFile(fileobj=result, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as tar:
            for name, (data, mode) in files.items():
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), mode
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                tar.addfile(info, io.BytesIO(data))
    return result.getvalue()

data_files = {
    "usr/bin/file-transfer-easy": (payload, 0o755),
    "usr/share/applications/org.wails.file_transfer_easy.desktop": (desktop, 0o644),
    "usr/share/icons/hicolor/256x256/apps/com.filetransfereasy.desktop.png": (icon, 0o644),
    "usr/share/doc/file-transfer-easy/README.txt": (readme, 0o644),
}
control = f"""Package: file-transfer-easy
Version: {version}
Architecture: {arch}
Maintainer: File Transfer Easy <noreply@filetransfereasy.local>
Section: net
Priority: optional
Depends: libc6 (>= 2.36), libgtk-3-0, libwebkit2gtk-4.1-0, libx11-6, xdg-utils
Installed-Size: {sum(len(v[0]) for v in data_files.values()) // 1024 + 1}
Description: Compartir archivos mediante enlaces de descarga
 Aplicación de escritorio para compartir archivos y carpetas desde el equipo.
""".encode()

dist = root / "dist"
dist.mkdir(exist_ok=True)
prefix = f"FileTransferEasy-{version}-linux-{arch}"
deb = bytearray(b"!<arch>\n")
for name, data in [("debian-binary", b"2.0\n"), ("control.tar.gz", archive({"control": (control, 0o644)})), ("data.tar.gz", archive(data_files))]:
    header = f"{name + '/':<16}{0:<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}`\n".encode()
    deb.extend(header)
    deb.extend(data)
    if len(data) % 2:
        deb.extend(b"\n")

install = b'''#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
command -v python3 >/dev/null || { printf '%s\\n' 'Falta Python 3'; exit 1; }
base="${XDG_DATA_HOME:-$HOME/.local/share}"
mkdir -p "$HOME/.local/bin" "$base/applications" "$base/icons/hicolor/256x256/apps"
install -m 755 file-transfer-easy "$HOME/.local/bin/file-transfer-easy"
install -m 644 icon.png "$base/icons/hicolor/256x256/apps/com.filetransfereasy.desktop.png"
python3 - "$HOME/.local/bin/file-transfer-easy" "$base/applications/org.wails.file_transfer_easy.desktop" <<'PY'
import pathlib, sys
slash = chr(92)
executable = sys.argv[1].replace(slash, slash * 4).replace('"', slash * 2 + '"').replace('`', slash * 2 + '`').replace('$', slash * 2 + '$').replace('%', '%%')
text = pathlib.Path("org.wails.file_transfer_easy.desktop").read_text()
text = text.replace('Exec=file-transfer-easy %F', 'Exec="' + executable + '" %F')
pathlib.Path(sys.argv[2]).write_text(text)
PY
if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database "$base/applications"; fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -f -t "$base/icons/hicolor" >/dev/null 2>&1 || true; fi
printf '%s\\n' "Instalado. Abre File Transfer Easy desde el lanzador."
'''
outputs = {
    prefix + ".deb": bytes(deb),
    prefix + ".tar.gz": archive({
        prefix + "/file-transfer-easy": (payload, 0o755),
        prefix + "/icon.png": (icon, 0o644),
        prefix + "/org.wails.file_transfer_easy.desktop": (desktop, 0o644),
        prefix + "/install.sh": (install, 0o755),
        prefix + "/README.txt": (readme, 0o644),
    }),
}
for name, data in outputs.items():
    (dist / name).write_bytes(data)
    (dist / (name + ".sha256")).write_text(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    print(dist / name)
