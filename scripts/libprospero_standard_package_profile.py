from __future__ import annotations

from pathlib import Path

PKG_BUILDER = Path("src/LibProsperoPkg/PKG/ProsperoPkgBuilder.cs")
HIGH_LEVEL_BUILDER = Path("src/LibProsperoPkg/ProsperoPackageBuilder.cs")

# Parity architecture: data-first inner image + naps_pkg_layout.dat
# -> SHA3 signed / AES-XTS encrypted outer PFS -> imagedigs.dat -> CNT/FIH/SI.
# The patcher intentionally uses small semantic tokens because the earlier
# exact-block strategy was brittle when other Packizard profiles reflowed code.


def _load(path: Path, label: str) -> str:
    if not path.is_file():
        raise RuntimeError(f"LibProsperoPKG {label} is missing: {path}")
    return path.read_text(encoding="utf-8")


def _write_if_changed(path: Path, before: str, after: str) -> bool:
    if before == after:
        return False
    path.write_text(after, encoding="utf-8")
    return True


def _insert_after_once(text: str, anchor: str, addition: str, present: str, label: str) -> str:
    if present in text:
        return text
    if anchor not in text:
        raise RuntimeError(f"Pinned LibProsperoPKG {label} anchor not found.")
    return text.replace(anchor, anchor + addition, 1)


def _replace_token_once(text: str, old: str, new: str, present: str, label: str) -> str:
    if present in text:
        return text
    if old not in text:
        raise RuntimeError(f"Pinned LibProsperoPKG {label} token not found.")
    return text.replace(old, new, 1)


def apply_standard_package_profile(vendor_dir: str | Path) -> bool:
    """Apply high-level MkPFS/PS5PkgTool parity controls.

    The PS5 inner assembler is no longer patched here. Packizard owns a deterministic
    override copied by prepare_pkg_bridge.py before the remaining profiles run.
    """
    vendor = Path(vendor_dir)
    low = vendor / PKG_BUILDER
    high = vendor / HIGH_LEVEL_BUILDER
    return changed
