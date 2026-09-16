#!/usr/bin/env python3
"""Prepare the complete Packizard source tree used by CI.

The public GitHub repository keeps a compact reviewed overlay over a pinned
Lazy_AMPR base. Release/source archives are already self-contained, while CI
reconstructs the reviewed source from the pinned upstream plus Packizard's
versioned overlays.
"""
from __future__ import annotations

import argparse
import base64
import lzma
import shutil
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


def _patch_macos_worker_specs(output: Path) -> None:
    """Convert macOS helper workers to one-file executables."""
    if sys.platform != "darwin":
        return

    for spec_name, executable_name in (
        ("ampr_pack.spec", "ampr_pack"),
        ("ampr_pack_profile.spec", "ampr_pack_profile"),
    ):
        spec_path = output / spec_name
        if not spec_path.is_file():
            raise RuntimeError(f"Missing macOS worker spec: {spec_path}")
        text = spec_path.read_text(encoding="utf-8")
        old_exe = (
            f'exe = EXE(pyz, a.scripts, [], exclude_binaries=True, '
            f'name="{executable_name}", console=True)'
        )
        new_exe = (
            f'exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], '
            f'name="{executable_name}", console=True)'
        )
        old_collect = f'coll = COLLECT(exe, a.binaries, a.datas, name="{executable_name}")'
        if old_exe not in text or old_collect not in text:
            raise RuntimeError(f"Unexpected PyInstaller worker spec layout: {spec_path}")
        text = text.replace(old_exe, new_exe, 1)
        text = text.replace(old_collect + "\n", "", 1)
        spec_path.write_text(text, encoding="utf-8", newline="\n")


def _patch_packaging_scripts(output: Path) -> None:
    """Apply the packaging hardening already validated in UAT 0.1.2."""
    macos_script = output / "build_macos.sh"
    if macos_script.is_file():
        text = macos_script.read_text(encoding="utf-8")
        text = text.replace("chmod +x --", "chmod +x")
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
        lines = [
            line for line in text.splitlines()
            if "codesign --force" not in line
            and "codesign --verify" not in line
            and 'find "$app/Contents/MacOS/workers" -type d' not in line
        ]
        try:
            xattr_idx = next(i for i, line in enumerate(lines) if 'xattr -cr "$app"' in line)
        except StopIteration as exc:
            raise RuntimeError("macOS xattr/signing marker not found") from exc
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
            try:
                appimage_idx = next(
                    i for i, line in enumerate(lines)
                    if "appimage-extract-and-run" in line and "$appimagetool" in line
                )
            except StopIteration as exc:
                raise RuntimeError("appimagetool invocation not found") from exc
            indent = lines[appimage_idx][:-len(lines[appimage_idx].lstrip())]
            lines.insert(appimage_idx, indent + cleanup)
        linux_script.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _decode_incremental_patch(overlay: Path) -> Path | None:
    """Decode the optional Packizard 0.2+ incremental overlay."""
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


def _write_branding(overlay: Path, output: Path) -> None:
    destination = output / "resources" / "branding"
    destination.mkdir(parents=True, exist_ok=True)
    logo = overlay / "ci" / "packizard_logo.b64"
    if not logo.is_file():
        raise SystemExit("Missing Packizard branding artwork")
    artwork = base64.b64decode(logo.read_text(encoding="ascii").strip(), validate=True)
    (destination / "packizard_icon.png").write_bytes(artwork)
    (destination / "packizard_sidebar.png").write_bytes(artwork)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="build-src")
    parser.add_argument("--upstream", default=UPSTREAM_URL)
    parser.add_argument("--upstream-ref", default=UPSTREAM_REF)
    parser.add_argument("--upstream-dir", help="Use an already available Lazy_AMPR directory instead of cloning.")
    args = parser.parse_args()

    overlay = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve()
    if output == overlay.resolve():
        raise SystemExit("--output must differ from the source repository")
    if output.exists():
        shutil.rmtree(output)

    if args.upstream_dir:
        source = Path(args.upstream_dir).resolve()
        if not source.is_dir():
            raise SystemExit(f"Upstream directory does not exist: {source}")
        shutil.copytree(source, output, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    else:
        run("git", "clone", "--filter=blob:none", "--no-checkout", args.upstream, str(output))
        run("git", "checkout", "--detach", args.upstream_ref, cwd=output)

    patch = _decode_overlay_patch(overlay)
    temporary = patch.name.startswith("packizard-overlay-")
    try:
        run("git", "apply", "--binary", str(patch), cwd=output)
    finally:
        if temporary:
            patch.unlink(missing_ok=True)

    # The 0.2 overlay is generated against the already hardened 0.1.2 tree.
    _patch_macos_worker_specs(output)
    _patch_packaging_scripts(output)

    incremental = _decode_incremental_patch(overlay)
    if incremental is not None:
        temporary_incremental = incremental.name.startswith("packizard-integrated-")
        try:
            run("git", "apply", "--binary", str(incremental), cwd=output)
        finally:
            if temporary_incremental:
                incremental.unlink(missing_ok=True)

    _write_branding(overlay, output)
    print(f"Prepared Packizard source at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
