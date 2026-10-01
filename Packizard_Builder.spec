# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

is_windows = sys.platform == "win32"
is_macos = sys.platform == "darwin"
project = Path(SPECPATH)

optional_datas = []
branding = project / "resources" / "branding"
if branding.exists():
    optional_datas.append((str(branding), "resources/branding"))

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("resources/fakelib/libSceAmpr.sprx", "resources/fakelib"),
        ("toml_profiles", "toml_profiles"),
        ("THIRD_PARTY_NOTICES.md", "."),
        ("external/ampr_emu/LICENSE", "licenses/ampr_emu"),
        ("external/ampr_emu/third_party/lz4/LICENSE", "licenses/lz4"),
    ] + optional_datas,
    hiddenimports=["FATtools.Volume"],
    hookspath=["pyinstaller_hooks"],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
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
    uac_admin=is_windows,
    disable_windowed_traceback=False,
    version="version_info.txt" if is_windows else None,
    icon="resources/branding/packizard_icon.ico" if sys.platform == "win32" else None,
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
