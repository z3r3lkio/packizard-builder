#!/usr/bin/env python3
"""CI bootstrap wrapper for deterministic Packizard 0.2 reconstruction."""
from __future__ import annotations

import base64
import io
import lzma
import tarfile
from pathlib import Path

# Valid 1x1 transparent PNG used only to unblock engine/tests when the historical
# Base64 artwork transport is corrupt. A Golden build is not considered promotable
# until the real high-resolution Packizard artwork replaces this fallback path.
_FALLBACK_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg=="


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


def main() -> int:
    ci_dir = Path(__file__).resolve().parent
    # Force the verified split payload. The monolithic compatibility copy is
    # retained in the branch for auditability but is not consumed by bootstrap.
    packed = ci_dir / "integrated_pkg.patch.xz.b64"
    if packed.is_file():
        packed.unlink()

    import bootstrap_source_impl as impl

    original_run = impl.run
    original_branding = impl._write_branding
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

    def deterministic_branding(overlay: Path, output: Path) -> None:
        """Keep CI moving while branding transport is repaired independently."""
        icon = output / "resources" / "branding" / "packizard_icon.png"
        sidebar = output / "resources" / "branding" / "packizard_sidebar.png"
        if icon.is_file() and sidebar.is_file():
            print("Using canonical Packizard branding assets for CI reconstruction")
            return
        try:
            original_branding(overlay, output)
            return
        except Exception as exc:
            destination = output / "resources" / "branding"
            destination.mkdir(parents=True, exist_ok=True)
            fallback = base64.b64decode(_FALLBACK_PNG_B64, validate=True)
            icon.write_bytes(fallback)
            sidebar.write_bytes(fallback)
            marker = output / ".packizard-ci-branding-fallback"
            marker.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
            print(f"WARNING: using CI-only branding fallback: {exc}")

    impl.run = deterministic_run
    impl._write_branding = deterministic_branding
    return impl.main()


if __name__ == "__main__":
    raise SystemExit(main())
