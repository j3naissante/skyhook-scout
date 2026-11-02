"""Version command checks run against temporary copies, never the working version."""
from datetime import date
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


class VersionTests(unittest.TestCase):
    def test_package_and_portable_builder_use_the_app_version(self):
        from skyhook_scout import __version__
        config = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertIn("version", config["project"]["dynamic"])
        self.assertNotIn("version", config["project"])
        self.assertEqual(config["tool"]["setuptools"]["dynamic"]["version"]["attr"], "skyhook_scout.__version__")
        self.assertEqual(runpy.run_path(str(ROOT / "tools/build.py"))["VERSION"], __version__)

    def test_setuptools_resolves_the_app_version(self):
        try:
            from setuptools.config.pyprojecttoml import read_configuration
        except ImportError:
            self.skipTest("setuptools is not installed")
        from skyhook_scout import __version__
        self.assertEqual(read_configuration(str(ROOT / "pyproject.toml"))["project"]["version"], __version__)

    @unittest.skipUnless(POWERSHELL, "PowerShell is not installed")
    def test_version_command_updates_docs_and_rejects_invalid_input_without_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "tools").mkdir()
            (root / "skyhook_scout").mkdir()
            script = root / "tools/Set-Version.ps1"
            shutil.copy2(ROOT / "tools/Set-Version.ps1", script)
            (root / "skyhook_scout/__init__.py").write_text('__version__ = "1.1.0"\n__release_date__ = "2020-01-01"\n')
            for name in ("README.md", "BUILD.md"):
                (root / name).write_text("Skyhook Scout 1.1.0\nSkyhookScout-1.1.0-source.zip\n")
            def invoke(*args):
                return subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-File", str(script), *args],
                                      capture_output=True, text=True, timeout=30)
            before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
            result = invoke("1.1.1", "-WhatIf")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(before, {p: p.read_bytes() for p in before})
            result = invoke("1.1.1")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('__version__ = "1.1.1"', (root / "skyhook_scout/__init__.py").read_text())
            self.assertIn(f'__release_date__ = "{date.today().isoformat()}"', (root / "skyhook_scout/__init__.py").read_text())
            for name in ("README.md", "BUILD.md"):
                self.assertNotIn("1.1.0", (root / name).read_text())
                self.assertIn("1.1.1", (root / name).read_text())
            after = {p: p.read_bytes() for p in before}
            for value in ("1.1.1", "1.2", "256.1.1", "1.1.65536"):
                result = invoke(value)
                self.assertEqual(result.returncode == 0, value == "1.1.1", result.stderr)
                self.assertEqual(after, {p: p.read_bytes() for p in after})
