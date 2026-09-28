#!/usr/bin/env python3
"""Compatibility entry point for Packizard's native NAPS engine.

The workflow historically invoked this filename for a sequence of LibProsperoPKG patches. Keep the
entry point stable while delegating to the Packizard-owned canonical DATA/NAPS implementation.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from packizard_native_naps_profile import apply


def _fix_logical_mount_geometry(root: Path) -> None:
    """Metadata placement is a logical-mount decision, never a compressed-physical-size decision."""
    path = root / "vendor/LibProsperoPKG/src/LibProsperoPkg/PFS/ProsperoPs5InnerImageAssembler.cs"
    text = path.read_text(encoding="utf-8")
    wrong = "long dataBlocks = RoundUp(dataStream.EncodedLength, BlockSize) / BlockSize;"
    right = "long dataBlocks = RoundUp(dataStream.LogicalLength, BlockSize) / BlockSize;"
    if wrong in text:
        text = text.replace(wrong, right, 1)
        path.write_text(text, encoding="utf-8", newline="\n")
    elif right not in text:
        raise RuntimeError("Could not locate Packizard logical dataBlocks geometry assignment")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="build-src")
    args = parser.parse_args()
    root = Path(args.root)
    apply(root)
    _fix_logical_mount_geometry(root)


if __name__ == "__main__":
    main()
