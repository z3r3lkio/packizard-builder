#!/usr/bin/env python3
"""Install the Packizard-owned PS5 runtime source tree into a reconstructed build."""
from __future__ import annotations

import argparse
import hashlib
import shutil
import tarfile
from pathlib import Path

ARCHIVE_NAME = "packizard_ps5_runtime.tar.xz"
ARCHIVE_SHA256 = "a51c1f9ec8ab9f56ea6736b5fbd08fce46ec345d20904a624fbaf23410504ae6"


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in archive.getmembers():
        name = Path(member.name)
        if name.is_absolute() or ".." in name.parts:
            raise RuntimeError(f"unsafe runtime archive member: {member.name}")
        resolved = (destination / name).resolve()
        if destination not in resolved.parents and resolved != destination:
            raise RuntimeError(f"runtime archive escapes destination: {member.name}")
    archive.extractall(destination, filter="data")


def install(repo_root: Path, output: Path) -> Path:
    source_archive = repo_root / "runtime" / "ps5" / ARCHIVE_NAME
    if not source_archive.is_file():
        raise RuntimeError(f"missing Packizard PS5 runtime source archive: {source_archive}")
    digest = hashlib.sha256(source_archive.read_bytes()).hexdigest()
    if digest != ARCHIVE_SHA256:
        raise RuntimeError(f"Packizard PS5 runtime source archive hash mismatch: {digest}")

    runtime_root = output / "packizard_runtime" / "ps5"
    shutil.rmtree(runtime_root, ignore_errors=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(source_archive, "r:xz") as archive:
        _safe_extract(archive, runtime_root)

    extracted = runtime_root / "packizard_ps5_runtime"
    required = [
        extracted / "src" / "sceampr_exports.cpp",
        extracted / "src" / "ampr_emu_pack.cpp",
        extracted / "include" / "ampr_emu_pack_format.h",
        extracted / "build_packizard_runtime.sh",
        extracted / "LICENSE",
    ]
    missing = [str(path.relative_to(runtime_root)) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("Packizard PS5 runtime source is incomplete: " + ", ".join(missing))

    identity = output / "core" / "packizard_ps5_runtime.py"
    identity.parent.mkdir(parents=True, exist_ok=True)
    identity.write_text(
        '"""Packizard PS5 runtime identity and compatibility ABI."""\n'
        'RUNTIME_NAME = "Packizard PS5 Runtime"\n'
        'RUNTIME_GENERATION = 1\n'
        'COMPATIBILITY_LIBRARY = "libSceAmpr.sprx"\n'
        'COMPATIBILITY_FORMAT = "AMPRPAK4"\n'
        'SOURCE_ROOT = "packizard_runtime/ps5/packizard_ps5_runtime"\n',
        encoding="utf-8", newline="\n",
    )

    marker = output / "resources" / "fakelib" / "PACKIZARD_RUNTIME_SOURCE.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        "Packizard PS5 Runtime source: packizard_runtime/ps5/packizard_ps5_runtime\n"
        "ABI compatibility filename: libSceAmpr.sprx\n"
        "Build with build_packizard_runtime.sh and PS5_PAYLOAD_SDK.\n",
        encoding="utf-8", newline="\n",
    )
    return extracted


def assert_installed(output: Path) -> None:
    root = output / "packizard_runtime" / "ps5" / "packizard_ps5_runtime"
    if not (root / "build_packizard_runtime.sh").is_file():
        raise RuntimeError("Packizard PS5 runtime build wrapper is missing")
    makefile = (root / "Makefile").read_text(encoding="utf-8", errors="replace")
    if "PS5_PAYLOAD_SDK" not in makefile:
        raise RuntimeError("Packizard PS5 runtime does not expose a PS5 payload SDK build")
    wrapper = (root / "build_packizard_runtime.sh").read_text(encoding="utf-8")
    if "out/packizard/libSceAmpr.sprx" not in wrapper:
        raise RuntimeError("Packizard PS5 runtime does not produce the compatibility SPRX")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="build-src")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output = Path(args.root).resolve()
    if not output.is_dir():
        raise SystemExit(f"source tree does not exist: {output}")
    installed = install(repo_root, output)
    assert_installed(output)
    print(f"Installed Packizard PS5 Runtime source at {installed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
