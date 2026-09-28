#!/usr/bin/env python3
"""Install Packizard-owned canonical DATA/NAPS engines into the reconstructed build tree.

This profile intentionally bypasses LibProsperoPKG's NAPS topology generator.  The reusable binary
record serializer remains in place, but Packizard owns DATA U-block formation, CblockInfo topology,
u2c budgeting, and generation.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ASSEMBLER = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PFS/ProsperoPs5InnerImageAssembler.cs")
PKG_BUILDER = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PKG/ProsperoPkgBuilder.cs")
NAPS_META = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PKG/ProsperoNapsMeta.cs")
SI_ARCHIVE = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PKG/ProsperoSiArchive.cs")
NATIVE_DATA_DST = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PFS/PackizardNativeDataStream.cs")
NATIVE_NAPS_DST = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PKG/PackizardNativeNapsEngine.cs")


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one {label}, found {count}")
    return text.replace(old, new, 1)


def _replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    a = text.find(start)
    if a < 0:
        raise RuntimeError(f"Could not find start marker for {label}")
    b = text.find(end, a)
    if b < 0:
        raise RuntimeError(f"Could not find end marker for {label}")
    return text[:a] + replacement + text[b:]


def _copy_native_sources(root: Path) -> None:
    source_root = Path(__file__).resolve().parent / "native_naps"
    pairs = [
        (source_root / "PackizardNativeDataStream.cs", root / NATIVE_DATA_DST),
        (source_root / "PackizardNativeNapsEngine.cs", root / NATIVE_NAPS_DST),
    ]
    for source, destination in pairs:
        if not source.is_file():
            raise RuntimeError(f"Missing Packizard native NAPS source: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _patch_assembler(root: Path) -> None:
    path = root / ASSEMBLER
    text = path.read_text(encoding="utf-8")
    marker = "Packizard canonical DATA U-block map"
    if marker in text:
        return

    old_prop = '''    /// <summary>Per-file on-disk/logical placement (afid order), for naps generation.</summary>\n    public IReadOnlyList<ProsperoPs5InnerPlacement> Placements { get; init; } = Array.Empty<ProsperoPs5InnerPlacement>();\n'''
    new_prop = old_prop + '''\n    /// <summary>Packizard canonical DATA U-block map; independent of file-count density.</summary>\n    public IReadOnlyList<PackizardInnerDataBlock> DataBlocks { get; init; } = Array.Empty<PackizardInnerDataBlock>(); // Packizard canonical DATA U-block map\n'''
    text = _replace_once(text, old_prop, new_prop, "inner-result DataBlocks property")

    step3_start = "        // ---- 3. Logical offsets (packed, in afid order) + store rule. -----------------------------\n"
    step3_end = "        // Pad dataBlocks up so that `metaBase = (dataBlocks + 63) * BlockSize`"
    step3 = '''        // ---- 3. Logical offsets + Packizard canonical DATA stream. ------------------------------------\n        // File boundaries remain inode/fidx boundaries, but they no longer create physical compression\n        // blocks.  This is the structural fix for u2c overflow with dense small-file trees.\n        long cursor = 0;\n        var afidOffsets = new long[afidOrder.Count];\n        foreach (var f in afidOrder)\n        {\n            f.LogicalOffset = cursor;\n            afidOffsets[f.Afid] = cursor;\n            cursor = checked(cursor + f.DataLength);\n            ProsperoInnerFilePolicy policy = f.Policy\n                ?? ProsperoInnerFileClassifier.Classify(f.Header);\n            f.StoreRaw = policy == ProsperoInnerFilePolicy.StoreVerbatim\n                || policy == ProsperoInnerFilePolicy.RequiresModuleConversion;\n            f.SceSys = f.FullPath.StartsWith("/sce_sys/", StringComparison.Ordinal);\n            f.WholeBlockRaw = IsKeystone(f.FullPath);\n        }\n\n        string nativeDataPath = temps.Create();\n        var nativeSources = afidOrder.Select(f => new PackizardLogicalDataSource\n        {\n            Path = f.FullPath,\n            LogicalOffset = f.LogicalOffset,\n            Length = f.DataLength,\n            Data = f.Data,\n            DataPath = f.DataPath,\n            // If any signed/module content intersects a U-block, preserve the entire U-block raw.\n            ForceRaw = f.StoreRaw,\n            OwnerFlag = f.Afid == 0 ? 0u : 1u,\n        }).ToArray();\n        PackizardNativeDataStreamResult dataStream =\n            PackizardNativeDataStream.Build(nativeSources, nativeDataPath);\n        if (dataStream.LogicalLength != cursor)\n            throw new InvalidOperationException(\n                $"Packizard DATA logical length mismatch: {dataStream.LogicalLength:N0}/{cursor:N0}.");\n\n        // Placements remain as file-level introspection/fidx metadata.  Their physical anchor is the\n        // containing canonical U-block; NAPS itself consumes DataBlocks directly.\n        foreach (var f in afidOrder)\n        {\n            f.OnDiskOffset = PackizardNativeDataStream.PhysicalAnchorForLogical(\n                dataStream.Blocks, f.LogicalOffset, dataStream.LogicalLength);\n            if (f.DataLength == 0)\n            {\n                f.OnDiskLength = 0;\n                continue;\n            }\n            int firstBlock = checked((int)(f.LogicalOffset / PackizardNativeDataStream.UBlockSize));\n            int lastBlock = checked((int)((f.LogicalOffset + f.DataLength - 1) / PackizardNativeDataStream.UBlockSize));\n            long physicalCoverage = 0;\n            for (int block = firstBlock; block <= lastBlock; block++)\n                physicalCoverage = checked(physicalCoverage + dataStream.Blocks[block].CompressedSize);\n            f.OnDiskLength = physicalCoverage;\n        }\n\n        long dataBlocks = RoundUp(dataStream.EncodedLength, BlockSize) / BlockSize;\n\n'''
    text = _replace_between(text, step3_start, step3_end, step3, "assembler canonical DATA step")

    old_call = '''        byte[] image = BuildImage(afidOrder, metaPlain, out long blockInfoOnDisk, out long metadataOnDisk,\n            out byte[] compressedMeta, out var metaBlocks, out string? imageFilePath, out long imageLength, temps);\n'''
    new_call = '''        byte[] image = BuildImage(afidOrder, dataStream, metaPlain, out long blockInfoOnDisk, out long metadataOnDisk,\n            out byte[] compressedMeta, out var metaBlocks, out string? imageFilePath, out long imageLength, temps);\n'''
    text = _replace_once(text, old_call, new_call, "native BuildImage call")

    old_result = '''            Placements = placements,\n            BlockInfoOnDiskOffset = blockInfoOnDisk,\n'''
    new_result = '''            Placements = placements,\n            DataBlocks = dataStream.Blocks,\n            BlockInfoOnDiskOffset = blockInfoOnDisk,\n'''
    text = _replace_once(text, old_result, new_result, "DataBlocks result propagation")

    image_start = "    private byte[] BuildImage(List<FileNode> afidOrder, byte[] metaPlain,\n"
    image_end = "    /// <summary>\n    /// PFSv3 build/SDK version stamped into every block-75 entry"
    image_method = '''    private byte[] BuildImage(List<FileNode> afidOrder, PackizardNativeDataStreamResult dataStream, byte[] metaPlain,\n        out long blockInfoOnDisk, out long metadataOnDisk, out byte[] compressedMeta,\n        out IReadOnlyList<ProsperoInnerMetaBlockChunk> metaBlocks,\n        out string? imageFilePath, out long imageLength, ProsperoBuildTempFiles temps)\n    {\n        const int BLK = ProsperoPs5InnerImageBuilder.BlockSize;\n        static long AlignUp(long v, long a) => (v + a - 1) & ~(a - 1);\n\n        var payloads = new List<ProsperoPs5InnerPayload>();\n        if (dataStream.EncodedLength > 0)\n        {\n            payloads.Add(new ProsperoPs5InnerPayload\n            {\n                DataPath = dataStream.EncodedPath,\n                StoreRaw = true,\n                BlockAligned = false,\n            });\n        }\n\n        long urootSize = 0;\n        foreach (var f in afidOrder)\n            if (!f.SceSys) urootSize = checked(urootSize + f.DataLength);\n        byte[] blockInfo = BuildBlockInfoTable(urootSize);\n        blockInfoOnDisk = AlignUp(dataStream.EncodedLength, BLK);\n        payloads.Add(new ProsperoPs5InnerPayload\n        {\n            Data = blockInfo, StoreRaw = true, BlockAligned = true,\n        });\n\n        compressedMeta = ProsperoPs5InnerImageBuilder.CompressPayload(metaPlain, storeRaw: false, out var metaPf);\n        metaBlocks = metaPf is null\n            ? Array.Empty<ProsperoInnerMetaBlockChunk>()\n            : metaPf.Blocks.Select(b => new ProsperoInnerMetaBlockChunk(\n                b.CompressedSize, b.UncompressedSize, b.IsMultiChunk, b.FirstChunkCompressedSize)).ToArray();\n        metadataOnDisk = AlignUp(blockInfoOnDisk + blockInfo.LongLength, BLK);\n        payloads.Add(new ProsperoPs5InnerPayload\n        {\n            Data = compressedMeta, StoreRaw = true, BlockAligned = true,\n        });\n\n        imageLength = checked(metadataOnDisk + compressedMeta.LongLength);\n        string builtPath = temps.Create();\n        long written = new ProsperoPs5InnerImageBuilder().BuildToFile(payloads, builtPath);\n        if (written != imageLength)\n            throw new InvalidOperationException(\n                $"Packizard native inner-image length mismatch: planned {imageLength:N0}, wrote {written:N0}.");\n\n        bool canReturnMemory = imageLength < 64L * 1024 * 1024 && afidOrder.All(f => f.DataPath is null);\n        if (canReturnMemory)\n        {\n            imageFilePath = null;\n            return File.ReadAllBytes(builtPath);\n        }\n\n        imageFilePath = builtPath;\n        return Array.Empty<byte>();\n    }\n\n'''
    text = _replace_between(text, image_start, image_end, image_method, "native BuildImage implementation")
    path.write_text(text, encoding="utf-8", newline="\n")


def _patch_pkg_builder(root: Path) -> None:
    path = root / PKG_BUILDER
    text = path.read_text(encoding="utf-8")
    old = "            byte[] nwonlyNaps = ProsperoNwonlyNapsGenerator.Generate(asmResult);\n"
    new = "            byte[] nwonlyNaps = PackizardNativeNapsEngine.Generate(asmResult);\n"
    if new not in text:
        text = _replace_once(text, old, new, "PKG native NAPS call")
        path.write_text(text, encoding="utf-8", newline="\n")


def _patch_naps_meta(root: Path) -> None:
    path = root / NAPS_META
    text = path.read_text(encoding="utf-8")
    marker = "Packizard canonical DATA blocks for naps_meta_18"
    if marker in text:
        return
    start = "    private static List<Meta18Block> BuildInnerBlocks(LibProsperoPkg.PFS.ProsperoPs5InnerImageResult inner)\n"
    end = "    // ihsh preimage for a hole block:"
    replacement = '''    private static List<Meta18Block> BuildInnerBlocks(LibProsperoPkg.PFS.ProsperoPs5InnerImageResult inner)\n    {\n        // Packizard canonical DATA blocks for naps_meta_18.  File boundaries do not manufacture block\n        // records; this table describes the same physical 256 KiB DATA map consumed by native NAPS.\n        var blocks = new List<Meta18Block>();\n        foreach (LibProsperoPkg.PFS.PackizardInnerDataBlock d in inner.DataBlocks)\n        {\n            uint cs = checked((uint)d.CompressedSize);\n            uint ps = checked((uint)d.UncompressedSize);\n            uint c0 = d.IsStored\n                ? cs\n                : checked((uint)(d.IsMultiChunk ? d.FirstChunkCompressedSize : d.CompressedSize));\n            uint c1 = d.IsStored || !d.IsMultiChunk ? 0u : checked(cs - c0);\n            blocks.Add(new Meta18Block(\n                Co: checked((ulong)d.OnDiskOffset), Cs: cs, Ps: ps, C0: c0, C1: c1,\n                Flag: 0x40090000u, IsHole: false, OwnerFlag: d.OwnerFlag, Tail: 0,\n                OnDiskOffset: d.OnDiskOffset, OnDiskLen: cs));\n        }\n\n        // The final DATA U-block is zero-padded by Packizard, so hole coverage begins at its end.\n        long dataCoverageEnd = checked((long)inner.DataBlocks.Count * Meta18UBlock);\n        long padding = inner.MetaBaseLogical - dataCoverageEnd;\n        if (padding < 0)\n            throw new InvalidOperationException(\n                $"Packizard naps_meta_18 DATA coverage overlaps metadata by {-padding:N0} bytes.");\n        if (padding > 0)\n        {\n            int nblk = checked((int)((padding + Meta18UBlock - 1) / Meta18UBlock));\n            var holeCo = new Dictionary<uint, ulong>();\n            ulong cursor = checked((ulong)inner.BlockInfoOnDiskOffset);\n            for (int k = 0; k < nblk; k++)\n            {\n                uint ps = checked((uint)Math.Min(Meta18UBlock, padding - (long)k * Meta18UBlock));\n                if (!holeCo.TryGetValue(ps, out ulong co))\n                {\n                    co = cursor;\n                    holeCo[ps] = co;\n                    cursor += 0x10;\n                }\n                blocks.Add(new Meta18Block(\n                    Co: co, Cs: 0x10, Ps: ps, C0: 8, C1: 8, Flag: 0x40110000u,\n                    IsHole: true, OwnerFlag: 0, Tail: 0, OnDiskOffset: 0, OnDiskLen: 0));\n            }\n        }\n\n        IReadOnlyList<LibProsperoPkg.PFS.ProsperoInnerMetaBlockChunk> metaChunks = inner.MetadataBlocks;\n        if (metaChunks.Count == 0 && inner.MetadataPlaintext.Length > 0)\n        {\n            var mf = LibProsperoPkg.PFS.Compression.ProsperoCompressedPfsFile.Parse(\n                LibProsperoPkg.PFS.Compression.ProsperoCompressedPfsImage.Pack(\n                    inner.MetadataPlaintext, 7, (int)Meta18UBlock));\n            metaChunks = mf.Blocks.Select(b => new LibProsperoPkg.PFS.ProsperoInnerMetaBlockChunk(\n                b.CompressedSize, b.UncompressedSize, b.IsMultiChunk, b.FirstChunkCompressedSize)).ToArray();\n        }\n        ulong metaCursor = checked((ulong)inner.MetadataOnDiskOffset);\n        foreach (LibProsperoPkg.PFS.ProsperoInnerMetaBlockChunk m in metaChunks)\n        {\n            uint cs = checked((uint)m.CompressedSize);\n            uint c0 = m.IsMultiChunk ? checked((uint)m.FirstChunkCompressedSize) : cs;\n            uint c1 = m.IsMultiChunk ? cs - c0 : 0;\n            uint flag = c1 > 0 ? 0x40450000u : 0x40050000u;\n            blocks.Add(new Meta18Block(\n                Co: metaCursor, Cs: cs, Ps: checked((uint)m.UncompressedSize), C0: c0, C1: c1, Flag: flag,\n                IsHole: false, OwnerFlag: 0, Tail: Meta300KindId,\n                OnDiskOffset: checked((long)metaCursor), OnDiskLen: cs));\n            metaCursor += cs;\n        }\n        return blocks;\n    }\n\n'''
    text = _replace_between(text, start, end, replacement, "naps_meta_18 native block map")
    path.write_text(text, encoding="utf-8", newline="\n")


def _patch_si_archive(root: Path) -> None:
    path = root / SI_ARCHIVE
    text = path.read_text(encoding="utf-8")
    old = '''        // File mount-logical offset -> on-disk (packed data-region) offset for the <file offset="..."> value.\n        var onDiskByLogical = new Dictionary<ulong, long>();\n        foreach (var p in inner.Placements)\n            onDiskByLogical[(ulong)p.LogicalOffset] = p.OnDiskOffset;\n'''
    new = '''        // File mount-logical offset -> physical anchor of the canonical U-block containing it.\n        // Multiple tiny files may intentionally share the same physical U-block anchor.\n        var onDiskByLogical = new Dictionary<ulong, long>();\n        foreach (var p in inner.Placements)\n            onDiskByLogical[(ulong)p.LogicalOffset] = PackizardNativeDataStream.PhysicalAnchorForLogical(\n                inner.DataBlocks, p.LogicalOffset, inner.DataEndLogical);\n'''
    if new not in text:
        text = _replace_once(text, old, new, "nested-image physical anchor map")
        path.write_text(text, encoding="utf-8", newline="\n")


def apply(root: Path) -> None:
    root = Path(root)
    _copy_native_sources(root)
    _patch_assembler(root)
    _patch_pkg_builder(root)
    _patch_naps_meta(root)
    _patch_si_archive(root)
    print("Applied Packizard-native canonical DATA/NAPS engine")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="build-src")
    args = parser.parse_args()
    apply(Path(args.root))


if __name__ == "__main__":
    main()
