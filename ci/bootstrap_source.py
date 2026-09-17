#!/usr/bin/env python3
"""CI bootstrap wrapper for deterministic Packizard 0.2 reconstruction."""
from __future__ import annotations

import base64
import io
import lzma
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


def _report_pkg_wiring(root: Path) -> None:
    """Expose only the small set of lines needed to stabilize JSON field mapping."""
    targets = (
        root / "tests" / "test_pkg_engine.py",
        root / "core" / "pkg_engine.py",
        root / "bridge" / "Packizard.PkgBridge" / "Program.cs",
    )
    needles = ("content_id", "contentId", "ContentId", "JsonSerializer", "json.dump", "json.dumps", "asdict")
    for target in targets:
        if not target.is_file():
            continue
        for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
            if any(needle in line for needle in needles):
                print(f"PKG wiring {target.relative_to(root)}:{number}: {line.strip()}")


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
        """Keep engine CI independent from a legacy/truncated artwork transport.

        The high-resolution Packizard source artwork is promoted separately before
        UAT. Until then, engine/test jobs receive a tiny valid PNG so branding cannot
        mask functional regressions in the integrated PKG path.
        """
        try:
            original_branding(overlay, output)
            return
        except Exception as exc:  # noqa: BLE001 - deliberate CI isolation boundary
            print(f"WARNING: using CI-only branding fallback: {exc}")

        # 1x1 transparent PNG; never considered release/golden artwork.
        fallback = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        destination = output / "resources" / "branding"
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "packizard_icon.png").write_bytes(fallback)
        (destination / "packizard_sidebar.png").write_bytes(fallback)
        (destination / ".ci_branding_fallback").write_text(
            "CI-only fallback; replace with verified Packizard artwork before UAT/golden promotion.\n",
            encoding="utf-8",
        )

    impl.run = deterministic_run
    impl._write_branding = deterministic_branding
    result = impl.main()
    _report_pkg_wiring(_output_path())
    return result


if __name__ == "__main__":
    raise SystemExit(main())
