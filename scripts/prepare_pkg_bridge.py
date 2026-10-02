#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_URL = "https://github.com/SvenGDK/LibProsperoPKG.git"
REF_FILE = ROOT / "bridge" / "LIBPROSPERO_REF"
VERSION_FILE = ROOT / "bridge" / "LIBPROSPERO_VERSION"
VENDOR_DIR = ROOT / "vendor" / "LibProsperoPKG"
PROJECT = ROOT / "bridge" / "Packizard.PkgBridge" / "Packizard.PkgBridge.csproj"

from libprospero_cnt_drm_profile import apply_cnt_drm_profile
from libprospero_fih_extract_fix import apply_fih_extract_fix
from libprospero_fih_profile import apply_fih_reference_profile
from libprospero_naps_block_profile import apply_naps_block_profile
from libprospero_warning_cleanup import apply_warning_cleanup


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def ensure_upstream() -> str:
    ref = REF_FILE.read_text(encoding="utf-8").strip()
    if not ref:
        raise SystemExit("bridge/LIBPROSPERO_REF is empty")
    if not (VENDOR_DIR / "src" / "LibProsperoPkg" / "LibProsperoPkg.csproj").is_file():
        git = shutil.which("git")
        if not git:
            raise SystemExit("git is required to fetch the pinned LibProsperoPKG source")
        VENDOR_DIR.parent.mkdir(parents=True, exist_ok=True)
        if VENDOR_DIR.exists():
            shutil.rmtree(VENDOR_DIR)
        run(git, "clone", "--filter=blob:none", "--no-checkout", UPSTREAM_URL, str(VENDOR_DIR))
        run(git, "checkout", "--detach", ref, cwd=VENDOR_DIR)
    else:
        git_dir = VENDOR_DIR / ".git"
        git = shutil.which("git")
        if git and git_dir.exists():
            head = subprocess.check_output([git, "rev-parse", "HEAD"], cwd=VENDOR_DIR, text=True).strip()
            if head != ref:
                run(git, "fetch", "origin", ref, cwd=VENDOR_DIR)
                run(git, "checkout", "--detach", ref, cwd=VENDOR_DIR)
    return ref


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Packizard's integrated LibProsperoPKG bridge")
    parser.add_argument("--rid", required=True, help=".NET runtime id, e.g. win-x64 or linux-arm64")
    parser.add_argument("--output", default="", help="Optional publish directory")
    parser.add_argument("--no-fetch", action="store_true", help="Require an existing pinned vendor checkout")
    args = parser.parse_args()

    dotnet = shutil.which("dotnet")
    if not dotnet:
        raise SystemExit(".NET 10 SDK is required to build the integrated PKG engine")

    ref = REF_FILE.read_text(encoding="utf-8").strip()
    if args.no_fetch:
        if not (VENDOR_DIR / "src" / "LibProsperoPkg" / "LibProsperoPkg.csproj").is_file():
            raise SystemExit(f"Pinned LibProsperoPKG source is missing: {VENDOR_DIR}")
    else:
        ref = ensure_upstream()

    try:
        profile_changed = apply_fih_reference_profile(VENDOR_DIR)
        profile_changed |= apply_fih_extract_fix(VENDOR_DIR)
        profile_changed |= apply_naps_block_profile(VENDOR_DIR)
        profile_changed |= apply_cnt_drm_profile(VENDOR_DIR)
        profile_changed |= apply_warning_cleanup(VENDOR_DIR)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    output = Path(args.output).resolve() if args.output else ROOT / "pkg_bridge" / args.rid
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    run(
        dotnet,
        "publish",
        str(PROJECT),
        "-c",
        "Release",
        "-r",
        args.rid,
        "--self-contained",
        "true",
        "-p:PublishSingleFile=true",
        "-p:PublishTrimmed=false",
        # Keep the integrated bridge warning-free. New C# warnings must be fixed,
        # not silently accumulated in release builds.
        "-p:TreatWarningsAsErrors=true",
        "-o",
        str(output),
    )

    executable = output / ("Packizard.PkgBridge.exe" if args.rid.startswith("win-") else "Packizard.PkgBridge")
    if not executable.is_file():
        raise SystemExit(f"dotnet publish did not produce {executable}")
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    profile_state = "applied" if profile_changed else "already applied"
    print(
        f"Built Packizard.PkgBridge for {args.rid} with LibProsperoPKG {version} ({ref}); "
        f"Packizard reference profiles {profile_state}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
