#!/usr/bin/env python3
"""Reconstruct the complete Packizard source tree from the pinned Lazy_AMPR base.

The GitHub repository is intentionally lightweight: unchanged upstream files are
fetched from a pinned public commit and Packizard's reviewed overlay patch plus
branding assets are applied on top. Local source archives remain self-contained
and can be built directly without using this bootstrapper.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

UPSTREAM_URL = "https://github.com/Nazky/Lazy_AMPR.git"
UPSTREAM_REF = "033a85bf2cbc343ed8da81dcef55faac8ba7628a"


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="build-src")
    parser.add_argument("--upstream", default=UPSTREAM_URL)
    parser.add_argument("--upstream-ref", default=UPSTREAM_REF)
    parser.add_argument(
        "--upstream-dir",
        help="Use an already available upstream directory instead of cloning (for offline tests).",
    )
    args = parser.parse_args()

    overlay = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve()
    patch = overlay / "ci" / "packizard_overlay.patch"
    packed_patch = overlay / "ci" / "packizard_overlay.patch.xz.b64"
    packed_parts = sorted((overlay / "ci").glob("packizard_overlay.patch.xz.b64.part-*"))
    temporary_patch = None
    if not patch.is_file():
        if packed_parts:
            packed_text = "".join(part.read_text(encoding="ascii").strip() for part in packed_parts)
        elif packed_patch.is_file():
            packed_text = packed_patch.read_text(encoding="ascii").strip()
        else:
            raise SystemExit(f"Missing overlay patch: {patch} (or packed parts)")
        import base64
        import lzma
        import tempfile

        decoded = lzma.decompress(base64.b64decode(packed_text, validate=True))
        handle = tempfile.NamedTemporaryFile(prefix="packizard-overlay-", suffix=".patch", delete=False)
        handle.write(decoded)
        handle.close()
        patch = Path(handle.name)
        temporary_patch = patch

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

    try:
        run("git", "apply", "--binary", str(patch), cwd=output)
    finally:
        if temporary_patch is not None:
            temporary_patch.unlink(missing_ok=True)

    branding_destination = output / "resources" / "branding"
    branding_destination.mkdir(parents=True, exist_ok=True)
    ci_logo = overlay / "ci" / "packizard_logo.png"
    ci_logo_b64 = overlay / "ci" / "packizard_logo.b64"
    local_branding = overlay / "resources" / "branding"
    if ci_logo.is_file():
        shutil.copy2(ci_logo, branding_destination / "packizard_icon.png")
        shutil.copy2(ci_logo, branding_destination / "packizard_sidebar.png")
    elif ci_logo_b64.is_file():
        import base64

        artwork = base64.b64decode(ci_logo_b64.read_text(encoding="ascii").strip(), validate=True)
        (branding_destination / "packizard_icon.png").write_bytes(artwork)
        (branding_destination / "packizard_sidebar.png").write_bytes(artwork)
    elif (local_branding / "packizard_icon.png").is_file():
        for item in local_branding.iterdir():
            if item.is_file() and item.name != "packizard_icon.icns":
                shutil.copy2(item, branding_destination / item.name)
    else:
        raise SystemExit("Missing Packizard branding artwork")

    ppr_source = overlay / "tools" / "ppr_pkg_builder"
    if (ppr_source / "LibProsperoPkg.Gui.exe").is_file():
        ppr_destination = output / "tools" / "ppr_pkg_builder"
        ppr_destination.parent.mkdir(parents=True, exist_ok=True)
        if ppr_destination.exists():
            shutil.rmtree(ppr_destination)
        shutil.copytree(ppr_source, ppr_destination)

    print(f"Prepared Packizard source at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
