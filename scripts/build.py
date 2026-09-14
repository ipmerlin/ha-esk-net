"""Build the manual-install ZIP using only integration files."""

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
component = ROOT / "custom_components/esk_net"
version = json.loads((component / "manifest.json").read_text(encoding="utf-8"))["version"]
destination = ROOT / "dist" / f"esk_net-{version}.zip"
destination.parent.mkdir(exist_ok=True)
with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
    for path in sorted(component.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".json", ".png"}:
            archive.write(path, path.relative_to(ROOT).as_posix())
print(destination)
