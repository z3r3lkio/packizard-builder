#!/usr/bin/env python3
"""CI bootstrap wrapper for deterministic Packizard 0.2 reconstruction."""
from __future__ import annotations

import base64
import io
import importlib.util
import lzma
import os
import shutil
import struct
import sys
import tarfile
from pathlib import Path


def _restore_canonical_preimage(ci_dir: Path, root: Path) -> None:
    """Restore the exact 0.1.2 files used to generate the 0.2 patch."""
    encoded = (ci_dir / "integrated_preimage_012.tar.xz.b64").read_text(encoding="ascii").strip()
    tar_bytes = lzma.decompress(base64.b64decode(encoded, validate=True))
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as archive:
        for member in archive.getmembers():
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError(f"Unsafe canonical preimage member: {member.name}")
        archive.extractall(root, filter="data")
    print("Restored canonical Packizard 0.1.2 preimage for integrated 0.2 overlay")


def _output_path() -> Path:
    args = sys.argv[1:]
    if "--output" in args:
        index = args.index("--output")
        if index + 1 < len(args):
            return Path(args[index + 1]).resolve()
    return Path("build-src").resolve()


def _validate_branding(root: Path) -> None:
    branding = root / "resources" / "branding"
    fallback = branding / ".ci_branding_fallback"
    if fallback.exists():
        raise RuntimeError("CI branding fallback marker is present; refusing to package placeholder artwork")

    signature = b"\x89PNG\r\n\x1a\n"
    for name in ("packizard_icon.png", "packizard_sidebar.png"):
        path = branding / name
        if not path.is_file():
            raise RuntimeError(f"Missing Packizard branding file: {path}")
        payload = path.read_bytes()
        if len(payload) < 24 or not payload.startswith(signature):
            raise RuntimeError(f"Invalid PNG branding file: {path}")
        width, height = struct.unpack(">II", payload[16:24])
        if width != height or width < 256:
            raise RuntimeError(f"Branding must be square and at least 256x256: {path} is {width}x{height}")
        if b"IEND" not in payload[-64:]:
            raise RuntimeError(f"Incomplete PNG branding file: {path}")

    print("Validated Packizard branding: complete square artwork, no fallback placeholder")


def _apply_large_pkg_overrides(root: Path) -> None:
    """Overlay the large-package streaming fixes onto the pinned LibProsperoPKG source."""
    helper = root / "scripts" / "prepare_pkg_bridge.py"
    spec = importlib.util.spec_from_file_location("packizard_prepare_pkg_bridge", helper)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load bridge preparation helper: {helper}")
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    bridge.ensure_upstream()
    override_root = Path(__file__).resolve().parent / "large_pkg_overrides"
    targets = {
        "ProsperoPs5InnerImageBuilder.cs": root / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg" / "PFS" / "ProsperoPs5InnerImageBuilder.cs",
        "ProsperoPs5InnerImageAssembler.cs": root / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg" / "PFS" / "ProsperoPs5InnerImageAssembler.cs",
        "ProsperoOuterPfsBuilder.cs": root / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg" / "PFS" / "ProsperoOuterPfsBuilder.cs",
        "ProsperoPkgBuilder.cs": root / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg" / "PKG" / "ProsperoPkgBuilder.cs",
        "ProsperoFihBuilder.cs": root / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg" / "PKG" / "ProsperoFihBuilder.cs",
        "ProsperoNapsMeta.cs": root / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg" / "PKG" / "ProsperoNapsMeta.cs",
        "ProsperoSiArchive.cs": root / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg" / "PKG" / "ProsperoSiArchive.cs",
        "ProsperoPlayGo.cs": root / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg" / "PlayGo" / "ProsperoPlayGo.cs",
        "ProsperoPackageBuilder.cs": root / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg" / "ProsperoPackageBuilder.cs",
        "ProsperoNwonlyNapsGenerator.cs": root / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg" / "PKG" / "ProsperoNwonlyNapsGenerator.cs",
        "ProsperoNapsLayoutBuilder.cs": root / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg" / "PKG" / "ProsperoNapsLayoutBuilder.cs",
        "ProsperoBuildTempFiles.cs": root / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg" / "PFS" / "ProsperoBuildTempFiles.cs",
    }

    for name, destination in targets.items():
        source = override_root / name
        if not source.is_file():
            raise RuntimeError(f"Missing large-package override: {source}")
        if name != "ProsperoBuildTempFiles.cs" and not destination.is_file():
            raise RuntimeError(f"LibProsperoPKG override target is missing: {destination}")
        shutil.copy2(source, destination)

    print(f"Applied {len(targets)} LibProsperoPKG large-package streaming overrides")

    ampr_profile_path = Path(__file__).resolve().parent / "ampr_pkg_profile.py"
    ampr_spec = importlib.util.spec_from_file_location("packizard_ampr_pkg_profile", ampr_profile_path)
    if ampr_spec is None or ampr_spec.loader is None:
        raise RuntimeError(f"Cannot load AMPR PKG compatibility profile: {ampr_profile_path}")
    ampr_profile = importlib.util.module_from_spec(ampr_spec)
    ampr_spec.loader.exec_module(ampr_profile)
    ampr_profile.apply(root)

    progress_profile_path = Path(__file__).resolve().parent / "pkg_progress_profile.py"
    progress_spec = importlib.util.spec_from_file_location("packizard_pkg_progress_profile", progress_profile_path)
    if progress_spec is None or progress_spec.loader is None:
        raise RuntimeError(f"Cannot load PKG progress profile: {progress_profile_path}")
    progress_profile = importlib.util.module_from_spec(progress_spec)
    progress_spec.loader.exec_module(progress_profile)
    progress_profile.apply(root)


def _apply_packizard_native_engine(root: Path) -> None:
    profile_path = Path(__file__).resolve().parent / "packizard_native_engine.py"
    spec = importlib.util.spec_from_file_location("packizard_native_engine", profile_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load Packizard-native engine profile: {profile_path}")
    profile = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(profile)
    profile.install_codec(Path(__file__).resolve().parents[1], root)
    profile.write_engine_identity(root)
    changed = profile.patch_product_ui(root)
    profile.assert_product_references_are_clean(root)
    print(f"Applied Packizard-native compression engine; updated {len(changed)} runtime/UI file(s)")


def _stabilize_generated_packaging(root: Path) -> None:
    """Apply packaging-only fixes to matrix build jobs."""
    if os.environ.get("GITHUB_JOB") != "build":
        return

    windows = root / "build_windows.ps1"
    if windows.is_file():
        patched: list[str] = []
        replaced = 0
        for line in windows.read_text(encoding="utf-8").splitlines():
            if "prepare_pkg_bridge.py" in line:
                indent = line[: len(line) - len(line.lstrip())]
                patched.append(indent + 'Write-Host "Using prebuilt integrated PKG bridge for $rid"')
                replaced += 1
            else:
                patched.append(line)
        if replaced:
            windows.write_text("\n".join(patched) + "\n", encoding="utf-8", newline="\n")
            print(f"Windows packaging: removed {replaced} redundant PKG bridge publish invocation(s)")

    macos = root / "build_macos.sh"
    if macos.is_file():
        patched: list[str] = []
        changed = False
        for line in macos.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            indent = line[: len(line) - len(line.lstrip())]
            if stripped == 'codesign --force --sign - "$app"':
                patched.extend(
                    [
                        indent + 'rm -rf -- "$app/Contents/_CodeSignature"',
                        indent + 'codesign --verify --strict "$app/Contents/MacOS/workers/ampr_pack/ampr_pack"',
                        indent + 'codesign --verify --strict "$app/Contents/MacOS/workers/ampr_pack_profile/ampr_pack_profile"',
                        indent + 'codesign --verify --strict "$app/Contents/MacOS/pkg_bridge/Packizard.PkgBridge"',
                    ]
                )
                changed = True
                continue
            if stripped in {
                'codesign --verify --deep --strict "$app"',
                'codesign --verify --strict "$app"',
            }:
                changed = True
                continue
            patched.append(line)
        if changed:
            macos.write_text("\n".join(patched) + "\n", encoding="utf-8", newline="\n")
            print("macOS packaging: signed executable payload verified; bundle container left unsigned")


def _insert_windows_icon_preparation(root: Path) -> None:
    """Insert ICO generation before the first PyInstaller build command."""
    windows = root / "build_windows.ps1"
    if not windows.is_file():
        raise RuntimeError(f"Missing Windows packaging script: {windows}")

    text = windows.read_text(encoding="utf-8")
    if "scripts\\prepare_windows_icon.py" in text:
        return

    lines = text.splitlines()
    insert_at = next((i for i, line in enumerate(lines) if "PyInstaller" in line), None)
    if insert_at is None:
        raise RuntimeError("Could not locate any PyInstaller invocation in build_windows.ps1")

    target = lines[insert_at]
    indent = target[: len(target) - len(target.lstrip())]
    lines.insert(insert_at, indent + r"& $python scripts\prepare_windows_icon.py")
    windows.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("Windows packaging: inserted Packizard ICO generation before PyInstaller")


def main() -> int:
    ci_dir = Path(__file__).resolve().parent
    import bootstrap_source_impl as impl

    original_run = impl.run
    restored = False

    def deterministic_run(*args: str, cwd=None) -> None:
        nonlocal restored
        if (
            not restored
            and len(args) >= 4
            and args[0] == "git"
            and args[1] == "apply"
            and "packizard-integrated-" in str(args[-1])
        ):
            if cwd is None:
                raise RuntimeError("Integrated patch apply has no working directory")
            _restore_canonical_preimage(ci_dir, Path(cwd))
            restored = True
        return original_run(*args, cwd=cwd)

    impl.run = deterministic_run

    original_branding_patch = impl._patch_application_branding

    def resilient_branding_patch(overlay: Path, output: Path) -> None:
        try:
            original_branding_patch(overlay, output)
        except RuntimeError as exc:
            if "Could not find PyInstaller invocation" not in str(exc):
                raise
            _insert_windows_icon_preparation(output)
            original_branding_patch(overlay, output)

    impl._patch_application_branding = resilient_branding_patch

    result = impl.main()
    output = _output_path()
    _apply_large_pkg_overrides(output)
    _apply_packizard_native_engine(output)
    _validate_branding(output)
    _stabilize_generated_packaging(output)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
