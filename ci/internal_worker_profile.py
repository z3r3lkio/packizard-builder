#!/usr/bin/env python3
"""Give bundled helper entry points first-party Packizard identities."""
from __future__ import annotations

import argparse
from pathlib import Path

PACK_ENTRY = '''"""Frozen Packizard packer entry point."""\nimport sys\nfrom packizard_engine.packer import main\nif __name__ == "__main__":\n    for stream in (sys.stdout, sys.stderr):\n        if stream is not None:\n            stream.reconfigure(encoding="utf-8")\n    raise SystemExit(main())\n'''
PROFILE_ENTRY = '''"""Frozen Packizard trace-profile entry point."""\nimport multiprocessing\nfrom packizard_engine.profile import main\nif __name__ == "__main__":\n    multiprocessing.freeze_support()\n    raise SystemExit(main())\n'''

SPEC_TEMPLATE = '''# -*- mode: python ; coding: utf-8 -*-\na = Analysis(\n    ["{entry}"],\n    pathex=["."],\n    binaries=[],\n    datas=[],\n    hiddenimports=[],\n    hookspath=[],\n    hooksconfig={{}},\n    runtime_hooks=[],\n    excludes=[],\n    noarchive=False,\n    optimize=0,\n)\npyz = PYZ(a.pure)\nexe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="{name}", console=True)\ncoll = COLLECT(exe, a.binaries, a.datas, name="{name}")\n'''

REPLACEMENTS = (
    ("ampr_pack_profile.spec", "Packizard_Profile_Worker.spec"),
    ("ampr_pack.spec", "Packizard_Packer_Worker.spec"),
    ("ampr_pack_profile", "Packizard-Profile-Worker"),
    ("ampr_pack", "Packizard-Packer-Worker"),
)


def _patch_build_scripts(root: Path) -> int:
    changed = 0
    for path in (root / "build_windows.ps1", root / "build_linux.sh", root / "build_macos.sh"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        new = text
        for old, replacement in REPLACEMENTS:
            new = new.replace(old, replacement)
        if new != text:
            path.write_text(new, encoding="utf-8", newline="\n")
            changed += 1
    return changed


def _write_tool_runner(root: Path) -> None:
    path = root / "utils" / "tool_runner.py"
    path.write_text('''"""Resolve Packizard engine helpers in source and frozen builds."""\n\nimport sys\nfrom pathlib import Path\n\n_WORKERS = {\n    "packer": "Packizard-Packer-Worker",\n    "profile": "Packizard-Profile-Worker",\n}\n\ndef command_for(script: Path) -> list[str]:\n    script = Path(script)\n    worker_name = _WORKERS.get(script.stem)\n    if getattr(sys, "frozen", False):\n        if worker_name is None:\n            raise FileNotFoundError(f"Unknown Packizard helper: {script.stem}")\n        suffix = ".exe" if sys.platform == "win32" else ""\n        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))\n        worker = root / "workers" / worker_name / f"{worker_name}{suffix}"\n        if not worker.is_file():\n            raise FileNotFoundError(f"Bundled Packizard helper not found: {worker}")\n        return [str(worker)]\n    if worker_name is not None:\n        return [sys.executable, "-m", f"packizard_engine.{script.stem}"]\n    return [sys.executable, str(script)]\n''', encoding="utf-8", newline="\n")


def _patch_cross_platform_test(root: Path) -> None:
    path = root / "tests" / "test_cross_platform.py"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    text = text.replace('app / "ampr_pack.py"', 'app / "packer.py"')
    text = text.replace('Path("tools") / "ampr_pack.py"', 'Path("packizard_engine") / "packer.py"')
    text = text.replace('"workers" / "ampr_pack" / "ampr_pack"', '"workers" / "Packizard-Packer-Worker" / "Packizard-Packer-Worker"')
    text = text.replace('"workers" / "ampr_pack" / "ampr_pack.exe"', '"workers" / "Packizard-Packer-Worker" / "Packizard-Packer-Worker.exe"')
    text = text.replace(
        'tool_runner.command_for(script), [sys.executable, str(script)]',
        'tool_runner.command_for(script), [sys.executable, "-m", "packizard_engine.packer"]',
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def _patch_build_diagnostics_test(root: Path) -> None:
    path = root / "tests" / "test_build_diagnostics.py"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    text = text.replace("worker_ampr_pack.py", "worker_packizard_packer.py")
    text = text.replace("worker_ampr_pack_profile.py", "worker_packizard_profile.py")
    text = text.replace("{'ampr_pack': command}", "{'packizard_engine.packer': command}")
    text = text.replace("{'packizard_packer': command}", "{'packizard_engine.packer': command}")
    path.write_text(text, encoding="utf-8", newline="\n")


def apply(root: Path) -> None:
    root = Path(root)
    (root / "worker_packizard_packer.py").write_text(PACK_ENTRY, encoding="utf-8", newline="\n")
    (root / "worker_packizard_profile.py").write_text(PROFILE_ENTRY, encoding="utf-8", newline="\n")
    (root / "Packizard_Packer_Worker.spec").write_text(
        SPEC_TEMPLATE.format(entry="worker_packizard_packer.py", name="Packizard-Packer-Worker"),
        encoding="utf-8", newline="\n")
    (root / "Packizard_Profile_Worker.spec").write_text(
        SPEC_TEMPLATE.format(entry="worker_packizard_profile.py", name="Packizard-Profile-Worker"),
        encoding="utf-8", newline="\n")
    for legacy in ("ampr_pack.spec", "ampr_pack_profile.spec", "worker_ampr_pack.py", "worker_ampr_pack_profile.py"):
        (root / legacy).unlink(missing_ok=True)
    _write_tool_runner(root)
    _patch_cross_platform_test(root)
    _patch_build_diagnostics_test(root)
    changed = _patch_build_scripts(root)
    print(f"Configured Packizard worker identities; patched {changed} packaging script(s)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="build-src")
    args = parser.parse_args()
    apply(Path(args.root).resolve())
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
