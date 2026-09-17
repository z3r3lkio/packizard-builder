#!/usr/bin/env python3
"""Prepare the complete Packizard source tree used by CI."""
from __future__ import annotations

import argparse
import base64
import json
import lzma
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

UPSTREAM_URL = "https://github.com/Nazky/Lazy_AMPR.git"
UPSTREAM_REF = "033a85bf2cbc343ed8da81dcef55faac8ba7628a"


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def _decode_overlay_patch(overlay: Path) -> Path:
    plain = overlay / "ci" / "packizard_overlay.patch"
    if plain.is_file():
        return plain
    packed = overlay / "ci" / "packizard_overlay.patch.xz.b64"
    parts = sorted((overlay / "ci").glob("packizard_overlay.patch.xz.b64.part-*"))
    if parts:
        encoded = "".join(part.read_text(encoding="ascii").strip() for part in parts)
    elif packed.is_file():
        encoded = packed.read_text(encoding="ascii").strip()
    else:
        raise SystemExit("Missing Packizard overlay patch")
    decoded = lzma.decompress(base64.b64decode(encoded, validate=True))
    handle = tempfile.NamedTemporaryFile(prefix="packizard-overlay-", suffix=".patch", delete=False)
    handle.write(decoded)
    handle.close()
    return Path(handle.name)


def _decode_incremental_patch(overlay: Path) -> Path | None:
    plain = overlay / "ci" / "integrated_pkg.patch"
    if plain.is_file():
        return plain
    packed = overlay / "ci" / "integrated_pkg.patch.xz.b64"
    parts = sorted((overlay / "ci").glob("integrated_pkg.patch.xz.b64.part-*"))
    if parts:
        encoded = "".join(part.read_text(encoding="ascii").strip() for part in parts)
    elif packed.is_file():
        encoded = packed.read_text(encoding="ascii").strip()
    else:
        return None
    decoded = lzma.decompress(base64.b64decode(encoded, validate=True))
    handle = tempfile.NamedTemporaryFile(prefix="packizard-integrated-", suffix=".patch", delete=False)
    handle.write(decoded)
    handle.close()
    return Path(handle.name)


def _patch_macos_worker_specs(output: Path) -> None:
    """Normalize the macOS worker specs before applying the 0.2 overlay.

    This is intentionally host-independent. CI reconstructs the same source tree on
    Linux, Windows and macOS, so the textual base for the incremental patch must be
    identical on every runner.
    """
    for spec_name, executable_name in (("ampr_pack.spec", "ampr_pack"), ("ampr_pack_profile.spec", "ampr_pack_profile")):
        spec_path = output / spec_name
        text = spec_path.read_text(encoding="utf-8")
        old_exe = f'exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="{executable_name}", console=True)'
        new_exe = f'exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="{executable_name}", console=True)'
        old_collect = f'coll = COLLECT(exe, a.binaries, a.datas, name="{executable_name}")'
        if old_exe not in text or old_collect not in text:
            raise RuntimeError(f"Unexpected PyInstaller worker spec layout: {spec_path}")
        text = text.replace(old_exe, new_exe, 1).replace(old_collect + "\n", "", 1)
        spec_path.write_text(text, encoding="utf-8", newline="\n")


def _patch_packaging_scripts(output: Path) -> None:
    macos_script = output / "build_macos.sh"
    if macos_script.is_file():
        text = macos_script.read_text(encoding="utf-8").replace("chmod +x --", "chmod +x")
        old_worker_copy = "\n".join([
            'mkdir -p -- "$macos_dir/workers"',
            'cp -a -- "$dist/ampr_pack" "$macos_dir/workers/"',
            'cp -a -- "$dist/ampr_pack_profile" "$macos_dir/workers/"',
        ])
        new_worker_copy = "\n".join([
            'mkdir -p -- "$macos_dir/workers/ampr_pack" "$macos_dir/workers/ampr_pack_profile"',
            'cp -a -- "$dist/ampr_pack" "$macos_dir/workers/ampr_pack/ampr_pack"',
            'cp -a -- "$dist/ampr_pack_profile" "$macos_dir/workers/ampr_pack_profile/ampr_pack_profile"',
        ])
        if old_worker_copy not in text and new_worker_copy not in text:
            raise RuntimeError("Unexpected macOS worker copy block")
        text = text.replace(old_worker_copy, new_worker_copy, 1)
        lines = [line for line in text.splitlines() if "codesign --force" not in line and "codesign --verify" not in line and 'find "$app/Contents/MacOS/workers" -type d' not in line]
        xattr_idx = next(i for i, line in enumerate(lines) if 'xattr -cr "$app"' in line)
        indent = lines[xattr_idx][:-len(lines[xattr_idx].lstrip())]
        lines[xattr_idx + 1:xattr_idx + 1] = [
            indent + 'codesign --force --sign - "$macos_dir/workers/ampr_pack/ampr_pack"',
            indent + 'codesign --force --sign - "$macos_dir/workers/ampr_pack_profile/ampr_pack_profile"',
            indent + 'codesign --force --sign - "$app"',
            indent + 'codesign --verify --deep --strict "$app"',
        ]
        macos_script.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    linux_script = output / "build_linux.sh"
    if linux_script.is_file():
        lines = linux_script.read_text(encoding="utf-8").splitlines()
        cleanup = 'rm -rf -- "$appdir/usr/share/metainfo"'
        if not any(cleanup in line for line in lines):
            appimage_idx = next(i for i, line in enumerate(lines) if "appimage-extract-and-run" in line and "$appimagetool" in line)
            indent = lines[appimage_idx][:-len(lines[appimage_idx].lstrip())]
            lines.insert(appimage_idx, indent + cleanup)
        linux_script.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _apply_engine_pin(overlay: Path, output: Path) -> None:
    pin_path = overlay / "ci" / "libprospero_pin.json"
    if not pin_path.is_file():
        return
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    version = str(pin["version"]).strip().lstrip("v")
    ref = str(pin["ref"]).strip().lower()
    updater = output / "scripts" / "update_libprospero_pin.py"
    if not updater.is_file():
        raise RuntimeError(f"Missing engine pin updater: {updater}")
    run(sys.executable, str(updater), "--version", version, "--ref", ref, cwd=output)


def _write_branding(overlay: Path, output: Path) -> None:
    ci_dir = overlay / "ci"
    parts = sorted(ci_dir.glob("packizard_logo.b64.part-*"))
    if parts:
        encoded = "".join("".join(part.read_text(encoding="ascii").split()) for part in parts)
    else:
        logo = ci_dir / "packizard_logo.b64"
        if not logo.is_file():
            raise SystemExit("Missing Packizard branding artwork")
        encoded = "".join(logo.read_text(encoding="ascii").split())

    encoded += "=" * (-len(encoded) % 4)
    artwork = base64.b64decode(encoded, validate=False)
    signature = b"\x89PNG\r\n\x1a\n"
    if len(artwork) < 24 or not artwork.startswith(signature):
        raise RuntimeError("Packizard branding artwork is not a valid PNG payload")
    width, height = struct.unpack(">II", artwork[16:24])
    if width != height or width < 256:
        raise RuntimeError(f"Packizard branding must be square and at least 256x256; got {width}x{height}")
    if b"IEND" not in artwork[-64:]:
        raise RuntimeError("Packizard branding PNG is incomplete")

    destination = output / "resources" / "branding"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "packizard_icon.png").write_bytes(artwork)
    (destination / "packizard_sidebar.png").write_bytes(artwork)
    fallback_marker = destination / ".ci_branding_fallback"
    fallback_marker.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="build-src")
    parser.add_argument("--upstream", default=UPSTREAM_URL)
    parser.add_argument("--upstream-ref", default=UPSTREAM_REF)
    parser.add_argument("--upstream-dir")
    args = parser.parse_args()

    overlay = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve()
    if output == overlay.resolve():
        raise SystemExit("--output must differ from the source repository")
    if output.exists():
        shutil.rmtree(output)

    if args.upstream_dir:
        source = Path(args.upstream_dir).resolve()
        shutil.copytree(source, output, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    else:
        run("git", "clone", "--filter=blob:none", "--no-checkout", args.upstream, str(output))
        run("git", "checkout", "--detach", args.upstream_ref, cwd=output)

    patch = _decode_overlay_patch(overlay)
    try:
        run("git", "apply", "--binary", str(patch), cwd=output)
    finally:
        if patch.name.startswith("packizard-overlay-"):
            patch.unlink(missing_ok=True)

    # The 0.2 overlay was generated against the already-hardened 0.1.2 tree.
    _patch_macos_worker_specs(output)
    _patch_packaging_scripts(output)

    incremental = _decode_incremental_patch(overlay)
    if incremental is not None:
        try:
            run("git", "apply", "--binary", str(incremental), cwd=output)
        finally:
            if incremental.name.startswith("packizard-integrated-"):
                incremental.unlink(missing_ok=True)

    _apply_engine_pin(overlay, output)
    _write_branding(overlay, output)
    print(f"Prepared Packizard source at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
