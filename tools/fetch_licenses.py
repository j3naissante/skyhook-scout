"""Fetch the open font and upstream license texts used in release archives."""
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "skyhook_scout/assets/Inter.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf",
    "skyhook_scout/assets/OFL-Inter.txt": "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/OFL.txt",
    "licenses/LGPL-3.0-only.txt": "https://raw.githubusercontent.com/pyside/pyside-setup/v6.11.0/LICENSES/LGPL-3.0-only.txt",
    "licenses/GPL-3.0-only.txt": "https://raw.githubusercontent.com/pyside/pyside-setup/v6.11.0/LICENSES/GPL-3.0-only.txt",
}
for filename, url in FILES.items():
    target = ROOT / filename
    if target.exists():
        continue
    response = requests.get(url, timeout=45)
    response.raise_for_status()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(response.content)
    print(f"Downloaded {filename} ({len(response.content)} bytes)")
