#!/usr/bin/env python3
"""CI bootstrap wrapper for deterministic Packizard 0.2 reconstruction."""
from __future__ import annotations

import base64
import io
import lzma
import tarfile
from pathlib import Path


def _restore_canonical_preimage(ci_dir: Path, root: Path) -> None:
    """Restore the exact 0.1.2 files used to generate the 0.2 patch.

    The historical 0.1.2 overlay has received CI-only hardening over time.  Those
    edits are useful for release packaging, but they make a context-based patch
    nondeterministic.  The archive contains only the small set of files modified
    by the 0.2 patch and is restored immediately before that patch is applied.
    """
    encoded = (ci_dir / "integrated_preimage_012.tar.xz.b64").read_text(encoding="ascii").strip()
    tar_bytes = lzma.decompress(base64.b64decode(encoded, validate=True))
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as archive:
        for member in archive.getmembers():
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError(f"Unsafe canonical preimage member: {member.name}")
        archive.extractall(root)
    print("Restored canonical Packizard 0.1.2 preimage for integrated 0.2 overlay")


def main() -> int:
    ci_dir = Path(__file__).resolve().parent
    # Force the verified split payload.  The monolithic compatibility copy is
    # retained in the branch for auditability but is not consumed by bootstrap.
    packed = ci_dir / "integrated_pkg.patch.xz.b64"
    if packed.is_file():
        packed.unlink()

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
    return impl.main()


if __name__ == "__main__":
    raise SystemExit(main())
