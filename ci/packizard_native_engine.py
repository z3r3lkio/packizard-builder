#!/usr/bin/env python3
"""Apply the Packizard-owned desktop engine to the reconstructed tree."""
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


def _patch_desktop_engine_paths(output: Path) -> None:
    candidates: list[Path] = []
    for folder in (output / "core", output / "utils", output / "tests"):
        if folder.is_dir():
            candidates.extend(folder.rglob("*.py"))
    replacements = (
        ('TOOLS_DIR = Path(__file__).resolve().parent.parent / "external" / "ampr_emu" / "tools"',
         'TOOLS_DIR = Path(__file__).resolve().parent.parent / "packizard_engine"'),
        ('TOOLS_DIR / "ampr_pack.py"', 'TOOLS_DIR / "packer.py"'),
        ("TOOLS_DIR / 'ampr_pack.py'", "TOOLS_DIR / 'packer.py'"),
        ('TOOLS_DIR / "ampr_pack_profile.py"', 'TOOLS_DIR / "profile.py"'),
        ('following the official ampr_pack_profile.py tutorial', 'using Packizard Engine traces'),
        ('ampr_pack_profile.py not found', 'Packizard profile engine not found'),
        ('Running ampr_pack_profile.py with', 'Running Packizard profile engine with'),
        ('from packizard_container import', 'from packizard_engine.container import'),
        ('from packizard_lz4 import', 'from packizard_engine.lz4 import'),
        ("{'packizard_packer': command}", "{'packizard_engine.packer': command}"),
        ('app / "ampr_pack.py"', 'app / "packer.py"'),
        ('Path("tools") / "ampr_pack.py"', 'Path("packizard_engine") / "packer.py"'),
    )
    for path in candidates:
        text = path.read_text(encoding="utf-8", errors="replace")
        changed = text
        for old, new in replacements:
            changed = changed.replace(old, new)
        if changed != text:
            path.write_text(changed, encoding="utf-8", newline="\n")


def install_engine(repo_root: Path, output: Path) -> None:
    """Install Packizard codec/container/packer/profiler as a first-party package."""
    engine = output / "packizard_engine"
    engine.mkdir(parents=True, exist_ok=True)
    mapping = {
        repo_root / "native" / "packizard_lz4.py": engine / "lz4.py",
        repo_root / "native" / "packizard_container.py": engine / "container.py",
        repo_root / "native" / "packizard_packer.py": engine / "packer.py",
        repo_root / "native" / "packizard_profile.py": engine / "profile.py",
    }
    for source, destination in mapping.items():
        if not source.is_file():
            raise RuntimeError(f"missing Packizard engine source: {source}")
        shutil.copy2(source, destination)

    (engine / "__init__.py").write_text(
        '"""Packizard-owned compression and asset-pack engine."""\n'
        'import sys as _sys\n'
        'from . import container as _container\n'
        'from . import lz4 as _lz4\n'
        '_sys.modules.setdefault("packizard_container", _container)\n'
        '_sys.modules.setdefault("packizard_lz4", _lz4)\n'
        'from .lz4 import PackizardLz4Codec\n'
        '__all__ = ["PackizardLz4Codec"]\n',
        encoding="utf-8", newline="\n",
    )
    _patch_desktop_engine_paths(output)

    # Transitional compatibility mirror for verification and old developer
    # commands. Runtime/UI/build code is forbidden from resolving through it.
    tools = output / "external" / "ampr_emu" / "tools"
    if tools.is_dir():
        shutil.copy2(repo_root / "native" / "packizard_lz4.py", tools / "packizard_lz4.py")
        shutil.copy2(repo_root / "native" / "packizard_container.py", tools / "packizard_container.py")
        shutil.copy2(repo_root / "native" / "packizard_packer.py", tools / "packizard_packer.py")
        (tools / "ampr_pack.py").write_text(
            "from packizard_packer import *  # noqa: F401,F403\n"
            "if __name__ == '__main__':\n    raise SystemExit(main())\n",
            encoding="utf-8", newline="\n",
        )
        (tools / "ampr_pack_format.py").unlink(missing_ok=True)


def install_codec(repo_root: Path, output: Path) -> None:
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


def _apply_internal_worker_profile(output: Path) -> None:
    profile_path = Path(__file__).resolve().parent / "internal_worker_profile.py"
    spec = importlib.util.spec_from_file_location("packizard_internal_workers", profile_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load Packizard worker profile: {profile_path}")
    profile = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(profile)
    profile.apply(output)


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
        'PROFILER_NAME = "Packizard Profiler"\n'
        'PACK_FORMAT = "AMPRPAK4"\n'
        'PACK_FORMAT_COMPATIBILITY = 4\n'
        'ENGINE_GENERATION = 4\n',
        encoding="utf-8", newline="\n",
    )
    _apply_internal_worker_profile(output)
    _apply_single_executable_profile(output)


def assert_product_references_are_clean(output: Path) -> None:
    offenders: list[str] = []
    candidates = [output / "main.py"]
    for folder in (output / "gui", output / "core"):
        if folder.is_dir():
            candidates.extend(folder.rglob("*.py"))
    for path in candidates:
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            if "Lazy_AMPR" in text or "Lazy AMPR" in text:
                offenders.append(str(path.relative_to(output)))
    if offenders:
        raise RuntimeError("legacy product references remain in runtime/UI source: " + ", ".join(offenders))


def assert_desktop_engine_is_native(output: Path) -> None:
    engine = output / "packizard_engine"
    for name in ("__init__.py", "lz4.py", "container.py", "packer.py", "profile.py"):
        if not (engine / name).is_file():
            raise RuntimeError(f"Packizard engine component missing: {name}")
    offenders: list[str] = []
    for folder in (output / "core", output / "gui", output / "utils"):
        if not folder.is_dir():
            continue
        for path in folder.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if "external/ampr_emu" in text or 'external" / "ampr_emu' in text:
                offenders.append(str(path.relative_to(output)))
    if offenders:
        raise RuntimeError("desktop engine still depends on external/ampr_emu: " + ", ".join(offenders))


def assert_packizard_packer_is_native(output: Path) -> None:
    assert_desktop_engine_is_native(output)


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
    assert_desktop_engine_is_native(output)
    print(f"Packizard-native engine generation 4 applied; updated {len(changed)} runtime/UI file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
