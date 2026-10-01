# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ["worker_packizard_profile.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
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
    a.binaries,
    a.datas,
    [],
    name="Packizard-Profile-Worker",
    console=True,
    exclude_binaries=False,
)
