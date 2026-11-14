#!/usr/bin/env python3
"""Cross-build Linux from Windows/macOS/Linux with Zig and Debian SDK packages.

Downloaded tools stay in a build cache; no Linux library is installed on the host.
Requires Go and Python 3. Unix hosts also need pkg-config.
Use --prepare-only to download tools without building application sources.
"""
import argparse
import concurrent.futures
import hashlib
import io
import json
import lzma
import os
import platform
import posixpath
import re
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--prepare-only", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parent.parent
windows = platform.system() == "Windows"
host_os = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}.get(platform.system())
if not host_os:
    raise SystemExit("Host no compatible: " + platform.system())
default_cache = (Path(os.environ["LOCALAPPDATA"]) / "FileTransferEasyBuild" if windows
                 else Path.home() / ("Library/Caches/FileTransferEasyBuild" if host_os == "macos" else ".cache/FileTransferEasyBuild"))
cache = Path(os.environ.get("FTE_CROSS_CACHE", default_cache)).resolve()
cache.mkdir(parents=True, exist_ok=True)

def fetch(url, path, digest=None):
    if path.exists() and (not digest or hashlib.sha256(path.read_bytes()).hexdigest() == digest):
        return path.read_bytes()
    if path.parent != cache / "deb":
        print("Descargando " + path.name, flush=True)
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    if digest and hashlib.sha256(data).hexdigest() != digest:
        raise RuntimeError(f"Checksum incorrecto: {url}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data

index = json.loads(fetch("https://ziglang.org/download/index.json", cache / "zig-index.json"))
host = "aarch64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
zig_asset = index["0.15.2"][host + "-" + host_os]
zig_name = Path(zig_asset["tarball"]).name
zig_archive = fetch(zig_asset["tarball"], cache / zig_name, zig_asset["shasum"])
zig_dir = cache / zig_name.removesuffix(".tar.xz").removesuffix(".zip")
if not zig_dir.exists():
    if windows:
        with zipfile.ZipFile(io.BytesIO(zig_archive)) as archive:
            archive.extractall(cache)
    else:
        with tarfile.open(fileobj=io.BytesIO(zig_archive), mode="r:xz") as archive:
            archive.extractall(cache, filter="data")
zig = zig_dir / ("zig.exe" if windows else "zig")

pkg_config = os.environ.get("PKG_CONFIG") or shutil.which("pkg-config") or shutil.which("pkgconf")
if not pkg_config and windows:
    # Administrative extraction only: no software is registered/installed.
    # The digest is published with this official GitHub release asset.
    pkg_version = "3.0.10"
    pkg_name = f"pkgconf-x64-{pkg_version}.msi"
    pkg_msi = cache / pkg_name
    fetch(f"https://github.com/pkgconf/pkgconf/releases/download/pkgconf-{pkg_version}/{pkg_name}", pkg_msi,
          "28cc9e44473a3ef277260f3dac20f58e2a667760393bd47dc309b6426e9bd727")
    pkg_dir = cache / ("pkgconf-" + pkg_version)
    found = list(pkg_dir.rglob("pkgconf.exe")) if pkg_dir.exists() else []
    if not found:
        subprocess.run(["msiexec.exe", "/a", str(pkg_msi), "/qn", f"TARGETDIR={pkg_dir}"],
                       check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        found = list(pkg_dir.rglob("pkgconf.exe"))
    if not found:
        raise RuntimeError("El paquete oficial pkgconf no contiene pkgconf.exe")
    pkg_config = str(found[0])
if not pkg_config:
    raise SystemExit("Falta pkg-config/pkgconf en el host")


def extract_sdk(tar, sysroot, links):
    for entry in tar:
        relative = PurePosixPath(entry.name.lstrip("/"))
        if ".." in relative.parts:
            raise RuntimeError("Ruta de paquete no segura: " + entry.name)
        destination = sysroot.joinpath(*relative.parts)
        if windows and (entry.issym() or entry.islnk()):
            target = (entry.linkname.lstrip("/") if entry.islnk() or entry.linkname.startswith("/")
                      else posixpath.normpath(str(relative.parent / entry.linkname)))
            target_path = PurePosixPath(target)
            if ".." in target_path.parts:
                raise RuntimeError("Enlace de paquete no seguro: " + entry.linkname)
            links[destination] = sysroot.joinpath(*target_path.parts)
        else:
            if entry.issym() and entry.linkname.startswith("/"):
                entry.linkname = os.path.relpath(sysroot / entry.linkname.lstrip("/"), destination.parent)
            tar.extract(entry, sysroot, filter="data")


def materialise_links(links):
    # SDK inputs can use regular copies on Windows without symlink privileges.
    pending = dict(links)
    while pending:
        completed = []
        for destination, target in pending.items():
            if not target.exists():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if target.is_dir():
                shutil.copytree(target, destination, dirs_exist_ok=True)
            else:
                shutil.copyfile(target, destination)
            completed.append(destination)
        if not completed:
            print(f"SDK: {len(pending)} enlaces a archivos no incluidos", flush=True)
            break
        for destination in completed:
            del pending[destination]

def prepare(arch):
    raw = fetch(f"https://deb.debian.org/debian/dists/bookworm/main/binary-{arch}/Packages.xz", cache / f"Packages-{arch}.xz")
    packages = {}
    for paragraph in lzma.decompress(raw).decode().split("\n\n"):
        fields = {}
        for line in paragraph.splitlines():
            if line and line[0] != " " and ": " in line:
                key, value = line.split(": ", 1)
                fields[key] = value
        if "Package" in fields:
            packages[fields["Package"]] = fields
    providers = {}
    for name, fields in packages.items():
        for provided in fields.get("Provides", "").split(","):
            match = re.match(r"\s*([\w+.-]+)", provided)
            if match:
                providers.setdefault(match[1], name)
    needed = set()
    def visit(name):
        if name in needed or name not in packages:
            return
        needed.add(name)
        entry = packages[name]
        for dependency in (entry.get("Depends", "") + "," + entry.get("Pre-Depends", "")).split(","):
            alternatives = [re.match(r"\s*([\w+.-]+)", part) for part in dependency.split("|")]
            candidate = next((m[1] if m[1] in packages else providers.get(m[1], "") for m in alternatives
                if m and (m[1] in packages or m[1] in providers)), "")
            if candidate.startswith("lib") or candidate.endswith("-dev") or candidate == "wayland-protocols":
                visit(candidate)
    for name in ("libc6-dev", "libgtk-3-dev", "libwebkit2gtk-4.1-dev", "libx11-dev", "shared-mime-info"):
        if name not in packages:
            raise RuntimeError(f"Paquete no encontrado: {name}")
        visit(name)
    sysroot = cache / f"sysroot-{arch}"
    stamp = sysroot / ".complete"
    sdk_hash = hashlib.sha256(("copy-links-v1\n" + "\n".join(packages[name]["SHA256"] for name in sorted(needed))).encode()).hexdigest()
    if stamp.exists() and stamp.read_text() == sdk_hash:
        return sysroot
    sysroot.mkdir(exist_ok=True)
    print(f"SDK {arch}: {len(needed)} paquetes de Debian", flush=True)
    def download(name):
        p = packages[name]
        data = fetch("https://deb.debian.org/debian/" + p["Filename"], cache / "deb" / Path(p["Filename"]).name, p["SHA256"])
        return name, data
    links = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for name, data in pool.map(download, sorted(needed)):
            offset = 8
            while offset < len(data):
                header = data[offset:offset+60]
                member = header[:16].decode().strip().rstrip("/")
                size = int(header[48:58])
                body = data[offset+60:offset+60+size]
                offset += 60 + size + size % 2
                if member.startswith("data.tar"):
                    with tarfile.open(fileobj=io.BytesIO(body), mode="r:*") as tar:
                        extract_sdk(tar, sysroot, links)
                    break
    if windows:
        materialise_links(links)
    stamp.write_text(sdk_hash)
    return sysroot

requested = os.environ.get("ARCH", "all")
arches = ["amd64", "arm64"] if requested == "all" else [requested]
if any(arch not in ("amd64", "arm64") for arch in arches):
    raise SystemExit("ARCH debe ser all, amd64 o arm64")
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    sysroots = dict(zip(arches, pool.map(prepare, arches)))
print("Zig: " + str(zig), flush=True)
print("pkg-config: " + pkg_config, flush=True)
if args.prepare_only:
    raise SystemExit(0)

version = os.environ.get("VERSION", (root / "VERSION").read_text().strip())
if not re.fullmatch(r"\d+\.\d+\.\d+", version):
    raise SystemExit("VERSION debe usar X.Y.Z")
subprocess.run(["go", "run", "./cmd/genicons"], cwd=root, check=True)
for arch, sysroot in sysroots.items():
    triplet = {"amd64": "x86_64-linux-gnu", "arm64": "aarch64-linux-gnu"}[arch]
    # Zig supplies glibc 2.36; --sysroot would prefix library paths twice.
    compiler = f'"{zig.as_posix()}" cc -target {triplet}.2.36'
    env = os.environ.copy()
    env.update(ARCH=arch, CC=compiler, CGO_ENABLED="1", GOOS="linux", GOARCH=arch,
        PKG_CONFIG=pkg_config, PKG_CONFIG_DONT_DEFINE_PREFIX="1", PKG_CONFIG_SYSROOT_DIR=sysroot.as_posix(),
        PKG_CONFIG_LIBDIR=os.pathsep.join(f"{sysroot.as_posix()}/{directory}" for directory in
            (f"usr/lib/{triplet}/pkgconfig", "usr/lib/pkgconfig", "usr/share/pkgconfig")),
        CGO_LDFLAGS=f"-L{sysroot.as_posix()}/usr/lib/{triplet} -L{sysroot.as_posix()}/lib/{triplet}")
    print(f"Compilando Linux/{arch}", flush=True)
    binary = cache / f"file-transfer-easy-{version}-{arch}"
    subprocess.run(["go", "build", "-tags", "gtk3,production", "-trimpath",
        "-ldflags", f"-s -w -X main.version={version}", "-o", str(binary), "."], cwd=root, env=env, check=True)
    subprocess.run([os.sys.executable, "scripts/package-linux.py", str(binary), version, arch], cwd=root, check=True)
