#!/usr/bin/env python3
"""Run the installed Linux app under Xvfb/DBus; exercise its real desktop process."""
import json
import os
import re
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def listening_ports(pid):
    sockets = set()
    for fd in Path(f"/proc/{pid}/fd").glob("*"):
        try:
            sockets.add(fd.readlink().as_posix())
        except OSError:
            pass
    for line in Path(f"/proc/{pid}/net/tcp").read_text().splitlines()[1:]:
        fields = line.split()
        address, port = fields[1].split(":")
        if fields[3] == "0A" and address == "0100007F" and f"socket:[{fields[9]}]" in sockets:
            yield int(port, 16)


with tempfile.TemporaryDirectory(prefix="fte-linux-smoke-") as temporary:
    workspace = Path(temporary)
    # Keep this test offline: the temporary helper stalls tunnel preparation.
    helper = workspace / "bin/cloudflared"
    helper.parent.mkdir()
    helper.write_text("#!/bin/sh\nexec /bin/sleep 60\n")
    helper.chmod(0o755)
    env = os.environ.copy()
    env.update(XDG_CONFIG_HOME=str(workspace / "config"),
               PATH=str(helper.parent) + os.pathsep + env["PATH"],
               WEBKIT_DISABLE_DMABUF_RENDERER="1")
    file = workspace / "nota con ñ.txt"
    file.write_text("File Transfer Easy Linux smoke test\n")
    folder = workspace / "Carpeta de prueba"
    folder.mkdir()
    (folder / "interior.txt").write_text("carpeta\n")
    with (workspace / "app.log").open("w+") as output:
        process = subprocess.Popen(["file-transfer-easy", str(file)], env=env,
                                   stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            deadline, base, token = time.monotonic() + 30, None, None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"La app terminó con {process.returncode}")
                for port in listening_ports(process.pid):
                    try:
                        candidate = f"http://127.0.0.1:{port}/"
                        html = urllib.request.urlopen(candidate, timeout=1).read().decode()
                        match = re.search(r'window\.__FTE_TOKEN__=("[^"\n]+")', html)
                        if match:
                            base, token = candidate, json.loads(match[1])
                            break
                    except (OSError, ValueError):
                        pass
                if base:
                    break
                time.sleep(0.1)
            assert base and token, "La interfaz no está disponible"

            def request(path, method="GET"):
                req = urllib.request.Request(base + path, headers={"X-FTE-Token": token},
                                             method=method, data=b"{}" if method == "POST" else None)
                return json.load(urllib.request.urlopen(req, timeout=3))

            # Wait for GTK's web process and the initial file-open event.
            while time.monotonic() < deadline:
                state = request("api/state")
                children = Path(f"/proc/{process.pid}/task/{process.pid}/children").read_text().split()
                webkit = any(b"WebKitWebProcess" in Path(f"/proc/{child}/cmdline").read_bytes()
                             for child in children if Path(f"/proc/{child}/cmdline").exists())
                if webkit and any(item["name"] == file.name for item in state["items"]):
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("GTK/WebKit o la apertura inicial del archivo no finalizaron")
            assert request("api/share/stop", "POST")["ok"]
            subprocess.run(["file-transfer-easy", str(folder)], env=env, check=True, timeout=10,
                           stdout=output, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if any(item["name"] == folder.name for item in request("api/state")["items"]):
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("La segunda instancia no añadió la carpeta")
            assert request("api/share/stop", "POST")["ok"]
            assert {item["name"] for item in request("api/state")["items"]} == {file.name, folder.name}
            assert process.poll() is None
            print("PASS Linux GTK/WebKit, initial file, second-instance folder and cancellation")
        except BaseException:
            output.flush()
            print((workspace / "app.log").read_text())
            raise
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
