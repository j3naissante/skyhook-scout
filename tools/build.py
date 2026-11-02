"""Native Windows/Linux portable build. Does not upload or publish anything."""
from importlib.metadata import distribution
import argparse
from pathlib import Path
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.1.0"


def compile_app():
    os.chdir(ROOT)
    subprocess.run([sys.executable, "tools/fetch_licenses.py"], check=True)
    icon = ROOT / "build/icon.ico"
    icon.parent.mkdir(exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from skyhook_scout.ui import make_icon
    app = QApplication.instance() or QApplication([])
    make_icon().pixmap(128, 128).save(str(icon), "ICO")
    # Only the build process is offscreen. Do not bake this into the normal app.
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
               "--windowed", "--name", "SkyhookScout", "--icon", str(icon),
               "--specpath", "build", "--add-data", str(ROOT / "skyhook_scout/assets") + ":skyhook_scout/assets",
               "--exclude-module", "PyQt5", "--exclude-module", "PyQt6",
               "--exclude-module", "PySide2", "run.py"]
    subprocess.run(command, check=True)


def package():
    folder = ROOT / "dist/SkyhookScout"
    for name in ("README.md", "BUILD.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, folder / name)
    licenses = folder / "licenses"
    shutil.copytree(ROOT / "licenses", licenses, dirs_exist_ok=True)
    shutil.copy2(ROOT / "skyhook_scout/assets/OFL-Inter.txt", licenses / "OFL-Inter.txt")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        shutil.copy2(python_license, licenses / "Python-LICENSE.txt")
    for package in ("PySide6", "PySide6_Essentials", "shiboken6", "requests", "urllib3", "charset-normalizer", "idna", "certifi", "pyinstaller"):
        dist = distribution(package)
        for f in dist.files or []:
            parts = str(f).lower()
            if ".dist-info" in parts and ("license" in parts or "copying" in parts):
                source = Path(dist.locate_file(f))
                if source.is_file():
                    target = licenses / package / source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    releases = ROOT / "releases"
    releases.mkdir(exist_ok=True)
    system = "windows" if sys.platform == "win32" else "linux"
    arch = "x64" if platform.machine().lower() in ("amd64", "x86_64") else platform.machine().lower()
    stem = f"SkyhookScout-{VERSION}-{system}-{arch}"
    if system == "windows":
        output = Path(shutil.make_archive(str(releases / stem), "zip", ROOT / "dist", "SkyhookScout"))
    else:
        output = releases / (stem + ".tar.gz")
        with tarfile.open(output, "w:gz") as archive:
            archive.add(folder, arcname="SkyhookScout")
    source_zip = releases / f"SkyhookScout-{VERSION}-source.zip"
    exclude = {".git", ".venv", ".tools", ".flatpak-builder", "__pycache__", "build", "dist", "docs", "releases", ".pytest_cache", "private", "private-packaging", ".private", "PRIVATE_BUILD.md"}
    with zipfile.ZipFile(source_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.rglob("*")):
            rel = path.relative_to(ROOT)
            if path.is_file() and not any(part in exclude for part in rel.parts) and path.suffix not in (".pyc", ".sqlite3"):
                archive.write(path, Path("SkyhookScout-source") / rel)
    source_tar = releases / f"SkyhookScout-{VERSION}-source.tar.gz"
    with zipfile.ZipFile(source_zip) as source, tarfile.open(source_tar, "w:gz") as archive:
        import io
        for name in source.namelist():
            data = source.read(name)
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode = len(data), 0o644
            archive.addfile(entry, io.BytesIO(data))
    checksums = []
    for path in sorted(releases.glob(f"SkyhookScout-{VERSION}-*")):
        if not path.is_file():
            continue
        checksums.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name)
    (releases / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n")
    print("\nBuild complete:")
    print(output)
    print(source_zip)


if __name__ == "__main__":
    # Ensure local sources are importable when running python tools/build.py.
    sys.path.insert(0, str(ROOT))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-only", action="store_true", help="Repackage an existing dist/SkyhookScout without recompiling")
    args = parser.parse_args()
    if not args.package_only:
        compile_app()
    package()
