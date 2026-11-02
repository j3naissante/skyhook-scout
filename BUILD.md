# Run and compile Skyhook Scout

Use 64-bit Python 3.11–3.14. All commands run from the source directory. The packaged app includes Python and does not require an interpreter on the destination computer.

## Windows

Run from source in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m skyhook_scout
```

Compile a portable Windows executable:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe tools\build.py
```

Output: `dist/SkyhookScout/SkyhookScout.exe` and `releases/SkyhookScout-1.1.0-windows-x64.zip`. Extract the ZIP and keep `_internal/` beside the EXE.

## Linux

On Debian/Ubuntu, install the desktop runtime dependencies:

```bash
sudo apt update
sudo apt install python3 python3-venv libegl1 libgl1 libxkbcommon-x11-0 \
  libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-render-util0 libxcb-xinerama0 libxcb-randr0 libxcb-shape0
```

Run from source:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m skyhook_scout
```

Compile a portable Linux application:

```bash
.venv/bin/python -m pip install -r requirements-build.txt
.venv/bin/python tools/build.py
./dist/SkyhookScout/SkyhookScout
```

Output: `dist/SkyhookScout/SkyhookScout` and `releases/SkyhookScout-1.1.0-linux-x64.tar.gz` on x86-64 (the filename follows the build architecture). Keep the entire folder intact. Equivalent system libraries are needed on other distributions.

Build each platform on that platform: Windows executables on Windows and Linux executables on Linux. Linux bundles should be built on the oldest distribution you intend to support. The Windows build has been tested; Linux builds have not been tested on this Windows host.

## Checks and source archives

`skyhook_scout/` contains the app, `tests/` contains automated checks, and `tools/` contains build and validation helpers.

```bash
python -m unittest discover -s tests -v
python -m skyhook_scout --smoke-test build/qa/preview.png
```

The optional UI check runs offscreen with synthetic targets. `python tools/live_check.py` explicitly checks the live public APIs.

The build script also creates source ZIP/tarballs and `releases/SHA256SUMS.txt`. To repackage an existing compiled folder without rebuilding, run `python tools/build.py --package-only`.

Keep the bundled font, SVG UI controls, LICENSE and third-party notices. Generated screenshots, caches, build output and private files are excluded from source archives.
