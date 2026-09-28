#!/usr/bin/env python3
"""Compatibility entry point for Packizard's native NAPS engine.

The workflow historically invoked this filename for a sequence of LibProsperoPKG patches. Keep the
entry point stable while delegating to the Packizard-owned canonical DATA/NAPS implementation.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import packizard_native_naps_profile as native


ASSEMBLER = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PFS/ProsperoPs5InnerImageAssembler.cs")


def _install_resilient_replacements() -> None:
    original = native._replace_once

    def replace_once(text: str, old: str, new: str, label: str) -> str:
        if text.count(old) == 1:
            return text.replace(old, new, 1)
        if label == "native BuildImage call":
            # The call is normalized after native.apply(); tolerate upstream argument drift here.
            return text
        return original(text, old, new, label)

    native._replace_once = replace_once


def _normalize_native_build_call(root: Path) -> None:
    """Replace the complete assembly call so upstream BuildImage parameters cannot leak into native code."""
    path = root / ASSEMBLER
    text = path.read_text(encoding="utf-8")
    anchor = "        byte[] image = BuildImage("
    start = text.find(anchor)
    if start < 0:
        native_anchor = "        byte[] image = BuildNativeImage("
        if native_anchor in text:
            return
        raise RuntimeError("Could not locate inner-image assembly call")
    end = text.find(");", start)
    if end < 0:
        raise RuntimeError("Could not locate end of inner-image assembly call")
    end += 2
    replacement = '''        byte[] image = BuildNativeImage(\n            afidOrder, dataStream, metaPlain,\n            out long blockInfoOnDisk, out long metadataOnDisk,\n            out byte[] compressedMeta, out var metaBlocks,\n            out string? imageFilePath, out long imageLength, temps);'''
    text = text[:start] + replacement + text[end:]
    path.write_text(text, encoding="utf-8", newline="\n")


def _ensure_native_image_writer(root: Path) -> None:
    """Inject a Packizard-only physical writer under a name that cannot collide with upstream."""
    path = root / ASSEMBLER
    text = path.read_text(encoding="utf-8")
    signature = (
        "private byte[] BuildNativeImage(List<FileNode> afidOrder, "
        "PackizardNativeDataStreamResult dataStream, byte[] metaPlain"
    )
    if signature in text:
        return

    # Prefer inserting before the legacy writer. If native.apply() replaced that method, insert before
    # the build/SDK-version summary that follows the writer in every pinned source variant.
    candidates = [
        "    private byte[] BuildImage(List<FileNode> afidOrder, byte[] metaPlain,",
        "    private byte[] BuildImage(List<FileNode> afidOrder, PackizardNativeDataStreamResult dataStream, byte[] metaPlain,",
        "    /// <summary>\n    /// PFSv3 build/SDK version stamped into every block-75 entry",
    ]
    positions = [text.find(marker) for marker in candidates]
    positions = [pos for pos in positions if pos >= 0]
    if not positions:
        raise RuntimeError("Could not find a class-level insertion point for BuildNativeImage")
    pos = min(positions)

    method = '''    // Packizard-native physical writer. Logical mount geometry is computed separately from\n    // dataStream.LogicalLength; this method deals only with encoded on-disk placement.\n    private byte[] BuildNativeImage(List<FileNode> afidOrder, PackizardNativeDataStreamResult dataStream, byte[] metaPlain,\n        out long blockInfoOnDisk, out long metadataOnDisk, out byte[] compressedMeta,\n        out IReadOnlyList<ProsperoInnerMetaBlockChunk> metaBlocks,\n        out string? imageFilePath, out long imageLength, ProsperoBuildTempFiles temps)\n    {\n        const int BLK = ProsperoPs5InnerImageBuilder.BlockSize;\n        static long AlignUp(long v, long a) => (v + a - 1) & ~(a - 1);\n\n        var payloads = new List<ProsperoPs5InnerPayload>();\n        if (dataStream.EncodedLength > 0)\n        {\n            payloads.Add(new ProsperoPs5InnerPayload\n            {\n                DataPath = dataStream.EncodedPath,\n                StoreRaw = true,\n                BlockAligned = false,\n            });\n        }\n\n        long urootSize = 0;\n        foreach (var f in afidOrder)\n            if (!f.SceSys) urootSize = checked(urootSize + f.DataLength);\n\n        byte[] blockInfo = BuildBlockInfoTable(urootSize);\n        blockInfoOnDisk = AlignUp(dataStream.EncodedLength, BLK);\n        payloads.Add(new ProsperoPs5InnerPayload\n        {\n            Data = blockInfo,\n            StoreRaw = true,\n            BlockAligned = true,\n        });\n\n        compressedMeta = ProsperoPs5InnerImageBuilder.CompressPayload(\n            metaPlain, storeRaw: false, out var metaPf);\n        metaBlocks = metaPf is null\n            ? Array.Empty<ProsperoInnerMetaBlockChunk>()\n            : metaPf.Blocks.Select(b => new ProsperoInnerMetaBlockChunk(\n                b.CompressedSize, b.UncompressedSize, b.IsMultiChunk,\n                b.FirstChunkCompressedSize)).ToArray();\n\n        metadataOnDisk = AlignUp(blockInfoOnDisk + blockInfo.LongLength, BLK);\n        payloads.Add(new ProsperoPs5InnerPayload\n        {\n            Data = compressedMeta,\n            StoreRaw = true,\n            BlockAligned = true,\n        });\n\n        imageLength = checked(metadataOnDisk + compressedMeta.LongLength);\n        string builtPath = temps.Create();\n        long written = new ProsperoPs5InnerImageBuilder().BuildToFile(payloads, builtPath);\n        if (written != imageLength)\n            throw new InvalidOperationException(\n                $"Packizard native inner-image length mismatch: planned {imageLength:N0}, wrote {written:N0}.");\n\n        bool canReturnMemory = imageLength < 64L * 1024 * 1024\n            && afidOrder.All(f => f.DataPath is null);\n        if (canReturnMemory)\n        {\n            imageFilePath = null;\n            return File.ReadAllBytes(builtPath);\n        }\n\n        imageFilePath = builtPath;\n        return Array.Empty<byte>();\n    }\n\n'''
    text = text[:pos] + method + text[pos:]
    path.write_text(text, encoding="utf-8", newline="\n")


def _fix_logical_mount_geometry(root: Path) -> None:
    """Metadata placement is a logical-mount decision, never a compressed-physical-size decision."""
    path = root / ASSEMBLER
    text = path.read_text(encoding="utf-8")
    wrong = "long dataBlocks = RoundUp(dataStream.EncodedLength, BlockSize) / BlockSize;"
    right = "long dataBlocks = RoundUp(dataStream.LogicalLength, BlockSize) / BlockSize;"
    if wrong in text:
        text = text.replace(wrong, right, 1)
        path.write_text(text, encoding="utf-8", newline="\n")
    elif right not in text:
        raise RuntimeError("Could not locate Packizard logical dataBlocks geometry assignment")


def _validate_native_route(root: Path) -> None:
    path = root / ASSEMBLER
    text = path.read_text(encoding="utf-8")
    if text.count("byte[] image = BuildNativeImage(") != 1:
        raise RuntimeError("Packizard native image call was not normalized exactly once")
    if text.count("private byte[] BuildNativeImage(") != 1:
        raise RuntimeError("Packizard native image writer was not installed exactly once")
    if "RoundUp(dataStream.LogicalLength, BlockSize)" not in text:
        raise RuntimeError("Packizard mount geometry is not based on logical DATA length")
    print("Validated Packizard native route: canonical DATA -> BuildNativeImage -> native NAPS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="build-src")
    args = parser.parse_args()
    root = Path(args.root)
    _install_resilient_replacements()
    native.apply(root)
    _normalize_native_build_call(root)
    _ensure_native_image_writer(root)
    _fix_logical_mount_geometry(root)
    _validate_native_route(root)


if __name__ == "__main__":
    main()
