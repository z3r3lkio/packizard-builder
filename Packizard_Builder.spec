# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

is_windows = sys.platform == "win32"
is_macos = sys.platform == "darwin"
project = Path(SPECPATH)
arch = os.environ.get("PACKIZARD_TARGET_ARCH") or ("arm64" if os.environ.get("PROCESSOR_ARCHITECTURE") == "ARM64" else "x64")


def add_tree(root: Path, destination: str):
    entries = []
    if not root.is_dir():
        return entries
    for path in root.rglob("*"):
        if path.is_file():
            rel_parent = path.parent.relative_to(root)
            entries.append((str(path), str(Path(destination) / rel_parent)))
    return entries


runtime_source = project / "packizard_runtime" / "ps5" / "packizard_ps5_runtime"
runtime_license = runtime_source / "LICENSE"
runtime_binary = project / "resources" / "fakelib" / "libSceAmpr.sprx"
if not runtime_binary.is_file():
    raise RuntimeError(f"Bundled Packizard PS5 Runtime is missing: {runtime_binary}")
if not runtime_license.is_file():
    raise RuntimeError(f"Packizard PS5 Runtime license is missing: {runtime_license}")

datas = [
    (str(runtime_binary), "resources/fakelib"),
    ("resources/fakelib/PACKIZARD_RUNTIME_SOURCE.txt", "resources/fakelib"),
    ("toml_profiles", "toml_profiles"),
    ("THIRD_PARTY_NOTICES.md", "."),
    (str(runtime_license), "licenses/packizard-runtime-compat"),
]
branding = project / "resources" / "branding"
if branding.exists():
    datas.append((str(branding), "resources/branding"))

if is_windows:
    dist = Path(DISTPATH)
    workers = {
        "Packizard-Packer-Worker": dist / "Packizard-Packer-Worker.exe",
        "Packizard-Profile-Worker": dist / "Packizard-Profile-Worker.exe",
    }
    for name, worker in workers.items():
        if not worker.is_file():
            raise RuntimeError(f"{name} must be built before Packizard Builder: {worker}")
        datas.append((str(worker), f"workers/{name}"))
    bridge = project / "pkg_bridge" / f"win-{arch}"
    if not bridge.is_dir():
        raise RuntimeError(f"PKG bridge must be prepared before Packizard Builder: {bridge}")
    datas.extend(add_tree(bridge, "pkg_bridge"))
    lpp_license = project / "vendor" / "LibProsperoPKG" / "LICENSE"
    if lpp_license.is_file():
        datas.append((str(lpp_license), "licenses/LibProsperoPKG"))

a = Analysis(
    ["main.py"],
    pathex=[str(project)],
    binaries=[],
    datas=datas,
    hiddenimports=["FATtools.Volume"],
    hookspath=["pyinstaller_hooks"],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if is_windows:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="Packizard-Builder",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        uac_admin=True,
        disable_windowed_traceback=False,
        version="version_info.txt",
        icon="resources/branding/packizard_icon.ico",
        exclude_binaries=False,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="Packizard_Builder",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=not is_macos,
        console=False,
        disable_windowed_traceback=False,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=not is_macos,
        upx_exclude=[],
        name="Packizard_Builder",
    )
    if is_macos:
        app = BUNDLE(
            coll,
            name="Packizard Builder.app",
            bundle_identifier="io.github.z3r3lkio.packizard-builder",
            info_plist={
                "CFBundleName": "Packizard Builder",
                "CFBundleDisplayName": "Packizard Builder",
                "CFBundleShortVersionString": "0.2.0",
                "NSHighResolutionCapable": True,
            },
        )
