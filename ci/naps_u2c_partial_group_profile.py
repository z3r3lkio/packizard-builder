#!/usr/bin/env python3
"""Apply Packizard NAPS large-layout compatibility fixes.

First preserve the real per-256KiB Kraken/stored data-block map, then fix the
terminal partial 8-U-block group. Keeping these in one entry point ensures the
existing CI/package workflow applies both fixes to every reconstructed engine.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


TARGET = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PKG/ProsperoNapsLayoutBuilder.cs")


def _load_data_block_profile():
    profile_path = Path(__file__).resolve().parent / "naps_data_block_map_profile.py"
    spec = importlib.util.spec_from_file_location("packizard_naps_data_block_map_profile", profile_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load NAPS data-block map profile: {profile_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def apply(root: Path) -> None:
    root = Path(root)

    # Must run first: this is the structural fix for real-U-block delta overflows.
    # The partial-group patch below only handles unused slots in the terminal group.
    _load_data_block_profile().apply(root)

    path = root / TARGET
    if not path.is_file():
        raise RuntimeError(f"Missing reconstructed NAPS builder: {path}")

    text = path.read_text(encoding="utf-8")
    marker = "Packizard terminal partial-group u2c fix"
    if marker in text:
        return

    old = '''        int Delta(int ublock, int baseIndex)\n        {\n            if (ublock < numUBlocks) return first[ublock] - baseIndex;\n            return (numCblockInfo - 1) - baseIndex;             // beyond last ublock -> terminator\n        }\n'''
    new = '''        // Packizard terminal partial-group u2c fix:\n        // u2c entries are fixed groups of 8 U-blocks, but the last group may be partial.\n        // Slots beyond NumUBlocks are not addressable by the reader and must remain zero; mapping\n        // them to the terminator can manufacture a delta > 255 for a slot that does not exist.\n        int Delta(int ublock, int baseIndex)\n        {\n            if (ublock >= numUBlocks) return 0;\n            int value = first[ublock] - baseIndex;\n            if (value is < 0 or > 255)\n                throw new NotSupportedException(\n                    $"NAPS u2c delta {value} is not encodable for real U-block {ublock} " +\n                    $"(first={first[ublock]}, base={baseIndex}, numUBlocks={numUBlocks}, numCblockInfo={numCblockInfo}).");\n            return value;\n        }\n'''

    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one legacy u2c Delta() block in {path}, found {count}. "
            "Rebase this profile against the pinned LibProsperoPKG source."
        )

    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    print("Applied Packizard NAPS u2c terminal partial-group fix")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="build-src")
    args = parser.parse_args()
    apply(Path(args.root))


if __name__ == "__main__":
    main()
