#!/usr/bin/env python3
"""Apply the first Packizard-native engine migration to a reconstructed tree.

This profile is intentionally transitional. It replaces the compression codec,
product-facing engine naming and Windows packaging assumptions while preserving
AMPRPAK4 compatibility. Once the inherited source tree has been absorbed into
this repository, this script can disappear and its changes become normal source.
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
from pathlib import Path


UI_REPLACEMENTS = (
    ("Lazy_AMPR", "Packizard Builder"),
    ("Lazy AMPR", "Packizard Builder"),
    ("AMPR/LZ4 compression", "Packizard compression"),
    ("LZ4/AMPR compression", "Packizard compression"),
    ("AMPR/LZ4", "Packizard Engine"),
    ("LZ4/AMPR", "Packizard Engine"),
    ("LZ4 Compression", "Packizard Compression"),
)


def _replace_text(path: Path, replacements: tuple[tuple[str, str], ...]) -> bool:
    text = path.read_text(encoding="utf-8")
    changed = text
    for old, new in replacements:
        changed = changed.replace(old, new)
    if changed == text:
        return False
    path.write_text(changed, encoding="utf-8", newline="\n")
    return True


def install_codec(repo_root: Path, output: Path) -> None:
    source = repo_root / "native" / "packizard_lz4.py"
    destination = output / "core" / "packizard_lz4.py"
    if not source.is_file():
        raise RuntimeError(f"missing Packizard codec source: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)

    pack_format = output / "external" / "ampr_emu" / "tools" / "ampr_pack_format.py"
    if not pack_format.is_file():
        raise RuntimeError(f"AMPR pack format module not found: {pack_format}")
    text = pack_format.read_text(encoding="utf-8")
    marker = "class Lz4Codec:\n"
    if marker not in text:
        if "PackizardLz4Codec as Lz4Codec" in text:
            return
        raise RuntimeError("unexpected Lz4Codec layout in ampr_pack_format.py")

    replacement = (
        "from core.packizard_lz4 import PackizardLz4Codec as Lz4Codec\n\n\n"
        "class _LegacyLz4Codec:\n"
    )
    text = text.replace(marker, replacement, 1)
    pack_format.write_text(text, encoding="utf-8", newline="\n")


def patch_product_ui(output: Path) -> list[Path]:
    changed: list[Path] = []
    candidates = [output / "main.py"]
    for folder in (output / "gui", output / "core"):
        if folder.is_dir():
            candidates.extend(folder.rglob("*.py"))

    for path in candidates:
        if path.is_file() and _replace_text(path, UI_REPLACEMENTS):
            changed.append(path)
    return changed


def _apply_single_executable_profile(output: Path) -> None:
    # The current milestone is the Windows distribution used for local PS5
    # workflows. Linux AppImage is already a single distributable file and
    # macOS requires an application bundle by platform convention.
    if sys.platform != "win32":
        return
    profile_path = Path(__file__).resolve().parent / "single_executable_profile.py"
    spec = importlib.util.spec_from_file_location("packizard_single_executable", profile_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load single-executable profile: {profile_path}")
    profile = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(profile)
    profile.apply(output)


def write_engine_identity(output: Path) -> None:
    path = output / "core" / "packizard_engine.py"
    path.write_text(
        '"""Packizard engine identity and compatibility constants."""\n'
        'ENGINE_NAME = "Packizard Engine"\n'
        'CODEC_NAME = "Packizard LZ4"\n'
        'PACK_FORMAT = "AMPRPAK4"\n'
        'PACK_FORMAT_COMPATIBILITY = 4\n'
        'ENGINE_GENERATION = 1\n',
        encoding="utf-8",
        newline="\n",
    )
    _apply_single_executable_profile(output)


def assert_product_references_are_clean(output: Path) -> None:
    offenders: list[str] = []
    candidates = [output / "main.py"]
    for folder in (output / "gui", output / "core"):
        if folder.is_dir():
            candidates.extend(folder.rglob("*.py"))
    for path in candidates:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "Lazy_AMPR" in text or "Lazy AMPR" in text:
            offenders.append(str(path.relative_to(output)))
    if offenders:
        raise RuntimeError(
            "legacy product references remain in runtime/UI source: " + ", ".join(offenders)
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="build-src")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    output = Path(args.root).resolve()
    if not output.is_dir():
        raise SystemExit(f"source tree does not exist: {output}")

    install_codec(repo_root, output)
    write_engine_identity(output)
    changed = patch_product_ui(output)
    assert_product_references_are_clean(output)
    print(f"Packizard-native engine profile applied; updated {len(changed)} runtime/UI file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
