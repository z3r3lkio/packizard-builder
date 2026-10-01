#!/usr/bin/env python3
"""Convert the reconstructed Windows distribution to one Packizard executable.

The worker programs and integrated PKG bridge are embedded in the PyInstaller
one-file payload. PyInstaller extracts them to its private runtime directory;
they are no longer shipped as user-visible sidecars.
"""
from __future__ import annotations

import argparse
from pathlib import Path


SPEC_TEXT = r'''# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

project = Path(SPECPATH)
arch = os.environ.get("PACKIZARD_TARGET_ARCH", "x64")
rid = f"win-{arch}"
dist = Path(DISTPATH)


def add_tree(root: Path, prefix: str):
    items = []
    if not root.is_dir():
        return items
    for path in root.rglob("*"):
        if path.is_file():
            relative_parent = path.parent.relative_to(root)
            destination = str(Path(prefix) / relative_parent)
            items.append((str(path), destination))
    return items


datas = []
for folder, prefix in (
    (project / "resources", "resources"),
    (project / "toml_profiles", "toml_profiles"),
    (project / "licenses", "licenses"),
    (project / "pkg_bridge" / rid, f"pkg_bridge/{rid}"),
):
    datas.extend(add_tree(folder, prefix))

worker_pack = dist / "ampr_pack.exe"
worker_profile = dist / "ampr_pack_profile.exe"
if not worker_pack.is_file() or not worker_profile.is_file():
    raise RuntimeError("Packizard worker executables must be built before the main one-file executable")
datas.extend([
    (str(worker_pack), "workers/ampr_pack"),
    (str(worker_profile), "workers/ampr_pack_profile"),
])

a = Analysis(
    ["main.py"],
    pathex=[str(project)],
    binaries=[],
    datas=datas,
    hiddenimports=["FATtools.Volume"],
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
)
'''


WINDOWS_BUILD_TEXT = r'''param(
    [string]$OutputDirectory = "",
    [ValidateSet("x64", "arm64")]
    [string]$Arch = "x64"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$parentDir = Split-Path -Parent $projectDir
$python = Join-Path $projectDir ".venv312\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python build environment not found at $python"
}

$version = (& $python -c "from version import VERSION; print(VERSION)").Trim()
if ($version -notmatch '^\d+\.\d+\.\d+(-rc\d+)?$') {
    throw "Invalid application version: $version"
}

$releaseBase = [System.IO.Path]::GetFullPath((Join-Path $parentDir "release"))
$releaseRoot = if ($OutputDirectory) {
    [System.IO.Path]::GetFullPath((Join-Path $projectDir $OutputDirectory))
} else {
    [System.IO.Path]::GetFullPath((Join-Path $releaseBase "$version-windows-$Arch"))
}
$work = Join-Path $releaseRoot "work"
$dist = Join-Path $releaseRoot "dist"
$archive = Join-Path $releaseRoot "Packizard-Builder-$version-Windows-$Arch.zip"
$checksum = Join-Path $releaseRoot "SHA256SUMS-Windows-$Arch.txt"
$env:PACKIZARD_TARGET_ARCH = $Arch

$oldPath = $env:Path
$pushed = $false
try {
    $env:Path = "$(Split-Path -Parent $python);$env:SystemRoot\System32;$env:SystemRoot"
    if (Test-Path -LiteralPath $releaseRoot) {
        Remove-Item -LiteralPath $releaseRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $work, $dist | Out-Null
    Push-Location $projectDir
    $pushed = $true

    & $python scripts\prepare_windows_icon.py

    # Internal helpers are built first, then embedded into the final one-file EXE.
    & $python -m PyInstaller --noconfirm --clean --workpath $work --distpath $dist ampr_pack.spec
    & $python -m PyInstaller --noconfirm --clean --workpath $work --distpath $dist ampr_pack_profile.spec
    & $python -m PyInstaller --noconfirm --clean --workpath $work --distpath $dist Packizard_Builder_OneFile.spec

    $exe = Join-Path $dist "Packizard-Builder.exe"
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
        throw "Single-file Packizard executable was not produced: $exe"
    }

    Compress-Archive -LiteralPath $exe -DestinationPath $archive -Force
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash
    Set-Content -LiteralPath $checksum -Value "$hash *$(Split-Path -Leaf $archive)" -Encoding ascii
    Write-Host "Built single-executable Packizard package: $archive"
    Write-Host "SHA-256 $hash"
}
finally {
    if ($pushed) { Pop-Location }
    $env:Path = $oldPath
}
'''


def _make_worker_onefile(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    # Worker specs in the inherited baseline are one-dir. Keep their entry
    # points but make each helper a temporary one-file payload that can itself
    # be embedded in the main Packizard executable.
    text = text.replace(
        'EXE(pyz, a.scripts, [], exclude_binaries=True,',
        'EXE(pyz, a.scripts, a.binaries, a.datas, [], exclude_binaries=False,',
    )
    if "coll = COLLECT(" in text:
        text = text[: text.index("coll = COLLECT(")].rstrip() + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def _patch_frozen_runtime_roots(root: Path) -> int:
    changed = 0
    old = 'Path(sys.executable).resolve().parent'
    new = 'Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))'
    for folder in (root / "core", root / "utils", root / "gui"):
        if not folder.is_dir():
            continue
        for path in folder.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if old not in text:
                continue
            path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
            changed += 1
    return changed


def apply(root: Path) -> None:
    root = Path(root)
    for worker in (root / "ampr_pack.spec", root / "ampr_pack_profile.spec"):
        if not worker.is_file():
            raise RuntimeError(f"missing worker spec: {worker}")
        _make_worker_onefile(worker)

    (root / "Packizard_Builder_OneFile.spec").write_text(
        SPEC_TEXT, encoding="utf-8", newline="\n"
    )
    (root / "build_windows.ps1").write_text(
        WINDOWS_BUILD_TEXT, encoding="utf-8", newline="\n"
    )
    changed = _patch_frozen_runtime_roots(root)
    print(f"Configured Windows single-executable packaging; patched {changed} frozen runtime root(s)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="build-src")
    args = parser.parse_args()
    apply(Path(args.root).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
