#!/usr/bin/env python3
"""Validate the Packizard-owned runtime layout and bundled compatibility module."""
from __future__ import annotations

from pathlib import Path

from core.packizard_ps5_runtime import COMPATIBILITY_LIBRARY, SOURCE_ROOT


def validate(root: Path) -> None:
    source = root / SOURCE_ROOT
    runtime = root / "resources" / "fakelib" / COMPATIBILITY_LIBRARY
    provenance = runtime.parent / "PACKIZARD_RUNTIME_SOURCE.txt"

    required = (
        source / "Makefile",
        source / "build_packizard_runtime.sh",
        source / "LICENSE",
        source / "PACKIZARD_RUNTIME.md",
    )
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("Packizard PS5 Runtime source is incomplete: " + ", ".join(missing))

    src_dir = source / "src"
    if not src_dir.is_dir() or not any(src_dir.glob("*.cpp")):
        raise RuntimeError(f"Packizard PS5 Runtime has no C++ implementation sources: {src_dir}")

    if not runtime.is_file():
        raise RuntimeError(f"Bundled PS5 runtime is missing: {runtime}")
    if runtime.stat().st_size < 4096:
        raise RuntimeError(f"Bundled PS5 runtime is unexpectedly small: {runtime}")
    if runtime.read_bytes()[:4] != b"\x7fELF":
        raise RuntimeError(f"Bundled PS5 runtime is not an ELF module: {runtime}")

    if not provenance.is_file():
        raise RuntimeError(f"Runtime source provenance marker is missing: {provenance}")
    text = provenance.read_text(encoding="utf-8")
    if SOURCE_ROOT not in text or COMPATIBILITY_LIBRARY not in text:
        raise RuntimeError("Runtime source provenance marker does not match the configured source/build contract")

    retired_external = root / "external" / "ampr_emu"
    if retired_external.exists():
        raise RuntimeError(f"Retired external runtime tree still exists: {retired_external}")


if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[1]
    validate(repo)
    print("Packizard PS5 Runtime validation passed")
