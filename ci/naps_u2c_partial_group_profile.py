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
            needle = "BuildImage(afidOrder, metaPlain"
            replacement = "BuildImage(afidOrder, dataStream, metaPlain"
            if text.count(needle) == 1:
                return text.replace(needle, replacement, 1)
        return original(text, old, new, label)

    native._replace_once = replace_once


def _ensure_native_build_image_overload(root: Path) -> None:
    """Keep the legacy builder intact and inject the Packizard physical writer as a new overload."""
    path = root / ASSEMBLER
    text = path.read_text(encoding="utf-8")
    native_signature = (
        "private byte[] BuildImage(List<FileNode> afidOrder, "
        "PackizardNativeDataStreamResult dataStream, byte[] metaPlain"
    )
    if native_signature in text:
        return

    legacy_marker = "    private byte[] BuildImage(List<FileNode> afidOrder, byte[] metaPlain,"
    pos = text.find(legacy_marker)
    if pos < 0:
        raise RuntimeError("Could not locate legacy BuildImage method for native-overload insertion")

    method = '''    // Packizard native physical writer. Logical mount geometry is computed separately from\n    // dataStream.LogicalLength; this method deals only with encoded on-disk placement.\n    private byte[] BuildImage(List<FileNode> afidOrder, PackizardNativeDataStreamResult dataStream, byte[] metaPlain,\n        out long blockInfoOnDisk, out long metadataOnDisk, out byte[] compressedMeta,\n        out IReadOnlyList<ProsperoInnerMetaBlockChunk> metaBlocks,\n        out string? imageFilePath, out long imageLength, ProsperoBuildTempFiles temps)\n    {\n        const int BLK = ProsperoPs5InnerImageBuilder.BlockSize;\n        static long AlignUp(long v, long a) => (v + a - 1) & ~(a - 1);\n\n        var payloads = new List<ProsperoPs5InnerPayload>();\n        if (dataStream.EncodedLength > 0)\n        {\n            payloads.Add(new ProsperoPs5InnerPayload\n            {\n                DataPath = dataStream.EncodedPath,\n                StoreRaw = true,\n                BlockAligned = false,\n            });\n        }\n\n        long urootSize = 0;\n        foreach (var f in afidOrder)\n            if (!f.SceSys) urootSize = checked(urootSize + f.DataLength);\n\n        byte[] blockInfo = BuildBlockInfoTable(urootSize);\n        blockInfoOnDisk = AlignUp(dataStream.EncodedLength, BLK);\n        payloads.Add(new ProsperoPs5InnerPayload\n        {\n            Data = blockInfo,\n            StoreRaw = true,\n            BlockAligned = true,\n        });\n\n        compressedMeta = ProsperoPs5InnerImageBuilder.CompressPayload(\n            metaPlain, storeRaw: false, out var metaPf);\n        metaBlocks = metaPf is null\n            ? Array.Empty<ProsperoInnerMetaBlockChunk>()\n            : metaPf.Blocks.Select(b => new ProsperoInnerMetaBlockChunk(\n                b.CompressedSize, b.UncompressedSize, b.IsMultiChunk,\n                b.FirstChunkCompressedSize)).ToArray();\n\n        metadataOnDisk = AlignUp(blockInfoOnDisk + blockInfo.LongLength, BLK);\n        payloads.Add(new ProsperoPs5InnerPayload\n        {\n            Data = compressedMeta,\n            StoreRaw = true,\n            BlockAligned = true,\n        });\n\n        imageLength = checked(metadataOnDisk + compressedMeta.LongLength);\n        string builtPath = temps.Create();\n        long written = new ProsperoPs5InnerImageBuilder().BuildToFile(payloads, builtPath);\n        if (written != imageLength)\n            throw new InvalidOperationException(\n                $"Packizard native inner-image length mismatch: planned {imageLength:N0}, wrote {written:N0}.");\n\n        bool canReturnMemory = imageLength < 64L * 1024 * 1024\n            && afidOrder.All(f => f.DataPath is null);\n        if (canReturnMemory)\n        {\n            imageFilePath = null;\n            return File.ReadAllBytes(builtPath);\n        }\n\n        imageFilePath = builtPath;\n        return Array.Empty<byte>();\n    }\n\n'''
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="build-src")
    args = parser.parse_args()
    root = Path(args.root)
    _install_resilient_replacements()
    native.apply(root)
    _ensure_native_build_image_overload(root)
    _fix_logical_mount_geometry(root)


if __name__ == "__main__":
    main()
