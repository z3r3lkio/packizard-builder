#!/usr/bin/env python3
"""Apply Packizard NAPS large-layout compatibility fixes.

First preserve the real per-256KiB Kraken/stored data-block map, then normalize
zero-length files and fix the terminal partial 8-U-block group. Keeping these in
one entry point ensures the existing CI/package workflow applies every NAPS fix
to each reconstructed engine.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


TARGET = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PKG/ProsperoNapsLayoutBuilder.cs")
ASSEMBLER = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PFS/ProsperoPs5InnerImageAssembler.cs")


def _load_data_block_profile():
    profile_path = Path(__file__).resolve().parent / "naps_data_block_map_profile.py"
    spec = importlib.util.spec_from_file_location("packizard_naps_data_block_map_profile", profile_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load NAPS data-block map profile: {profile_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize_readonly_placement(root: Path) -> None:
    """Avoid a C# struct field-initializer requirement while keeping assembler-owned maps non-null."""
    path = root / ASSEMBLER
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    old = '''    public IReadOnlyList<ProsperoInnerDataBlockChunk> CompressedBlocks { get; init; }\n        = Array.Empty<ProsperoInnerDataBlockChunk>();\n'''
    new = '''    public IReadOnlyList<ProsperoInnerDataBlockChunk> CompressedBlocks { get; init; }\n'''
    if old in text:
        path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    elif new not in text:
        raise RuntimeError(f"Could not locate per-block placement property in {path}")


def _normalize_zero_length_files(root: Path) -> None:
    """A zero-byte file occupies no logical U-block and therefore has no data CblockInfo entry."""
    assembler_path = root / ASSEMBLER
    layout_path = root / TARGET

    assembler = assembler_path.read_text(encoding="utf-8")
    old_capture = '''                if (!f.StoreRaw && compressedFile is not null)\n                {\n'''
    new_capture = '''                // A zero-byte file has no logical U-block. ProsperoCompressedPfsImage can\n                // still expose an implementation-level empty PFSC block in the in-memory path; do\n                // not propagate that artifact into NAPS, so memory and streaming geometry agree.\n                if (!f.StoreRaw && f.DataLength > 0 && compressedFile is not null)\n                {\n'''
    if old_capture in assembler:
        assembler = assembler.replace(old_capture, new_capture, 1)
        assembler_path.write_text(assembler, encoding="utf-8", newline="\n")
    elif new_capture not in assembler:
        raise RuntimeError(f"Could not locate in-memory block-map capture in {assembler_path}")

    layout = layout_path.read_text(encoding="utf-8")
    old_guard = '''                if (f.Blocks.Count == 0)\n                    throw new InvalidOperationException(\n                        $"Compressed NAPS placement at logical 0x{f.LogicalOffset:X} has no encoder block map.");\n\n                long blockOnDisk = f.OnDiskOffset;\n'''
    new_guard = '''                // Empty files contribute fidx/inode metadata but consume no logical U-block and\n                // therefore no DATA-region CblockInfo record.\n                if (f.UncompressedSize == 0)\n                    continue;\n                if (f.Blocks.Count == 0)\n                    throw new InvalidOperationException(\n                        $"Compressed NAPS placement at logical 0x{f.LogicalOffset:X} has no encoder block map.");\n\n                long blockOnDisk = f.OnDiskOffset;\n'''
    if old_guard in layout:
        layout_path.write_text(layout.replace(old_guard, new_guard, 1), encoding="utf-8", newline="\n")
    elif new_guard not in layout:
        raise RuntimeError(f"Could not locate compressed NAPS block-map guard in {layout_path}")


def apply(root: Path) -> None:
    root = Path(root)

    # Must run first: this is the structural fix for real-U-block delta overflows.
    # The partial-group patch below only handles unused slots in the terminal group.
    _load_data_block_profile().apply(root)
    _normalize_readonly_placement(root)
    _normalize_zero_length_files(root)

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
