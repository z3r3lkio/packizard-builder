#!/usr/bin/env python3
"""Stage the exact external PPR-PKG Builder archive for Windows packaging.

The third-party binary is intentionally not tracked by git. CI can download an
operator-controlled archive, verify its SHA-256, and expand it into the location
that Packizard auto-detects and build_windows.ps1 bundles when present.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import urllib.request
import zipfile
from pathlib import Path

EXPECTED_ENTRY = "LibProsperoPkg.Gui.exe"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--destination", default="tools/ppr_pkg_builder")
    args = parser.parse_args()

    expected = args.sha256.strip().lower()
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise SystemExit("--sha256 must be a 64-character hexadecimal SHA-256")

    destination = Path(args.destination).resolve()
    archive = destination.parent / ".fpkg-gui-download.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)

    request = urllib.request.Request(args.url, headers={"User-Agent": "Packizard-Builder-CI"})
    with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as out:
        shutil.copyfileobj(response, out)

    actual = sha256(archive)
    if actual != expected:
        archive.unlink(missing_ok=True)
        raise SystemExit(f"SHA-256 mismatch: expected {expected}, got {actual}")

    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    with zipfile.ZipFile(archive) as zf:
        bad = [name for name in zf.namelist() if Path(name).is_absolute() or ".." in Path(name).parts]
        if bad:
            raise SystemExit(f"Unsafe ZIP path(s): {bad[:3]}")
        zf.extractall(destination)
    archive.unlink(missing_ok=True)

    if not (destination / EXPECTED_ENTRY).is_file():
        raise SystemExit(f"Archive does not contain {EXPECTED_ENTRY}")
    print(f"Staged PPR-PKG Builder at {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
