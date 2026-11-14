#!/usr/bin/env python3
"""Archive the current desktop sources, including uncommitted changes, for builds."""
import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
repository = root.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--version", default=(root / "VERSION").read_text().strip())
parser.add_argument("--output", type=Path)
parser.add_argument("--check-only", action="store_true")
args = parser.parse_args()
if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
    raise SystemExit("Version must use X.Y.Z")

# An explicit source allowlist keeps caches, credentials, user settings and old
# executable artifacts out of an archive made from a dirty working directory.
files = set()
for name in ("frontend", "public", "internal", "cmd", "scripts", "installer", "winres", "build/icons"):
    files.update(path for path in (root / name).rglob("*")
                 if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
for pattern in ("*.go", "*.h", "*.m", "*.md", "go.mod", "go.sum", "VERSION", ".gitignore"):
    files.update(root.glob(pattern))
files.add(repository / ".github/workflows/build.yml")
if (repository / ".gitattributes").exists():
    files.add(repository / ".gitattributes")
paths = sorted(files, key=lambda path: path.relative_to(repository).as_posix())
for required in (root / "main.go", root / "go.mod", root / "frontend/index.html", root / "build/icons/icon.ico"):
    if required not in files:
        raise SystemExit("Missing source input: " + str(required))
contents = {path.relative_to(repository).as_posix(): path.read_bytes() for path in paths}
for name, data in contents.items():
    if name.endswith(".sh"):
        contents[name] = data.replace(b"\r\n", b"\n")
manifest = {
    "version": args.version,
    "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip(),
    "description": "Desktop build snapshot of working-tree files; no remote mutation performed",
    "shell_line_endings": "LF for execution on macOS/Linux",
    "files": {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()},
}
if args.check_only:
    print(json.dumps({"version": args.version, "file_count": len(contents), "bytes": sum(map(len, contents.values()))}))
    raise SystemExit(0)

output = (args.output or root / "dist" / f"FileTransferEasy-{args.version}-source.zip").resolve()
output.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    contents["BUILD-SNAPSHOT.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    for name, data in sorted(contents.items()):
        entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
        entry.compress_type = zipfile.ZIP_DEFLATED
        entry.create_system = 3
        entry.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
        archive.writestr(entry, data)
digest = hashlib.sha256(output.read_bytes()).hexdigest()
Path(str(output) + ".sha256").write_text(f"{digest}  {output.name}\n")
with zipfile.ZipFile(output) as archive:
    assert archive.testzip() is None
    saved = json.loads(archive.read("BUILD-SNAPSHOT.json"))
    for name, expected in saved["files"].items():
        assert hashlib.sha256(archive.read(name)).hexdigest() == expected
print(output)
print(f"{len(paths)} source files; SHA-256 {digest}")
