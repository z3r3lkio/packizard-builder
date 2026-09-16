#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import platform
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

VERSION = "v2.5"
BASE = f"https://github.com/SvenGDK/LibProsperoPKG/releases/download/{VERSION}"
ASSETS = {
    "win-x64": ("libprosperopkg-win-x64.zip", "b4b3d290d5058a4fd408ca5c6e0207d8f4998eab3849c36d51dc5d97592fc151"),
    "win-arm64": ("libprosperopkg-win-arm64.zip", "0d9627c29177ddbd5fe8b03b209a7cf6b2ec49bc3ff32f7ef549b4c863dd92ea"),
    "linux-x64": ("libprosperopkg-linux-x64.zip", "c24797c3c75c28fd5642a62987edc37b4a03dfe11d31222c0af8b09a1373487b"),
    "linux-arm64": ("libprosperopkg-linux-arm64.zip", "79af4444e2126e0500da4a0767f5356573ac8dd5dfa1d761ca4838b29b710715"),
    "osx-arm64": ("libprosperopkg-osx-arm64.zip", "dc9056e290ecce591d211fb9a6a11560723dc35fce556e37bcae04c7b3b77b12"),
}


def current_platform() -> str:
    machine = platform.machine().lower()
    arm = machine in {"arm64", "aarch64"}
    if sys.platform.startswith("win"):
        return "win-arm64" if arm else "win-x64"
    if sys.platform == "darwin":
        if not arm:
            raise SystemExit("LibProsperoPkg v2.5 no publica un binario macOS x64.")
        return "osx-arm64"
    return "linux-arm64" if arm else "linux-x64"


def fetch(key: str, root: Path, force: bool = False) -> Path:
    if key not in ASSETS:
        raise SystemExit(f"Plataforma no soportada: {key}")
    asset, expected = ASSETS[key]
    dest = root / key
    marker = dest / ".libprospero-version"
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == VERSION and not force:
        print(f"LibProsperoPkg {VERSION} ya está instalado en {dest}")
        return dest

    url = f"{BASE}/{asset}"
    print(f"Descargando {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Packizard-Builder"})
    with urllib.request.urlopen(req, timeout=120) as response:
        data = response.read()
    actual = hashlib.sha256(data).hexdigest()
    if actual.lower() != expected.lower():
        raise SystemExit(f"SHA-256 inválido para {asset}: {actual}")

    tmp = dest.with_name(dest.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(tmp)
    libs = [p for p in tmp.rglob("*") if p.is_file() and p.suffix.lower() in {".dll", ".so", ".dylib"}]
    if not libs:
        raise SystemExit(f"El archivo {asset} no contiene una biblioteca nativa reconocible.")
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    for file in tmp.rglob("*"):
        if file.is_file():
            target = dest / file.name
            if not target.exists():
                shutil.copy2(file, target)
    shutil.rmtree(tmp, ignore_errors=True)
    marker.write_text(VERSION + "\n", encoding="utf-8")
    print(f"Instalado en {dest}")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description="Descarga el motor nativo LibProsperoPkg usado por Packizard Builder.")
    parser.add_argument("--platform", default="auto", choices=["auto", *ASSETS.keys()])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    root = Path(args.output).expanduser() if args.output else Path(__file__).resolve().parent.parent / "resources" / "pkg_engine"
    key = current_platform() if args.platform == "auto" else args.platform
    fetch(key, root, args.force)


if __name__ == "__main__":
    main()
