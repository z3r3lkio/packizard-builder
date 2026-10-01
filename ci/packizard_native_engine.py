#!/usr/bin/env python3
"""Apply the Packizard-owned engine to the transitional reconstructed tree."""
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


def install_engine(repo_root: Path, output: Path) -> None:
    """Install Packizard's codec, compatibility container and packer CLI."""
    tools = output / "external" / "ampr_emu" / "tools"
    if not tools.is_dir():
        raise RuntimeError(f"legacy tools directory not found during migration: {tools}")
    mapping = {
        repo_root / "native" / "packizard_lz4.py": tools / "packizard_lz4.py",
        repo_root / "native" / "packizard_container.py": tools / "packizard_container.py",
        repo_root / "native" / "packizard_packer.py": tools / "packizard_packer.py",
    }
    for source, destination in mapping.items():
        if not source.is_file():
            raise RuntimeError(f"missing Packizard engine source: {source}")
        shutil.copy2(source, destination)

    (tools / "ampr_pack.py").write_text(
        "from packizard_packer import *  # noqa: F401,F403\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n",
        encoding="utf-8",
        newline="\n",
    )

    legacy_format = tools / "ampr_pack_format.py"
    legacy_format.unlink(missing_ok=True)
    candidates = []
    for folder in (output / "external" / "ampr_emu" / "tools", output / "tests"):
        if folder.is_dir():
            candidates.extend(folder.rglob("*.py"))
    for path in candidates:
        text = path.read_text(encoding="utf-8", errors="replace")
        changed = text.replace("from ampr_pack_format import", "from packizard_container import")
        changed = changed.replace(
            "from external.ampr_emu.tools.ampr_pack_format import",
            "from external.ampr_emu.tools.packizard_container import",
        )
        if path.name == "ampr_pack_profile.py":
            changed = changed.replace(
                "from packizard_container import Lz4Codec, parse_size",
                "from packizard_lz4 import PackizardLz4Codec as Lz4Codec\nfrom packizard_container import parse_size",
            )
        if changed != text:
            path.write_text(changed, encoding="utf-8", newline="\n")


def install_codec(repo_root: Path, output: Path) -> None:
    """Compatibility alias retained for older migration tests/callers."""
    install_engine(repo_root, output)


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
        'CONTAINER_NAME = "Packizard Container"\n'
        'PACKER_NAME = "Packizard Packer"\n'
        'PACK_FORMAT = "AMPRPAK4"\n'
        'PACK_FORMAT_COMPATIBILITY = 4\n'
        'ENGINE_GENERATION = 2\n',
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
        raise RuntimeError("legacy product references remain in runtime/UI source: " + ", ".join(offenders))


def assert_packizard_packer_is_native(output: Path) -> None:
    tools = output / "external" / "ampr_emu" / "tools"
    if (tools / "ampr_pack_format.py").exists():
        raise RuntimeError("inherited ampr_pack_format.py is still present")
    wrapper = (tools / "ampr_pack.py").read_text(encoding="utf-8")
    if "packizard_packer" not in wrapper or len(wrapper.splitlines()) > 4:
        raise RuntimeError("historical pack command is not a thin Packizard wrapper")
    for name in ("packizard_lz4.py", "packizard_container.py", "packizard_packer.py"):
        if not (tools / name).is_file():
            raise RuntimeError(f"Packizard engine component missing: {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="build-src")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output = Path(args.root).resolve()
    if not output.is_dir():
        raise SystemExit(f"source tree does not exist: {output}")
    install_engine(repo_root, output)
    write_engine_identity(output)
    changed = patch_product_ui(output)
    assert_product_references_are_clean(output)
    assert_packizard_packer_is_native(output)
    print(f"Packizard-native engine generation 2 applied; updated {len(changed)} runtime/UI file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
