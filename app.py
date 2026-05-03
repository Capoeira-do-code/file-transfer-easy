from __future__ import annotations

import contextlib
import csv
import hashlib
import hmac
import importlib
import io
import json
import mimetypes
import os
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

APP_NAME = "File Transfer Easy"
APP_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "FileTransferEasy"
DB_PATH = APP_DIR / "file_transfer_easy.db"
LOCAL_BIN_DIR = APP_DIR / "bin"
SETTINGS_PATH = APP_DIR / "settings.json"
DEFAULT_UPLOAD_DIR = Path.home() / "Downloads" / "File Transfer Easy Uploads"
DEFAULT_PORT_CANDIDATES = [80, 8080, 8000, 5000]
TAILSCALE_PUBLIC_PORTS = ["443", "8443", "10000"]
REQUIRED_MODULES = {"flask": "Flask", "waitress": "waitress", "PySide6": "PySide6"}
INSTALL_CLOUDFLARED_COMMAND = (
    "winget install --id Cloudflare.cloudflared "
    "--accept-package-agreements --accept-source-agreements"
)
CLOUDFLARED_WINDOWS_AMD64_URL = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-windows-amd64.exe"
)
CHUNK_SIZE = 256 * 1024

DEFAULT_PREFERENCES = {
    "save_preferences": False,
    "ui_language": "en",
    "mode": "auto",
    "port": "80",
    "manual_port": False,
    "tailscale_public_port": "443",
    "upload_enabled": False,
    "upload_dir": str(DEFAULT_UPLOAD_DIR),
    "include_subfolders": False,
    "file_paths": [],
    "folders": [],
    "expiration_minutes": 0,
    "download_limit_per_file": 0,
    "uploads_require_global": False,
}

UI_LANGUAGES = ("en", "es")

I18N = {
    "en": {
        "qt": {
            "language_label": "Language",
            "language_en": "English",
            "language_es": "Spanish",
            "status_prefix": "Status",
            "status_ready": "Ready",
            "status_starting": "Starting",
            "status_published": "Published",
            "status_local": "Local",
            "status_stopped": "Stopped",
            "status_error": "Error",
            "status_active_transfer": "Active",
            "status_canceling_transfer": "Canceling",
            "status_completed_transfer": "Completed",
            "status_cancelled_transfer": "Cancelled",
            "status_interrupted_transfer": "Interrupted",
            "status_error_transfer": "Failed",
            "tab_files": "Files",
            "tab_publish": "Publish",
            "tab_security": "Security",
            "tab_activity": "Activity",
            "btn_add_files": "Add Files",
            "btn_add_folder": "Add Folder",
            "btn_remove_files": "Remove Files",
            "btn_remove_folders": "Remove Folders",
            "btn_refresh_folder": "Refresh Folder",
            "include_subfolders": "Include Subfolders",
            "files_name": "Name",
            "files_size": "Size",
            "files_source": "Source",
            "files_protected": "Protected",
            "files_date": "Date",
            "folders_name": "Folder",
            "folders_count": "Files",
            "folders_size": "Size",
            "folders_protected": "Protected",
            "publish_mode": "Mode",
            "publish_port": "Local Port",
            "publish_manual_port": "Use Exact Port",
            "publish_tailscale_port": "Tailscale Public Port",
            "publish_uploads": "Allow Uploads",
            "publish_upload_dir": "Upload Folder",
            "btn_choose": "Choose",
            "btn_publish": "Publish Now",
            "btn_stop": "Stop",
            "btn_copy_url": "Copy URL",
            "security_global_password": "Global Password",
            "security_selection_password": "Selection Password",
            "btn_apply_global": "Set Global",
            "btn_clear_global": "Clear Global",
            "btn_apply_file_password": "Protect Files",
            "btn_clear_file_password": "Unprotect Files",
            "btn_apply_folder_password": "Protect Folders",
            "btn_clear_folder_password": "Unprotect Folders",
            "security_expire_minutes": "Link Expiration Minutes (0 = never)",
            "security_download_limit": "Per-File Download Limit (0 = unlimited)",
            "security_uploads_require_global": "Uploads Require Global Password",
            "btn_save_security": "Save Security Rules",
            "ip_placeholder": "IP (e.g. 1.2.3.4)",
            "btn_block_ip": "Block IP",
            "btn_unblock_ip": "Unblock IP",
            "activity_cancel": "Cancel Selected Download",
            "activity_export": "Export CSV",
            "activity_completed": "Completed",
            "activity_cancelled": "Cancelled",
            "activity_failed": "Failed",
            "activity_type": "Type",
            "activity_file": "File",
            "activity_ip": "IP",
            "activity_progress": "Progress",
            "activity_speed": "Speed",
            "activity_status": "Status",
            "history_time": "Time",
            "history_type": "Type",
            "history_file": "File",
            "history_status": "Status",
            "history_reason": "Reason",
            "history_bytes": "Bytes",
            "history_ip": "IP",
            "logs_title": "Logs",
            "history_reason_none": "-",
            "protected_yes": "Yes",
            "protected_no": "No",
            "mode_auto": "Automatic",
            "mode_tailscale": "Tailscale Funnel",
            "mode_cloudflare": "Cloudflare Quick Tunnel",
            "mode_direct": "Direct Port",
            "context_remove": "Remove",
            "context_protect": "Protect",
            "context_unprotect": "Unprotect",
            "context_open_location": "Open Location",
            "context_copy_link": "Copy Link",
            "context_refresh": "Refresh",
            "password_prompt_title": "Set Password",
            "password_prompt_file": "Password for selected file(s):",
            "password_prompt_folder": "Password for selected folder(s):",
            "error_select_file": "Select at least one file.",
            "error_select_folder": "Select at least one folder.",
            "error_no_url": "No share URL is available yet.",
            "exit_confirm": "Services are still running. Stop everything and exit?",
            "security_summary": "Blocked IPs: {ips}",
            "security_on": "ON",
            "security_off": "OFF",
            "indicator_global_password": "Global Password",
            "indicator_upload_guard": "Upload Guard",
            "indicator_protected_files": "Protected Files",
            "indicator_protected_folders": "Protected Folders",
            "activity_log_title": "Activity Log",
            "recommendation_empty": "Start by adding files or a folder.",
            "recommendation_ready": "Link is ready. Copy it or stop publishing.",
            "recommendation_uploads": "Uploads are enabled. Verify target folder before publishing.",
            "recommendation_publish": "Ready to publish with Automatic mode.",
        },
        "web": {
            "auth_title": "Protected Access",
            "auth_message": "Enter the global password to view this shared session.",
            "auth_password_placeholder": "Password",
            "auth_submit": "Enter",
            "file_lock_title": "Protected File",
            "file_lock_message": "Enter the file or folder password to download this file.",
            "file_lock_submit": "Unlock",
            "folder_lock_submit": "Unlock Folder",
            "folder_lock_message": "Enter this folder password.",
            "wrong_password": "Incorrect password.",
            "session_title": "Private Session",
            "shared_files_title": "Shared Files",
            "shared_files_subtitle": "Download host files. Upload and password rules update in real time.",
            "files_count": "files",
            "total_size": "total",
            "badge_protected": "protected",
            "download_label": "Download",
            "empty_title": "No files yet",
            "empty_subtitle": "The host can add files from the admin panel.",
            "actions_title": "Actions",
            "actions_subtitle": "This session remains available while the host app is running.",
            "download_zip_label": "Download ( ZIP )",
            "folders_title": "Folders",
            "folder_password_placeholder": "Folder password",
            "folder_ok": "OK",
            "folder_files": "files",
            "uploads_disabled": "Host disabled uploads.",
            "upload_title": "Upload Files",
            "upload_help": "Drag files here or use the picker.",
            "upload_choose": "Choose Files",
            "unlock_file_placeholder": "File or folder password",
            "upload_msg_disabled": "Host disabled uploads.",
            "upload_msg_sending": "Uploading...",
            "upload_msg_done": "Operation completed.",
            "upload_msg_failed": "Upload failed. Verify the host app is still running.",
            "upload_guard_message": "Unlock the session first.",
            "upload_global_guard": "Uploads require global password.",
            "upload_disabled_server": "Uploads are disabled.",
            "upload_empty": "No file was received.",
            "upload_no_valid": "No valid files were provided.",
            "download_limit_message": "Download limit reached for this file.",
            "download_none_message": "No unlocked files are available for download.",
            "zip_name": "file-transfer-easy.zip",
            "status_yes": "Yes",
            "status_no": "No",
        },
    },
    "es": {
        "qt": {
            "language_label": "Idioma",
            "language_en": "Ingles",
            "language_es": "Espanol",
            "status_prefix": "Estado",
            "status_ready": "Preparado",
            "status_starting": "Iniciando",
            "status_published": "Publicado",
            "status_local": "Local",
            "status_stopped": "Detenido",
            "status_error": "Error",
            "status_active_transfer": "Activa",
            "status_canceling_transfer": "Cancelando",
            "status_completed_transfer": "Completada",
            "status_cancelled_transfer": "Cancelada",
            "status_interrupted_transfer": "Interrumpida",
            "status_error_transfer": "Fallida",
            "tab_files": "Archivos",
            "tab_publish": "Publicacion",
            "tab_security": "Seguridad",
            "tab_activity": "Actividad",
            "btn_add_files": "Anadir archivos",
            "btn_add_folder": "Anadir carpeta",
            "btn_remove_files": "Quitar archivos",
            "btn_remove_folders": "Quitar carpetas",
            "btn_refresh_folder": "Refrescar carpeta",
            "include_subfolders": "Incluir subcarpetas",
            "files_name": "Nombre",
            "files_size": "Tamano",
            "files_source": "Origen",
            "files_protected": "Protegido",
            "files_date": "Fecha",
            "folders_name": "Carpeta",
            "folders_count": "Archivos",
            "folders_size": "Tamano",
            "folders_protected": "Protegida",
            "publish_mode": "Modo",
            "publish_port": "Puerto local",
            "publish_manual_port": "Usar exactamente este puerto",
            "publish_tailscale_port": "Puerto publico Tailscale",
            "publish_uploads": "Permitir subidas",
            "publish_upload_dir": "Carpeta de subidas",
            "btn_choose": "Elegir",
            "btn_publish": "Publicar ahora",
            "btn_stop": "Detener",
            "btn_copy_url": "Copiar URL",
            "security_global_password": "Contrasena global",
            "security_selection_password": "Contrasena para seleccion",
            "btn_apply_global": "Aplicar global",
            "btn_clear_global": "Quitar global",
            "btn_apply_file_password": "Proteger archivos",
            "btn_clear_file_password": "Desproteger archivos",
            "btn_apply_folder_password": "Proteger carpetas",
            "btn_clear_folder_password": "Desproteger carpetas",
            "security_expire_minutes": "Expirar enlace en minutos (0 = nunca)",
            "security_download_limit": "Limite por archivo (0 = sin limite)",
            "security_uploads_require_global": "Subidas requieren contrasena global",
            "btn_save_security": "Guardar reglas de seguridad",
            "ip_placeholder": "IP (ej: 1.2.3.4)",
            "btn_block_ip": "Bloquear IP",
            "btn_unblock_ip": "Desbloquear IP",
            "activity_cancel": "Anular descarga seleccionada",
            "activity_export": "Exportar CSV",
            "activity_completed": "Completada",
            "activity_cancelled": "Cancelada",
            "activity_failed": "Fallida",
            "activity_type": "Tipo",
            "activity_file": "Archivo",
            "activity_ip": "IP",
            "activity_progress": "Progreso",
            "activity_speed": "Velocidad",
            "activity_status": "Estado",
            "history_time": "Hora",
            "history_type": "Tipo",
            "history_file": "Archivo",
            "history_status": "Estado",
            "history_reason": "Detalle",
            "history_bytes": "Bytes",
            "history_ip": "IP",
            "logs_title": "Logs",
            "history_reason_none": "-",
            "protected_yes": "Si",
            "protected_no": "No",
            "mode_auto": "Automatico",
            "mode_tailscale": "Tailscale Funnel",
            "mode_cloudflare": "Cloudflare Quick Tunnel",
            "mode_direct": "Puerto propio",
            "context_remove": "Quitar",
            "context_protect": "Proteger",
            "context_unprotect": "Desproteger",
            "context_open_location": "Abrir ubicacion",
            "context_copy_link": "Copiar enlace",
            "context_refresh": "Refrescar",
            "password_prompt_title": "Definir contrasena",
            "password_prompt_file": "Contrasena para archivo(s) seleccionado(s):",
            "password_prompt_folder": "Contrasena para carpeta(s) seleccionada(s):",
            "error_select_file": "Selecciona al menos un archivo.",
            "error_select_folder": "Selecciona al menos una carpeta.",
            "error_no_url": "Todavia no hay una URL publicada.",
            "exit_confirm": "Hay servicios activos. Quieres detener todo y salir?",
            "security_summary": "IPs bloqueadas: {ips}",
            "security_on": "ACTIVA",
            "security_off": "INACTIVA",
            "indicator_global_password": "Contrasena global",
            "indicator_upload_guard": "Guardia de subida",
            "indicator_protected_files": "Archivos protegidos",
            "indicator_protected_folders": "Carpetas protegidas",
            "activity_log_title": "Registro de actividad",
            "recommendation_empty": "Empieza anadiendo archivos o una carpeta.",
            "recommendation_ready": "Enlace listo. Puedes copiarlo o detener la publicacion.",
            "recommendation_uploads": "Subidas activadas. Revisa la carpeta de destino antes de publicar.",
            "recommendation_publish": "Todo listo para publicar con modo automatico.",
        },
        "web": {
            "auth_title": "Acceso protegido",
            "auth_message": "Introduce la contraseña global para ver esta sesión compartida.",
            "auth_password_placeholder": "Contraseña",
            "auth_submit": "Entrar",
            "file_lock_title": "Archivo protegido",
            "file_lock_message": "Introduce la contraseña del archivo o de su carpeta para descargarlo.",
            "file_lock_submit": "Desbloquear",
            "folder_lock_submit": "Desbloquear carpeta",
            "folder_lock_message": "Introduce la contraseña de esta carpeta.",
            "wrong_password": "Contraseña incorrecta.",
            "session_title": "Sesión privada",
            "shared_files_title": "Archivos compartidos",
            "shared_files_subtitle": "Descarga archivos del host. Las reglas de subidas y contraseñas se actualizan en vivo.",
            "files_count": "archivos",
            "total_size": "total",
            "badge_protected": "protegido",
            "download_label": "Descargar",
            "empty_title": "No hay archivos todavía",
            "empty_subtitle": "El host puede añadir archivos desde el panel admin.",
            "actions_title": "Acciones",
            "actions_subtitle": "La sesión se mantiene disponible mientras la app del host siga abierta.",
            "download_zip_label": "Descargar ( ZIP )",
            "folders_title": "Carpetas",
            "folder_password_placeholder": "Contraseña de carpeta",
            "folder_ok": "OK",
            "folder_files": "archivos",
            "uploads_disabled": "El host desactivó las subidas.",
            "upload_title": "Subir archivos",
            "upload_help": "Arrastra archivos aquí o usa el selector.",
            "upload_choose": "Elegir archivos",
            "unlock_file_placeholder": "Contraseña del archivo o carpeta",
            "upload_msg_disabled": "El host desactivó las subidas.",
            "upload_msg_sending": "Subiendo...",
            "upload_msg_done": "Operación completada.",
            "upload_msg_failed": "No se pudo subir. Comprueba que la app del host siga abierta.",
            "upload_guard_message": "Desbloquea la sesión primero.",
            "upload_global_guard": "Las subidas requieren contraseña global.",
            "upload_disabled_server": "Las subidas están desactivadas.",
            "upload_empty": "No se recibió ningún archivo.",
            "upload_no_valid": "No había archivos válidos.",
            "download_limit_message": "Límite de descargas alcanzado para este archivo.",
            "download_none_message": "No hay archivos desbloqueados para descargar.",
            "zip_name": "file-transfer-easy.zip",
            "status_yes": "Si",
            "status_no": "No",
        },
    },
}


def normalize_ui_language(raw: str | None) -> str:
    language = str(raw or "en").strip().lower()
    return language if language in UI_LANGUAGES else "en"


def i18n_bundle(language: str) -> dict:
    return I18N[normalize_ui_language(language)]


def normalize_status_code(status: str | None) -> str:
    value = str(status or "").strip().lower()
    mapping = {
        "ready": "ready",
        "starting": "starting",
        "published": "published",
        "local": "local",
        "stopped": "stopped",
        "error": "error",
        "preparado": "ready",
        "iniciando": "starting",
        "publicado": "published",
        "detenido": "stopped",
    }
    return mapping.get(value, "ready")


def localize_controller_status(status: str, labels: dict) -> str:
    status_code = normalize_status_code(status)
    return labels.get(f"status_{status_code}", labels.get("status_ready", "Ready"))


def localize_transfer_status(status: str, labels: dict) -> str:
    mapping = {
        "activa": "status_active_transfer",
        "cancelando": "status_canceling_transfer",
        "completada": "status_completed_transfer",
        "cancelada": "status_cancelled_transfer",
        "interrumpida": "status_interrupted_transfer",
        "error": "status_error_transfer",
    }
    key = mapping.get(str(status or "").strip().lower())
    return labels.get(key, str(status or "")) if key else str(status or "")


def localize_event_type(event_type: str, labels: dict, language: str | None = None) -> str:
    mapping = {
        "download": {"en": "Download", "es": "Descarga"},
        "download_zip": {"en": "ZIP", "es": "ZIP"},
        "upload": {"en": "Upload", "es": "Subida"},
    }
    language = normalize_ui_language(language) if language else ("es" if labels.get("language_label") == "Idioma" else "en")
    table = mapping.get(str(event_type or "").strip().lower())
    return table[language] if table else str(event_type or "")


def is_failed_transfer_status(status: str) -> bool:
    return str(status or "").strip().lower() in {"error", "interrumpida"}

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


def load_preferences(path: Path | None = None) -> dict:
    path = path or SETTINGS_PATH
    if not path.exists():
        return dict(DEFAULT_PREFERENCES)
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_PREFERENCES)
    if not isinstance(loaded, dict):
        return dict(DEFAULT_PREFERENCES)
    preferences = dict(DEFAULT_PREFERENCES)
    for key, value in loaded.items():
        if key in preferences:
            preferences[key] = value
    return preferences


def save_preferences(preferences: dict, path: Path | None = None) -> None:
    path = path or SETTINGS_PATH
    safe = sanitize_preferences(preferences)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(safe, handle, indent=2, ensure_ascii=True)


def delete_preferences(path: Path | None = None) -> None:
    path = path or SETTINGS_PATH
    with contextlib.suppress(OSError):
        path.unlink()


def sanitize_preferences(raw: dict) -> dict:
    def as_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    preferences = dict(DEFAULT_PREFERENCES)
    preferences["save_preferences"] = bool(raw.get("save_preferences"))
    preferences["ui_language"] = normalize_ui_language(str(raw.get("ui_language") or "en"))
    preferences["mode"] = str(raw.get("mode") or "auto")
    if preferences["mode"] not in {"auto", "tailscale", "cloudflare", "direct"}:
        preferences["mode"] = "auto"
    preferences["port"] = str(raw.get("port") or "80")
    preferences["manual_port"] = bool(raw.get("manual_port"))
    preferences["tailscale_public_port"] = str(raw.get("tailscale_public_port") or "443")
    if preferences["tailscale_public_port"] not in TAILSCALE_PUBLIC_PORTS:
        preferences["tailscale_public_port"] = "443"
    preferences["upload_enabled"] = bool(raw.get("upload_enabled"))
    preferences["upload_dir"] = str(raw.get("upload_dir") or DEFAULT_UPLOAD_DIR)
    preferences["include_subfolders"] = bool(raw.get("include_subfolders"))
    preferences["file_paths"] = [
        str(path) for path in raw.get("file_paths", []) if isinstance(path, str) and path.strip()
    ]
    folders = []
    for folder in raw.get("folders", []):
        if isinstance(folder, str):
            folders.append({"path": folder, "include_subfolders": preferences["include_subfolders"]})
        elif isinstance(folder, dict) and folder.get("path"):
            folders.append(
                {
                    "path": str(folder.get("path")),
                    "include_subfolders": bool(folder.get("include_subfolders")),
                }
            )
    preferences["folders"] = folders
    preferences["expiration_minutes"] = as_int(raw.get("expiration_minutes"), 0)
    preferences["download_limit_per_file"] = as_int(raw.get("download_limit_per_file"), 0)
    preferences["uploads_require_global"] = bool(raw.get("uploads_require_global"))
    return preferences


def preferences_without_secrets(preferences: dict) -> dict:
    safe = sanitize_preferences(preferences)
    for forbidden in [
        "password",
        "global_password",
        "file_password",
        "folder_password",
        "token",
        "password_hash",
        "global_password_hash",
    ]:
        safe.pop(forbidden, None)
    return safe


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
    remaining = missing_runtime_modules()
    if remaining:
        raise RuntimeError("Siguen faltando dependencias: " + ", ".join(remaining))


def show_native_notice(title: str, message: str, error: bool = False) -> None:
    if os.name == "nt":
        with contextlib.suppress(Exception):
            import ctypes

            style = 0x00010000  # MB_SETFOREGROUND
            style |= 0x00000010 if error else 0x00000040  # MB_ICONERROR / MB_ICONINFORMATION
            ctypes.windll.user32.MessageBoxW(0, message, title, style)
            return
    stream = sys.stderr if error else sys.stdout
    print(f"[{title}] {message}", file=stream)


def run_dependency_bootstrap_if_needed() -> bool:
    missing = missing_runtime_modules()
    if not missing:
        return import_web_dependencies()

    try:
        install_python_dependencies()
    except Exception as exc:
        show_native_notice(
            APP_NAME,
            (
                "No se pudieron instalar las dependencias automaticamente.\n\n"
                f"Detalle: {exc}\n\n"
                "Ejecuta iniciar.bat o instala requirements.txt manualmente."
            ),
            error=True,
        )
        return False

    if not import_web_dependencies():
        show_native_notice(
            APP_NAME,
            "Las dependencias se instalaron, pero no se pudieron cargar.",
            error=True,
        )
        return False

    show_native_notice(
        APP_NAME,
        "Dependencias instaladas correctamente. Iniciando la app.",
        error=False,
    )
    return True


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
    folder_id: str | None = None

    @classmethod
    def from_path(
        cls,
        path: Path,
        source: str = "Host",
        password: str = "",
        folder_id: str | None = None,
    ) -> "SharedFile":
        stat = path.stat()
        return cls(
            id=uuid.uuid4().hex,
            display_name=path.name,
            path=str(path.resolve()),
            size=stat.st_size,
            mtime=stat.st_mtime,
            source=source,
            password_hash=make_password_hash(password) if password else None,
            folder_id=folder_id,
        )

    @property
    def protected(self) -> bool:
        return bool(self.password_hash)


@dataclass
class FolderShare:
    id: str
    name: str
    path: str
    include_subfolders: bool
    password_hash: str | None = None
    updated_at: str = ""

    @property
    def protected(self) -> bool:
        return bool(self.password_hash)


class ShareState:
    def __init__(self) -> None:
        self.token = secrets.token_urlsafe(18)
        self._ui_language = "en"
        self._upload_enabled = False
        self._upload_dir = str(DEFAULT_UPLOAD_DIR)
        self._shared_folder = ""
        self._include_subfolders = False
        self._global_password_hash: str | None = None
        self._files: dict[str, SharedFile] = {}
        self._folders: dict[str, FolderShare] = {}
        self._expires_at: float | None = None
        self._download_limit_per_file: int | None = None
        self._download_counts: dict[str, int] = {}
        self._blocked_ips: set[str] = set()
        self._uploads_require_global = False
        self._lock = threading.RLock()

    def add_paths(
        self,
        paths: Iterable[str],
        source: str = "Host",
        password: str = "",
        folder_id: str | None = None,
    ) -> tuple[int, list[str]]:
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
                    item = SharedFile.from_path(
                        resolved,
                        source=source,
                        password=password,
                        folder_id=folder_id,
                    )
                    self._files[item.id] = item
                    existing.add(resolved)
                    added += 1
                except OSError as exc:
                    errors.append(f"{path.name}: {exc}")
        return added, errors

    def add_folder(
        self,
        folder: str,
        include_subfolders: bool = False,
        password: str = "",
    ) -> tuple[int, list[str]]:
        folder_path = Path(folder).expanduser()
        if not folder_path.is_dir():
            return 0, [f"{folder}: no es una carpeta."]
        folder_share = FolderShare(
            id=uuid.uuid4().hex,
            name=folder_path.name or str(folder_path),
            path=str(folder_path.resolve()),
            include_subfolders=bool(include_subfolders),
            password_hash=make_password_hash(password) if password else None,
            updated_at=now_iso(),
        )
        with self._lock:
            self._folders[folder_share.id] = folder_share
        return self.refresh_folder(folder_share.id)

    def refresh_folder(self, folder_id: str) -> tuple[int, list[str]]:
        with self._lock:
            folder_share = self._folders.get(folder_id)
        if not folder_share:
            return 0, ["Carpeta no encontrada."]
        folder = Path(folder_share.path)
        paths = list(iter_folder_files(folder, folder_share.include_subfolders))
        return self.add_paths(
            [str(path) for path in paths],
            source=folder_share.name,
            folder_id=folder_share.id,
        )

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
            self._folders.clear()

    def get(self, file_id: str) -> SharedFile | None:
        with self._lock:
            return self._files.get(file_id)

    def snapshot(self) -> list[SharedFile]:
        with self._lock:
            return list(self._files.values())

    def folders_snapshot(self) -> list[FolderShare]:
        with self._lock:
            return list(self._folders.values())

    def get_folder(self, folder_id: str) -> FolderShare | None:
        with self._lock:
            return self._folders.get(folder_id)

    def remove_folder(self, folder_id: str, remove_files: bool = True) -> bool:
        with self._lock:
            removed = self._folders.pop(folder_id, None)
            if removed and remove_files:
                for file_id in [
                    item.id for item in self._files.values() if item.folder_id == folder_id
                ]:
                    self._files.pop(file_id, None)
        return removed is not None

    def has_files(self) -> bool:
        with self._lock:
            return bool(self._files)

    def set_ui_language(self, language: str) -> None:
        with self._lock:
            self._ui_language = normalize_ui_language(language)

    def ui_language(self) -> str:
        with self._lock:
            return self._ui_language

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

    def set_folder_passwords(self, folder_ids: Iterable[str], password: str) -> int:
        new_hash = make_password_hash(password) if password else None
        updated = 0
        with self._lock:
            for folder_id in folder_ids:
                folder = self._folders.get(folder_id)
                if folder:
                    folder.password_hash = new_hash
                    updated += 1
        return updated

    def effective_password_hash(self, item: SharedFile) -> str | None:
        with self._lock:
            if item.password_hash:
                return item.password_hash
            if item.folder_id and item.folder_id in self._folders:
                return self._folders[item.folder_id].password_hash
        return None

    def item_is_protected(self, item: SharedFile) -> bool:
        return bool(self.effective_password_hash(item))

    def verify_effective_file_password(self, file_id: str, password: str) -> str | None:
        item = self.get(file_id)
        if not item:
            return None
        with self._lock:
            if item.password_hash and verify_password(password, item.password_hash):
                return "file"
            if item.folder_id:
                folder = self._folders.get(item.folder_id)
                if folder and folder.password_hash and verify_password(password, folder.password_hash):
                    return "folder"
        return None

    def configure_security_options(
        self,
        expiration_minutes: int | None = None,
        download_limit_per_file: int | None = None,
        uploads_require_global: bool = False,
    ) -> None:
        with self._lock:
            self._expires_at = (
                time.time() + expiration_minutes * 60
                if expiration_minutes and expiration_minutes > 0
                else None
            )
            self._download_limit_per_file = (
                download_limit_per_file if download_limit_per_file and download_limit_per_file > 0 else None
            )
            self._uploads_require_global = bool(uploads_require_global)

    def security_options(self) -> dict:
        with self._lock:
            return {
                "expires_at": self._expires_at,
                "expires_at_text": format_mtime(self._expires_at) if self._expires_at else "",
                "download_limit_per_file": self._download_limit_per_file or 0,
                "uploads_require_global": self._uploads_require_global,
                "blocked_ips": sorted(self._blocked_ips),
            }

    def link_expired(self) -> bool:
        with self._lock:
            return bool(self._expires_at and time.time() > self._expires_at)

    def uploads_require_global(self) -> bool:
        with self._lock:
            return self._uploads_require_global

    def block_ip(self, ip: str) -> None:
        ip = ip.strip()
        if ip:
            with self._lock:
                self._blocked_ips.add(ip)

    def unblock_ip(self, ip: str) -> None:
        with self._lock:
            self._blocked_ips.discard(ip.strip())

    def ip_blocked(self, ip: str) -> bool:
        with self._lock:
            return ip in self._blocked_ips

    def download_limit_reached(self, file_id: str) -> bool:
        with self._lock:
            if not self._download_limit_per_file:
                return False
            return self._download_counts.get(file_id, 0) >= self._download_limit_per_file

    def record_download_completed(self, file_id: str) -> None:
        with self._lock:
            self._download_counts[file_id] = self._download_counts.get(file_id, 0) + 1


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


def file_view(item: SharedFile, state: ShareState) -> dict:
    folder = state.get_folder(item.folder_id) if item.folder_id else None
    protected = state.item_is_protected(item)
    return {
        "id": item.id,
        "display_name": item.display_name,
        "path": item.path,
        "size": item.size,
        "size_text": format_bytes(item.size),
        "mtime": item.mtime,
        "mtime_text": format_mtime(item.mtime),
        "source": item.source,
        "folder_id": item.folder_id,
        "folder_name": folder.name if folder else "",
        "file_protected": bool(item.password_hash),
        "folder_protected": bool(folder and folder.password_hash),
        "protected": protected,
    }


def folder_view(folder: FolderShare, state: ShareState) -> dict:
    files = [item for item in state.snapshot() if item.folder_id == folder.id]
    return {
        "id": folder.id,
        "name": folder.name,
        "path": folder.path,
        "include_subfolders": folder.include_subfolders,
        "protected": folder.protected,
        "updated_at": folder.updated_at,
        "file_count": len(files),
        "total_size": sum(item.size for item in files),
        "total_size_text": format_bytes(sum(item.size for item in files)),
    }


def session_global_unlocked(state: ShareState) -> bool:
    if not state.global_password_enabled():
        return True
    return bool(session.get("global_unlocked"))


def unlocked_file_ids() -> set[str]:
    return set(session.get("unlocked_files", []))


def unlocked_folder_ids() -> set[str]:
    return set(session.get("unlocked_folders", []))


def mark_file_unlocked(file_id: str) -> None:
    unlocked = unlocked_file_ids()
    unlocked.add(file_id)
    session["unlocked_files"] = sorted(unlocked)


def mark_folder_unlocked(folder_id: str) -> None:
    unlocked = unlocked_folder_ids()
    unlocked.add(folder_id)
    session["unlocked_folders"] = sorted(unlocked)


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
    web_app = Flask(APP_NAME, static_folder=None)
    web_app.secret_key = state.token
    web_app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    @web_app.after_request
    def no_store(response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response

    def current_language() -> str:
        return state.ui_language() if hasattr(state, "ui_language") else "en"

    def web_labels() -> dict:
        return i18n_bundle(current_language())["web"]

    def require_token(token: str) -> None:
        if token != state.token:
            abort(404)
        if state.link_expired():
            abort(410)

    def require_allowed_ip() -> tuple[str, str]:
        ip, ip_source = get_client_ip(request)
        if state.ip_blocked(ip):
            abort(403)
        return ip, ip_source

    def require_global_or_form(token: str):
        if session_global_unlocked(state):
            return None
        labels = web_labels()
        return render_template_string(
            CLIENT_LOGIN_HTML,
            token=token,
            error="",
            auth_css=AUTH_CSS,
            web=labels,
            lang=current_language(),
        )

    def can_download_file(item: SharedFile) -> bool:
        if not state.item_is_protected(item):
            return True
        if item.id in unlocked_file_ids():
            return True
        return bool(item.folder_id and item.folder_id in unlocked_folder_ids())

    def stream_path(path: Path, file_id: str, file_name: str, event_type: str, cleanup: bool = False):
        ip, ip_source = require_allowed_ip()
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
                if status == "completada" and event_type == "download":
                    state.record_download_completed(file_id)
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

    @web_app.get("/s/<token>/assets/client.css")
    def client_css(token: str):
        require_token(token)
        return Response(CLIENT_CSS, mimetype="text/css")

    @web_app.get("/s/<token>/assets/client.js")
    def client_js(token: str):
        require_token(token)
        return Response(CLIENT_JS, mimetype="application/javascript")

    @web_app.get("/s/<token>")
    def share_page(token: str):
        require_token(token)
        require_allowed_ip()
        locked_response = require_global_or_form(token)
        if locked_response:
            return locked_response
        labels = web_labels()
        files = state.snapshot()
        file_rows = [file_view(item, state) for item in files]
        return render_template_string(
            CLIENT_HTML,
            token=token,
            web=labels,
            lang=current_language(),
            client_text=labels,
            files=file_rows,
            folders=[folder_view(folder, state) for folder in state.folders_snapshot()],
            upload_enabled=state.uploads_enabled(),
            file_count=len(files),
            total_size_text=format_bytes(sum(item.size for item in files)),
            unlocked_files=unlocked_file_ids(),
            unlocked_folders=unlocked_folder_ids(),
        )

    @web_app.get("/s/<token>/status")
    def share_status(token: str):
        require_token(token)
        require_allowed_ip()
        return jsonify(
            {
                "ok": True,
                "upload_enabled": state.uploads_enabled(),
                "file_count": len(state.snapshot()),
                "global_locked": not session_global_unlocked(state),
            }
        )

    @web_app.post("/s/<token>/auth")
    def auth_global(token: str):
        require_token(token)
        require_allowed_ip()
        labels = web_labels()
        password = request.form.get("password", "")
        if state.verify_global_password(password):
            session["global_unlocked"] = True
            return redirect(url_for("share_page", token=token))
        return render_template_string(
            CLIENT_LOGIN_HTML,
            token=token,
            error=labels["wrong_password"],
            auth_css=AUTH_CSS,
            web=labels,
            lang=current_language(),
        ), 403

    @web_app.post("/s/<token>/unlock/<file_id>")
    def unlock_file(token: str, file_id: str):
        require_token(token)
        require_allowed_ip()
        labels = web_labels()
        if not session_global_unlocked(state):
            return redirect(url_for("share_page", token=token))
        password = request.form.get("password", "")
        scope = state.verify_effective_file_password(file_id, password)
        item = state.get(file_id)
        if scope == "file":
            mark_file_unlocked(file_id)
            return redirect(url_for("download_file", token=token, file_id=file_id))
        if scope == "folder" and item and item.folder_id:
            mark_folder_unlocked(item.folder_id)
            return redirect(url_for("download_file", token=token, file_id=file_id))
        return render_template_string(
            FILE_PASSWORD_HTML,
            token=token,
            file_id=file_id,
            error=labels["wrong_password"],
            auth_css=AUTH_CSS,
            web=labels,
            lang=current_language(),
        ), 403

    @web_app.post("/s/<token>/unlock-folder/<folder_id>")
    def unlock_folder(token: str, folder_id: str):
        require_token(token)
        require_allowed_ip()
        labels = web_labels()
        if not session_global_unlocked(state):
            return redirect(url_for("share_page", token=token))
        folder = state.get_folder(folder_id)
        if not folder:
            abort(404)
        password = request.form.get("password", "")
        if verify_password(password, folder.password_hash):
            mark_folder_unlocked(folder_id)
            return redirect(url_for("share_page", token=token))
        return render_template_string(
            FOLDER_PASSWORD_HTML,
            token=token,
            folder_id=folder_id,
            folder_name=folder.name,
            error=labels["wrong_password"],
            auth_css=AUTH_CSS,
            web=labels,
            lang=current_language(),
        ), 403

    @web_app.get("/s/<token>/download/<file_id>")
    def download_file(token: str, file_id: str):
        require_token(token)
        require_allowed_ip()
        labels = web_labels()
        if not session_global_unlocked(state):
            return redirect(url_for("share_page", token=token))
        item = state.get(file_id)
        if item is None:
            abort(404)
        if not can_download_file(item):
            return render_template_string(
                FILE_PASSWORD_HTML,
                token=token,
                file_id=file_id,
                error="",
                auth_css=AUTH_CSS,
                web=labels,
                lang=current_language(),
            )
        if state.download_limit_reached(item.id):
            return labels["download_limit_message"], 403
        path = Path(item.path)
        if not path.is_file():
            abort(404)
        return stream_path(path, item.id, item.display_name, "download")

    @web_app.get("/s/<token>/download-all")
    def download_all(token: str):
        require_token(token)
        require_allowed_ip()
        labels = web_labels()
        if not session_global_unlocked(state):
            return redirect(url_for("share_page", token=token))
        files = [item for item in state.snapshot() if can_download_file(item)]
        if not files:
            return labels["download_none_message"], 403
        zip_path = build_zip(files)
        return stream_path(zip_path, "zip", labels["zip_name"], "download_zip", cleanup=True)

    @web_app.post("/s/<token>/upload")
    def upload(token: str):
        require_token(token)
        labels = web_labels()
        ip, ip_source = require_allowed_ip()
        if not session_global_unlocked(state):
            return jsonify({"ok": False, "message": labels["upload_guard_message"]}), 403
        if state.uploads_require_global() and state.global_password_enabled() and not session.get("global_unlocked"):
            return jsonify({"ok": False, "message": labels["upload_global_guard"]}), 403
        if not state.uploads_enabled():
            return jsonify({"ok": False, "message": labels["upload_disabled_server"]}), 403
        uploaded_files = request.files.getlist("files")
        if not uploaded_files:
            return jsonify({"ok": False, "message": labels["upload_empty"]}), 400
        folder = state.upload_folder()
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
            return jsonify({"ok": False, "message": labels["upload_no_valid"]}), 400
        return jsonify({"ok": True, "message": labels["upload_msg_done"], "files": saved})

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
        self._lock = threading.RLock()

    @property
    def running(self) -> bool:
        with self._lock:
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
        self.log(f"Iniciando tunel {kind}: {' '.join(command)}")
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags(),
        )
        with self._lock:
            self.kind = kind
            self.process = process
        self.thread = threading.Thread(
            target=self._read_output,
            args=(process, kind),
            name=f"{kind}-tunnel",
            daemon=True,
        )
        self.thread.start()

    def _read_output(self, process: subprocess.Popen[str], kind: str) -> None:
        url_pattern = re.compile(r"https?://[^\s|)]+", re.IGNORECASE)
        for line in process.stdout or []:
            clean = line.strip()
            if not clean:
                continue
            self.log(clean)
            for match in url_pattern.findall(clean):
                if is_shareable_tunnel_url(kind, match):
                    self.on_url(match.rstrip(".,"))
        exit_code = process.poll()
        if exit_code not in (None, 0):
            self.log(f"El tunel termino con codigo {exit_code}.")
        with self._lock:
            if self.process is process:
                self.process = None

    def stop(self) -> None:
        with self._lock:
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


class AppController:
    def __init__(self, dialog_runner: Callable[[str], list[str]] | None = None) -> None:
        self.state = ShareState()
        self.stats = StatsStore()
        self.transfers = TransferManager(self.stats)
        self.admin_token = secrets.token_urlsafe(24)
        self.dialog_runner = dialog_runner
        self.logs: list[str] = []
        self.logs_lock = threading.RLock()
        self.share_url = ""
        self.status = "ready"
        self.local_port = ""
        self.admin_url = ""
        self.web_server = WebServer(self.state, self.stats, self.transfers, self.log)
        self.tunnel = TunnelProcess(self.log, self.set_public_url)
        self.preferences = load_preferences()
        self.ui_language = normalize_ui_language(self.preferences.get("ui_language"))
        self.state.set_ui_language(self.ui_language)
        self.preferences_saved = SETTINGS_PATH.exists() and bool(self.preferences.get("save_preferences"))
        self.last_preference_warnings: list[str] = []
        if self.preferences_saved:
            self.apply_preferences(self.preferences)

    def log(self, message: str) -> None:
        line = f"[{now_text()}] {message}"
        with self.logs_lock:
            self.logs.append(line)
            self.logs = self.logs[-500:]

    def set_public_url(self, url: str) -> None:
        if "/s/" not in url:
            url = f"{url.rstrip('/')}/s/{self.state.token}"
        self.share_url = url
        self.status = "published"
        self.log(f"URL publica lista: {url}")

    def set_ui_language(self, language: str, persist: bool = True) -> None:
        language = normalize_ui_language(language)
        self.ui_language = language
        self.state.set_ui_language(language)
        self.preferences["ui_language"] = language
        if persist:
            save_preferences(self.preferences)

    def apply_preferences(self, raw_preferences: dict) -> None:
        preferences = sanitize_preferences(raw_preferences)
        warnings: list[str] = []
        self.preferences = preferences
        self.set_ui_language(preferences.get("ui_language", "en"), persist=False)
        self.state.configure_uploads(
            preferences["upload_enabled"],
            preferences["upload_dir"],
        )
        self.state.configure_security_options(
            preferences["expiration_minutes"],
            preferences["download_limit_per_file"],
            preferences["uploads_require_global"],
        )
        existing_files = []
        for path in preferences["file_paths"]:
            if Path(path).expanduser().is_file():
                existing_files.append(path)
            else:
                warnings.append(f"No existe el archivo guardado: {path}")
        if existing_files:
            self.add_files(existing_files)
        for folder in preferences["folders"]:
            folder_path = Path(folder["path"]).expanduser()
            if folder_path.is_dir():
                self.add_folder(str(folder_path), bool(folder.get("include_subfolders")))
            else:
                warnings.append(f"No existe la carpeta guardada: {folder['path']}")
        self.last_preference_warnings = warnings
        for warning in warnings:
            self.log(warning)

    def preferences_payload(self) -> dict:
        return {
            "ok": True,
            "saved": self.preferences_saved,
            "path": str(SETTINGS_PATH),
            "preferences": preferences_without_secrets(self.preferences),
            "warnings": list(self.last_preference_warnings),
        }

    def save_preferences_from_payload(self, payload: dict) -> dict:
        preferences = preferences_without_secrets(payload)
        if not preferences.get("save_preferences"):
            delete_preferences()
            self.preferences = dict(DEFAULT_PREFERENCES)
            self.set_ui_language(self.preferences.get("ui_language", "en"), persist=False)
            self.preferences_saved = False
            self.log("Configuracion guardada eliminada.")
            return self.preferences_payload()
        save_preferences(preferences)
        self.preferences = load_preferences()
        self.set_ui_language(self.preferences.get("ui_language", "en"), persist=False)
        self.preferences_saved = True
        self.log("Configuracion guardada.")
        return self.preferences_payload()

    def delete_saved_preferences(self) -> dict:
        delete_preferences()
        self.preferences = dict(DEFAULT_PREFERENCES)
        self.set_ui_language(self.preferences.get("ui_language", "en"), persist=False)
        self.preferences_saved = False
        self.last_preference_warnings = []
        self.log("Configuracion guardada borrada.")
        return self.preferences_payload()

    def wizard_step(self) -> int:
        if self.share_url:
            return 4
        if self.state.has_files():
            return 2
        return 1

    def recommendation(self) -> str:
        qt_labels = i18n_bundle(self.ui_language)["qt"]
        if not self.state.has_files():
            return qt_labels["recommendation_empty"]
        if self.share_url:
            return qt_labels["recommendation_ready"]
        if self.state.uploads_enabled():
            return qt_labels["recommendation_uploads"]
        return qt_labels["recommendation_publish"]

    def serialize(self) -> dict:
        files = [file_view(item, self.state) for item in self.state.snapshot()]
        folders = [folder_view(folder, self.state) for folder in self.state.folders_snapshot()]
        active = self.transfers.snapshot_active()
        history = self.stats.recent_events(limit=200)
        qt_labels = i18n_bundle(self.ui_language)["qt"]
        security = self.state.security_options()
        history_rows: list[dict] = []
        for row in history:
            row_copy = dict(row)
            status_value = str(row_copy.get("status", ""))
            row_copy["status_label"] = localize_transfer_status(status_value, qt_labels)
            row_copy["event_type_label"] = localize_event_type(
                str(row_copy.get("event_type", "")),
                qt_labels,
                self.ui_language,
            )
            row_copy["reason_text"] = str(row_copy.get("error") or qt_labels["history_reason_none"])
            row_copy["bytes_text"] = (
                f"{format_bytes(int(row_copy.get('bytes_done') or 0))}/"
                f"{format_bytes(int(row_copy.get('size_total') or 0))}"
            )
            if status_value == "completada":
                row_copy["status_group"] = "completed"
            elif status_value == "cancelada":
                row_copy["status_group"] = "cancelled"
            elif is_failed_transfer_status(status_value):
                row_copy["status_group"] = "failed"
            else:
                row_copy["status_group"] = "active"
            history_rows.append(row_copy)
        protected_files = sum(1 for item in files if item.get("protected"))
        protected_folders = sum(1 for item in folders if item.get("protected"))
        with self.logs_lock:
            logs = list(self.logs[-160:])
        return {
            "status": localize_controller_status(self.status, qt_labels),
            "status_code": normalize_status_code(self.status),
            "share_url": self.share_url,
            "local_port": self.local_port,
            "token": self.state.token,
            "ui_language": self.ui_language,
            "files": files,
            "folders": folders,
            "upload_enabled": self.state.uploads_enabled(),
            "upload_dir": str(self.state.upload_folder()),
            "file_count": len(files),
            "total_size": sum(item["size"] for item in files),
            "total_size_text": format_bytes(sum(item["size"] for item in files)),
            "active": active,
            "history": history_rows,
            "logs": logs,
            "security": security,
            "security_indicators": {
                "global_password": self.state.global_password_enabled(),
                "upload_guard": bool(security.get("uploads_require_global")),
                "protected_files": protected_files,
                "protected_folders": protected_folders,
            },
            "share_running": self.web_server.running,
            "tunnel_running": self.tunnel.running,
            "preferences_saved": self.preferences_saved,
            "preferences": preferences_without_secrets(self.preferences),
            "wizard_step": self.wizard_step(),
            "has_files": bool(files),
            "can_publish": bool(files) and not self.web_server.running,
            "recommendation": self.recommendation(),
            "preference_warnings": list(self.last_preference_warnings),
        }

    def pick(self, kind: str) -> list[str]:
        if not self.dialog_runner:
            return []
        return self.dialog_runner(kind)

    def add_files(self, paths: Iterable[str]) -> dict:
        added, errors = self.state.add_paths(paths)
        self.log(f"{added} archivo(s) anadido(s).")
        for error in errors:
            self.log(error)
        return {"ok": not errors, "added": added, "errors": errors}

    def add_folder(self, path: str, include_subfolders: bool = False, password: str = "") -> dict:
        added, errors = self.state.add_folder(path, include_subfolders, password=password)
        self.log(f"Carpeta anadida: {added} archivo(s).")
        for error in errors:
            self.log(error)
        return {"ok": not errors, "added": added, "errors": errors}

    def configure_uploads(self, enabled: bool, upload_dir: str) -> dict:
        self.state.configure_uploads(enabled, upload_dir)
        if enabled:
            self.state.upload_folder().mkdir(parents=True, exist_ok=True)
        self.log("Subidas activadas." if enabled else "Subidas desactivadas.")
        return {"ok": True}

    def start_publish(self, options: dict) -> dict:
        if self.web_server.running:
            return {"ok": False, "message": "Ya hay una publicacion activa."}
        raw_port = str(options.get("port") or "80")
        manual = bool(options.get("manual_port"))
        mode = str(options.get("mode") or "tailscale")
        tailscale_public_port = str(options.get("tailscale_public_port") or "443")
        port, error = choose_port(raw_port, manual)
        if error:
            self.log(error)
            return {"ok": False, "message": error}
        assert port is not None

        self.status = "starting"
        self.local_port = str(port)
        self.web_server.start(port)
        local_url = f"http://127.0.0.1:{port}/s/{self.state.token}"
        lan_url = f"http://{get_lan_ip()}:{port}/s/{self.state.token}"
        self.share_url = local_url

        if mode == "auto":
            try:
                self.tunnel.start_tailscale(port, tailscale_public_port)
                return {"ok": True, "url": self.share_url, "mode": "tailscale"}
            except Exception as exc:
                self.log(f"Tailscale no disponible: {exc}")
                self.log("Intentando Cloudflare Quick Tunnel...")
            try:
                self.tunnel.start_cloudflare(port)
                return {"ok": True, "url": self.share_url, "mode": "cloudflare"}
            except Exception as exc:
                self.status = "local"
                self.share_url = lan_url
                self.log(f"Cloudflare no disponible: {exc}")
                self.log(f"URL local: {local_url}")
                self.log(f"URL LAN: {lan_url}")
                return {"ok": True, "url": self.share_url, "mode": "direct", "message": str(exc)}

        if mode == "direct":
            self.share_url = lan_url
            self.status = "local"
            self.log(f"URL local: {local_url}")
            self.log(f"URL LAN: {lan_url}")
            return {"ok": True, "url": self.share_url}

        try:
            if mode == "tailscale":
                try:
                    self.tunnel.start_tailscale(port, tailscale_public_port)
                except Exception as exc:
                    self.log(f"Tailscale no disponible: {exc}")
                    self.log("Intentando Cloudflare Quick Tunnel...")
                    self.tunnel.start_cloudflare(port)
            elif mode == "cloudflare":
                self.tunnel.start_cloudflare(port)
        except Exception as exc:
            self.status = "local"
            self.log(str(exc))
            self.log(f"URL local disponible: {local_url}")
            return {"ok": False, "message": str(exc), "url": local_url}
        return {"ok": True, "url": self.share_url}

    def stop_publish(self) -> dict:
        self.tunnel.stop()
        if self.web_server.running:
            self.web_server.stop()
        self.share_url = ""
        self.status = "stopped"
        return {"ok": True}

    def open_location(self, file_id: str) -> dict:
        item = self.state.get(file_id)
        if not item:
            return {"ok": False, "message": "Archivo no encontrado."}
        path = Path(item.path)
        if os.name == "nt":
            os.startfile(str(path.parent))
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path.parent)])
        return {"ok": True}

    def open_folder_location(self, folder_id: str) -> dict:
        folder = self.state.get_folder(folder_id)
        if not folder:
            return {"ok": False, "message": "Carpeta no encontrada."}
        path = Path(folder.path)
        if os.name == "nt":
            os.startfile(str(path))
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
        return {"ok": True}


def create_admin_app(controller: AppController) -> "Flask":
    if not import_web_dependencies():
        raise RuntimeError("Faltan dependencias web.")
    admin_app = Flask(f"{APP_NAME} Admin", static_folder=None)
    admin_app.secret_key = controller.admin_token

    def require_admin(token: str) -> None:
        if token != controller.admin_token:
            abort(404)

    @admin_app.after_request
    def no_store(response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response

    @admin_app.get("/admin/<token>")
    def admin_page(token: str):
        require_admin(token)
        return render_template_string(ADMIN_HTML, token=token, app_name=APP_NAME)

    @admin_app.get("/admin/<token>/assets/admin.css")
    def admin_css(token: str):
        require_admin(token)
        return Response(ADMIN_CSS, mimetype="text/css")

    @admin_app.get("/admin/<token>/assets/admin.js")
    def admin_js(token: str):
        require_admin(token)
        return Response(ADMIN_JS, mimetype="application/javascript")

    @admin_app.get("/admin/<token>/api/state")
    def api_state(token: str):
        require_admin(token)
        return jsonify(controller.serialize())

    @admin_app.get("/admin/<token>/api/preferences")
    def api_get_preferences(token: str):
        require_admin(token)
        return jsonify(controller.preferences_payload())

    @admin_app.post("/admin/<token>/api/preferences")
    def api_save_preferences(token: str):
        require_admin(token)
        data = request.get_json(silent=True) or {}
        return jsonify(controller.save_preferences_from_payload(data))

    @admin_app.delete("/admin/<token>/api/preferences")
    def api_delete_preferences(token: str):
        require_admin(token)
        return jsonify(controller.delete_saved_preferences())

    @admin_app.post("/admin/<token>/api/files/add")
    def api_add_files(token: str):
        require_admin(token)
        data = request.get_json(silent=True) or {}
        return jsonify(controller.add_files(data.get("paths", [])))

    @admin_app.post("/admin/<token>/api/files/pick")
    def api_pick_files(token: str):
        require_admin(token)
        return jsonify(controller.add_files(controller.pick("files")))

    @admin_app.post("/admin/<token>/api/files/remove")
    def api_remove_files(token: str):
        require_admin(token)
        data = request.get_json(silent=True) or {}
        removed = controller.state.remove(data.get("ids", []))
        controller.log(f"{removed} archivo(s) quitado(s).")
        return jsonify({"ok": True, "removed": removed})

    @admin_app.post("/admin/<token>/api/files/password")
    def api_file_password(token: str):
        require_admin(token)
        data = request.get_json(silent=True) or {}
        updated = controller.state.set_file_passwords(data.get("ids", []), data.get("password", ""))
        controller.log(f"Contrasena de archivo actualizada en {updated} archivo(s).")
        return jsonify({"ok": True, "updated": updated})

    @admin_app.post("/admin/<token>/api/global-password")
    def api_global_password(token: str):
        require_admin(token)
        data = request.get_json(silent=True) or {}
        controller.state.set_global_password(data.get("password", ""))
        controller.log("Contrasena global aplicada." if data.get("password") else "Contrasena global quitada.")
        return jsonify({"ok": True})

    @admin_app.post("/admin/<token>/api/security/options")
    def api_security_options(token: str):
        require_admin(token)
        data = request.get_json(silent=True) or {}
        controller.state.configure_security_options(
            int(data.get("expiration_minutes") or 0),
            int(data.get("download_limit_per_file") or 0),
            bool(data.get("uploads_require_global")),
        )
        controller.log("Opciones de seguridad actualizadas.")
        return jsonify({"ok": True, "security": controller.state.security_options()})

    @admin_app.post("/admin/<token>/api/ips/block")
    def api_block_ip(token: str):
        require_admin(token)
        data = request.get_json(silent=True) or {}
        controller.state.block_ip(data.get("ip", ""))
        controller.log(f"IP bloqueada: {data.get('ip', '')}")
        return jsonify({"ok": True, "security": controller.state.security_options()})

    @admin_app.post("/admin/<token>/api/ips/unblock")
    def api_unblock_ip(token: str):
        require_admin(token)
        data = request.get_json(silent=True) or {}
        controller.state.unblock_ip(data.get("ip", ""))
        controller.log(f"IP desbloqueada: {data.get('ip', '')}")
        return jsonify({"ok": True, "security": controller.state.security_options()})

    @admin_app.post("/admin/<token>/api/files/open-location")
    def api_open_location(token: str):
        require_admin(token)
        data = request.get_json(silent=True) or {}
        return jsonify(controller.open_location(data.get("id", "")))

    @admin_app.post("/admin/<token>/api/folders/add")
    def api_add_folder(token: str):
        require_admin(token)
        data = request.get_json(silent=True) or {}
        path = data.get("path") or ""
        return jsonify(
            controller.add_folder(
                path,
                bool(data.get("include_subfolders")),
                data.get("password", ""),
            )
        )

    @admin_app.post("/admin/<token>/api/folders/pick")
    def api_pick_folder(token: str):
        require_admin(token)
        data = request.get_json(silent=True) or {}
        paths = controller.pick("folder")
        if not paths:
            return jsonify({"ok": False, "message": "No se selecciono carpeta."})
        return jsonify(
            controller.add_folder(
                paths[0],
                bool(data.get("include_subfolders")),
                data.get("password", ""),
            )
        )

    @admin_app.post("/admin/<token>/api/folders/refresh")
    def api_refresh_folder(token: str):
        require_admin(token)
        data = request.get_json(silent=True) or {}
        added, errors = controller.state.refresh_folder(data.get("id", ""))
        controller.log(f"Carpeta refrescada: {added} archivo(s) nuevo(s).")
        return jsonify({"ok": not errors, "added": added, "errors": errors})

    @admin_app.post("/admin/<token>/api/folders/remove")
    def api_remove_folder(token: str):
        require_admin(token)
        data = request.get_json(silent=True) or {}
        ok = controller.state.remove_folder(data.get("id", ""), bool(data.get("remove_files", True)))
        controller.log("Carpeta quitada." if ok else "No se encontro la carpeta.")
        return jsonify({"ok": ok})

    @admin_app.post("/admin/<token>/api/folders/password")
    def api_folder_password(token: str):
        require_admin(token)
        data = request.get_json(silent=True) or {}
        updated = controller.state.set_folder_passwords(data.get("ids", []), data.get("password", ""))
        controller.log(f"Contrasena de carpeta actualizada en {updated} carpeta(s).")
        return jsonify({"ok": True, "updated": updated})

    @admin_app.post("/admin/<token>/api/uploads")
    def api_uploads(token: str):
        require_admin(token)
        data = request.get_json(silent=True) or {}
        try:
            return jsonify(
                controller.configure_uploads(
                    bool(data.get("enabled")),
                    data.get("upload_dir") or str(DEFAULT_UPLOAD_DIR),
                )
            )
        except Exception as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400

    @admin_app.post("/admin/<token>/api/publish/start")
    def api_publish_start(token: str):
        require_admin(token)
        data = request.get_json(silent=True) or {}
        try:
            return jsonify(controller.start_publish(data))
        except Exception as exc:
            controller.log(str(exc))
            return jsonify({"ok": False, "message": str(exc)}), 400

    @admin_app.post("/admin/<token>/api/publish/stop")
    def api_publish_stop(token: str):
        require_admin(token)
        return jsonify(controller.stop_publish())

    @admin_app.post("/admin/<token>/api/transfers/cancel")
    def api_transfer_cancel(token: str):
        require_admin(token)
        data = request.get_json(silent=True) or {}
        ok = controller.transfers.cancel(data.get("id", ""))
        return jsonify({"ok": ok})

    @admin_app.get("/admin/<token>/api/history/export")
    def api_history_export(token: str):
        require_admin(token)
        rows = controller.stats.recent_events(limit=10_000)
        buffer = io.StringIO()
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
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
        return Response(
            buffer.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=historial.csv"},
        )

    return admin_app


class AdminServer:
    def __init__(self, controller: AppController, log: Callable[[str], None]) -> None:
        self.controller = controller
        self.log = log
        self.host = "127.0.0.1"
        self.port: int | None = None
        self._server = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> str:
        with self._lock:
            if self.running and self.port:
                return f"http://127.0.0.1:{self.port}/admin/{self.controller.admin_token}"
            port = get_free_port()
            self._server = create_server(
                create_admin_app(self.controller),
                host=self.host,
                port=port,
                threads=8,
            )
            self.port = port
            self._thread = threading.Thread(target=self._server.run, name="admin-server", daemon=True)
            self._thread.start()
        url = f"http://127.0.0.1:{port}/admin/{self.controller.admin_token}"
        self.controller.admin_url = url
        self.log(f"Panel admin local: {url}")
        return url

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


def needs_exit_confirmation(controller: AppController) -> bool:
    return (
        controller.web_server.running
        or controller.tunnel.running
        or bool(controller.transfers.snapshot_active())
    )


def run_integrated_admin_app() -> int:
    try:
        qt_core = importlib.import_module("PySide6.QtCore")
        qt_gui = importlib.import_module("PySide6.QtGui")
        qt_widgets = importlib.import_module("PySide6.QtWidgets")
    except ImportError as exc:
        raise RuntimeError("Falta PySide6. Ejecuta iniciar.bat o reinstala dependencias.") from exc

    Qt = qt_core.Qt
    QTimer = qt_core.QTimer
    QAction = qt_gui.QAction
    QTextCursor = qt_gui.QTextCursor
    QApplication = qt_widgets.QApplication
    QAbstractItemView = qt_widgets.QAbstractItemView
    QCheckBox = qt_widgets.QCheckBox
    QComboBox = qt_widgets.QComboBox
    QFileDialog = qt_widgets.QFileDialog
    QFormLayout = qt_widgets.QFormLayout
    QGridLayout = qt_widgets.QGridLayout
    QHBoxLayout = qt_widgets.QHBoxLayout
    QInputDialog = qt_widgets.QInputDialog
    QLabel = qt_widgets.QLabel
    QLineEdit = qt_widgets.QLineEdit
    QMainWindow = qt_widgets.QMainWindow
    QMenu = qt_widgets.QMenu
    QMessageBox = qt_widgets.QMessageBox
    QPushButton = qt_widgets.QPushButton
    QPlainTextEdit = qt_widgets.QPlainTextEdit
    QSpinBox = qt_widgets.QSpinBox
    QTabWidget = qt_widgets.QTabWidget
    QTableWidget = qt_widgets.QTableWidget
    QTableWidgetItem = qt_widgets.QTableWidgetItem
    QVBoxLayout = qt_widgets.QVBoxLayout
    QWidget = qt_widgets.QWidget

    class AdminMainWindow(QMainWindow):
        def __init__(self, controller: AppController) -> None:
            super().__init__()
            self.controller = controller
            self._prefs_applied = False
            self._last_log_dump = ""
            self._labels = i18n_bundle(self.controller.ui_language)["qt"]
            self.setWindowTitle(APP_NAME)
            self.resize(1220, 780)
            self.setMinimumSize(980, 640)
            self._build_ui()
            self._build_styles()
            self._apply_language_texts()
            self.timer = QTimer(self)
            self.timer.setInterval(1500)
            self.timer.timeout.connect(self.refresh_state)
            self.timer.start()
            self.refresh_state()

        def _build_styles(self) -> None:
            self.setStyleSheet(
                """
                QWidget { font-family: "Segoe UI"; font-size: 10pt; color: #1f2937; border-radius: 0; }
                QMainWindow, QWidget#root { background: #f4f6f9; }
                QTabWidget::pane { border: 1px solid #d2d9e3; background: #ffffff; top: -1px; }
                QTabBar::tab {
                    background: #eef2f7;
                    border: 1px solid #d2d9e3;
                    border-bottom: 0;
                    padding: 6px 10px;
                    margin-right: 1px;
                }
                QTabBar::tab:selected { background: #ffffff; }
                QPushButton {
                    background: #0b57d0;
                    color: #ffffff;
                    border: 1px solid #0b57d0;
                    padding: 5px 10px;
                    min-height: 30px;
                    font-weight: 600;
                }
                QPushButton:hover { background: #0949b3; }
                QPushButton#secondary {
                    background: #ffffff;
                    color: #1f2937;
                    border: 1px solid #bcc6d4;
                }
                QPushButton#secondary:hover { background: #f4f7fb; }
                QLineEdit, QComboBox, QSpinBox {
                    background: #ffffff;
                    border: 1px solid #bcc6d4;
                    padding: 5px 7px;
                    min-height: 30px;
                }
                QTableWidget {
                    border: 1px solid #d2d9e3;
                    background: #ffffff;
                    gridline-color: #e7edf5;
                }
                QTableView::item { padding: 4px 6px; }
                QHeaderView::section {
                    background: #f5f8fc;
                    border: 0;
                    border-bottom: 1px solid #d2d9e3;
                    padding: 5px 6px;
                    font-weight: 600;
                }
                QPlainTextEdit {
                    background: #0f172a;
                    color: #dbe7ff;
                    border: 1px solid #1e293b;
                    padding: 6px;
                }
                QLabel#statusBadge {
                    background: #e8f0fe;
                    color: #0b57d0;
                    border: 1px solid #c6d7ff;
                    padding: 6px 10px;
                    font-weight: 700;
                }
                QLabel#metricBadge {
                    background: #f8fafc;
                    border: 1px solid #d2d9e3;
                    padding: 5px 9px;
                    font-weight: 600;
                }
                """
            )

        def _t(self, key: str) -> str:
            return self._labels.get(key, key)

        def _apply_language_texts(self) -> None:
            self._labels = i18n_bundle(self.controller.ui_language)["qt"]
            self.language_label.setText(self._t("language_label"))
            self.tabs.setTabText(self.tabs.indexOf(self.files_tab), self._t("tab_files"))
            self.tabs.setTabText(self.tabs.indexOf(self.publish_tab), self._t("tab_publish"))
            self.tabs.setTabText(self.tabs.indexOf(self.security_tab), self._t("tab_security"))
            self.tabs.setTabText(self.tabs.indexOf(self.activity_tab), self._t("tab_activity"))

            self.add_files_button.setText(self._t("btn_add_files"))
            self.add_folder_button.setText(self._t("btn_add_folder"))
            self.remove_files_button.setText(self._t("btn_remove_files"))
            self.remove_folders_button.setText(self._t("btn_remove_folders"))
            self.refresh_folders_button.setText(self._t("btn_refresh_folder"))
            self.include_subfolders_check.setText(self._t("include_subfolders"))
            self.file_table.setHorizontalHeaderLabels(
                [
                    self._t("files_name"),
                    self._t("files_size"),
                    self._t("files_source"),
                    self._t("files_protected"),
                    self._t("files_date"),
                ]
            )
            self.folder_table.setHorizontalHeaderLabels(
                [
                    self._t("folders_name"),
                    self._t("folders_count"),
                    self._t("folders_size"),
                    self._t("folders_protected"),
                ]
            )

            current_mode = self.mode_combo.currentData()
            self.mode_combo.blockSignals(True)
            self.mode_combo.clear()
            mode_items = [
                ("auto", self._t("mode_auto")),
                ("tailscale", self._t("mode_tailscale")),
                ("cloudflare", self._t("mode_cloudflare")),
                ("direct", self._t("mode_direct")),
            ]
            for value, label in mode_items:
                self.mode_combo.addItem(label, value)
            mode_index = self.mode_combo.findData(current_mode or "auto")
            self.mode_combo.setCurrentIndex(mode_index if mode_index >= 0 else 0)
            self.mode_combo.blockSignals(False)

            self.publish_mode_label.setText(self._t("publish_mode"))
            self.publish_port_label.setText(self._t("publish_port"))
            self.manual_port_check.setText(self._t("publish_manual_port"))
            self.publish_tailscale_label.setText(self._t("publish_tailscale_port"))
            self.upload_enabled_check.setText(self._t("publish_uploads"))
            self.publish_upload_dir_label.setText(self._t("publish_upload_dir"))
            self.choose_upload_dir_button.setText(self._t("btn_choose"))
            self.start_button.setText(self._t("btn_publish"))
            self.stop_button.setText(self._t("btn_stop"))
            self.copy_button.setText(self._t("btn_copy_url"))

            self.security_global_label.setText(self._t("security_global_password"))
            self.security_selection_label.setText(self._t("security_selection_password"))
            self.apply_global_button.setText(self._t("btn_apply_global"))
            self.clear_global_button.setText(self._t("btn_clear_global"))
            self.apply_file_button.setText(self._t("btn_apply_file_password"))
            self.clear_file_button.setText(self._t("btn_clear_file_password"))
            self.apply_folder_button.setText(self._t("btn_apply_folder_password"))
            self.clear_folder_button.setText(self._t("btn_clear_folder_password"))
            self.security_expire_label.setText(self._t("security_expire_minutes"))
            self.security_download_label.setText(self._t("security_download_limit"))
            self.uploads_require_global_check.setText(self._t("security_uploads_require_global"))
            self.save_security_button.setText(self._t("btn_save_security"))
            self.ip_edit.setPlaceholderText(self._t("ip_placeholder"))
            self.block_ip_button.setText(self._t("btn_block_ip"))
            self.unblock_ip_button.setText(self._t("btn_unblock_ip"))

            self.cancel_button.setText(self._t("activity_cancel"))
            self.export_button.setText(self._t("activity_export"))
            self.active_table.setHorizontalHeaderLabels(
                [
                    self._t("activity_type"),
                    self._t("activity_file"),
                    self._t("activity_ip"),
                    self._t("activity_progress"),
                    self._t("activity_speed"),
                    self._t("activity_status"),
                ]
            )
            self.history_table.setHorizontalHeaderLabels(
                [
                    self._t("history_time"),
                    self._t("history_type"),
                    self._t("history_file"),
                    self._t("history_status"),
                    self._t("history_reason"),
                    self._t("history_bytes"),
                    self._t("history_ip"),
                ]
            )
            self.log_title_label.setText(self._t("activity_log_title"))

        def _build_ui(self) -> None:
            root = QWidget(self)
            root.setObjectName("root")
            self.setCentralWidget(root)
            layout = QVBoxLayout(root)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(8)

            header = QHBoxLayout()
            header.setSpacing(8)
            title_box = QVBoxLayout()
            title = QLabel(APP_NAME)
            title.setStyleSheet("font-size: 20px; font-weight: 700;")
            self.recommendation_label = QLabel("")
            self.recommendation_label.setStyleSheet("color: #5d6778;")
            title_box.addWidget(title)
            title_box.addWidget(self.recommendation_label)
            header.addLayout(title_box, 1)

            language_box = QHBoxLayout()
            language_box.setSpacing(6)
            self.language_label = QLabel("")
            self.language_combo = QComboBox()
            self.language_combo.addItem("English", "en")
            self.language_combo.addItem("Espanol", "es")
            language_box.addWidget(self.language_label)
            language_box.addWidget(self.language_combo)
            header.addLayout(language_box)

            self.status_label = QLabel("")
            self.status_label.setObjectName("statusBadge")
            header.addWidget(self.status_label)
            layout.addLayout(header)

            self.tabs = QTabWidget()
            layout.addWidget(self.tabs, 1)

            self.files_tab = QWidget()
            self.publish_tab = QWidget()
            self.security_tab = QWidget()
            self.activity_tab = QWidget()
            self.tabs.addTab(self.files_tab, "")
            self.tabs.addTab(self.publish_tab, "")
            self.tabs.addTab(self.security_tab, "")
            self.tabs.addTab(self.activity_tab, "")

            self._build_files_tab()
            self._build_publish_tab()
            self._build_security_tab()
            self._build_activity_tab()
            self.language_combo.currentIndexChanged.connect(self.on_language_changed)

        def _secondary_button(self, text: str) -> QPushButton:
            button = QPushButton(text)
            button.setObjectName("secondary")
            return button

        def _table(self, headers: list[str]) -> QTableWidget:
            table = QTableWidget(0, len(headers))
            table.setHorizontalHeaderLabels(headers)
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setSelectionMode(QAbstractItemView.ExtendedSelection)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.horizontalHeader().setStretchLastSection(True)
            table.verticalHeader().setVisible(False)
            table.verticalHeader().setDefaultSectionSize(28)
            return table

        def _selected_ids(self, table: QTableWidget) -> list[str]:
            rows = sorted({index.row() for index in table.selectedIndexes()})
            ids: list[str] = []
            for row in rows:
                item = table.item(row, 0)
                if item:
                    value = item.data(Qt.UserRole)
                    if value:
                        ids.append(str(value))
            return ids

        def _show_error(self, message: str) -> None:
            QMessageBox.critical(self, APP_NAME, message)

        def on_language_changed(self) -> None:
            language = str(self.language_combo.currentData() or "en")
            self.controller.set_ui_language(language, persist=True)
            self._apply_language_texts()
            self._prefs_applied = False
            self.refresh_state()

        def _build_files_tab(self) -> None:
            layout = QVBoxLayout(self.files_tab)
            layout.setSpacing(8)
            layout.setContentsMargins(10, 10, 10, 10)

            top_actions = QHBoxLayout()
            self.add_files_button = QPushButton("")
            self.add_files_button.clicked.connect(self.add_files_dialog)
            self.add_folder_button = self._secondary_button("")
            self.add_folder_button.clicked.connect(self.add_folder_dialog)
            self.remove_files_button = self._secondary_button("")
            self.remove_files_button.clicked.connect(self.remove_selected_files)
            self.remove_folders_button = self._secondary_button("")
            self.remove_folders_button.clicked.connect(self.remove_selected_folders)
            self.refresh_folders_button = self._secondary_button("")
            self.refresh_folders_button.clicked.connect(self.refresh_selected_folders)
            top_actions.addWidget(self.add_files_button)
            top_actions.addWidget(self.add_folder_button)
            top_actions.addWidget(self.remove_files_button)
            top_actions.addWidget(self.remove_folders_button)
            top_actions.addWidget(self.refresh_folders_button)
            top_actions.addStretch(1)
            self.include_subfolders_check = QCheckBox("")
            top_actions.addWidget(self.include_subfolders_check)
            layout.addLayout(top_actions)

            self.file_table = self._table(["", "", "", "", ""])
            self.file_table.setMinimumHeight(240)
            self.file_table.setContextMenuPolicy(Qt.CustomContextMenu)
            self.file_table.customContextMenuRequested.connect(self.show_file_context_menu)
            layout.addWidget(self.file_table, 2)

            self.folder_table = self._table(["", "", "", ""])
            self.folder_table.setMinimumHeight(160)
            self.folder_table.setContextMenuPolicy(Qt.CustomContextMenu)
            self.folder_table.customContextMenuRequested.connect(self.show_folder_context_menu)
            layout.addWidget(self.folder_table, 1)

        def _build_publish_tab(self) -> None:
            layout = QVBoxLayout(self.publish_tab)
            layout.setSpacing(8)
            layout.setContentsMargins(10, 10, 10, 10)
            self.publish_indicators_box = QHBoxLayout()
            self.indicator_global = QLabel("")
            self.indicator_upload_guard = QLabel("")
            self.indicator_protected_files = QLabel("")
            self.indicator_protected_folders = QLabel("")
            for label in [
                self.indicator_global,
                self.indicator_upload_guard,
                self.indicator_protected_files,
                self.indicator_protected_folders,
            ]:
                label.setObjectName("metricBadge")
                self.publish_indicators_box.addWidget(label)
            self.publish_indicators_box.addStretch(1)
            layout.addLayout(self.publish_indicators_box)

            form = QFormLayout()
            form.setVerticalSpacing(8)
            self.mode_combo = QComboBox()
            self.port_edit = QLineEdit("80")
            self.manual_port_check = QCheckBox("")
            self.tailscale_port_combo = QComboBox()
            self.tailscale_port_combo.addItems(TAILSCALE_PUBLIC_PORTS)
            self.upload_enabled_check = QCheckBox("")
            self.upload_dir_edit = QLineEdit(str(DEFAULT_UPLOAD_DIR))
            upload_dir_widget = QWidget()
            upload_dir_row = QHBoxLayout(upload_dir_widget)
            upload_dir_row.setContentsMargins(0, 0, 0, 0)
            upload_dir_row.setSpacing(6)
            upload_dir_row.addWidget(self.upload_dir_edit, 1)
            self.choose_upload_dir_button = self._secondary_button("")
            self.choose_upload_dir_button.clicked.connect(self.choose_upload_dir)
            upload_dir_row.addWidget(self.choose_upload_dir_button)

            self.publish_mode_label = QLabel("")
            self.publish_port_label = QLabel("")
            self.publish_tailscale_label = QLabel("")
            self.publish_upload_dir_label = QLabel("")
            form.addRow(self.publish_mode_label, self.mode_combo)
            form.addRow(self.publish_port_label, self.port_edit)
            form.addRow("", self.manual_port_check)
            form.addRow(self.publish_tailscale_label, self.tailscale_port_combo)
            form.addRow("", self.upload_enabled_check)
            form.addRow(self.publish_upload_dir_label, upload_dir_widget)
            layout.addLayout(form)

            actions = QHBoxLayout()
            self.start_button = QPushButton("")
            self.start_button.clicked.connect(self.start_publish)
            self.stop_button = self._secondary_button("")
            self.stop_button.clicked.connect(self.stop_publish)
            self.copy_button = self._secondary_button("")
            self.copy_button.clicked.connect(self.copy_share_url)
            actions.addWidget(self.start_button)
            actions.addWidget(self.stop_button)
            actions.addWidget(self.copy_button)
            actions.addStretch(1)
            layout.addLayout(actions)

            self.share_url_edit = QLineEdit("")
            self.share_url_edit.setReadOnly(True)
            layout.addWidget(self.share_url_edit)
            layout.addStretch(1)

        def _build_security_tab(self) -> None:
            layout = QVBoxLayout(self.security_tab)
            layout.setSpacing(8)
            layout.setContentsMargins(10, 10, 10, 10)
            self.global_password_edit = QLineEdit()
            self.global_password_edit.setEchoMode(QLineEdit.Password)
            global_row = QHBoxLayout()
            global_row.setSpacing(6)
            global_row.addWidget(self.global_password_edit, 1)
            self.apply_global_button = QPushButton("")
            self.apply_global_button.clicked.connect(self.apply_global_password)
            self.clear_global_button = self._secondary_button("")
            self.clear_global_button.clicked.connect(self.clear_global_password)
            global_row.addWidget(self.apply_global_button)
            global_row.addWidget(self.clear_global_button)

            self.selection_password_edit = QLineEdit()
            self.selection_password_edit.setEchoMode(QLineEdit.Password)
            file_row = QGridLayout()
            file_row.setHorizontalSpacing(6)
            file_row.setVerticalSpacing(6)
            self.apply_file_button = QPushButton("")
            self.apply_file_button.clicked.connect(self.apply_file_password)
            self.clear_file_button = self._secondary_button("")
            self.clear_file_button.clicked.connect(self.clear_file_password)
            self.apply_folder_button = QPushButton("")
            self.apply_folder_button.clicked.connect(self.apply_folder_password)
            self.clear_folder_button = self._secondary_button("")
            self.clear_folder_button.clicked.connect(self.clear_folder_password)
            file_row.addWidget(self.apply_file_button, 0, 0)
            file_row.addWidget(self.clear_file_button, 0, 1)
            file_row.addWidget(self.apply_folder_button, 1, 0)
            file_row.addWidget(self.clear_folder_button, 1, 1)

            self.expiration_spin = QSpinBox()
            self.expiration_spin.setRange(0, 525600)
            self.download_limit_spin = QSpinBox()
            self.download_limit_spin.setRange(0, 1_000_000)
            self.uploads_require_global_check = QCheckBox("")
            self.save_security_button = QPushButton("")
            self.save_security_button.clicked.connect(self.save_security_options)

            ip_row = QHBoxLayout()
            self.ip_edit = QLineEdit()
            self.block_ip_button = QPushButton("")
            self.block_ip_button.clicked.connect(self.block_ip)
            self.unblock_ip_button = self._secondary_button("")
            self.unblock_ip_button.clicked.connect(self.unblock_ip)
            ip_row.addWidget(self.ip_edit, 1)
            ip_row.addWidget(self.block_ip_button)
            ip_row.addWidget(self.unblock_ip_button)

            self.security_global_label = QLabel("")
            self.security_selection_label = QLabel("")
            self.security_expire_label = QLabel("")
            self.security_download_label = QLabel("")

            layout.addWidget(self.security_global_label)
            layout.addLayout(global_row)
            layout.addWidget(self.security_selection_label)
            layout.addWidget(self.selection_password_edit)
            layout.addLayout(file_row)
            layout.addWidget(self.security_expire_label)
            layout.addWidget(self.expiration_spin)
            layout.addWidget(self.security_download_label)
            layout.addWidget(self.download_limit_spin)
            layout.addWidget(self.uploads_require_global_check)
            layout.addWidget(self.save_security_button)
            layout.addLayout(ip_row)
            self.security_summary = QLabel("")
            self.security_summary.setStyleSheet("color: #5d6778;")
            layout.addWidget(self.security_summary)
            layout.addStretch(1)

        def _build_activity_tab(self) -> None:
            layout = QVBoxLayout(self.activity_tab)
            layout.setSpacing(8)
            layout.setContentsMargins(10, 10, 10, 10)
            metrics = QHBoxLayout()
            self.completed_label = QLabel("")
            self.completed_label.setObjectName("metricBadge")
            self.cancelled_label = QLabel("")
            self.cancelled_label.setObjectName("metricBadge")
            self.failed_label = QLabel("")
            self.failed_label.setObjectName("metricBadge")
            metrics.addWidget(self.completed_label)
            metrics.addWidget(self.cancelled_label)
            metrics.addWidget(self.failed_label)
            metrics.addStretch(1)
            layout.addLayout(metrics)

            top = QHBoxLayout()
            self.cancel_button = self._secondary_button("")
            self.cancel_button.clicked.connect(self.cancel_selected_transfer)
            self.export_button = self._secondary_button("")
            self.export_button.clicked.connect(self.export_history_csv)
            top.addWidget(self.cancel_button)
            top.addWidget(self.export_button)
            top.addStretch(1)
            layout.addLayout(top)
            self.active_table = self._table(["", "", "", "", "", ""])
            self.active_table.setMinimumHeight(140)
            self.history_table = self._table(["", "", "", "", "", "", ""])
            layout.addWidget(self.active_table, 1)
            layout.addWidget(self.history_table, 2)
            self.log_title_label = QLabel("")
            layout.addWidget(self.log_title_label)
            self.log_text = QPlainTextEdit()
            self.log_text.setReadOnly(True)
            self.log_text.setMinimumHeight(130)
            layout.addWidget(self.log_text)

        def _prompt_password(self, title: str, label: str) -> str | None:
            password, accepted = QInputDialog.getText(self, title, label, QLineEdit.Password)
            if not accepted:
                return None
            return password

        def _focus_row(self, table: QTableWidget, row: int) -> None:
            if row >= 0:
                table.selectRow(row)

        def show_file_context_menu(self, pos) -> None:
            item = self.file_table.itemAt(pos)
            if item is None:
                return
            self._focus_row(self.file_table, item.row())
            file_ids = self._selected_ids(self.file_table)
            if not file_ids:
                return

            menu = QMenu(self)
            remove_action = QAction(self._t("context_remove"), self)
            protect_action = QAction(self._t("context_protect"), self)
            unprotect_action = QAction(self._t("context_unprotect"), self)
            open_action = QAction(self._t("context_open_location"), self)
            copy_action = QAction(self._t("context_copy_link"), self)
            menu.addAction(remove_action)
            menu.addAction(protect_action)
            menu.addAction(unprotect_action)
            menu.addSeparator()
            menu.addAction(open_action)
            menu.addAction(copy_action)
            chosen = menu.exec(self.file_table.viewport().mapToGlobal(pos))
            if chosen is None:
                return
            if chosen is remove_action:
                self.remove_selected_files()
            elif chosen is protect_action:
                password = self._prompt_password(self._t("password_prompt_title"), self._t("password_prompt_file"))
                if password is not None:
                    updated = self.controller.state.set_file_passwords(file_ids, password)
                    self.controller.log(f"Password updated for {updated} file(s).")
                    self.refresh_state()
            elif chosen is unprotect_action:
                updated = self.controller.state.set_file_passwords(file_ids, "")
                self.controller.log(f"Password removed from {updated} file(s).")
                self.refresh_state()
            elif chosen is open_action:
                self.controller.open_location(file_ids[0])
            elif chosen is copy_action:
                share_url = self.share_url_edit.text().strip()
                if not share_url:
                    self._show_error(self._t("error_no_url"))
                    return
                QApplication.clipboard().setText(f"{share_url.rstrip('/')}/download/{file_ids[0]}")
                self.controller.log("Download link copied.")

        def show_folder_context_menu(self, pos) -> None:
            item = self.folder_table.itemAt(pos)
            if item is None:
                return
            self._focus_row(self.folder_table, item.row())
            folder_ids = self._selected_ids(self.folder_table)
            if not folder_ids:
                return

            menu = QMenu(self)
            remove_action = QAction(self._t("context_remove"), self)
            protect_action = QAction(self._t("context_protect"), self)
            unprotect_action = QAction(self._t("context_unprotect"), self)
            refresh_action = QAction(self._t("context_refresh"), self)
            open_action = QAction(self._t("context_open_location"), self)
            menu.addAction(remove_action)
            menu.addAction(protect_action)
            menu.addAction(unprotect_action)
            menu.addAction(refresh_action)
            menu.addAction(open_action)
            chosen = menu.exec(self.folder_table.viewport().mapToGlobal(pos))
            if chosen is None:
                return
            if chosen is remove_action:
                self.remove_selected_folders()
            elif chosen is protect_action:
                password = self._prompt_password(self._t("password_prompt_title"), self._t("password_prompt_folder"))
                if password is not None:
                    updated = self.controller.state.set_folder_passwords(folder_ids, password)
                    self.controller.log(f"Password updated for {updated} folder(s).")
                    self.refresh_state()
            elif chosen is unprotect_action:
                updated = self.controller.state.set_folder_passwords(folder_ids, "")
                self.controller.log(f"Password removed from {updated} folder(s).")
                self.refresh_state()
            elif chosen is refresh_action:
                self.refresh_selected_folders()
            elif chosen is open_action:
                self.controller.open_folder_location(folder_ids[0])

        def add_files_dialog(self) -> None:
            paths, _ = QFileDialog.getOpenFileNames(self, APP_NAME)
            if not paths:
                return
            self.controller.add_files(paths)
            self.refresh_state()

        def add_folder_dialog(self) -> None:
            path = QFileDialog.getExistingDirectory(self, APP_NAME)
            if not path:
                return
            self.controller.add_folder(path, self.include_subfolders_check.isChecked())
            self.refresh_state()

        def remove_selected_files(self) -> None:
            ids = self._selected_ids(self.file_table)
            if not ids:
                return
            removed = self.controller.state.remove(ids)
            self.controller.log(f"{removed} file(s) removed.")
            self.refresh_state()

        def remove_selected_folders(self) -> None:
            ids = self._selected_ids(self.folder_table)
            if not ids:
                return
            removed = 0
            for folder_id in ids:
                if self.controller.state.remove_folder(folder_id, True):
                    removed += 1
            self.controller.log(f"{removed} folder(s) removed.")
            self.refresh_state()

        def refresh_selected_folders(self) -> None:
            ids = self._selected_ids(self.folder_table)
            if not ids:
                return
            for folder_id in ids:
                added, errors = self.controller.state.refresh_folder(folder_id)
                self.controller.log(f"Folder refreshed: {added} new file(s).")
                for error in errors:
                    self.controller.log(error)
            self.refresh_state()

        def choose_upload_dir(self) -> None:
            path = QFileDialog.getExistingDirectory(
                self,
                APP_NAME,
                self.upload_dir_edit.text() or str(DEFAULT_UPLOAD_DIR),
            )
            if path:
                self.upload_dir_edit.setText(path)

        def _mode_value(self) -> str:
            value = self.mode_combo.currentData()
            return str(value or "auto")

        def start_publish(self) -> None:
            try:
                self.controller.configure_uploads(
                    self.upload_enabled_check.isChecked(),
                    self.upload_dir_edit.text().strip() or str(DEFAULT_UPLOAD_DIR),
                )
            except Exception as exc:
                self._show_error(str(exc))
                return
            result = self.controller.start_publish(
                {
                    "mode": self._mode_value(),
                    "port": self.port_edit.text().strip() or "80",
                    "manual_port": self.manual_port_check.isChecked(),
                    "tailscale_public_port": self.tailscale_port_combo.currentText().strip() or "443",
                }
            )
            if not result.get("ok"):
                self._show_error(str(result.get("message") or "Unable to publish."))
            self.refresh_state()

        def stop_publish(self) -> None:
            self.controller.stop_publish()
            self.refresh_state()

        def copy_share_url(self) -> None:
            value = self.share_url_edit.text().strip()
            if not value:
                return
            QApplication.clipboard().setText(value)
            self.controller.log("Share URL copied.")
            self.refresh_state()

        def apply_global_password(self) -> None:
            password = self.global_password_edit.text()
            self.controller.state.set_global_password(password)
            self.controller.log("Global password updated." if password else "Global password cleared.")
            self.global_password_edit.clear()
            self.refresh_state()

        def clear_global_password(self) -> None:
            self.controller.state.set_global_password("")
            self.global_password_edit.clear()
            self.controller.log("Global password cleared.")
            self.refresh_state()

        def apply_file_password(self) -> None:
            ids = self._selected_ids(self.file_table)
            if not ids:
                self._show_error(self._t("error_select_file"))
                return
            updated = self.controller.state.set_file_passwords(ids, self.selection_password_edit.text())
            self.controller.log(f"Password updated for {updated} file(s).")
            self.selection_password_edit.clear()
            self.refresh_state()

        def clear_file_password(self) -> None:
            ids = self._selected_ids(self.file_table)
            if not ids:
                return
            updated = self.controller.state.set_file_passwords(ids, "")
            self.controller.log(f"Password removed from {updated} file(s).")
            self.refresh_state()

        def apply_folder_password(self) -> None:
            ids = self._selected_ids(self.folder_table)
            if not ids:
                self._show_error(self._t("error_select_folder"))
                return
            updated = self.controller.state.set_folder_passwords(ids, self.selection_password_edit.text())
            self.controller.log(f"Password updated for {updated} folder(s).")
            self.selection_password_edit.clear()
            self.refresh_state()

        def clear_folder_password(self) -> None:
            ids = self._selected_ids(self.folder_table)
            if not ids:
                return
            updated = self.controller.state.set_folder_passwords(ids, "")
            self.controller.log(f"Password removed from {updated} folder(s).")
            self.refresh_state()

        def save_security_options(self) -> None:
            self.controller.state.configure_security_options(
                self.expiration_spin.value(),
                self.download_limit_spin.value(),
                self.uploads_require_global_check.isChecked(),
            )
            self.controller.log("Security options updated.")
            self.refresh_state()

        def block_ip(self) -> None:
            ip = self.ip_edit.text().strip()
            if not ip:
                return
            self.controller.state.block_ip(ip)
            self.controller.log(f"Blocked IP: {ip}")
            self.refresh_state()

        def unblock_ip(self) -> None:
            ip = self.ip_edit.text().strip()
            if not ip:
                return
            self.controller.state.unblock_ip(ip)
            self.controller.log(f"Unblocked IP: {ip}")
            self.refresh_state()

        def cancel_selected_transfer(self) -> None:
            ids = self._selected_ids(self.active_table)
            for transfer_id in ids:
                if self.controller.transfers.cancel(transfer_id):
                    self.controller.log(f"Transfer cancelled: {transfer_id}")
            self.refresh_state()

        def export_history_csv(self) -> None:
            path, _ = QFileDialog.getSaveFileName(
                self,
                APP_NAME,
                str(Path.home() / "historial.csv"),
                "CSV (*.csv)",
            )
            if not path:
                return
            self.controller.stats.export_csv(Path(path))
            self.controller.log(f"History exported: {path}")
            self.refresh_state()

        def _set_row(self, table: QTableWidget, row: int, values: list[str], row_id: str = "") -> None:
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0 and row_id:
                    item.setData(Qt.UserRole, row_id)
                table.setItem(row, col, item)

        def refresh_state(self) -> None:
            state = self.controller.serialize()
            if state.get("ui_language") != self.controller.ui_language:
                self.controller.set_ui_language(str(state.get("ui_language") or "en"), persist=False)
                self._apply_language_texts()

            selected_language = str(state.get("ui_language") or self.controller.ui_language)
            combo_index = self.language_combo.findData(selected_language)
            if combo_index >= 0 and combo_index != self.language_combo.currentIndex():
                self.language_combo.blockSignals(True)
                self.language_combo.setCurrentIndex(combo_index)
                self.language_combo.blockSignals(False)

            self.status_label.setText(f"{self._t('status_prefix')}: {state['status']}")
            self.recommendation_label.setText(state.get("recommendation", ""))
            self.share_url_edit.setText(state.get("share_url", ""))

            if not self._prefs_applied:
                preferences = state.get("preferences", {})
                mode = str(preferences.get("mode") or "auto")
                index = self.mode_combo.findData(mode)
                if index >= 0:
                    self.mode_combo.setCurrentIndex(index)
                self.port_edit.setText(str(preferences.get("port") or "80"))
                self.manual_port_check.setChecked(bool(preferences.get("manual_port")))
                tailscale_port = str(preferences.get("tailscale_public_port") or "443")
                idx = self.tailscale_port_combo.findText(tailscale_port)
                if idx >= 0:
                    self.tailscale_port_combo.setCurrentIndex(idx)
                self.upload_enabled_check.setChecked(bool(state.get("upload_enabled")))
                self.upload_dir_edit.setText(str(state.get("upload_dir") or DEFAULT_UPLOAD_DIR))
                self.include_subfolders_check.setChecked(bool(preferences.get("include_subfolders")))
                preferred_language = normalize_ui_language(preferences.get("ui_language"))
                language_index = self.language_combo.findData(preferred_language)
                if language_index >= 0:
                    self.language_combo.blockSignals(True)
                    self.language_combo.setCurrentIndex(language_index)
                    self.language_combo.blockSignals(False)
                security = state.get("security", {})
                self.expiration_spin.setValue(int(security.get("expiration_minutes") or 0))
                self.download_limit_spin.setValue(int(security.get("download_limit_per_file") or 0))
                self.uploads_require_global_check.setChecked(bool(security.get("uploads_require_global")))
                self._prefs_applied = True

            files = state.get("files", [])
            self.file_table.setRowCount(len(files))
            for row, item in enumerate(files):
                self._set_row(
                    self.file_table,
                    row,
                    [
                        str(item.get("display_name", "")),
                        str(item.get("size_text", "")),
                        str(item.get("source", "")),
                        self._t("protected_yes") if item.get("protected") else self._t("protected_no"),
                        str(item.get("mtime_text", "")),
                    ],
                    str(item.get("id", "")),
                )

            folders = state.get("folders", [])
            self.folder_table.setRowCount(len(folders))
            for row, item in enumerate(folders):
                self._set_row(
                    self.folder_table,
                    row,
                    [
                        str(item.get("name", "")),
                        str(item.get("file_count", "")),
                        str(item.get("total_size_text", "")),
                        self._t("protected_yes") if item.get("protected") else self._t("protected_no"),
                    ],
                    str(item.get("id", "")),
                )

            active = state.get("active", [])
            self.active_table.setRowCount(len(active))
            for row, item in enumerate(active):
                self._set_row(
                    self.active_table,
                    row,
                    [
                        localize_event_type(str(item.get("event_type", "")), self._labels, self.controller.ui_language),
                        str(item.get("file_name", "")),
                        str(item.get("ip", "")),
                        f"{float(item.get('percent') or 0):.0f}%",
                        f"{format_bytes(int(item.get('speed') or 0))}/s",
                        localize_transfer_status(str(item.get("status", "")), self._labels),
                    ],
                    str(item.get("id", "")),
                )

            history = state.get("history", [])[:200]
            self.history_table.setRowCount(len(history))
            for row, item in enumerate(history):
                self._set_row(
                    self.history_table,
                    row,
                    [
                        str(item.get("updated_at", "")),
                        str(item.get("event_type_label", "")),
                        str(item.get("file_name", "")),
                        str(item.get("status_label", "")),
                        str(item.get("reason_text", "")),
                        str(item.get("bytes_text", "")),
                        str(item.get("ip", "")),
                    ],
                    str(item.get("id", "")),
                )

            security = state.get("security", {})
            blocked = security.get("blocked_ips", [])
            blocked_text = ", ".join(blocked) if blocked else "-"
            self.security_summary.setText(self._t("security_summary").format(ips=blocked_text))

            indicators = state.get("security_indicators", {})
            self.indicator_global.setText(
                f"{self._t('indicator_global_password')}: "
                f"{self._t('security_on') if indicators.get('global_password') else self._t('security_off')}"
            )
            self.indicator_upload_guard.setText(
                f"{self._t('indicator_upload_guard')}: "
                f"{self._t('security_on') if indicators.get('upload_guard') else self._t('security_off')}"
            )
            self.indicator_protected_files.setText(
                f"{self._t('indicator_protected_files')}: {int(indicators.get('protected_files') or 0)}"
            )
            self.indicator_protected_folders.setText(
                f"{self._t('indicator_protected_folders')}: {int(indicators.get('protected_folders') or 0)}"
            )

            completed = sum(1 for row in history if row.get("status_group") == "completed")
            cancelled = sum(1 for row in history if row.get("status_group") == "cancelled")
            failed = sum(1 for row in history if row.get("status_group") == "failed")
            self.completed_label.setText(f"{self._t('activity_completed')}: {completed}")
            self.cancelled_label.setText(f"{self._t('activity_cancelled')}: {cancelled}")
            self.failed_label.setText(f"{self._t('activity_failed')}: {failed}")

            log_dump = "\n".join(state.get("logs", []))
            if log_dump != self._last_log_dump:
                self.log_text.setPlainText(log_dump)
                cursor = self.log_text.textCursor()
                cursor.movePosition(QTextCursor.End)
                self.log_text.setTextCursor(cursor)
                self._last_log_dump = log_dump

        def closeEvent(self, event) -> None:
            if needs_exit_confirmation(self.controller):
                answer = QMessageBox.question(
                    self,
                    APP_NAME,
                    self._t("exit_confirm"),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    event.ignore()
                    return
            self.controller.stop_publish()
            event.accept()

    qt_app = QApplication.instance() or QApplication(sys.argv[:1])
    controller = AppController()
    controller.log("Panel nativo Qt iniciado.")
    window = AdminMainWindow(controller)
    window.show()
    try:
        return int(qt_app.exec())
    finally:
        controller.stop_publish()


BASE_AUTH_CSS = """
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#eef3f6;font-family:"Segoe UI",system-ui,sans-serif;color:#17212b}
.auth{width:min(420px,calc(100% - 28px));background:#fff;border:1px solid #dce6ec;border-radius:8px;padding:24px;box-shadow:0 18px 45px rgba(23,33,43,.1)}
h1{margin:0 0 8px;font-size:1.6rem}p{color:#607080;line-height:1.45}input{width:100%;padding:12px;border:1px solid #dce6ec;border-radius:8px;margin:8px 0 12px}
button{width:100%;padding:12px;border:0;border-radius:8px;background:#0f8a7a;color:#fff;font-weight:760}.error{background:#ffe3df;border:1px solid #f3b2aa;color:#7b2016;padding:10px;border-radius:8px;margin:10px 0}
"""

AUTH_CSS = BASE_AUTH_CSS

CLIENT_LOGIN_HTML = r"""
<!doctype html>
<html lang="{{ lang }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ web.auth_title }}</title>
  <style>{{ auth_css|default(AUTH_CSS)|safe }}</style>
</head>
<body>
  <main class="auth">
    <h1>{{ web.auth_title }}</h1>
    <p>{{ web.auth_message }}</p>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
    <form method="post" action="{{ url_for('auth_global', token=token) }}">
      <input name="password" type="password" placeholder="{{ web.auth_password_placeholder }}" autofocus>
      <button type="submit">{{ web.auth_submit }}</button>
    </form>
  </main>
</body>
</html>
"""

FILE_PASSWORD_HTML = r"""
<!doctype html>
<html lang="{{ lang }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ web.file_lock_title }}</title>
  <style>{{ auth_css|default(AUTH_CSS)|safe }}</style>
</head>
<body>
  <main class="auth">
    <h1>{{ web.file_lock_title }}</h1>
    <p>{{ web.file_lock_message }}</p>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
    <form method="post" action="{{ url_for('unlock_file', token=token, file_id=file_id) }}">
      <input name="password" type="password" placeholder="{{ web.unlock_file_placeholder }}" autofocus>
      <button type="submit">{{ web.file_lock_submit }}</button>
    </form>
  </main>
</body>
</html>
"""

FOLDER_PASSWORD_HTML = r"""
<!doctype html>
<html lang="{{ lang }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ web.folders_title }}</title>
  <style>{{ auth_css|default(AUTH_CSS)|safe }}</style>
</head>
<body>
  <main class="auth">
    <h1>{{ folder_name }}</h1>
    <p>{{ web.folder_lock_message }}</p>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
    <form method="post" action="{{ url_for('unlock_folder', token=token, folder_id=folder_id) }}">
      <input name="password" type="password" placeholder="{{ web.folder_password_placeholder }}" autofocus>
      <button type="submit">{{ web.folder_lock_submit }}</button>
    </form>
  </main>
</body>
</html>
"""

CLIENT_HTML = r"""
<!doctype html>
<html lang="{{ lang }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>File Transfer Easy</title>
  <link rel="stylesheet" href="{{ url_for('client_css', token=token) }}">
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">{{ web.session_title }}</p>
        <h1>{{ web.shared_files_title }}</h1>
        <p class="subtitle">{{ web.shared_files_subtitle }}</p>
      </div>
      <div class="stats">
        <div class="stat"><strong>{{ file_count }}</strong><span>{{ web.files_count }}</span></div>
        <div class="stat"><strong>{{ total_size_text }}</strong><span>{{ web.total_size }}</span></div>
      </div>
    </header>
    <section class="layout">
      <div class="file-list">
        {% if files %}
          {% for item in files %}
            <article class="file-card">
              <div class="file-icon" aria-hidden="true">{{ item.display_name[:1].upper() or "F" }}</div>
              <div class="file-title">
                <a href="{{ url_for('download_file', token=token, file_id=item.id) }}">{{ item.display_name }}</a>
                <div class="file-meta">
                  <span>{{ item.size_text }}</span>
                  <span>{{ item.source }}</span>
                  {% if item.folder_name %}<span>{{ item.folder_name }}</span>{% endif %}
                  <span>{{ item.mtime_text }}</span>
                  {% if item.protected %}<span class="pill">{{ web.badge_protected }}</span>{% endif %}
                </div>
                {% if item.protected and item.id not in unlocked_files and item.folder_id not in unlocked_folders %}
                  <form class="unlock" method="post" action="{{ url_for('unlock_file', token=token, file_id=item.id) }}">
                    <input name="password" type="password" placeholder="{{ web.unlock_file_placeholder }}">
                    <button type="submit">{{ web.file_lock_submit }}</button>
                  </form>
                {% endif %}
              </div>
              {% if not item.protected or item.id in unlocked_files or item.folder_id in unlocked_folders %}
                <a class="download" href="{{ url_for('download_file', token=token, file_id=item.id) }}">{{ web.download_label }}</a>
              {% endif %}
            </article>
          {% endfor %}
        {% else %}
          <div class="empty"><strong>{{ web.empty_title }}</strong><span>{{ web.empty_subtitle }}</span></div>
        {% endif %}
      </div>
      <aside class="tool-panel">
        <h2>{{ web.actions_title }}</h2>
        <p>{{ web.actions_subtitle }}</p>
        {% if files %}<a class="secondary" href="{{ url_for('download_all', token=token) }}">{{ web.download_zip_label }}</a>{% endif %}
        {% if folders %}
          <div class="folder-box">
            <strong>{{ web.folders_title }}</strong>
            {% for folder in folders %}
              <div class="folder-line">
                <span>{{ folder.name }}</span>
                {% if folder.protected and folder.id not in unlocked_folders %}
                  <form method="post" action="{{ url_for('unlock_folder', token=token, folder_id=folder.id) }}">
                    <input name="password" type="password" placeholder="{{ web.folder_password_placeholder }}">
                    <button type="submit">{{ web.folder_ok }}</button>
                  </form>
                {% else %}
                  <small>{{ folder.file_count }} {{ web.folder_files }}</small>
                {% endif %}
              </div>
            {% endfor %}
          </div>
        {% endif %}
        <div id="upload-disabled" class="notice" {% if upload_enabled %}hidden{% endif %}>{{ web.uploads_disabled }}</div>
        <form class="upload-zone" id="upload-zone" {% if not upload_enabled %}hidden{% endif %}>
          <strong>{{ web.upload_title }}</strong>
          <p>{{ web.upload_help }}</p>
          <input class="file-input" id="file-input" name="files" type="file" multiple>
          <button class="upload-button" type="button" id="choose-files">{{ web.upload_choose }}</button>
          <progress id="upload-progress" value="0" max="100" hidden></progress>
          <div class="message" id="message"></div>
        </form>
      </aside>
    </section>
  </main>
  <script>window.SHARE_TOKEN = {{ token|tojson }};</script>
  <script>window.CLIENT_TEXT = {{ client_text|tojson }};</script>
  <script src="{{ url_for('client_js', token=token) }}"></script>
</body>
</html>
"""


CLIENT_JS = r"""
const token=window.SHARE_TOKEN;
const text=window.CLIENT_TEXT||{};
const zone=document.getElementById("upload-zone"),disabled=document.getElementById("upload-disabled"),input=document.getElementById("file-input"),button=document.getElementById("choose-files"),message=document.getElementById("message"),progress=document.getElementById("upload-progress");
async function refreshStatus(){const r=await fetch(`/s/${token}/status`,{cache:"no-store"});if(!r.ok)return;const s=await r.json();if(zone)zone.hidden=!s.upload_enabled;if(disabled)disabled.hidden=s.upload_enabled}
async function uploadFiles(files){await refreshStatus();if(zone&&zone.hidden){if(message)message.textContent=text.upload_msg_disabled||"";return}if(!files||files.length===0)return;const f=new FormData();for(const file of files)f.append("files",file);if(progress){progress.hidden=false;progress.value=15}if(message)message.textContent=text.upload_msg_sending||"";try{const r=await fetch(`/s/${token}/upload`,{method:"POST",body:f,cache:"no-store"});if(progress)progress.value=100;const d=await r.json();if(message)message.textContent=d.message||text.upload_msg_done||"";if(r.ok)setTimeout(()=>window.location.reload(),800)}catch{if(message)message.textContent=text.upload_msg_failed||""}finally{if(input)input.value="";setTimeout(()=>{if(progress){progress.hidden=true;progress.value=0}},900)}}
if(zone&&input&&button){button.addEventListener("click",()=>input.click());input.addEventListener("change",()=>uploadFiles(input.files));["dragenter","dragover"].forEach(n=>zone.addEventListener(n,e=>{e.preventDefault();zone.classList.add("drag")}));["dragleave","drop"].forEach(n=>zone.addEventListener(n,e=>{e.preventDefault();zone.classList.remove("drag")}));zone.addEventListener("drop",e=>uploadFiles(e.dataTransfer.files))}
refreshStatus();setInterval(refreshStatus,2500);
"""





CLIENT_CSS = r"""
:root{--ink:#17212b;--muted:#607080;--line:rgba(255,255,255,.58);--glass:rgba(255,255,255,.66);--teal:#0f8a7a;--teal-dark:#0a655c;--coral:#ec6d5f;--shadow:0 24px 70px rgba(31,48,62,.15)}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:linear-gradient(135deg,#f4faf8 0%,#e9f1f5 48%,#f7f2ef 100%);color:var(--ink);font-family:"Segoe UI",system-ui,sans-serif;letter-spacing:0}body:before{content:"";position:fixed;inset:0;background:linear-gradient(120deg,rgba(15,138,122,.12),transparent 42%,rgba(236,109,95,.12));pointer-events:none}.shell{position:relative;z-index:1;width:min(1120px,calc(100% - 32px));margin:0 auto;padding:30px 0 38px}.topbar{display:grid;grid-template-columns:1fr auto;gap:18px;align-items:end;padding:18px;margin-bottom:18px;border-radius:8px;background:var(--glass);border:1px solid var(--line);box-shadow:var(--shadow);backdrop-filter:blur(24px)}.eyebrow{color:var(--teal-dark);font-weight:780;margin:0 0 8px}h1{margin:0;font-size:2rem;line-height:1.1}.subtitle{margin:10px 0 0;color:var(--muted);line-height:1.5}.stats{display:flex;gap:10px}.stat,.file-card,.tool-panel,.empty{background:var(--glass);border:1px solid var(--line);border-radius:8px;box-shadow:var(--shadow);backdrop-filter:blur(24px)}.stat{min-width:112px;padding:12px 14px}.stat strong{display:block;font-size:1.2rem}.stat span{color:var(--muted);font-size:.85rem}.layout{display:grid;grid-template-columns:minmax(0,1fr)340px;gap:18px;align-items:start}.file-list{display:grid;gap:10px}.file-card{display:grid;grid-template-columns:44px minmax(0,1fr) auto;gap:14px;align-items:center;padding:14px}.file-icon{width:44px;height:44px;border-radius:8px;background:linear-gradient(145deg,#d8f3ea,#fff);color:var(--teal-dark);display:grid;place-items:center;font-weight:900;border:1px solid rgba(15,138,122,.18)}.file-title{min-width:0}.file-title a{color:var(--ink);text-decoration:none;font-weight:780;overflow-wrap:anywhere}.file-meta{color:var(--muted);display:flex;flex-wrap:wrap;gap:8px 12px;margin-top:6px;font-size:.92rem}.pill{color:#7b2016;background:#ffe3df;border-radius:999px;padding:1px 8px}.download,.upload-button{border:1px solid rgba(255,255,255,.55);border-radius:8px;color:#fff;background:linear-gradient(180deg,var(--teal),var(--teal-dark));padding:11px 14px;min-width:112px;cursor:pointer;font-weight:760;text-decoration:none;text-align:center;box-shadow:0 10px 26px rgba(15,138,122,.2)}.download:hover,.upload-button:hover{filter:brightness(1.03)}.tool-panel{padding:18px;position:sticky;top:16px}.tool-panel h2{margin:0;font-size:1.15rem}.tool-panel p{margin:8px 0 0;color:var(--muted);line-height:1.45}.secondary{display:block;text-align:center;border:1px solid rgba(23,33,43,.1);color:var(--ink);background:rgba(255,255,255,.56);border-radius:8px;padding:11px 14px;text-decoration:none;font-weight:720;margin-top:12px}.folder-box{margin-top:18px;display:grid;gap:10px}.folder-line{border:1px solid rgba(23,33,43,.08);background:rgba(255,255,255,.5);border-radius:8px;padding:10px}.folder-line form{display:grid;grid-template-columns:1fr auto;gap:6px;margin-top:8px}.folder-line input,.unlock input{width:100%;padding:10px;border:1px solid rgba(23,33,43,.12);border-radius:8px;background:rgba(255,255,255,.72)}.folder-line button,.unlock button{border:0;border-radius:8px;background:var(--ink);color:#fff;padding:10px;font-weight:750}.upload-zone{margin-top:18px;border:2px dashed rgba(15,138,122,.35);background:rgba(244,251,249,.68);border-radius:8px;padding:18px;text-align:center}.upload-zone.drag{border-color:var(--coral);background:#fff3f1}.file-input{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}.notice,.unlock{margin-top:12px;padding:12px;border-radius:8px;background:rgba(255,248,223,.8);color:#684a08;border:1px solid #efd997;font-size:.94rem}.message{min-height:22px;margin-top:12px;color:var(--muted);font-size:.94rem}progress{width:100%;margin-top:12px;accent-color:var(--teal)}.empty{min-height:260px;display:grid;place-items:center;text-align:center;padding:28px}.empty span{color:var(--muted);margin-top:8px;display:block}@media(max-width:860px){.topbar,.layout{grid-template-columns:1fr}.tool-panel{position:static}}@media(max-width:620px){.shell{width:min(100% - 20px,1120px);padding-top:18px}h1{font-size:1.55rem}.file-card{grid-template-columns:40px minmax(0,1fr)}.download{grid-column:1/-1;width:100%}.stats{flex-direction:column}}
"""

ADMIN_HTML = r"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ app_name }} Admin</title>
  <link rel="stylesheet" href="{{ url_for('admin_css', token=token) }}">
</head>
<body>
  <main class="shell">
    <header class="top">
      <div>
        <p class="eyebrow">Asistente de publicacion</p>
        <h1>Comparte archivos en 4 pasos</h1>
        <p id="recommendation">Empieza anadiendo archivos o una carpeta.</p>
      </div>
      <div class="top-actions">
        <button data-action="start" class="primary">Publicar ahora</button>
        <button data-action="stop" class="secondary">Detener</button>
      </div>
    </header>

    <section class="status-strip">
      <div><span>Estado</span><strong id="status">Preparado</strong></div>
      <div><span>Archivos</span><strong id="file-count">0</strong></div>
      <div><span>Total</span><strong id="total-size">0 B</strong></div>
      <div><span>Subidas</span><strong id="upload-state">No</strong></div>
      <div><span>Descargas</span><strong id="active-count">0</strong></div>
    </section>

    <nav class="steps" aria-label="Pasos del asistente">
      <button class="step active" data-nav="step-files"><b>1</b><span>Que compartir</span></button>
      <button class="step" data-nav="step-access"><b>2</b><span>Acceso</span></button>
      <button class="step" data-nav="step-publish"><b>3</b><span>Publicar</span></button>
      <button class="step" data-nav="step-ready"><b>4</b><span>Listo</span></button>
    </nav>

    <section class="card wizard-panel active" id="step-files" data-section="step-files">
      <div class="section-head">
        <div><h2>Que quieres compartir?</h2><p>Anade archivos sueltos o una carpeta. Puedes quitar elementos desde la lista.</p></div>
        <div class="button-row">
          <button data-action="pick-files">Anadir archivos</button>
          <button data-action="pick-folder" class="secondary">Anadir carpeta</button>
        </div>
      </div>
      <label class="inline-check"><input id="include-subfolders" type="checkbox"> Incluir subcarpetas al anadir carpetas</label>
      <input id="file-search" class="search" placeholder="Buscar en archivos compartidos">
      <div id="files-list" class="item-list"></div>
      <div id="folders-list" class="item-list compact"></div>
    </section>

    <section class="card wizard-panel" id="step-access" data-section="step-access">
      <div class="section-head"><div><h2>Quien puede acceder?</h2><p>El enlace ya lleva token privado. Activa solo lo que necesites.</p></div></div>
      <div class="two-col">
        <div class="option-box">
          <h3>Contrasena global</h3>
          <p>Se pedira al abrir la pagina publica. No se guarda en configuracion.</p>
          <input id="global-password" type="password" placeholder="Nueva contrasena global">
          <div class="button-row"><button data-action="set-global">Aplicar</button><button data-action="clear-global" class="secondary">Quitar</button></div>
        </div>
        <div class="option-box">
          <h3>Subidas de clientes</h3>
          <label class="inline-check"><input id="upload-enabled" type="checkbox"> Permitir que suban archivos</label>
          <input id="upload-dir" placeholder="Carpeta donde guardar subidas">
          <button data-action="save-uploads">Guardar subidas</button>
        </div>
      </div>
      <details class="advanced">
        <summary>Seguridad avanzada</summary>
        <div class="three-col">
          <label>Clave para seleccion <input id="selection-password" type="password"></label>
          <button data-action="set-file-password">Clave archivo</button>
          <button data-action="set-folder-password">Clave carpeta</button>
          <button data-action="clear-file-password" class="secondary">Quitar clave archivo</button>
          <button data-action="clear-folder-password" class="secondary">Quitar clave carpeta</button>
          <label>Expirar enlace en minutos <input id="expiration-minutes" type="number" min="0" placeholder="0 = nunca"></label>
          <label>Limite por archivo <input id="download-limit" type="number" min="0" placeholder="0 = sin limite"></label>
          <label class="inline-check"><input id="uploads-require-global" type="checkbox"> Subidas requieren contrasena global</label>
          <button data-action="save-security">Guardar reglas</button>
          <label>IP <input id="ip-input" placeholder="1.2.3.4"></label>
          <button data-action="block-ip">Bloquear IP</button>
          <button data-action="unblock-ip" class="secondary">Desbloquear IP</button>
        </div>
        <p id="security-summary" class="muted"></p>
      </details>
    </section>

    <section class="card wizard-panel" id="step-publish" data-section="step-publish">
      <div class="section-head"><div><h2>Como lo publicamos?</h2><p>Automatico intenta Tailscale, despues Cloudflare y finalmente una URL LAN/local.</p></div></div>
      <div class="publish-choice">
        <label><input type="radio" name="mode-choice" value="auto" checked><span>Automatico recomendado</span><small>Tailscale -> Cloudflare -> puerto propio</small></label>
        <label><input type="radio" name="mode-choice" value="cloudflare"><span>Cloudflare rapido</span><small>Quick Tunnel temporal</small></label>
        <label><input type="radio" name="mode-choice" value="direct"><span>Puerto propio</span><small>Usa LAN/router/firewall del host</small></label>
      </div>
      <details class="advanced">
        <summary>Publicacion avanzada</summary>
        <div class="three-col">
          <label>Modo manual <select id="mode"><option value="auto">Automatico</option><option value="tailscale">Tailscale Funnel</option><option value="cloudflare">Cloudflare Quick Tunnel</option><option value="direct">Puerto propio</option></select></label>
          <label>Puerto local <input id="port" value="80"></label>
          <label>Puerto publico Tailscale <select id="tailscale-port"><option>443</option><option>8443</option><option>10000</option></select></label>
          <label class="inline-check"><input id="manual-port" type="checkbox"> Usar exactamente este puerto</label>
        </div>
      </details>
      <label class="save-box"><input id="save-preferences" type="checkbox"> Guardar esta configuracion y no preguntarme la proxima vez</label>
      <div class="button-row"><button data-action="start" class="primary big">Publicar ahora</button><button data-action="delete-preferences" class="secondary">Borrar configuracion guardada</button></div>
      <p id="preferences-message" class="muted"></p>
    </section>

    <section class="card wizard-panel" id="step-ready" data-section="step-ready">
      <div class="section-head"><div><h2>Enlace listo</h2><p>Copia esta URL para compartir los archivos. El panel admin sigue siendo solo local.</p></div></div>
      <div class="url-card">
        <input id="share-url" readonly placeholder="La URL aparecera aqui al publicar">
        <button id="copy-url" type="button">Copiar URL</button>
        <button id="open-client" type="button" class="secondary">Previsualizar</button>
      </div>
      <div class="two-col">
        <div class="option-box"><h3>Descargas activas</h3><div id="active-list" class="item-list compact"></div></div>
        <div class="option-box"><h3>Historial reciente</h3><a id="export-history" class="text-link" href="#">Exportar CSV</a><div id="history-list" class="item-list compact"></div></div>
      </div>
      <details class="advanced">
        <summary>Logs</summary>
        <pre id="logs"></pre>
      </details>
    </section>
  </main>

  <section id="client-preview" class="preview" hidden>
    <div class="preview-card">
      <div class="section-head"><div><h2>Previsualizacion cliente</h2><p>Vista integrada de la pagina publica.</p></div><button id="close-preview" class="secondary">Cerrar</button></div>
      <iframe id="preview-frame" title="Vista cliente"></iframe>
    </div>
  </section>
  <div id="context-menu" class="context-menu" hidden></div>
  <div id="toast" class="toast" hidden></div>
  <script>window.ADMIN_TOKEN = {{ token|tojson }};</script>
  <script src="{{ url_for('admin_js', token=token) }}"></script>
</body>
</html>
"""

ADMIN_CSS = r"""
:root{--bg:#f3f5f8;--surface:#fff;--surface-alt:#f9fbfe;--ink:#1b1f24;--muted:#5d6778;--line:#d7dde7;--line-strong:#c7ceda;--accent:#0b57d0;--accent-hover:#0847ab;--accent-soft:#e8f0fe;--warn:#fff6d9;--danger:#fde7e9;--danger-ink:#8a2f36;--shadow:0 10px 24px rgba(20,31,53,.08)}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:var(--bg);color:var(--ink);font-family:"Segoe UI",system-ui,sans-serif;letter-spacing:0}button,input,select{font:inherit;letter-spacing:0}button{border:1px solid transparent;border-radius:4px;background:var(--accent);color:#fff;padding:10px 14px;font-weight:700;cursor:pointer;min-height:40px}button:hover{background:var(--accent-hover)}button.secondary{background:#fff;color:var(--ink);border-color:var(--line-strong)}button.secondary:hover{background:var(--surface-alt)}button.big{font-size:1.02rem;padding:12px 18px}input,select{width:100%;border:1px solid var(--line-strong);border-radius:4px;padding:10px 12px;background:#fff;color:var(--ink)}label{display:grid;gap:7px;color:var(--muted);font-size:.92rem}.shell{width:min(1220px,calc(100% - 28px));margin:0 auto;padding:20px 0 32px}.top,.card,.status-strip,.steps{background:var(--surface);border:1px solid var(--line);border-radius:8px;box-shadow:var(--shadow)}.top{display:flex;justify-content:space-between;gap:18px;align-items:center;padding:18px;margin-bottom:12px}.top h1{margin:0;font-size:1.82rem;line-height:1.15}.top p{margin:6px 0 0;color:var(--muted)}.eyebrow{margin:0 0 6px;color:var(--accent);font-weight:760}.top-actions,.button-row,.url-card{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.status-strip{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:0;margin-bottom:12px;overflow:hidden}.status-strip div{padding:12px 14px;border-right:1px solid var(--line)}.status-strip div:last-child{border-right:0}.status-strip span{display:block;color:var(--muted);font-size:.82rem}.status-strip strong{display:block;margin-top:4px}.steps{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0;margin-bottom:14px;overflow:hidden}.step{background:#fff;color:var(--ink);border-radius:0;border-right:1px solid var(--line);justify-content:flex-start;display:flex;gap:10px;align-items:center;box-shadow:none}.step:last-child{border-right:0}.step b{width:28px;height:28px;border-radius:999px;background:var(--surface-alt);display:grid;place-items:center}.step.active{background:var(--accent-soft);color:var(--accent)}.step.active b{background:var(--accent);color:#fff}.wizard-panel{display:none;padding:18px;margin-bottom:14px}.wizard-panel.active{display:block}.section-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;margin-bottom:14px}.section-head h2{margin:0;font-size:1.4rem}.section-head h3,.option-box h3{margin:0 0 8px}.section-head p,.option-box p,.muted{color:var(--muted);margin:6px 0 0}.two-col{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.three-col{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;align-items:end}.option-box{border:1px solid var(--line);border-radius:8px;background:var(--surface-alt);padding:14px;display:grid;gap:10px}.inline-check,.save-box{display:flex;align-items:center;gap:9px;color:var(--ink);font-weight:620}.inline-check input,.save-box input{width:auto}.save-box{margin:14px 0;padding:12px;background:var(--warn);border:1px solid #e9d58f;border-radius:8px}.search{margin:12px 0}.item-list{display:grid;gap:8px}.item-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:center;border:1px solid var(--line);border-radius:8px;background:#fff;padding:11px}.item-row.selected{border-color:var(--accent);background:var(--accent-soft)}.item-row strong{display:block;overflow-wrap:anywhere}.item-row small{display:block;color:var(--muted);margin-top:4px;overflow-wrap:anywhere}.row-actions{display:flex;gap:6px;flex-wrap:wrap}.row-actions button{min-height:34px;padding:7px 10px;font-size:.9rem}.compact{max-height:310px;overflow:auto}.publish-choice{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.publish-choice label{border:1px solid var(--line);background:#fff;border-radius:8px;padding:14px;cursor:pointer;color:var(--ink)}.publish-choice input{width:auto;margin-right:8px}.publish-choice span{font-weight:760}.publish-choice small{display:block;color:var(--muted);margin-top:6px}.advanced{margin-top:16px;border:1px solid var(--line);border-radius:8px;background:var(--surface-alt);padding:12px}.advanced summary{cursor:pointer;font-weight:760}.advanced>div,.advanced pre{margin-top:12px}.url-card{background:var(--accent-soft);border:1px solid #cfdcff;border-radius:8px;padding:14px}.url-card input{flex:1;min-width:280px;font-weight:700}pre{margin:0;min-height:220px;max-height:360px;overflow:auto;background:#111827;color:#e6ecfa;padding:12px;border-radius:8px;white-space:pre-wrap}.text-link{color:var(--accent);font-weight:700}.pill{border-radius:999px;padding:2px 8px;background:var(--surface-alt);font-size:.82rem}.pill.danger{background:var(--danger);color:var(--danger-ink)}.preview{position:fixed;inset:0;z-index:20;background:rgba(20,24,33,.48);padding:24px}.preview-card{height:100%;display:grid;grid-template-rows:auto 1fr;background:#fff;border-radius:8px;padding:14px}.preview iframe{width:100%;height:100%;border:1px solid var(--line);border-radius:8px}.toast{position:fixed;right:22px;bottom:22px;z-index:30;background:#1e2430;color:#fff;border-radius:8px;padding:12px 14px;box-shadow:0 14px 34px rgba(13,18,28,.3)}.context-menu{position:fixed;z-index:25;background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 16px 34px rgba(20,31,53,.17);min-width:210px;padding:6px}.context-menu button{width:100%;justify-content:flex-start;background:transparent;color:var(--ink);border:0;font-weight:600}.context-menu button:hover{background:var(--surface-alt)}@media(max-width:900px){.top,.section-head{flex-direction:column}.status-strip,.steps,.two-col,.three-col,.publish-choice{grid-template-columns:1fr}.status-strip div,.step{border-right:0;border-bottom:1px solid var(--line)}}@media(max-width:620px){.shell{width:min(100% - 18px,1220px);padding-top:12px}.top h1{font-size:1.38rem}.top-actions,.button-row,.url-card{display:grid}.item-row{grid-template-columns:1fr}}
"""

ADMIN_JS = r"""
const token=window.ADMIN_TOKEN;
const apiBase=`/admin/${token}/api`;
let state=null,selectedFiles=new Set(),selectedFolders=new Set(),contextTarget=null,currentStep="step-files",initialPreferencesApplied=false;
const $=id=>document.getElementById(id);
async function api(path,options={}){const r=await fetch(`${apiBase}${path}`,{headers:{"Content-Type":"application/json",...(options.headers||{})},cache:"no-store",...options});const t=await r.text();let d={};try{d=t?JSON.parse(t):{}}catch{d={message:t}}if(!r.ok||d.ok===false)throw new Error(d.message||t||"Error");return d}
function escapeHtml(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function formatBytes(size){let v=Number(size||0);for(const u of["B","KB","MB","GB","TB"]){if(v<1024||u==="TB")return u==="B"?`${Math.round(v)} ${u}`:`${v.toFixed(1)} ${u}`;v/=1024}}
function notify(message){const t=$("toast");t.textContent=message;t.hidden=false;clearTimeout(notify.timer);notify.timer=setTimeout(()=>t.hidden=true,2600)}
function showStep(id){currentStep=id;document.querySelectorAll("[data-section]").forEach(s=>s.classList.toggle("active",s.dataset.section===id));document.querySelectorAll("[data-nav]").forEach(b=>b.classList.toggle("active",b.dataset.nav===id))}
function selectedFileIds(){return Array.from(selectedFiles)}
function selectedFolderIds(){return Array.from(selectedFolders)}
async function refresh(){state=await api("/state",{method:"GET"});render()}
function render(){if(!state)return;$("status").textContent=state.status;$("file-count").textContent=state.file_count;$("total-size").textContent=state.total_size_text;$("upload-state").textContent=state.upload_enabled?"Si":"No";$("active-count").textContent=state.active.length;$("recommendation").textContent=state.recommendation||"";$("share-url").value=state.share_url||"";$("logs").textContent=state.logs.join("\n");$("export-history").href=`${apiBase}/history/export`;$("expiration-minutes").placeholder=state.security.expires_at_text?`Expira: ${state.security.expires_at_text}`:"0 = nunca";$("security-summary").textContent=`IPs bloqueadas: ${(state.security.blocked_ips||[]).join(", ")||"ninguna"}`;if(!initialPreferencesApplied){$("upload-enabled").checked=!!state.upload_enabled;$("upload-dir").value=state.upload_dir||"";$("save-preferences").checked=!!state.preferences_saved;$("download-limit").value=state.security.download_limit_per_file||"";$("uploads-require-global").checked=!!state.security.uploads_require_global;applyPreferencesToInputs();initialPreferencesApplied=true}renderFiles();renderFolders();renderActive();renderHistory();if(state.wizard_step===4)showStep("step-ready");}
function applyPreferencesToInputs(){const p=state.preferences||{};$("mode").value=p.mode||"auto";$("port").value=p.port||"80";$("manual-port").checked=!!p.manual_port;$("tailscale-port").value=p.tailscale_public_port||"443";$("include-subfolders").checked=!!p.include_subfolders;document.querySelectorAll("input[name='mode-choice']").forEach(r=>r.checked=r.value===($("mode").value||"auto"))}
function renderFiles(){const list=$("files-list"),q=$("file-search").value.trim().toLowerCase();list.innerHTML="";const files=(state.files||[]).filter(f=>!q||f.display_name.toLowerCase().includes(q));if(!files.length){list.innerHTML="<div class='item-row'><div><strong>No hay archivos todavia</strong><small>Anade archivos o una carpeta para empezar.</small></div></div>";return}for(const f of files){const row=document.createElement("div");row.className=`item-row ${selectedFiles.has(f.id)?"selected":""}`;row.innerHTML=`<div><strong>${escapeHtml(f.display_name)}</strong><small>${f.size_text} - ${escapeHtml(f.source)} ${f.protected?"- protegido":""}</small><small>${escapeHtml(f.path)}</small></div><div class="row-actions"><button data-file-action="select" data-id="${f.id}" class="secondary">${selectedFiles.has(f.id)?"Seleccionado":"Seleccionar"}</button><button data-file-action="copy" data-id="${f.id}" class="secondary">Copiar enlace</button><button data-file-action="open" data-id="${f.id}" class="secondary">Ubicacion</button><button data-file-action="remove" data-id="${f.id}" class="secondary">Quitar</button></div>`;row.addEventListener("contextmenu",e=>showContext(e,"file",f.id));list.appendChild(row)}}
function renderFolders(){const list=$("folders-list");list.innerHTML="";for(const f of state.folders||[]){const row=document.createElement("div");row.className=`item-row ${selectedFolders.has(f.id)?"selected":""}`;row.innerHTML=`<div><strong>${escapeHtml(f.name)}</strong><small>${f.file_count} archivos - ${f.total_size_text}${f.protected?" - protegida":""}</small><small>${escapeHtml(f.path)}</small></div><div class="row-actions"><button data-folder-action="select" data-id="${f.id}" class="secondary">${selectedFolders.has(f.id)?"Seleccionada":"Seleccionar"}</button><button data-folder-action="refresh" data-id="${f.id}" class="secondary">Actualizar</button><button data-folder-action="remove" data-id="${f.id}" class="secondary">Quitar</button></div>`;row.addEventListener("contextmenu",e=>showContext(e,"folder",f.id));list.appendChild(row)}}
function renderActive(){const list=$("active-list");list.innerHTML="";for(const a of state.active||[]){const row=document.createElement("div");row.className="item-row";row.innerHTML=`<div><strong>${escapeHtml(a.file_name)}</strong><small>${escapeHtml(a.ip)} - ${a.percent.toFixed(0)}% - ${formatBytes(a.speed)}/s</small></div><div class="row-actions"><button data-transfer-action="cancel" data-id="${a.id}" class="secondary">Anular</button></div>`;list.appendChild(row)}if(!state.active.length)list.innerHTML="<p class='muted'>No hay descargas activas.</p>"}
function renderHistory(){const list=$("history-list");list.innerHTML="";for(const row of (state.history||[]).slice(0,40)){const div=document.createElement("div");div.className="item-row";div.innerHTML=`<div><strong>${escapeHtml(row.file_name||"-")}</strong><small>${row.updated_at} - ${row.event_type} - ${row.ip} - ${row.status}</small></div>`;list.appendChild(div)}}
function currentPreferences(){const mode=$("mode").value||document.querySelector("input[name='mode-choice']:checked")?.value||"auto";return{save_preferences:$("save-preferences").checked,mode,port:$("port").value,manual_port:$("manual-port").checked,tailscale_public_port:$("tailscale-port").value,upload_enabled:$("upload-enabled").checked,upload_dir:$("upload-dir").value,include_subfolders:$("include-subfolders").checked,file_paths:(state.files||[]).map(f=>f.path),folders:(state.folders||[]).map(f=>({path:f.path,include_subfolders:f.include_subfolders})),expiration_minutes:$("expiration-minutes").value,download_limit_per_file:$("download-limit").value,uploads_require_global:$("uploads-require-global").checked}}
async function savePreferenceChoice(prefs=currentPreferences()){if(prefs.save_preferences){await api("/preferences",{method:"POST",body:JSON.stringify(prefs)});$("preferences-message").textContent="Configuracion guardada."}else{await api("/preferences",{method:"DELETE"});$("preferences-message").textContent="La app preguntara cada vez."}}
async function copyText(value){if(!value){notify("No hay URL todavia.");return}try{await navigator.clipboard.writeText(value);notify("Copiado al portapapeles.")}catch{$("share-url").select();document.execCommand("copy");notify("Copiado al portapapeles.")}}
async function action(name){try{if(name==="pick-files"){await api("/files/pick",{method:"POST",body:"{}"});showStep("step-files")}if(name==="pick-folder"){await api("/folders/pick",{method:"POST",body:JSON.stringify({include_subfolders:$("include-subfolders").checked})});showStep("step-files")}if(name==="save-uploads")await api("/uploads",{method:"POST",body:JSON.stringify({enabled:$("upload-enabled").checked,upload_dir:$("upload-dir").value})});if(name==="start"){if(!state?.has_files){showStep("step-files");notify("Anade algun archivo antes de publicar.");return}const prefs=currentPreferences();await api("/uploads",{method:"POST",body:JSON.stringify({enabled:prefs.upload_enabled,upload_dir:prefs.upload_dir})});await api("/security/options",{method:"POST",body:JSON.stringify(prefs)});await savePreferenceChoice(prefs);await api("/publish/start",{method:"POST",body:JSON.stringify(prefs)});showStep("step-ready")}if(name==="stop")await api("/publish/stop",{method:"POST",body:"{}"});if(name==="set-global")await setGlobalPassword($("global-password").value);if(name==="clear-global")await setGlobalPassword("");if(name==="set-file-password")await api("/files/password",{method:"POST",body:JSON.stringify({ids:selectedFileIds(),password:$("selection-password").value})});if(name==="clear-file-password")await api("/files/password",{method:"POST",body:JSON.stringify({ids:selectedFileIds(),password:""})});if(name==="set-folder-password")await api("/folders/password",{method:"POST",body:JSON.stringify({ids:selectedFolderIds(),password:$("selection-password").value})});if(name==="clear-folder-password")await api("/folders/password",{method:"POST",body:JSON.stringify({ids:selectedFolderIds(),password:""})});if(name==="save-security")await api("/security/options",{method:"POST",body:JSON.stringify(currentPreferences())});if(name==="block-ip")await api("/ips/block",{method:"POST",body:JSON.stringify({ip:$("ip-input").value})});if(name==="unblock-ip")await api("/ips/unblock",{method:"POST",body:JSON.stringify({ip:$("ip-input").value})});if(name==="delete-preferences"){await api("/preferences",{method:"DELETE"});$("save-preferences").checked=false;$("preferences-message").textContent="Configuracion borrada."}$("selection-password").value="";$("global-password").value="";await refresh();notify("Listo.")}catch(e){notify(e.message)}}
async function setGlobalPassword(password){await api("/global-password",{method:"POST",body:JSON.stringify({password})})}
async function fileAction(kind,id){if(kind==="select"){selectedFiles.has(id)?selectedFiles.delete(id):selectedFiles.add(id);renderFiles();return}if(kind==="copy")await copyText(`${state.share_url}/download/${id}`);if(kind==="open")await api("/files/open-location",{method:"POST",body:JSON.stringify({id})});if(kind==="remove")await api("/files/remove",{method:"POST",body:JSON.stringify({ids:[id]})});await refresh()}
async function folderAction(kind,id){if(kind==="select"){selectedFolders.has(id)?selectedFolders.delete(id):selectedFolders.add(id);renderFolders();return}if(kind==="refresh")await api("/folders/refresh",{method:"POST",body:JSON.stringify({id})});if(kind==="remove")await api("/folders/remove",{method:"POST",body:JSON.stringify({id,remove_files:true})});await refresh()}
function showContext(e,type,id){e.preventDefault();contextTarget={type,id};const m=$("context-menu"),items=[];if(type==="file")items.push(["Copiar enlace","copy-file"],["Abrir ubicacion","open-location"],["Quitar","remove-file"],["Aplicar clave","file-pass"],["Quitar clave","file-clear"]);if(type==="folder")items.push(["Refrescar","refresh-folder"],["Quitar carpeta","remove-folder"],["Aplicar clave","folder-pass"],["Quitar clave","folder-clear"]);m.innerHTML=items.map(([l,a])=>`<button data-context="${a}">${l}</button>`).join("");m.style.left=`${e.clientX}px`;m.style.top=`${e.clientY}px`;m.hidden=false}
async function handleContext(a){const t=contextTarget;$("context-menu").hidden=true;if(!t)return;if(t.type==="file")selectedFiles=new Set([t.id]);if(t.type==="folder")selectedFolders=new Set([t.id]);const p=$("selection-password").value;if(a==="copy-file")await copyText(`${state.share_url}/download/${t.id}`);if(a==="open-location")await api("/files/open-location",{method:"POST",body:JSON.stringify({id:t.id})});if(a==="remove-file")await api("/files/remove",{method:"POST",body:JSON.stringify({ids:[t.id]})});if(a==="file-pass")await api("/files/password",{method:"POST",body:JSON.stringify({ids:[t.id],password:p})});if(a==="file-clear")await api("/files/password",{method:"POST",body:JSON.stringify({ids:[t.id],password:""})});if(a==="refresh-folder")await api("/folders/refresh",{method:"POST",body:JSON.stringify({id:t.id})});if(a==="remove-folder")await api("/folders/remove",{method:"POST",body:JSON.stringify({id:t.id,remove_files:true})});if(a==="folder-pass")await api("/folders/password",{method:"POST",body:JSON.stringify({ids:[t.id],password:p})});if(a==="folder-clear")await api("/folders/password",{method:"POST",body:JSON.stringify({ids:[t.id],password:""})});await refresh()}
function previewClient(){if(!state?.share_url){notify("Publica primero para previsualizar.");return}$("preview-frame").src=state.share_url;$("client-preview").hidden=false}
document.addEventListener("click",e=>{const nav=e.target.closest("[data-nav]");if(nav)showStep(nav.dataset.nav);const actionButton=e.target.closest("[data-action]");if(actionButton)action(actionButton.dataset.action);const fileButton=e.target.closest("[data-file-action]");if(fileButton)fileAction(fileButton.dataset.fileAction,fileButton.dataset.id);const folderButton=e.target.closest("[data-folder-action]");if(folderButton)folderAction(folderButton.dataset.folderAction,folderButton.dataset.id);const transferButton=e.target.closest("[data-transfer-action]");if(transferButton)api("/transfers/cancel",{method:"POST",body:JSON.stringify({id:transferButton.dataset.id})}).then(refresh);const context=e.target.closest("[data-context]");if(context)handleContext(context.dataset.context);if(!e.target.closest(".context-menu"))$("context-menu").hidden=true});
document.querySelectorAll("input[name='mode-choice']").forEach(r=>r.addEventListener("change",()=>{$("mode").value=r.value}));
$("mode").addEventListener("change",()=>document.querySelectorAll("input[name='mode-choice']").forEach(r=>r.checked=r.value===$("mode").value));
$("file-search").addEventListener("input",renderFiles);$("copy-url").addEventListener("click",()=>copyText(state?.share_url));$("open-client").addEventListener("click",previewClient);$("close-preview").addEventListener("click",()=>{$("client-preview").hidden=true;$("preview-frame").src="about:blank"});
refresh();setInterval(refresh,1500);
"""

def main() -> int:
    if not run_dependency_bootstrap_if_needed():
        return 1
    return run_integrated_admin_app()


if __name__ == "__main__":
    raise SystemExit(main())


