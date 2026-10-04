import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


class ProcessRestart(BaseException):
    """Stand-in for execv replacing the process rather than returning."""


class DependencyBootstrapTests(unittest.TestCase):
    def test_ready_environment_starts_without_installation(self):
        with mock.patch.object(app, "missing_runtime_modules", return_value=[]), \
                mock.patch.object(app, "import_web_dependencies", return_value=True), \
                mock.patch.object(app, "install_python_dependencies") as install, \
                mock.patch.object(app, "prepare_python_environment") as prepare:
            self.assertTrue(app.run_dependency_bootstrap_if_needed())
        install.assert_not_called()
        prepare.assert_not_called()

    def test_base_python_restarts_in_environment_preserving_arguments(self):
        python = Path("/tmp/usuario con espacios/python/bin/python")
        with mock.patch.object(app, "missing_runtime_modules", return_value=["PySide6"]), \
                mock.patch.object(app.sys, "prefix", sys.base_prefix), \
                mock.patch.object(app.sys, "argv", ["app.py", "nota con ñ.txt"]), \
                mock.patch.object(app, "prepare_python_environment", return_value=python), \
                mock.patch.object(app, "install_python_dependencies") as install, \
                mock.patch.object(app.os, "execv", side_effect=ProcessRestart) as restart:
            with self.assertRaises(ProcessRestart):
                app.run_dependency_bootstrap_if_needed()
        restart.assert_called_once_with(str(python), [str(python), str(Path(app.__file__).resolve()), "nota con ñ.txt"])
        install.assert_not_called()

    def test_script_without_requirements_installs_embedded_packages(self):
        result = subprocess.CompletedProcess([], 0, "installed")
        with mock.patch.object(app.Path, "is_file", return_value=False), \
                mock.patch.object(app.subprocess, "run", return_value=result) as run, \
                mock.patch.object(app, "import_web_dependencies", return_value=True), \
                mock.patch.object(app, "missing_runtime_modules", return_value=[]):
            app.install_python_dependencies(lambda _: None)
        command = run.call_args.args[0]
        self.assertEqual(command[0], sys.executable)
        self.assertNotIn("-r", command)
        self.assertEqual(command[-3:], list(app.RUNTIME_REQUIREMENTS))

    def test_missing_pip_is_bootstrapped_before_install(self):
        result = subprocess.CompletedProcess([], 0, "ok")
        with mock.patch.object(app.importlib.util, "find_spec", return_value=None), \
                mock.patch.object(app.subprocess, "run", return_value=result) as run, \
                mock.patch.object(app, "import_web_dependencies", return_value=True), \
                mock.patch.object(app, "missing_runtime_modules", return_value=[]):
            app.install_python_dependencies(lambda _: None)
        self.assertEqual(run.call_args_list[0].args[0], [sys.executable, "-m", "ensurepip", "--upgrade"])
        self.assertIn("install", run.call_args_list[1].args[0])

    def test_pip_can_be_repaired_from_base_when_ensurepip_is_unavailable(self):
        failure = subprocess.CompletedProcess([], 1, "No module named ensurepip")
        success = subprocess.CompletedProcess([], 0, "ok")
        with mock.patch.object(app.importlib.util, "find_spec", return_value=None), \
                mock.patch.object(app.sys, "_base_executable", "/base/python", create=True), \
                mock.patch.object(app.subprocess, "run", side_effect=[failure, success, success]) as run, \
                mock.patch.object(app, "import_web_dependencies", return_value=True), \
                mock.patch.object(app, "missing_runtime_modules", return_value=[]):
            app.install_python_dependencies(lambda _: None)
        command = run.call_args_list[1].args[0]
        self.assertEqual(command[:5], ["/base/python", "-m", "pip", "--python", sys.executable])

    def test_pip_failure_retains_the_diagnostic(self):
        result = subprocess.CompletedProcess([], 1, "ERROR: No matching distribution found for PySide6")
        with mock.patch.object(app.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "No matching distribution found for PySide6"):
                app.install_python_dependencies(lambda _: None)

    def test_environment_is_reused_without_recreation(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(app, "APP_DIR", Path(temp)), \
                    mock.patch.object(app.Path, "is_file", return_value=True), \
                    mock.patch.object(app.subprocess, "run") as run:
                python = app.prepare_python_environment(lambda _: None)
        self.assertTrue(str(python).startswith(temp))
        run.assert_not_called()

    def test_environment_creation_can_use_base_pip_on_linux(self):
        failure = subprocess.CompletedProcess([], 1, "ensurepip is not available")
        success = subprocess.CompletedProcess([], 0, "ok")
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(app, "APP_DIR", Path(temp)), \
                    mock.patch.object(app.subprocess, "run", side_effect=[failure, success, success]) as run:
                python = app.prepare_python_environment(lambda _: None)
        self.assertIn("--without-pip", run.call_args_list[1].args[0])
        self.assertEqual(run.call_args_list[2].args[0][3:5], ["--python", str(python)])

    def test_packaged_app_never_runs_pip_or_restarts_itself(self):
        with mock.patch.object(app.sys, "frozen", True, create=True), \
                mock.patch.object(app, "missing_runtime_modules", return_value=["PySide6"]), \
                mock.patch.object(app.subprocess, "run") as run, \
                mock.patch.object(app.os, "execv") as restart, \
                mock.patch.object(app, "show_native_notice") as notice:
            self.assertFalse(app.run_dependency_bootstrap_if_needed())
        run.assert_not_called()
        restart.assert_not_called()
        self.assertIn("Reinstala", notice.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
