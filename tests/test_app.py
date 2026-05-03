import io
import json
import tempfile
import unittest
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock

import app


class FileTransferEasyTests(unittest.TestCase):
    def make_state(self, tmp_path: Path) -> tuple[app.ShareState, app.StatsStore, app.TransferManager]:
        state = app.ShareState()
        stats = app.StatsStore(tmp_path / "stats.db")
        transfers = app.TransferManager(stats)
        return state, stats, transfers

    def test_share_page_download_zip_uploads_and_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            host_file = tmp_path / "documento con espacios.txt"
            host_file.write_text("hola mundo", encoding="utf-8")

            state, stats, transfers = self.make_state(tmp_path)
            added, errors = state.add_paths([str(host_file)])
            self.assertEqual(added, 1, errors)
            state.configure_uploads(False, str(tmp_path / "subidas"))

            web = app.create_web_app(state, stats, transfers)
            client = web.test_client()

            response = client.get("/s/token-invalido")
            self.assertEqual(response.status_code, 404)
            response.close()

            response = client.get(f"/s/{state.token}")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"documento con espacios.txt", response.data)
            response.close()

            file_id = state.snapshot()[0].id
            response = client.get(f"/s/{state.token}/download/{file_id}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"hola mundo")
            response.close()

            rows = stats.recent_events()
            self.assertEqual(rows[0]["event_type"], "download")
            self.assertEqual(rows[0]["status"], "completada")

            response = client.post(
                f"/s/{state.token}/upload",
                data={"files": (io.BytesIO(b"x"), "x.txt")},
            )
            self.assertEqual(response.status_code, 403)
            response.close()

            upload_dir = tmp_path / "subidas"
            state.configure_uploads(True, str(upload_dir))
            response = client.post(
                f"/s/{state.token}/upload",
                data={
                    "files": [
                        (io.BytesIO(b"uno"), "cliente.txt"),
                        (io.BytesIO(b"dos"), "cliente.txt"),
                    ]
                },
                content_type="multipart/form-data",
            )
            self.assertEqual(response.status_code, 200, response.data)
            response.close()
            self.assertEqual((upload_dir / "cliente.txt").read_bytes(), b"uno")
            self.assertEqual((upload_dir / "cliente (2).txt").read_bytes(), b"dos")

            response = client.get(f"/s/{state.token}/download-all")
            self.assertEqual(response.status_code, 200)
            zip_bytes = response.data
            response.close()
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
                names = set(archive.namelist())
                self.assertIn("documento con espacios.txt", names)
                self.assertIn("cliente.txt", names)
                self.assertIn("cliente (2).txt", names)

    def test_global_and_file_passwords(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            public_file = tmp_path / "publico.txt"
            secret_file = tmp_path / "secreto.txt"
            public_file.write_text("publico", encoding="utf-8")
            secret_file.write_text("secreto", encoding="utf-8")

            state, stats, transfers = self.make_state(tmp_path)
            state.add_paths([str(public_file), str(secret_file)])
            file_ids = {item.display_name: item.id for item in state.snapshot()}
            state.set_global_password("global")
            state.set_file_passwords([file_ids["secreto.txt"]], "archivo")

            web = app.create_web_app(state, stats, transfers)
            with web.test_client() as client:
                response = client.get(f"/s/{state.token}")
                self.assertIn(b"Protected Access", response.data)
                response.close()

                response = client.post(f"/s/{state.token}/auth", data={"password": "mal"})
                self.assertEqual(response.status_code, 403)
                response.close()

                response = client.post(f"/s/{state.token}/auth", data={"password": "global"})
                self.assertEqual(response.status_code, 302)
                response.close()

                response = client.get(f"/s/{state.token}")
                self.assertIn(b"secreto.txt", response.data)
                response.close()

                response = client.get(f"/s/{state.token}/download/{file_ids['secreto.txt']}")
                self.assertIn(b"Protected File", response.data)
                response.close()

                response = client.post(
                    f"/s/{state.token}/unlock/{file_ids['secreto.txt']}",
                    data={"password": "archivo"},
                )
                self.assertEqual(response.status_code, 302)
                response.close()

                response = client.get(f"/s/{state.token}/download/{file_ids['secreto.txt']}")
                self.assertEqual(response.data, b"secreto")
                response.close()

    def test_zip_excludes_locked_files_until_unlocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            unlocked = tmp_path / "abierto.txt"
            locked = tmp_path / "cerrado.txt"
            unlocked.write_text("a", encoding="utf-8")
            locked.write_text("b", encoding="utf-8")

            state, stats, transfers = self.make_state(tmp_path)
            state.add_paths([str(unlocked), str(locked)])
            ids = {item.display_name: item.id for item in state.snapshot()}
            state.set_file_passwords([ids["cerrado.txt"]], "clave")

            web = app.create_web_app(state, stats, transfers)
            client = web.test_client()
            response = client.get(f"/s/{state.token}/download-all")
            self.assertEqual(response.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                self.assertEqual(set(archive.namelist()), {"abierto.txt"})
            response.close()

    def test_folder_password_unlocks_folder_and_filters_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            public_file = tmp_path / "publico.txt"
            public_file.write_text("publico", encoding="utf-8")
            folder = tmp_path / "privada"
            folder.mkdir()
            folder_file = folder / "carpeta.txt"
            folder_file.write_text("carpeta", encoding="utf-8")

            state, stats, transfers = self.make_state(tmp_path)
            state.add_paths([str(public_file)])
            added, errors = state.add_folder(str(folder), password="clave")
            self.assertEqual(added, 1, errors)
            folder_id = state.folders_snapshot()[0].id
            folder_file_id = [item.id for item in state.snapshot() if item.display_name == "carpeta.txt"][0]

            web = app.create_web_app(state, stats, transfers)
            with web.test_client() as client:
                response = client.get(f"/s/{state.token}/download-all")
                self.assertEqual(response.status_code, 200)
                with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                    self.assertEqual(set(archive.namelist()), {"publico.txt"})
                response.close()

                response = client.get(f"/s/{state.token}/download/{folder_file_id}")
                self.assertIn(b"Protected File", response.data)
                response.close()

                response = client.post(
                    f"/s/{state.token}/unlock-folder/{folder_id}",
                    data={"password": "clave"},
                )
                self.assertEqual(response.status_code, 302)
                response.close()

                response = client.get(f"/s/{state.token}/download/{folder_file_id}")
                self.assertEqual(response.data, b"carpeta")
                response.close()

    def test_stale_page_cannot_upload_when_uploads_are_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            upload_dir = tmp_path / "uploads"
            state, stats, transfers = self.make_state(tmp_path)
            state.configure_uploads(True, str(upload_dir))
            web = app.create_web_app(state, stats, transfers)
            client = web.test_client()

            response = client.get(f"/s/{state.token}")
            self.assertEqual(response.status_code, 200)
            response.close()

            state.configure_uploads(False, str(upload_dir))
            response = client.post(
                f"/s/{state.token}/upload",
                data={"files": (io.BytesIO(b"late"), "late.txt")},
            )
            self.assertEqual(response.status_code, 403)
            response.close()
            self.assertFalse((upload_dir / "late.txt").exists())

    def test_folder_selection_non_recursive_and_recursive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "carpeta"
            nested = folder / "sub"
            nested.mkdir(parents=True)
            (folder / "uno.txt").write_text("1", encoding="utf-8")
            (nested / "dos.txt").write_text("2", encoding="utf-8")

            state = app.ShareState()
            added, errors = state.add_folder(str(folder), include_subfolders=False)
            self.assertEqual(added, 1, errors)
            self.assertEqual({item.display_name for item in state.snapshot()}, {"uno.txt"})

            added, errors = state.add_folder(str(folder), include_subfolders=True)
            self.assertEqual(added, 1, errors)
            self.assertEqual({item.display_name for item in state.snapshot()}, {"uno.txt", "dos.txt"})

    def test_stats_store_persists_and_exports_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "stats.db"
            stats = app.StatsStore(db_path)
            stats.record_simple("upload", "f1", "archivo.txt", "1.2.3.4", "directa", "ua", 12, "completada")

            reopened = app.StatsStore(db_path)
            rows = reopened.recent_events()
            self.assertEqual(rows[0]["file_name"], "archivo.txt")
            self.assertEqual(rows[0]["ip"], "1.2.3.4")

            csv_path = Path(tmp) / "historial.csv"
            reopened.export_csv(csv_path)
            self.assertIn("archivo.txt", csv_path.read_text(encoding="utf-8"))

    def test_streaming_download_can_be_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            big_file = tmp_path / "grande.bin"
            big_file.write_bytes(b"x" * (app.CHUNK_SIZE * 4))

            state, stats, transfers = self.make_state(tmp_path)
            state.add_paths([str(big_file)])
            file_id = state.snapshot()[0].id

            web = app.create_web_app(state, stats, transfers)
            client = web.test_client()
            response = client.get(f"/s/{state.token}/download/{file_id}", buffered=False)
            iterator = iter(response.response)
            first_chunk = next(iterator)
            self.assertGreater(len(first_chunk), 0)
            active = transfers.snapshot_active()
            self.assertEqual(len(active), 1)
            self.assertTrue(transfers.cancel(active[0]["id"]))
            b"".join(iterator)
            response.close()

            rows = stats.recent_events()
            self.assertEqual(rows[0]["status"], "cancelada")
            self.assertLess(rows[0]["bytes_done"], rows[0]["size_total"])

    def test_waitress_server_starts_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            host_file = tmp_path / "archivo.txt"
            host_file.write_text("ok", encoding="utf-8")

            state, stats, transfers = self.make_state(tmp_path)
            state.add_paths([str(host_file)])
            port = app.get_free_port()

            logs: list[str] = []
            server = app.WebServer(state, stats, transfers, logs.append)
            server.start(port)
            try:
                response = urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/s/{state.token}",
                    timeout=5,
                )
                try:
                    self.assertEqual(response.status, 200)
                finally:
                    response.close()
            finally:
                server.stop()

    def test_admin_api_requires_token_and_manages_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            host_file = tmp_path / "admin.txt"
            host_file.write_text("admin", encoding="utf-8")

            controller = app.AppController()
            web = app.create_admin_app(controller)
            client = web.test_client()

            response = client.get("/admin/bad/api/state")
            self.assertEqual(response.status_code, 404)
            response.close()

            response = client.post(
                f"/admin/{controller.admin_token}/api/files/add",
                json={"paths": [str(host_file)]},
            )
            self.assertEqual(response.status_code, 200)
            response.close()

            response = client.get(f"/admin/{controller.admin_token}/api/state")
            data = response.get_json()
            response.close()
            self.assertEqual(data["file_count"], 1)
            self.assertEqual(data["files"][0]["display_name"], "admin.txt")

    def test_admin_wizard_ui_smoke(self) -> None:
        self.assertIn("Comparte archivos en 4 pasos", app.ADMIN_HTML)
        self.assertIn("Guardar esta configuracion y no preguntarme la proxima vez", app.ADMIN_HTML)
        self.assertIn("Que compartir", app.ADMIN_HTML)
        self.assertIn("Automatico recomendado", app.ADMIN_HTML)
        self.assertIn("Seguridad avanzada", app.ADMIN_HTML)
        self.assertIn("Publicacion avanzada", app.ADMIN_HTML)

    def test_admin_and_public_routes_are_separated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state, stats, transfers = self.make_state(tmp_path)
            public_app = app.create_web_app(state, stats, transfers)
            controller = app.AppController()
            admin_app = app.create_admin_app(controller)

            public_response = public_app.test_client().get(f"/admin/{controller.admin_token}")
            self.assertEqual(public_response.status_code, 404)
            public_response.close()

            admin_response = admin_app.test_client().get(f"/s/{state.token}")
            self.assertEqual(admin_response.status_code, 404)
            admin_response.close()

    def test_embedded_assets_are_served_no_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state, stats, transfers = self.make_state(Path(tmp))
            public_app = app.create_web_app(state, stats, transfers)
            public_client = public_app.test_client()

            response = public_client.get(f"/s/{state.token}/assets/client.css")
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/css", response.headers["Content-Type"])
            self.assertIn("no-store", response.headers["Cache-Control"])
            response.close()

            response = public_client.get(f"/s/{state.token}/assets/client.js")
            self.assertEqual(response.status_code, 200)
            self.assertIn("javascript", response.headers["Content-Type"])
            response.close()

            controller = app.AppController()
            admin_app = app.create_admin_app(controller)
            admin_client = admin_app.test_client()
            response = admin_client.get(f"/admin/{controller.admin_token}/assets/admin.css")
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/css", response.headers["Content-Type"])
            response.close()

            response = admin_client.get(f"/admin/{controller.admin_token}/assets/admin.js")
            self.assertEqual(response.status_code, 200)
            self.assertIn("javascript", response.headers["Content-Type"])
            response.close()

    def test_preferences_are_saved_without_secrets_and_can_be_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            with mock.patch.object(app, "SETTINGS_PATH", settings_path):
                controller = app.AppController()
                payload = {
                    "save_preferences": True,
                    "mode": "auto",
                    "port": "8080",
                    "manual_port": True,
                    "tailscale_public_port": "8443",
                    "upload_enabled": True,
                    "upload_dir": str(Path(tmp) / "uploads"),
                    "include_subfolders": True,
                    "file_paths": [str(Path(tmp) / "archivo.txt")],
                    "folders": [{"path": str(Path(tmp) / "carpeta"), "include_subfolders": True}],
                    "expiration_minutes": 30,
                    "download_limit_per_file": 2,
                    "uploads_require_global": True,
                    "ui_language": "es",
                    "global_password": "no-se-guarda",
                    "password_hash": "tampoco",
                    "token": "no",
                }
                controller.save_preferences_from_payload(payload)
                saved = json.loads(settings_path.read_text(encoding="utf-8"))
                self.assertTrue(saved["save_preferences"])
                self.assertEqual(saved["mode"], "auto")
                self.assertEqual(saved["ui_language"], "es")
                self.assertNotIn("global_password", saved)
                self.assertNotIn("password_hash", saved)
                self.assertNotIn("token", saved)

                controller.delete_saved_preferences()
                self.assertFalse(settings_path.exists())

    def test_ui_language_preference_defaults_and_roundtrip(self) -> None:
        self.assertEqual(app.sanitize_preferences({})["ui_language"], "en")
        self.assertEqual(app.sanitize_preferences({"ui_language": "invalid"})["ui_language"], "en")
        self.assertEqual(app.sanitize_preferences({"ui_language": "es"})["ui_language"], "es")

        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            raw = dict(app.DEFAULT_PREFERENCES)
            raw["ui_language"] = "es"
            app.save_preferences(raw, settings_path)
            loaded = app.load_preferences(settings_path)
            self.assertEqual(loaded["ui_language"], "es")

    def test_public_web_uses_host_language_for_en_and_es(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            host_file = tmp_path / "hello.txt"
            host_file.write_text("ok", encoding="utf-8")
            state, stats, transfers = self.make_state(tmp_path)
            state.add_paths([str(host_file)])
            public_app = app.create_web_app(state, stats, transfers)
            client = public_app.test_client()

            response = client.get(f"/s/{state.token}")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Shared Files", response.data)
            self.assertIn(b"Download ( ZIP )", response.data)
            response.close()

            state.set_ui_language("es")
            response = client.get(f"/s/{state.token}")
            self.assertEqual(response.status_code, 200)
            self.assertIn("Archivos compartidos".encode("utf-8"), response.data)
            self.assertIn("Descargar ( ZIP )".encode("utf-8"), response.data)
            self.assertIn("Sesión privada".encode("utf-8"), response.data)
            response.close()

    def test_saved_preferences_restore_existing_paths_and_ignore_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            settings_path = tmp_path / "settings.json"
            host_file = tmp_path / "ok.txt"
            host_file.write_text("ok", encoding="utf-8")
            folder = tmp_path / "folder"
            folder.mkdir()
            (folder / "inside.txt").write_text("inside", encoding="utf-8")
            settings_path.write_text(
                json.dumps(
                    {
                        "save_preferences": True,
                        "file_paths": [str(host_file), str(tmp_path / "missing.txt")],
                        "folders": [
                            {"path": str(folder), "include_subfolders": False},
                            {"path": str(tmp_path / "missing-folder"), "include_subfolders": False},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(app, "SETTINGS_PATH", settings_path):
                controller = app.AppController()

            names = {item.display_name for item in controller.state.snapshot()}
            self.assertEqual(names, {"ok.txt", "inside.txt"})
            self.assertEqual(len(controller.last_preference_warnings), 2)

    def test_automatic_publish_falls_back_to_direct(self) -> None:
        controller = app.AppController()
        controller.web_server.start = mock.Mock()
        controller.tunnel.start_tailscale = mock.Mock(side_effect=RuntimeError("sin tailscale"))
        controller.tunnel.start_cloudflare = mock.Mock(side_effect=RuntimeError("sin cloudflare"))
        result = controller.start_publish({"mode": "auto", "port": "0"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "direct")
        self.assertIn("/s/", result["url"])

    def test_link_expiration_blocks_public_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state, stats, transfers = self.make_state(Path(tmp))
            with mock.patch("app.time.time", return_value=1000):
                state.configure_security_options(expiration_minutes=1)

            public_app = app.create_web_app(state, stats, transfers)
            with mock.patch("app.time.time", return_value=1061):
                response = public_app.test_client().get(f"/s/{state.token}")
            self.assertEqual(response.status_code, 410)
            response.close()

    def test_download_limit_and_ip_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            host_file = tmp_path / "limite.txt"
            host_file.write_text("limite", encoding="utf-8")

            state, stats, transfers = self.make_state(tmp_path)
            state.add_paths([str(host_file)])
            state.configure_security_options(download_limit_per_file=1)
            file_id = state.snapshot()[0].id
            public_app = app.create_web_app(state, stats, transfers)
            client = public_app.test_client()

            response = client.get(f"/s/{state.token}/download/{file_id}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"limite")
            response.close()

            response = client.get(f"/s/{state.token}/download/{file_id}")
            self.assertEqual(response.status_code, 403)
            response.close()

            state.block_ip("127.0.0.1")
            response = client.get(f"/s/{state.token}")
            self.assertEqual(response.status_code, 403)
            response.close()

    def test_uploads_can_require_global_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            upload_dir = tmp_path / "subidas"
            state, stats, transfers = self.make_state(tmp_path)
            state.configure_uploads(True, str(upload_dir))
            state.set_global_password("global")
            state.configure_security_options(uploads_require_global=True)

            public_app = app.create_web_app(state, stats, transfers)
            with public_app.test_client() as client:
                response = client.post(
                    f"/s/{state.token}/upload",
                    data={"files": (io.BytesIO(b"no"), "no.txt")},
                )
                self.assertEqual(response.status_code, 403)
                response.close()
                self.assertFalse((upload_dir / "no.txt").exists())

                response = client.post(f"/s/{state.token}/auth", data={"password": "global"})
                self.assertEqual(response.status_code, 302)
                response.close()

                response = client.post(
                    f"/s/{state.token}/upload",
                    data={"files": (io.BytesIO(b"si"), "si.txt")},
                    content_type="multipart/form-data",
                )
                self.assertEqual(response.status_code, 200)
                response.close()
                self.assertEqual((upload_dir / "si.txt").read_bytes(), b"si")

    def test_build_script_does_not_require_template_static_add_data(self) -> None:
        build_script = Path("build.ps1").read_text(encoding="utf-8")
        self.assertNotIn("--add-data \"templates;templates\"", build_script)
        self.assertNotIn("--add-data \"static;static\"", build_script)
        self.assertIn("$LASTEXITCODE", build_script)

    def test_tunnel_read_output_survives_stop_race(self) -> None:
        logs: list[str] = []
        urls: list[str] = []
        tunnel = app.TunnelProcess(logs.append, urls.append)
        process = mock.Mock()
        process.stdout = ["https://race.trycloudflare.com\n"]
        process.poll.return_value = 0
        tunnel.process = None
        tunnel._read_output(process, "cloudflare")
        self.assertEqual(urls, ["https://race.trycloudflare.com"])

    def test_cloudflared_download_fallback_with_mocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"

            def fake_download(_url, target):
                Path(target).write_bytes(b"exe")
                return target, None

            with mock.patch.object(app, "LOCAL_BIN_DIR", bin_dir):
                with mock.patch("app.shutil.which", return_value=None):
                    with mock.patch("app.urlretrieve", side_effect=fake_download):
                        path = app.install_cloudflared()

            self.assertEqual(Path(path), bin_dir / "cloudflared.exe")
            self.assertTrue(Path(path).exists())

    def test_python_dependency_installer_uses_requirements(self) -> None:
        completed = subprocess_result = mock.Mock()
        subprocess_result.returncode = 0
        subprocess_result.stdout = "ok"
        logs: list[str] = []
        with mock.patch("app.subprocess.run", return_value=completed) as run:
            with mock.patch("app.import_web_dependencies", return_value=True):
                with mock.patch("app.missing_runtime_modules", return_value=[]):
                    app.install_python_dependencies(logs.append)

        command = run.call_args.args[0]
        self.assertIn("-m", command)
        self.assertIn("pip", command)
        self.assertIn("-r", command)
        self.assertTrue(any("Instalando dependencias" in line for line in logs))

    def test_python_dependency_installer_reports_failure(self) -> None:
        completed = mock.Mock()
        completed.returncode = 1
        completed.stdout = "boom"
        with mock.patch("app.subprocess.run", return_value=completed):
            with self.assertRaises(RuntimeError):
                app.install_python_dependencies()

    def test_runtime_ui_has_no_tkinter_legacy(self) -> None:
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertNotIn("import tkinter", source)
        self.assertNotIn("from tkinter import", source)
        self.assertNotIn("class LegacyTkApp", source)
        self.assertNotIn("class FileTransferApp", source)

    def test_dependency_bootstrap_success_returns_true_without_error_notice(self) -> None:
        with mock.patch("app.missing_runtime_modules", return_value=["PySide6"]):
            with mock.patch("app.install_python_dependencies") as installer:
                with mock.patch("app.import_web_dependencies", return_value=True):
                    with mock.patch("app.show_native_notice") as notice:
                        self.assertTrue(app.run_dependency_bootstrap_if_needed())
        installer.assert_called_once()
        notice.assert_called_once()
        self.assertFalse(notice.call_args.kwargs.get("error", False))

    def test_dependency_bootstrap_failure_returns_false_and_shows_error(self) -> None:
        with mock.patch("app.missing_runtime_modules", return_value=["PySide6"]):
            with mock.patch(
                "app.install_python_dependencies",
                side_effect=RuntimeError("fallo de instalacion"),
            ):
                with mock.patch("app.show_native_notice") as notice:
                    self.assertFalse(app.run_dependency_bootstrap_if_needed())
        notice.assert_called_once()
        self.assertTrue(notice.call_args.kwargs.get("error", False))

    def test_tunnel_url_filtering(self) -> None:
        self.assertTrue(app.is_shareable_tunnel_url("tailscale", "https://equipo.tailnet.ts.net"))
        self.assertFalse(app.is_shareable_tunnel_url("tailscale", "http://127.0.0.1:8080"))
        self.assertTrue(app.is_shareable_tunnel_url("cloudflare", "https://random-name.trycloudflare.com"))
        self.assertFalse(app.is_shareable_tunnel_url("cloudflare", "http://localhost:8080"))

    def test_integrated_qt_webview_runtime_is_declared(self) -> None:
        requirements = Path("requirements.txt").read_text(encoding="utf-8")
        build_script = Path("build.ps1").read_text(encoding="utf-8")
        self.assertIn("PySide6", requirements)
        self.assertIn("--hidden-import PySide6.QtWebEngineWidgets", build_script)
        self.assertNotIn("window.open", app.ADMIN_JS)

    def test_only_one_active_embedded_constant_per_asset(self) -> None:
        source = Path("app.py").read_text(encoding="utf-8")
        for name in ["CLIENT_HTML", "CLIENT_CSS", "CLIENT_JS", "ADMIN_HTML", "ADMIN_CSS", "ADMIN_JS"]:
            self.assertEqual(source.count(f"\n{name} = r\"\"\""), 1, name)


if __name__ == "__main__":
    unittest.main()
