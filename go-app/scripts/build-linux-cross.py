#!/usr/bin/env python3
"""Cross-build Linux from macOS with Zig and official Debian SDK packages.

Downloaded tools stay in a build cache; no Linux library is installed on macOS.
Requires Go, Python 3, pkg-config and tar. Run from go-app.
"""
import concurrent.futures
import hashlib
import io
import json
import lzma
import os
import platform
import re
import shlex
import subprocess
import tarfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
cache = Path(os.environ.get("FTE_CROSS_CACHE", Path.home() / "Library/Caches/FileTransferEasyBuild"))
cache.mkdir(parents=True, exist_ok=True)

def fetch(url, path, digest=None):
    if path.exists() and (not digest or hashlib.sha256(path.read_bytes()).hexdigest() == digest):
        return path.read_bytes()
    data = subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location", "--retry", "3", url],
        stdout=subprocess.PIPE, check=True).stdout
    if digest and hashlib.sha256(data).hexdigest() != digest:
        raise RuntimeError(f"Checksum incorrecto: {url}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data

index = json.loads(fetch("https://ziglang.org/download/index.json", cache / "zig-index.json"))
host = "aarch64" if platform.machine() == "arm64" else "x86_64"
zig_asset = index["0.15.2"][host + "-macos"]
zig_archive = fetch(zig_asset["tarball"], cache / "zig.tar.xz", zig_asset["shasum"])
zig_dir = cache / Path(zig_asset["tarball"]).name.removesuffix(".tar.xz")
if not zig_dir.exists():
    with tarfile.open(fileobj=io.BytesIO(zig_archive), mode="r:xz") as tar:
        tar.extractall(cache, filter="data")
zig = zig_dir / "zig"

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
    sdk_hash = hashlib.sha256("\n".join(packages[name]["SHA256"] for name in sorted(needed)).encode()).hexdigest()
    if stamp.exists() and stamp.read_text() == sdk_hash:
        return sysroot
    sysroot.mkdir(exist_ok=True)
    print(f"SDK {arch}: {len(needed)} paquetes de Debian", flush=True)
    def download(name):
        p = packages[name]
        data = fetch("https://deb.debian.org/debian/" + p["Filename"], cache / "deb" / Path(p["Filename"]).name, p["SHA256"])
        return name, data
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
                        for entry in tar:
                            destination = sysroot / entry.name.lstrip("/")
                            if entry.issym() and entry.linkname.startswith("/"):
                                entry.linkname = os.path.relpath(sysroot / entry.linkname.lstrip("/"), destination.parent)
                            tar.extract(entry, sysroot, filter="data")
                    break
    stamp.write_text(sdk_hash)
    return sysroot

requested = os.environ.get("ARCH", "all")
arches = ["amd64", "arm64"] if requested == "all" else [requested]
if any(arch not in ("amd64", "arm64") for arch in arches):
    raise SystemExit("ARCH debe ser all, amd64 o arm64")
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    sysroots = dict(zip(arches, pool.map(prepare, arches)))
for arch, sysroot in sysroots.items():
    triplet = {"amd64": "x86_64-linux-gnu", "arm64": "aarch64-linux-gnu"}[arch]
    wrapper = cache / f"cc-{arch}"
    # pkg-config supplies absolute SDK include/library paths. Zig provides the
    # glibc 2.36 runtime itself; --sysroot would prefix those library paths twice.
    wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(str(zig)) + " cc -target " + triplet + '.2.36 "$@"\n')
    wrapper.chmod(0o755)
    env = os.environ.copy()
    env.update(ARCH=arch, CC=str(wrapper), PKG_CONFIG_SYSROOT_DIR=str(sysroot),
        PKG_CONFIG_LIBDIR=f"{sysroot}/usr/lib/{triplet}/pkgconfig:{sysroot}/usr/lib/pkgconfig:{sysroot}/usr/share/pkgconfig",
        CGO_LDFLAGS=f"-L{sysroot}/usr/lib/{triplet} -L{sysroot}/lib/{triplet}")
    print(f"Compilando Linux/{arch}", flush=True)
    subprocess.run(["bash", "scripts/build-linux.sh"], cwd=root, env=env, check=True)
