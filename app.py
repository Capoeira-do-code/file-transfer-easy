from __future__ import annotations

import contextlib
import csv
import hashlib
import hmac
import importlib
import io
import mimetypes
import os
import queue
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote
from urllib.request import urlretrieve

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_NAME = "File Transfer Easy"
APP_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "FileTransferEasy"
DB_PATH = APP_DIR / "file_transfer_easy.db"
LOCAL_BIN_DIR = APP_DIR / "bin"
DEFAULT_UPLOAD_DIR = Path.home() / "Downloads" / "File Transfer Easy Uploads"
DEFAULT_PORT_CANDIDATES = [80, 8080, 8000, 5000]
TAILSCALE_PUBLIC_PORTS = ["443", "8443", "10000"]
REQUIRED_MODULES = {"flask": "Flask", "waitress": "waitress"}
INSTALL_CLOUDFLARED_COMMAND = (
    "winget install --id Cloudflare.cloudflared "
    "--accept-package-agreements --accept-source-agreements"
)
CLOUDFLARED_WINDOWS_AMD64_URL = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-windows-amd64.exe"
)
CHUNK_SIZE = 256 * 1024

Flask = None
Response = None
abort = None
jsonify = None
redirect = None
render_template_string = None
request = None
session = None
url_for = None
create_server = None


def import_web_dependencies() -> bool:
    global Flask, Response, abort, jsonify, redirect, render_template_string
    global request, session, url_for, create_server
    try:
        flask = importlib.import_module("flask")
        waitress_server = importlib.import_module("waitress.server")
    except ImportError:
        return False
    Flask = flask.Flask
    Response = flask.Response
    abort = flask.abort
    jsonify = flask.jsonify
    redirect = flask.redirect
    render_template_string = flask.render_template_string
    request = flask.request
    session = flask.session
    url_for = flask.url_for
    create_server = waitress_server.create_server
    return True


import_web_dependencies()


def missing_runtime_modules() -> list[str]:
    return [label for module, label in REQUIRED_MODULES.items() if importlib.util.find_spec(module) is None]


def install_python_dependencies(log: Callable[[str], None] | None = None) -> None:
    requirements = Path(__file__).resolve().parent / "requirements.txt"
    command = [sys.executable, "-m", "pip", "install", "-r", str(requirements)]
    if log:
        log("Instalando dependencias Python faltantes...")
        log(" ".join(command))
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if log and completed.stdout:
        for line in completed.stdout.splitlines():
            log(line)
    if completed.returncode != 0:
        raise RuntimeError("No se pudieron instalar las dependencias Python.")
    importlib.invalidate_caches()
    if not import_web_dependencies():
        raise RuntimeError("Las dependencias se instalaron, pero no se pudieron importar.")


def run_dependency_bootstrap_if_needed() -> bool:
    missing = missing_runtime_modules()
    if not missing:
        return import_web_dependencies()

    root = tk.Tk()
    root.title(f"{APP_NAME} - instalacion")
    root.geometry("620x360")
    root.configure(bg="#eef3f6")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Preparando File Transfer Easy", font=("Segoe UI", 16, "bold")).pack(anchor="w")
    ttk.Label(
        frame,
        text="Faltan dependencias. La app las instalara automaticamente y se abrira despues.",
        wraplength=560,
    ).pack(anchor="w", pady=(8, 12))
    output = tk.Text(frame, height=12, bg="#17212b", fg="#d8f3ea", relief="flat", wrap="word")
    output.pack(fill="both", expand=True)
    output.configure(state="disabled")

    done = {"ok": False}

    def log(message: str) -> None:
        output.configure(state="normal")
        output.insert("end", message + "\n")
        output.configure(state="disabled")
        output.see("end")
        root.update_idletasks()

    def worker() -> None:
        try:
            install_python_dependencies(log)
            done["ok"] = True
            log("Listo.")
        except Exception as exc:
            log(str(exc))
            done["ok"] = False
        finally:
            root.after(900, root.destroy)

    threading.Thread(target=worker, daemon=True).start()
    root.mainloop()
    return done["ok"]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def now_text() -> str:
    return datetime.now().strftime("%H:%M:%S")


def format_bytes(size: int) -> str:
    value = float(max(size, 0))
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def format_mtime(timestamp: float) -> str:
    with contextlib.suppress(Exception):
        return datetime.fromtimestamp(timestamp).strftime("%d/%m/%Y %H:%M")
    return "-"


def sanitize_filename(name: str) -> str:
    filename = Path(name or "archivo").name
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename)
    filename = filename.strip().strip(".")
    filename = re.sub(r"\s+", " ", filename)
    return filename or "archivo"


def unique_path(folder: Path, filename: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    safe = sanitize_filename(filename)
    candidate = folder / safe
    if not candidate.exists():
        return candidate
    stem = candidate.stem or "archivo"
    suffix = candidate.suffix
    counter = 2
    while True:
        next_candidate = folder / f"{stem} ({counter}){suffix}"
        if not next_candidate.exists():
            return next_candidate
        counter += 1


def is_port_available(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("0.0.0.0", 0))
        return int(sock.getsockname()[1])


def choose_port(raw_port: str, manual: bool) -> tuple[int | None, str | None]:
    raw_port = raw_port.strip()
    if manual:
        try:
            port = int(raw_port)
        except ValueError:
            return None, "El puerto personalizado debe ser un numero."
        if port < 1 or port > 65535:
            return None, "El puerto debe estar entre 1 y 65535."
        if not is_port_available(port):
            return None, f"El puerto {port} esta ocupado o requiere permisos."
        return port, None

    candidates: list[int] = []
    if raw_port:
        with contextlib.suppress(ValueError):
            candidates.append(int(raw_port))
    candidates.extend(DEFAULT_PORT_CANDIDATES)
    seen: set[int] = set()
    for port in candidates:
        if port in seen or port < 1 or port > 65535:
            continue
        seen.add(port)
        if is_port_available(port):
            return port, None
    return get_free_port(), None


def get_lan_ip() -> str:
    with contextlib.suppress(Exception):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
    with contextlib.suppress(Exception):
        return socket.gethostbyname(socket.gethostname())
    return "127.0.0.1"


def creation_flags() -> int:
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def is_shareable_tunnel_url(kind: str, url: str) -> bool:
    if kind == "cloudflare":
        return "trycloudflare.com" in url
    if kind == "tailscale":
        return "127.0.0.1" not in url and "localhost" not in url
    return True


def make_password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), 160_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return True
    try:
        algorithm, salt, digest = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        160_000,
    ).hex()
    return hmac.compare_digest(candidate, digest)


def get_client_ip(req) -> tuple[str, str]:
    for header, label in [
        ("CF-Connecting-IP", "cloudflare"),
        ("X-Forwarded-For", "proxy"),
        ("X-Real-IP", "proxy"),
    ]:
        value = req.headers.get(header)
        if value:
            return value.split(",")[0].strip(), label
    return req.remote_addr or "desconocida", "directa"


def content_disposition(filename: str) -> str:
    safe = sanitize_filename(filename)
    return f"attachment; filename=\"{safe}\"; filename*=UTF-8''{quote(safe)}"


def find_cloudflared() -> str | None:
    path = shutil.which("cloudflared")
    if path:
        return path
    candidates = [
        Path(__file__).resolve().parent / "cloudflared.exe",
        Path(__file__).resolve().parent / "cloudflared",
        LOCAL_BIN_DIR / "cloudflared.exe",
        LOCAL_BIN_DIR / "cloudflared",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def install_cloudflared(log: Callable[[str], None] | None = None) -> str:
    existing = find_cloudflared()
    if existing:
        return existing
    LOCAL_BIN_DIR.mkdir(parents=True, exist_ok=True)
    target = LOCAL_BIN_DIR / ("cloudflared.exe" if os.name == "nt" else "cloudflared")
    if os.name == "nt":
        try:
            if log:
                log("Descargando cloudflared desde GitHub oficial de Cloudflare...")
            urlretrieve(CLOUDFLARED_WINDOWS_AMD64_URL, target)
            return str(target)
        except Exception as exc:
            if log:
                log(f"No se pudo descargar cloudflared: {exc}")
    winget = shutil.which("winget")
    if winget:
        command = [
            winget,
            "install",
            "--id",
            "Cloudflare.cloudflared",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ]
        if log:
            log("Instalando cloudflared con winget...")
            log(" ".join(command))
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags(),
        )
        if log and completed.stdout:
            for line in completed.stdout.splitlines():
                log(line)
        found = find_cloudflared()
        if completed.returncode == 0 and found:
            return found
    raise RuntimeError(
        "Cloudflared no esta instalado y no se pudo instalar automaticamente. "
        f"Ejecuta: {INSTALL_CLOUDFLARED_COMMAND}"
    )


@dataclass
class SharedFile:
    id: str
    display_name: str
    path: str
    size: int
    mtime: float
    source: str
    password_hash: str | None = None

    @classmethod
    def from_path(cls, path: Path, source: str = "Host", password: str = "") -> "SharedFile":
        stat = path.stat()
        return cls(
            id=uuid.uuid4().hex,
            display_name=path.name,
            path=str(path.resolve()),
            size=stat.st_size,
            mtime=stat.st_mtime,
            source=source,
            password_hash=make_password_hash(password) if password else None,
        )

    @property
    def protected(self) -> bool:
        return bool(self.password_hash)


class ShareState:
    def __init__(self) -> None:
        self.token = secrets.token_urlsafe(18)
        self._upload_enabled = False
        self._upload_dir = str(DEFAULT_UPLOAD_DIR)
        self._shared_folder = ""
        self._include_subfolders = False
        self._global_password_hash: str | None = None
        self._files: dict[str, SharedFile] = {}
        self._lock = threading.RLock()

    def add_paths(self, paths: Iterable[str], source: str = "Host", password: str = "") -> tuple[int, list[str]]:
        added = 0
        errors: list[str] = []
        with self._lock:
            existing = {Path(item.path).resolve() for item in self._files.values()}
            for raw_path in paths:
                path = Path(raw_path)
                try:
                    resolved = path.resolve()
                    if not resolved.is_file():
                        errors.append(f"{path.name}: no es un archivo.")
                        continue
                    if resolved in existing:
                        errors.append(f"{path.name}: ya esta en la lista.")
                        continue
                    item = SharedFile.from_path(resolved, source=source, password=password)
                    self._files[item.id] = item
                    existing.add(resolved)
                    added += 1
                except OSError as exc:
                    errors.append(f"{path.name}: {exc}")
        return added, errors

    def add_folder(self, folder: str, include_subfolders: bool = False) -> tuple[int, list[str]]:
        paths = list(iter_folder_files(Path(folder), include_subfolders))
        return self.add_paths([str(path) for path in paths], source="Carpeta")

    def configure_shared_folder(self, folder: str, include_subfolders: bool) -> None:
        with self._lock:
            self._shared_folder = folder.strip()
            self._include_subfolders = bool(include_subfolders)

    def refresh_shared_folder(self) -> tuple[int, list[str]]:
        with self._lock:
            folder = self._shared_folder
            include = self._include_subfolders
        if not folder:
            return 0, ["No hay carpeta compartida configurada."]
        return self.add_folder(folder, include)

    def add_uploaded_file(self, path: Path) -> SharedFile:
        item = SharedFile.from_path(path, source="Subido")
        with self._lock:
            self._files[item.id] = item
        return item

    def remove(self, file_ids: Iterable[str]) -> int:
        removed = 0
        with self._lock:
            for file_id in file_ids:
                if self._files.pop(file_id, None):
                    removed += 1
        return removed

    def clear(self) -> None:
        with self._lock:
            self._files.clear()

    def get(self, file_id: str) -> SharedFile | None:
        with self._lock:
            return self._files.get(file_id)

    def snapshot(self) -> list[SharedFile]:
        with self._lock:
            return list(self._files.values())

    def has_files(self) -> bool:
        with self._lock:
            return bool(self._files)

    def configure_uploads(self, enabled: bool, upload_dir: str) -> None:
        with self._lock:
            self._upload_enabled = bool(enabled)
            self._upload_dir = upload_dir.strip() or str(DEFAULT_UPLOAD_DIR)

    def uploads_enabled(self) -> bool:
        with self._lock:
            return self._upload_enabled

    def upload_folder(self) -> Path:
        with self._lock:
            return Path(self._upload_dir).expanduser()

    def set_global_password(self, password: str) -> None:
        with self._lock:
            self._global_password_hash = make_password_hash(password) if password else None

    def global_password_enabled(self) -> bool:
        with self._lock:
            return bool(self._global_password_hash)

    def verify_global_password(self, password: str) -> bool:
        with self._lock:
            return verify_password(password, self._global_password_hash)

    def set_file_passwords(self, file_ids: Iterable[str], password: str) -> int:
        new_hash = make_password_hash(password) if password else None
        updated = 0
        with self._lock:
            for file_id in file_ids:
                item = self._files.get(file_id)
                if item:
                    item.password_hash = new_hash
                    updated += 1
        return updated

    def verify_file_password(self, file_id: str, password: str) -> bool:
        item = self.get(file_id)
        if not item:
            return False
        return verify_password(password, item.password_hash)


def iter_folder_files(folder: Path, include_subfolders: bool) -> Iterable[Path]:
    if not folder.is_dir():
        return []
    iterator = folder.rglob("*") if include_subfolders else folder.iterdir()
    return [path for path in iterator if path.is_file()]


class StatsStore:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @contextlib.contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS transfer_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    transfer_id TEXT,
                    file_id TEXT,
                    file_name TEXT,
                    ip TEXT,
                    ip_source TEXT,
                    user_agent TEXT,
                    size_total INTEGER DEFAULT 0,
                    bytes_done INTEGER DEFAULT 0,
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def create_event(
        self,
        event_type: str,
        transfer_id: str,
        file_id: str,
        file_name: str,
        ip: str,
        ip_source: str,
        user_agent: str,
        size_total: int,
        status: str = "activa",
    ) -> int:
        stamp = now_iso()
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO transfer_events
                (event_type, transfer_id, file_id, file_name, ip, ip_source, user_agent,
                 size_total, bytes_done, status, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, NULL, ?, ?)
                """,
                (
                    event_type,
                    transfer_id,
                    file_id,
                    file_name,
                    ip,
                    ip_source,
                    user_agent,
                    size_total,
                    status,
                    stamp,
                    stamp,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def update_event(self, transfer_id: str, bytes_done: int, status: str, error: str | None = None) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                UPDATE transfer_events
                SET bytes_done = ?, status = ?, error = ?, updated_at = ?
                WHERE transfer_id = ?
                """,
                (bytes_done, status, error, now_iso(), transfer_id),
            )
            connection.commit()

    def record_simple(
        self,
        event_type: str,
        file_id: str,
        file_name: str,
        ip: str,
        ip_source: str,
        user_agent: str,
        size_total: int,
        status: str,
        error: str | None = None,
    ) -> None:
        transfer_id = uuid.uuid4().hex
        self.create_event(event_type, transfer_id, file_id, file_name, ip, ip_source, user_agent, size_total, status)
        self.update_event(transfer_id, size_total, status, error)

    def recent_events(self, limit: int = 250, ip: str = "", file_name: str = "", status: str = "") -> list[dict]:
        clauses: list[str] = []
        params: list[object] = []
        if ip:
            clauses.append("ip LIKE ?")
            params.append(f"%{ip}%")
        if file_name:
            clauses.append("file_name LIKE ?")
            params.append(f"%{file_name}%")
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM transfer_events
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def export_csv(self, destination: Path, rows: list[dict] | None = None) -> None:
        rows = rows if rows is not None else self.recent_events(limit=10_000)
        fields = [
            "id",
            "event_type",
            "transfer_id",
            "file_id",
            "file_name",
            "ip",
            "ip_source",
            "user_agent",
            "size_total",
            "bytes_done",
            "status",
            "error",
            "created_at",
            "updated_at",
        ]
        with destination.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in fields})


@dataclass
class ActiveTransfer:
    id: str
    event_type: str
    file_id: str
    file_name: str
    ip: str
    ip_source: str
    user_agent: str
    total_bytes: int
    bytes_done: int
    status: str
    started_at: float
    updated_at: float
    cancel_event: threading.Event

    def snapshot(self) -> dict:
        elapsed = max(time.time() - self.started_at, 0.001)
        speed = self.bytes_done / elapsed
        percent = 0 if self.total_bytes <= 0 else min(100, (self.bytes_done / self.total_bytes) * 100)
        return {
            "id": self.id,
            "event_type": self.event_type,
            "file_id": self.file_id,
            "file_name": self.file_name,
            "ip": self.ip,
            "ip_source": self.ip_source,
            "total_bytes": self.total_bytes,
            "bytes_done": self.bytes_done,
            "percent": percent,
            "speed": speed,
            "status": self.status,
        }


class TransferManager:
    def __init__(self, stats: StatsStore) -> None:
        self.stats = stats
        self._active: dict[str, ActiveTransfer] = {}
        self._lock = threading.RLock()

    def start(
        self,
        event_type: str,
        file_id: str,
        file_name: str,
        ip: str,
        ip_source: str,
        user_agent: str,
        total_bytes: int,
    ) -> ActiveTransfer:
        transfer_id = uuid.uuid4().hex
        transfer = ActiveTransfer(
            id=transfer_id,
            event_type=event_type,
            file_id=file_id,
            file_name=file_name,
            ip=ip,
            ip_source=ip_source,
            user_agent=user_agent,
            total_bytes=total_bytes,
            bytes_done=0,
            status="activa",
            started_at=time.time(),
            updated_at=time.time(),
            cancel_event=threading.Event(),
        )
        with self._lock:
            self._active[transfer_id] = transfer
        self.stats.create_event(event_type, transfer_id, file_id, file_name, ip, ip_source, user_agent, total_bytes)
        return transfer

    def progress(self, transfer_id: str, bytes_done: int) -> None:
        with self._lock:
            transfer = self._active.get(transfer_id)
            if not transfer:
                return
            transfer.bytes_done = bytes_done
            transfer.updated_at = time.time()
        self.stats.update_event(transfer_id, bytes_done, "activa")

    def finish(self, transfer_id: str, status: str = "completada", error: str | None = None) -> None:
        with self._lock:
            transfer = self._active.pop(transfer_id, None)
        if transfer:
            transfer.status = status
            self.stats.update_event(transfer_id, transfer.bytes_done, status, error)

    def cancel(self, transfer_id: str) -> bool:
        with self._lock:
            transfer = self._active.get(transfer_id)
            if not transfer:
                return False
            transfer.status = "cancelando"
            transfer.cancel_event.set()
        self.stats.update_event(transfer_id, transfer.bytes_done, "cancelando")
        return True

    def snapshot_active(self) -> list[dict]:
        with self._lock:
            return [transfer.snapshot() for transfer in self._active.values()]


def build_zip(files: Iterable[SharedFile]) -> Path:
    temp = tempfile.NamedTemporaryFile(prefix="file-transfer-easy-", suffix=".zip", delete=False)
    temp_path = Path(temp.name)
    temp.close()
    used_names: set[str] = set()
    with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in files:
            path = Path(item.path)
            if not path.is_file():
                continue
            arcname = sanitize_filename(item.display_name)
            if arcname in used_names:
                base = Path(arcname).stem or "archivo"
                suffix = Path(arcname).suffix
                counter = 2
                while f"{base} ({counter}){suffix}" in used_names:
                    counter += 1
                arcname = f"{base} ({counter}){suffix}"
            used_names.add(arcname)
            archive.write(path, arcname=arcname)
    return temp_path


def session_global_unlocked(state: ShareState) -> bool:
    if not state.global_password_enabled():
        return True
    return bool(session.get("global_unlocked"))


def unlocked_file_ids() -> set[str]:
    return set(session.get("unlocked_files", []))


def mark_file_unlocked(file_id: str) -> None:
    unlocked = unlocked_file_ids()
    unlocked.add(file_id)
    session["unlocked_files"] = sorted(unlocked)


def create_web_app(
    state: ShareState,
    stats: StatsStore | None = None,
    transfers: TransferManager | None = None,
) -> "Flask":
    if not import_web_dependencies():
        raise RuntimeError("Faltan dependencias. Ejecuta: python -m pip install -r requirements.txt")
    assert Flask is not None and Response is not None

    stats = stats or StatsStore()
    transfers = transfers or TransferManager(stats)
    web_app = Flask(APP_NAME)
    web_app.secret_key = state.token
    web_app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    def require_token(token: str) -> None:
        if token != state.token:
            abort(404)

    def require_global_or_form(token: str):
        if session_global_unlocked(state):
            return None
        return render_template_string(LOGIN_HTML, token=token, error="", base_css=BASE_AUTH_CSS)

    def can_download_file(item: SharedFile) -> bool:
        return not item.protected or item.id in unlocked_file_ids()

    def stream_path(path: Path, file_id: str, file_name: str, event_type: str, cleanup: bool = False):
        ip, ip_source = get_client_ip(request)
        user_agent = request.headers.get("User-Agent", "")
        total = path.stat().st_size if path.exists() else 0
        transfer = transfers.start(event_type, file_id, file_name, ip, ip_source, user_agent, total)

        def generate():
            sent = 0
            status = "completada"
            error = None
            try:
                with path.open("rb") as handle:
                    while True:
                        if transfer.cancel_event.is_set():
                            status = "cancelada"
                            break
                        chunk = handle.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        sent += len(chunk)
                        transfer.bytes_done = sent
                        transfers.progress(transfer.id, sent)
                        yield chunk
            except GeneratorExit:
                status = "interrumpida"
                error = "Cliente desconectado"
                raise
            except Exception as exc:
                status = "error"
                error = str(exc)
                raise
            finally:
                transfer.bytes_done = sent
                transfers.finish(transfer.id, status, error)
                if cleanup:
                    with contextlib.suppress(OSError):
                        path.unlink(missing_ok=True)

        mimetype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        headers = {
            "Content-Disposition": content_disposition(file_name),
            "Content-Length": str(total),
            "X-Transfer-Id": transfer.id,
        }
        return Response(generate(), headers=headers, mimetype=mimetype, direct_passthrough=True)

    @web_app.get("/")
    def root():
        return redirect(url_for("share_page", token=state.token))

    @web_app.get("/s/<token>")
    def share_page(token: str):
        require_token(token)
        locked_response = require_global_or_form(token)
        if locked_response:
            return locked_response
        files = state.snapshot()
        return render_template_string(
            CLIENT_HTML,
            token=token,
            files=files,
            upload_enabled=state.uploads_enabled(),
            file_count=len(files),
            total_size_text=format_bytes(sum(item.size for item in files)),
            format_bytes=format_bytes,
            format_mtime=format_mtime,
            unlocked_files=unlocked_file_ids(),
        )

    @web_app.post("/s/<token>/auth")
    def auth_global(token: str):
        require_token(token)
        password = request.form.get("password", "")
        if state.verify_global_password(password):
            session["global_unlocked"] = True
            return redirect(url_for("share_page", token=token))
        return render_template_string(LOGIN_HTML, token=token, error="Contrasena incorrecta.", base_css=BASE_AUTH_CSS), 403

    @web_app.post("/s/<token>/unlock/<file_id>")
    def unlock_file(token: str, file_id: str):
        require_token(token)
        if not session_global_unlocked(state):
            return redirect(url_for("share_page", token=token))
        password = request.form.get("password", "")
        if state.verify_file_password(file_id, password):
            mark_file_unlocked(file_id)
            return redirect(url_for("download_file", token=token, file_id=file_id))
        return render_template_string(
            FILE_PASSWORD_HTML,
            token=token,
            file_id=file_id,
            error="Contrasena incorrecta.",
            base_css=BASE_AUTH_CSS,
        ), 403

    @web_app.get("/s/<token>/download/<file_id>")
    def download_file(token: str, file_id: str):
        require_token(token)
        if not session_global_unlocked(state):
            return redirect(url_for("share_page", token=token))
        item = state.get(file_id)
        if item is None:
            abort(404)
        if not can_download_file(item):
            return render_template_string(FILE_PASSWORD_HTML, token=token, file_id=file_id, error="", base_css=BASE_AUTH_CSS)
        path = Path(item.path)
        if not path.is_file():
            abort(404)
        return stream_path(path, item.id, item.display_name, "download")

    @web_app.get("/s/<token>/download-all")
    def download_all(token: str):
        require_token(token)
        if not session_global_unlocked(state):
            return redirect(url_for("share_page", token=token))
        files = [item for item in state.snapshot() if can_download_file(item)]
        if not files:
            return "No hay archivos desbloqueados para descargar.", 403
        zip_path = build_zip(files)
        return stream_path(zip_path, "zip", "file-transfer-easy.zip", "download_zip", cleanup=True)

    @web_app.post("/s/<token>/upload")
    def upload(token: str):
        require_token(token)
        if not session_global_unlocked(state):
            return jsonify({"ok": False, "message": "Desbloquea la sesion primero."}), 403
        if not state.uploads_enabled():
            return jsonify({"ok": False, "message": "Las subidas estan desactivadas."}), 403
        uploaded_files = request.files.getlist("files")
        if not uploaded_files:
            return jsonify({"ok": False, "message": "No se recibio ningun archivo."}), 400
        folder = state.upload_folder()
        ip, ip_source = get_client_ip(request)
        user_agent = request.headers.get("User-Agent", "")
        saved: list[dict[str, str]] = []
        for uploaded in uploaded_files:
            if not uploaded or not uploaded.filename:
                continue
            destination = unique_path(folder, uploaded.filename)
            uploaded.save(destination)
            item = state.add_uploaded_file(destination)
            saved.append({"id": item.id, "name": item.display_name})
            stats.record_simple("upload", item.id, item.display_name, ip, ip_source, user_agent, item.size, "completada")
        if not saved:
            return jsonify({"ok": False, "message": "No habia archivos validos."}), 400
        return jsonify({"ok": True, "message": f"{len(saved)} archivo(s) subido(s).", "files": saved})

    return web_app


class WebServer:
    def __init__(self, state: ShareState, stats: StatsStore, transfers: TransferManager, log: Callable[[str], None]) -> None:
        self.state = state
        self.stats = stats
        self.transfers = transfers
        self.log = log
        self.host = "0.0.0.0"
        self.port: int | None = None
        self._server = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, port: int) -> None:
        with self._lock:
            if self.running:
                raise RuntimeError("El servidor ya esta iniciado.")
            if not import_web_dependencies() or create_server is None:
                raise RuntimeError("Falta Flask o Waitress. Revisa requirements.txt.")
            app = create_web_app(self.state, self.stats, self.transfers)
            self._server = create_server(app, host=self.host, port=port, threads=12)
            self.port = port
            self._thread = threading.Thread(target=self._serve, name="web-server", daemon=True)
            self._thread.start()
            self.log(f"Servidor web escuchando en 0.0.0.0:{port}")

    def _serve(self) -> None:
        try:
            self._server.run()
        except Exception as exc:
            self.log(f"Servidor detenido por error: {exc}")

    def stop(self) -> None:
        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
            self.port = None
        if server is not None:
            with contextlib.suppress(Exception):
                server.close()
            dispatcher = getattr(server, "task_dispatcher", None)
            if dispatcher is not None:
                with contextlib.suppress(Exception):
                    dispatcher.shutdown()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
        self.log("Servidor web detenido.")


class TunnelProcess:
    def __init__(self, log: Callable[[str], None], on_url: Callable[[str], None]) -> None:
        self.log = log
        self.on_url = on_url
        self.process: subprocess.Popen[str] | None = None
        self.thread: threading.Thread | None = None
        self.kind = ""

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start_tailscale(self, local_port: int, public_port: str) -> None:
        executable = shutil.which("tailscale")
        if not executable:
            raise RuntimeError("Tailscale no esta instalado o no esta en PATH.")
        self._start([executable, "funnel", "--yes", f"--https={public_port}", f"http://127.0.0.1:{local_port}"], "tailscale")

    def start_cloudflare(self, local_port: int) -> None:
        executable = install_cloudflared(self.log)
        self._start([executable, "tunnel", "--url", f"http://127.0.0.1:{local_port}"], "cloudflare")

    def _start(self, command: list[str], kind: str) -> None:
        self.stop()
        self.kind = kind
        self.log(f"Iniciando tunel {kind}: {' '.join(command)}")
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags(),
        )
        self.thread = threading.Thread(target=self._read_output, name=f"{kind}-tunnel", daemon=True)
        self.thread.start()

    def _read_output(self) -> None:
        assert self.process is not None
        url_pattern = re.compile(r"https?://[^\s|)]+", re.IGNORECASE)
        for line in self.process.stdout or []:
            clean = line.strip()
            if not clean:
                continue
            self.log(clean)
            for match in url_pattern.findall(clean):
                if is_shareable_tunnel_url(self.kind, match):
                    self.on_url(match.rstrip(".,"))
        exit_code = self.process.poll()
        if exit_code not in (None, 0):
            self.log(f"El tunel termino con codigo {exit_code}.")

    def stop(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.poll() is None:
            self.log("Deteniendo tunel...")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


class FileTransferApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.state = ShareState()
        self.stats = StatsStore()
        self.transfers = TransferManager(self.stats)
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.web_server = WebServer(self.state, self.stats, self.transfers, self.queue_log)
        self.tunnel = TunnelProcess(self.queue_log, self.set_public_url)

        self.share_url = tk.StringVar(value="")
        self.status_text = tk.StringVar(value="Preparado")
        self.mode = tk.StringVar(value="tailscale")
        self.local_port = tk.StringVar(value="80")
        self.manual_port = tk.BooleanVar(value=False)
        self.tailscale_public_port = tk.StringVar(value="443")
        self.upload_enabled_var = tk.BooleanVar(value=False)
        self.upload_dir_var = tk.StringVar(value=str(DEFAULT_UPLOAD_DIR))
        self.shared_folder_var = tk.StringVar(value="")
        self.include_subfolders_var = tk.BooleanVar(value=False)
        self.global_password_var = tk.StringVar(value="")
        self.file_password_var = tk.StringVar(value="")
        self.history_ip_filter = tk.StringVar(value="")
        self.history_file_filter = tk.StringVar(value="")
        self.history_status_filter = tk.StringVar(value="")

        self._build_style()
        self._build_ui()
        self.sync_upload_config()
        self._schedule_log_flush()
        self._schedule_refresh()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_style(self) -> None:
        self.root.title(APP_NAME)
        self.root.geometry("1180x820")
        self.root.minsize(1040, 720)
        self.root.configure(bg="#eef3f6")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#eef3f6")
        style.configure("Panel.TFrame", background="#ffffff")
        style.configure("TNotebook", background="#eef3f6", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 8), font=("Segoe UI", 10, "bold"))
        style.configure("Muted.TLabel", background="#ffffff", foreground="#5f6d7a")
        style.configure("Body.TLabel", background="#ffffff", foreground="#17212b")
        style.configure("Title.TLabel", background="#eef3f6", foreground="#17212b")
        style.configure("PanelTitle.TLabel", background="#ffffff", foreground="#17212b")
        style.configure("Accent.TButton", padding=(14, 9), font=("Segoe UI", 10, "bold"))
        style.configure("TButton", padding=(11, 7), font=("Segoe UI", 10))
        style.configure("TCheckbutton", background="#ffffff", foreground="#17212b")
        style.configure("TRadiobutton", background="#ffffff", foreground="#17212b")
        style.configure("Treeview", rowheight=31, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

    def _panel(self, parent, padding=16) -> ttk.Frame:
        return ttk.Frame(parent, style="Panel.TFrame", padding=padding)

    def _build_ui(self) -> None:
        shell = ttk.Frame(self.root, padding=20)
        shell.pack(fill="both", expand=True)
        header = ttk.Frame(shell)
        header.pack(fill="x", pady=(0, 14))
        ttk.Label(header, text=APP_NAME, style="Title.TLabel", font=("Segoe UI", 24, "bold")).pack(side="left")
        self.status_badge = tk.Label(header, textvariable=self.status_text, bg="#ffffff", fg="#17212b", padx=14, pady=8, font=("Segoe UI", 10, "bold"))
        self.status_badge.pack(side="right")

        self.notebook = ttk.Notebook(shell)
        self.notebook.pack(fill="both", expand=True)
        self.files_tab = self._panel(self.notebook)
        self.publish_tab = self._panel(self.notebook)
        self.security_tab = self._panel(self.notebook)
        self.activity_tab = self._panel(self.notebook)
        self.settings_tab = self._panel(self.notebook)
        for frame, title in [
            (self.files_tab, "Archivos"),
            (self.publish_tab, "Publicacion"),
            (self.security_tab, "Seguridad"),
            (self.activity_tab, "Actividad"),
            (self.settings_tab, "Ajustes"),
        ]:
            self.notebook.add(frame, text=title)

        self._build_files_tab()
        self._build_publish_tab()
        self._build_security_tab()
        self._build_activity_tab()
        self._build_settings_tab()
        self._build_log_panel(shell)

    def _build_files_tab(self) -> None:
        self.files_tab.columnconfigure(0, weight=1)
        self.files_tab.rowconfigure(2, weight=1)
        ttk.Label(self.files_tab, text="Archivos compartidos", style="PanelTitle.TLabel", font=("Segoe UI", 15, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(self.files_tab, text="Anade archivos sueltos o una carpeta completa para que aparezcan en la web.", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 10))

        columns = ("name", "size", "source", "protected", "mtime")
        self.file_tree = ttk.Treeview(self.files_tab, columns=columns, show="headings", selectmode="extended")
        for key, text, width in [
            ("name", "Nombre", 360),
            ("size", "Tamano", 90),
            ("source", "Origen", 90),
            ("protected", "Clave", 80),
            ("mtime", "Fecha", 150),
        ]:
            self.file_tree.heading(key, text=text)
            self.file_tree.column(key, width=width, minwidth=70)
        self.file_tree.grid(row=2, column=0, sticky="nsew")
        ttk.Scrollbar(self.files_tab, orient="vertical", command=self.file_tree.yview).grid(row=2, column=1, sticky="ns")

        actions = ttk.Frame(self.files_tab, style="Panel.TFrame")
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="Anadir archivos", command=self.add_files, style="Accent.TButton").pack(side="left")
        ttk.Button(actions, text="Quitar seleccion", command=self.remove_selected).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Limpiar lista", command=self.clear_files).pack(side="left", padx=(8, 0))

        folder = ttk.Frame(self.files_tab, style="Panel.TFrame")
        folder.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        folder.columnconfigure(1, weight=1)
        ttk.Label(folder, text="Carpeta compartida", style="Body.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(folder, textvariable=self.shared_folder_var).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(folder, text="Elegir", command=self.choose_shared_folder).grid(row=0, column=2)
        ttk.Checkbutton(folder, text="Incluir subcarpetas", variable=self.include_subfolders_var).grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Button(folder, text="Actualizar carpeta", command=self.refresh_shared_folder).grid(row=1, column=2, sticky="e", pady=(8, 0))

    def _build_publish_tab(self) -> None:
        self.publish_tab.columnconfigure(0, weight=1)
        ttk.Label(self.publish_tab, text="Publicacion", style="PanelTitle.TLabel", font=("Segoe UI", 15, "bold")).grid(row=0, column=0, sticky="w")
        modes = ttk.Frame(self.publish_tab, style="Panel.TFrame")
        modes.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        for value, title, detail in [
            ("tailscale", "Tailscale Funnel", "Primero intenta Tailscale; si no esta disponible, cae a Cloudflare."),
            ("cloudflare", "Cloudflare Quick Tunnel", "Instala cloudflared automaticamente si hace falta."),
            ("direct", "Puerto propio", "Usa LAN/local; router y firewall quedan a cargo del host."),
        ]:
            row = ttk.Frame(modes, style="Panel.TFrame")
            row.pack(fill="x", pady=(0, 8))
            ttk.Radiobutton(row, text=title, variable=self.mode, value=value).pack(anchor="w")
            ttk.Label(row, text=detail, style="Muted.TLabel").pack(anchor="w", padx=(24, 0))

        port = ttk.Frame(self.publish_tab, style="Panel.TFrame")
        port.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(port, text="Puerto local", style="Body.TLabel").pack(side="left")
        ttk.Entry(port, textvariable=self.local_port, width=10).pack(side="left", padx=(8, 12))
        ttk.Checkbutton(port, text="Usar exactamente este puerto", variable=self.manual_port).pack(side="left")
        ttk.Label(port, text="Puerto publico Tailscale", style="Body.TLabel").pack(side="left", padx=(18, 6))
        ttk.Combobox(port, textvariable=self.tailscale_public_port, values=TAILSCALE_PUBLIC_PORTS, width=8, state="readonly").pack(side="left")

        uploads = ttk.Frame(self.publish_tab, style="Panel.TFrame")
        uploads.grid(row=3, column=0, sticky="ew", pady=(18, 0))
        uploads.columnconfigure(1, weight=1)
        ttk.Checkbutton(uploads, text="Permitir subidas de clientes", variable=self.upload_enabled_var, command=self.sync_upload_config).grid(row=0, column=0, sticky="w", columnspan=3)
        ttk.Label(uploads, text="Carpeta de subidas", style="Body.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 0), padx=(0, 8))
        ttk.Entry(uploads, textvariable=self.upload_dir_var).grid(row=1, column=1, sticky="ew", pady=(10, 0), padx=(0, 8))
        ttk.Button(uploads, text="Elegir", command=self.choose_upload_dir).grid(row=1, column=2, pady=(10, 0))

        actions = ttk.Frame(self.publish_tab, style="Panel.TFrame")
        actions.grid(row=4, column=0, sticky="ew", pady=(22, 0))
        ttk.Button(actions, text="Iniciar", command=self.start, style="Accent.TButton").pack(side="left")
        ttk.Button(actions, text="Detener", command=self.stop).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Copiar URL", command=self.copy_url).pack(side="left", padx=(8, 0))
        ttk.Entry(self.publish_tab, textvariable=self.share_url).grid(row=5, column=0, sticky="ew", pady=(14, 0))

    def _build_security_tab(self) -> None:
        self.security_tab.columnconfigure(0, weight=1)
        ttk.Label(self.security_tab, text="Seguridad", style="PanelTitle.TLabel", font=("Segoe UI", 15, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(self.security_tab, text="Las contrasenas se guardan con hash local, no como texto plano.", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 16))
        global_box = ttk.Frame(self.security_tab, style="Panel.TFrame")
        global_box.grid(row=2, column=0, sticky="ew")
        global_box.columnconfigure(1, weight=1)
        ttk.Label(global_box, text="Contrasena global", style="Body.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(global_box, textvariable=self.global_password_var, show="*").grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(global_box, text="Aplicar", command=self.apply_global_password).grid(row=0, column=2)
        ttk.Button(global_box, text="Quitar", command=self.clear_global_password).grid(row=0, column=3, padx=(8, 0))

        file_box = ttk.Frame(self.security_tab, style="Panel.TFrame")
        file_box.grid(row=3, column=0, sticky="ew", pady=(22, 0))
        file_box.columnconfigure(1, weight=1)
        ttk.Label(file_box, text="Contrasena para archivos seleccionados", style="Body.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(file_box, textvariable=self.file_password_var, show="*").grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(file_box, text="Aplicar a seleccion", command=self.apply_file_password).grid(row=0, column=2)
        ttk.Button(file_box, text="Quitar de seleccion", command=self.clear_file_password).grid(row=0, column=3, padx=(8, 0))

    def _build_activity_tab(self) -> None:
        self.activity_tab.columnconfigure(0, weight=1)
        self.activity_tab.rowconfigure(1, weight=1)
        self.activity_tab.rowconfigure(4, weight=1)
        ttk.Label(self.activity_tab, text="Descargas activas", style="PanelTitle.TLabel", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        self.active_tree = ttk.Treeview(self.activity_tab, columns=("file", "ip", "progress", "speed", "status"), show="headings", height=6)
        for key, text, width in [("file", "Archivo", 300), ("ip", "IP", 150), ("progress", "Progreso", 120), ("speed", "Velocidad", 120), ("status", "Estado", 100)]:
            self.active_tree.heading(key, text=text)
            self.active_tree.column(key, width=width)
        self.active_tree.grid(row=1, column=0, sticky="nsew", pady=(8, 8))
        ttk.Button(self.activity_tab, text="Anular descarga seleccionada", command=self.cancel_selected_transfer).grid(row=2, column=0, sticky="w")

        filters = ttk.Frame(self.activity_tab, style="Panel.TFrame")
        filters.grid(row=3, column=0, sticky="ew", pady=(18, 8))
        ttk.Label(filters, text="Historial", style="PanelTitle.TLabel", font=("Segoe UI", 14, "bold")).pack(side="left", padx=(0, 14))
        ttk.Entry(filters, textvariable=self.history_ip_filter, width=18).pack(side="left")
        ttk.Entry(filters, textvariable=self.history_file_filter, width=24).pack(side="left", padx=(8, 0))
        ttk.Combobox(filters, textvariable=self.history_status_filter, values=("", "activa", "completada", "cancelada", "interrumpida", "error"), width=14, state="readonly").pack(side="left", padx=(8, 0))
        ttk.Button(filters, text="Filtrar", command=self.refresh_history).pack(side="left", padx=(8, 0))
        ttk.Button(filters, text="Limpiar vista", command=self.clear_history_filters).pack(side="left", padx=(8, 0))
        ttk.Button(filters, text="Exportar CSV", command=self.export_history_csv).pack(side="left", padx=(8, 0))

        self.history_tree = ttk.Treeview(self.activity_tab, columns=("time", "type", "file", "ip", "bytes", "status"), show="headings")
        for key, text, width in [("time", "Hora", 155), ("type", "Tipo", 90), ("file", "Archivo", 300), ("ip", "IP", 150), ("bytes", "Bytes", 110), ("status", "Estado", 110)]:
            self.history_tree.heading(key, text=text)
            self.history_tree.column(key, width=width)
        self.history_tree.grid(row=4, column=0, sticky="nsew")

    def _build_settings_tab(self) -> None:
        ttk.Label(self.settings_tab, text="Ajustes", style="PanelTitle.TLabel", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(self.settings_tab, text=f"Base de datos: {DB_PATH}", style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        ttk.Label(self.settings_tab, text=f"Cloudflared local: {LOCAL_BIN_DIR}", style="Muted.TLabel").pack(anchor="w", pady=(4, 18))
        ttk.Button(self.settings_tab, text="Instalar o comprobar cloudflared", command=self.install_cloudflared_from_ui, style="Accent.TButton").pack(anchor="w")
        ttk.Button(self.settings_tab, text="Comprobar dependencias Python", command=self.install_python_deps_from_ui).pack(anchor="w", pady=(8, 0))

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, padding=(0, 12, 0, 0))
        panel.pack(fill="x")
        self.log_text = tk.Text(panel, height=6, bg="#17212b", fg="#d8f3ea", insertbackground="#d8f3ea", relief="flat", font=("Consolas", 9), padx=12, pady=10, wrap="word")
        self.log_text.pack(fill="x")
        self.log_text.configure(state="disabled")

    def queue_log(self, message: str) -> None:
        self.log_queue.put(message)

    def log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{now_text()}] {message}\n")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _schedule_log_flush(self) -> None:
        while True:
            try:
                self.log(self.log_queue.get_nowait())
            except queue.Empty:
                break
        self.root.after(150, self._schedule_log_flush)

    def _schedule_refresh(self) -> None:
        self.refresh_files()
        self.refresh_active_transfers()
        self.refresh_history()
        self.root.after(1500, self._schedule_refresh)

    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(title="Selecciona archivos para compartir")
        if not paths:
            return
        added, errors = self.state.add_paths(paths)
        self.refresh_files()
        self.log(f"{added} archivo(s) anadido(s).")
        for error in errors:
            self.log(error)

    def remove_selected(self) -> None:
        removed = self.state.remove(self.file_tree.selection())
        self.refresh_files()
        self.log(f"{removed} archivo(s) quitado(s).")

    def clear_files(self) -> None:
        if self.state.has_files() and messagebox.askyesno(APP_NAME, "Quitar todos los archivos de la lista?"):
            self.state.clear()
            self.refresh_files()
            self.log("Lista limpiada.")

    def choose_shared_folder(self) -> None:
        path = filedialog.askdirectory(title="Carpeta compartida")
        if path:
            self.shared_folder_var.set(path)
            self.refresh_shared_folder()

    def refresh_shared_folder(self) -> None:
        self.state.configure_shared_folder(self.shared_folder_var.get(), self.include_subfolders_var.get())
        added, errors = self.state.refresh_shared_folder()
        self.refresh_files()
        self.log(f"Carpeta actualizada: {added} archivo(s) nuevo(s).")
        for error in errors:
            self.log(error)

    def choose_upload_dir(self) -> None:
        path = filedialog.askdirectory(title="Carpeta donde guardar subidas", initialdir=self.upload_dir_var.get() or str(DEFAULT_UPLOAD_DIR))
        if path:
            self.upload_dir_var.set(path)
            self.sync_upload_config()

    def sync_upload_config(self) -> None:
        self.state.configure_uploads(self.upload_enabled_var.get(), self.upload_dir_var.get())

    def refresh_files(self) -> None:
        if not hasattr(self, "file_tree"):
            return
        selected = set(self.file_tree.selection())
        self.file_tree.delete(*self.file_tree.get_children())
        for item in self.state.snapshot():
            self.file_tree.insert(
                "",
                "end",
                iid=item.id,
                values=(item.display_name, format_bytes(item.size), item.source, "Si" if item.protected else "No", format_mtime(item.mtime)),
            )
        for file_id in selected:
            if self.file_tree.exists(file_id):
                self.file_tree.selection_add(file_id)

    def apply_global_password(self) -> None:
        password = self.global_password_var.get()
        self.state.set_global_password(password)
        self.global_password_var.set("")
        self.log("Contrasena global aplicada." if password else "Contrasena global quitada.")

    def clear_global_password(self) -> None:
        self.state.set_global_password("")
        self.global_password_var.set("")
        self.log("Contrasena global quitada.")

    def apply_file_password(self) -> None:
        selected = self.file_tree.selection()
        if not selected:
            self.log("Selecciona archivos antes de aplicar una contrasena.")
            return
        updated = self.state.set_file_passwords(selected, self.file_password_var.get())
        self.file_password_var.set("")
        self.refresh_files()
        self.log(f"Contrasena aplicada a {updated} archivo(s).")

    def clear_file_password(self) -> None:
        selected = self.file_tree.selection()
        updated = self.state.set_file_passwords(selected, "")
        self.refresh_files()
        self.log(f"Contrasena quitada de {updated} archivo(s).")

    def refresh_active_transfers(self) -> None:
        if not hasattr(self, "active_tree"):
            return
        current = set(self.active_tree.selection())
        self.active_tree.delete(*self.active_tree.get_children())
        for item in self.transfers.snapshot_active():
            self.active_tree.insert(
                "",
                "end",
                iid=item["id"],
                values=(
                    item["file_name"],
                    f"{item['ip']} ({item['ip_source']})",
                    f"{item['percent']:.0f}% {format_bytes(item['bytes_done'])}/{format_bytes(item['total_bytes'])}",
                    f"{format_bytes(int(item['speed']))}/s",
                    item["status"],
                ),
            )
        for transfer_id in current:
            if self.active_tree.exists(transfer_id):
                self.active_tree.selection_add(transfer_id)

    def cancel_selected_transfer(self) -> None:
        for transfer_id in self.active_tree.selection():
            if self.transfers.cancel(transfer_id):
                self.log(f"Descarga anulada: {transfer_id}")

    def refresh_history(self) -> None:
        if not hasattr(self, "history_tree"):
            return
        rows = self.stats.recent_events(
            ip=self.history_ip_filter.get().strip(),
            file_name=self.history_file_filter.get().strip(),
            status=self.history_status_filter.get().strip(),
        )
        self.history_tree.delete(*self.history_tree.get_children())
        for row in rows:
            self.history_tree.insert(
                "",
                "end",
                values=(
                    row["updated_at"],
                    row["event_type"],
                    row["file_name"],
                    f"{row['ip']} ({row['ip_source']})",
                    f"{format_bytes(row['bytes_done'])}/{format_bytes(row['size_total'])}",
                    row["status"],
                ),
            )

    def clear_history_filters(self) -> None:
        self.history_ip_filter.set("")
        self.history_file_filter.set("")
        self.history_status_filter.set("")
        self.refresh_history()

    def export_history_csv(self) -> None:
        destination = filedialog.asksaveasfilename(title="Exportar historial", defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not destination:
            return
        self.stats.export_csv(Path(destination))
        self.log(f"Historial exportado: {destination}")

    def install_cloudflared_from_ui(self) -> None:
        threading.Thread(target=lambda: self.queue_log(f"Cloudflared listo: {install_cloudflared(self.queue_log)}"), daemon=True).start()

    def install_python_deps_from_ui(self) -> None:
        threading.Thread(target=lambda: self._install_python_deps_worker(), daemon=True).start()

    def _install_python_deps_worker(self) -> None:
        try:
            install_python_dependencies(self.queue_log)
            self.queue_log("Dependencias Python listas.")
        except Exception as exc:
            self.queue_log(str(exc))

    def set_public_url(self, url: str) -> None:
        if "/s/" not in url:
            url = f"{url.rstrip('/')}/s/{self.state.token}"
        self.root.after(0, lambda: self._set_url(url))

    def _set_url(self, url: str) -> None:
        self.share_url.set(url)
        self.set_status("Publicado")
        self.log(f"URL publica lista: {url}")

    def set_status(self, text: str) -> None:
        self.status_text.set(text)
        colors = {"Preparado": "#ffffff", "Iniciando": "#fff8dc", "Publicado": "#d8f3ea", "Local": "#e3f0ff", "Detenido": "#ffffff", "Error": "#ffe3df"}
        self.status_badge.configure(bg=colors.get(text, "#ffffff"))

    def start(self) -> None:
        if self.web_server.running:
            self.log("Ya hay una publicacion activa.")
            return
        self.sync_upload_config()
        self.state.configure_shared_folder(self.shared_folder_var.get(), self.include_subfolders_var.get())
        if self.shared_folder_var.get().strip():
            self.refresh_shared_folder()
        port, error = choose_port(self.local_port.get(), self.manual_port.get())
        if error:
            messagebox.showerror(APP_NAME, error)
            self.log(error)
            return
        assert port is not None
        if self.upload_enabled_var.get():
            try:
                self.state.upload_folder().mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror(APP_NAME, f"No se pudo crear la carpeta de subidas:\n{exc}")
                return
        self.set_status("Iniciando")
        self.local_port.set(str(port))
        try:
            self.web_server.start(port)
        except Exception as exc:
            self.set_status("Error")
            self.log(str(exc))
            messagebox.showerror(APP_NAME, str(exc))
            return
        local_url = f"http://127.0.0.1:{port}/s/{self.state.token}"
        lan_url = f"http://{get_lan_ip()}:{port}/s/{self.state.token}"
        mode = self.mode.get()
        if mode == "direct":
            self.share_url.set(lan_url)
            self.set_status("Local")
            self.log(f"URL local: {local_url}")
            self.log(f"URL LAN: {lan_url}")
            return
        self.share_url.set(local_url)
        try:
            if mode == "tailscale":
                try:
                    self.tunnel.start_tailscale(port, self.tailscale_public_port.get())
                except Exception as exc:
                    self.log(f"Tailscale no disponible: {exc}")
                    self.log("Intentando Cloudflare Quick Tunnel...")
                    self.tunnel.start_cloudflare(port)
            elif mode == "cloudflare":
                self.tunnel.start_cloudflare(port)
        except Exception as exc:
            self.set_status("Local")
            self.log(str(exc))
            self.log(f"URL local disponible: {local_url}")
            messagebox.showwarning(APP_NAME, str(exc))

    def stop(self) -> None:
        self.tunnel.stop()
        if self.web_server.running:
            self.web_server.stop()
        self.share_url.set("")
        self.set_status("Detenido")

    def copy_url(self) -> None:
        url = self.share_url.get().strip()
        if not url:
            self.log("No hay URL para copiar todavia.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.root.update()
        self.log("URL copiada al portapapeles.")

    def on_close(self) -> None:
        self.stop()
        self.root.destroy()


LOGIN_HTML = r"""
<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Acceso protegido</title><style>{{ base_css|safe }}</style></head><body><main class="auth"><h1>Acceso protegido</h1>
<p>Introduce la contrasena global para ver la sesion compartida.</p>{% if error %}<div class="error">{{ error }}</div>{% endif %}
<form method="post" action="{{ url_for('auth_global', token=token) }}"><input name="password" type="password" placeholder="Contrasena" autofocus>
<button type="submit">Entrar</button></form></main></body></html>
"""


FILE_PASSWORD_HTML = r"""
<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Archivo protegido</title><style>{{ base_css|safe }}</style></head><body><main class="auth"><h1>Archivo protegido</h1>
<p>Introduce la contrasena de este archivo para descargarlo.</p>{% if error %}<div class="error">{{ error }}</div>{% endif %}
<form method="post" action="{{ url_for('unlock_file', token=token, file_id=file_id) }}"><input name="password" type="password" placeholder="Contrasena" autofocus>
<button type="submit">Desbloquear</button></form></main></body></html>
"""


CLIENT_HTML = r"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>File Transfer Easy</title>
  <style>
    :root{--bg:#eef3f6;--surface:#fff;--ink:#17212b;--muted:#607080;--line:#dce6ec;--teal:#0f8a7a;--teal-dark:#0b6c61;--coral:#ec6d5f;--shadow:0 18px 45px rgba(23,33,43,.1)}
    *{box-sizing:border-box}body{margin:0;min-height:100vh;font-family:"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--ink);letter-spacing:0}.shell{width:min(1120px,calc(100% - 32px));margin:0 auto;padding:30px 0 38px}.topbar{display:grid;grid-template-columns:1fr auto;gap:18px;align-items:end;padding-bottom:20px}.eyebrow{color:var(--teal-dark);font-weight:750;margin:0 0 8px}h1{margin:0;font-size:2rem;line-height:1.1}.subtitle{margin:10px 0 0;color:var(--muted);line-height:1.5}.stats{display:flex;gap:10px}.stat,.file-card,.tool-panel,.empty{background:var(--surface);border:1px solid var(--line);border-radius:8px;box-shadow:var(--shadow)}.stat{min-width:112px;padding:12px 14px}.stat strong{display:block;font-size:1.2rem}.stat span{color:var(--muted);font-size:.85rem}.layout{display:grid;grid-template-columns:minmax(0,1fr)340px;gap:18px;align-items:start}.file-list{display:grid;gap:10px}.file-card{display:grid;grid-template-columns:44px minmax(0,1fr) auto;gap:14px;align-items:center;padding:14px}.file-icon{width:44px;height:44px;border-radius:8px;background:#d8f3ea;color:var(--teal-dark);display:grid;place-items:center;font-weight:800;border:1px solid #b9e5da}.file-title{min-width:0}.file-title a{color:var(--ink);text-decoration:none;font-weight:750;overflow-wrap:anywhere}.file-meta{color:var(--muted);display:flex;flex-wrap:wrap;gap:8px 12px;margin-top:6px;font-size:.92rem}.download,.upload-button{border:0;border-radius:8px;color:#fff;background:var(--teal);padding:11px 14px;min-width:112px;cursor:pointer;font-weight:760;text-decoration:none;text-align:center}.download:hover{background:var(--teal-dark)}.tool-panel{padding:18px;position:sticky;top:16px}.tool-panel h2{margin:0;font-size:1.15rem}.tool-panel p{margin:8px 0 0;color:var(--muted);line-height:1.45}.secondary{display:block;text-align:center;border:1px solid var(--line);color:var(--ink);background:#f7fafb;border-radius:8px;padding:11px 14px;text-decoration:none;font-weight:720;margin-top:12px}.upload-zone{margin-top:18px;border:2px dashed #95cfc5;background:#f4fbf9;border-radius:8px;padding:18px;text-align:center}.upload-zone.drag{border-color:var(--coral);background:#fff3f1}.file-input{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}.notice,.unlock{margin-top:12px;padding:12px;border-radius:8px;background:#fff8df;color:#684a08;border:1px solid #efd997;font-size:.94rem}.unlock input{width:100%;padding:10px;border:1px solid var(--line);border-radius:8px;margin:8px 0}.unlock button{width:100%;border:0;border-radius:8px;background:var(--ink);color:#fff;padding:10px;font-weight:750}.message{min-height:22px;margin-top:12px;color:var(--muted);font-size:.94rem}.empty{min-height:260px;display:grid;place-items:center;text-align:center;padding:28px}.empty span{color:var(--muted)}@media(max-width:860px){.topbar,.layout{grid-template-columns:1fr}.tool-panel{position:static}}@media(max-width:620px){.shell{width:min(100% - 20px,1120px);padding-top:18px}h1{font-size:1.55rem}.file-card{grid-template-columns:40px minmax(0,1fr)}.download{grid-column:1/-1;width:100%}.stats{flex-direction:column}}
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div><p class="eyebrow">Sesion privada</p><h1>Archivos compartidos</h1>
      <p class="subtitle">Descarga lo que necesites. El host puede proteger la sesion completa y tambien archivos concretos.</p></div>
      <div class="stats"><div class="stat"><strong>{{ file_count }}</strong><span>archivos</span></div><div class="stat"><strong>{{ total_size_text }}</strong><span>total</span></div></div>
    </header>
    <section class="layout">
      <div class="file-list">
        {% if files %}
          {% for item in files %}
            <article class="file-card">
              <div class="file-icon" aria-hidden="true">{{ item.display_name[:1].upper() or "F" }}</div>
              <div class="file-title">
                <a href="{{ url_for('download_file', token=token, file_id=item.id) }}">{{ item.display_name }}</a>
                <div class="file-meta"><span>{{ format_bytes(item.size) }}</span><span>{{ item.source }}</span><span>{{ format_mtime(item.mtime) }}</span>{% if item.protected %}<span>protegido</span>{% endif %}</div>
                {% if item.protected and item.id not in unlocked_files %}
                  <form class="unlock" method="post" action="{{ url_for('unlock_file', token=token, file_id=item.id) }}">
                    <input name="password" type="password" placeholder="Contrasena de este archivo">
                    <button type="submit">Desbloquear y descargar</button>
                  </form>
                {% endif %}
              </div>
              {% if not item.protected or item.id in unlocked_files %}
                <a class="download" href="{{ url_for('download_file', token=token, file_id=item.id) }}">Descargar</a>
              {% endif %}
            </article>
          {% endfor %}
        {% else %}
          <div class="empty"><div><strong>No hay archivos todavia</strong><br><span>El host puede anadir archivos desde la app.</span></div></div>
        {% endif %}
      </div>
      <aside class="tool-panel">
        <h2>Acciones</h2>
        <p>Las descargas salen directamente del ordenador host mientras la app siga abierta.</p>
        {% if files %}<a class="secondary" href="{{ url_for('download_all', token=token) }}">Descargar ZIP permitido</a>{% endif %}
        {% if upload_enabled %}
          <form class="upload-zone" id="upload-zone"><strong>Subir archivos</strong><p>Arrastra archivos aqui o usa el selector.</p>
          <input class="file-input" id="file-input" name="files" type="file" multiple><button class="upload-button" type="button" id="choose-files">Elegir archivos</button><div class="message" id="message"></div></form>
        {% else %}
          <div class="notice">Las subidas estan desactivadas por el host.</div>
        {% endif %}
      </aside>
    </section>
  </main>
  {% if upload_enabled %}
  <script>
    const zone=document.getElementById("upload-zone"),input=document.getElementById("file-input"),button=document.getElementById("choose-files"),message=document.getElementById("message");
    button.addEventListener("click",()=>input.click());input.addEventListener("change",()=>uploadFiles(input.files));
    ["dragenter","dragover"].forEach(n=>zone.addEventListener(n,e=>{e.preventDefault();zone.classList.add("drag")}));["dragleave","drop"].forEach(n=>zone.addEventListener(n,e=>{e.preventDefault();zone.classList.remove("drag")}));
    zone.addEventListener("drop",e=>uploadFiles(e.dataTransfer.files));
    async function uploadFiles(files){if(!files||files.length===0)return;const formData=new FormData();for(const file of files){formData.append("files",file)}message.textContent="Subiendo...";try{const response=await fetch("{{ url_for('upload', token=token) }}",{method:"POST",body:formData});const data=await response.json();message.textContent=data.message||"Operacion completada.";if(response.ok)setTimeout(()=>window.location.reload(),900)}catch(error){message.textContent="No se pudo subir. Comprueba que la app del host sigue abierta."}finally{input.value=""}}
  </script>
  {% endif %}
</body>
</html>
"""


BASE_AUTH_CSS = """
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#eef3f6;font-family:"Segoe UI",system-ui,sans-serif;color:#17212b}
.auth{width:min(420px,calc(100% - 28px));background:#fff;border:1px solid #dce6ec;border-radius:8px;padding:24px;box-shadow:0 18px 45px rgba(23,33,43,.1)}
h1{margin:0 0 8px;font-size:1.6rem}p{color:#607080;line-height:1.45}input{width:100%;padding:12px;border:1px solid #dce6ec;border-radius:8px;margin:8px 0 12px}
button{width:100%;padding:12px;border:0;border-radius:8px;background:#0f8a7a;color:#fff;font-weight:760}.error{background:#ffe3df;border:1px solid #f3b2aa;color:#7b2016;padding:10px;border-radius:8px;margin:10px 0}
"""


@contextlib.contextmanager
def inject_auth_css():
    yield


def main() -> int:
    if not run_dependency_bootstrap_if_needed():
        return 1
    globals()["base_css"] = BASE_AUTH_CSS
    root = tk.Tk()
    FileTransferApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
