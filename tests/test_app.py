import io
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
                self.assertIn(b"Acceso protegido", response.data)
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
                self.assertIn(b"Archivo protegido", response.data)
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

    def test_tunnel_url_filtering(self) -> None:
        self.assertTrue(app.is_shareable_tunnel_url("tailscale", "https://equipo.tailnet.ts.net"))
        self.assertFalse(app.is_shareable_tunnel_url("tailscale", "http://127.0.0.1:8080"))
        self.assertTrue(app.is_shareable_tunnel_url("cloudflare", "https://random-name.trycloudflare.com"))
        self.assertFalse(app.is_shareable_tunnel_url("cloudflare", "http://localhost:8080"))


if __name__ == "__main__":
    unittest.main()
