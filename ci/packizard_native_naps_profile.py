#!/usr/bin/env python3
"""Install Packizard-owned DATA/NAPS engines into the reconstructed build tree.

The upstream package code remains responsible for generic PFS/PKG cryptographic/container work.
Packizard owns the inner DATA coding geometry, NAPS topology, u2c planning/validation and binary NAPS
serialization.  This profile is intentionally applied after the generic large-package/AMPR overlays.
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
NATIVE_WRITER_DST = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PKG/PackizardNativeNapsWriter.cs")
NATIVE_VALIDATOR_DST = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PKG/PackizardNativeNapsValidator.cs")


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
        (source_root / "PackizardNativeNapsWriter.cs", root / NATIVE_WRITER_DST),
        (source_root / "PackizardNativeNapsValidator.cs", root / NATIVE_VALIDATOR_DST),
    ]
    for source, destination in pairs:
        if not source.is_file():
            raise RuntimeError(f"Missing Packizard native source: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _patch_assembler(root: Path) -> None:
    path = root / ASSEMBLER
    text = path.read_text(encoding="utf-8")

    if "Packizard canonical DATA block map" not in text:
        old_prop = '''    /// <summary>Per-file on-disk/logical placement (afid order), for naps generation.</summary>\n    public IReadOnlyList<ProsperoPs5InnerPlacement> Placements { get; init; } = Array.Empty<ProsperoPs5InnerPlacement>();\n'''
        new_prop = old_prop + '''\n    /// <summary>Packizard canonical DATA block map; ordinary file boundaries do not split blocks.</summary>\n    public IReadOnlyList<PackizardInnerDataBlock> DataBlocks { get; init; } = Array.Empty<PackizardInnerDataBlock>(); // Packizard canonical DATA block map\n'''
        text = _replace_once(text, old_prop, new_prop, "inner-result DataBlocks property")

        step3_start = "        // ---- 3. Logical offsets (packed, in afid order) + store rule. -----------------------------\n"
        step3_end = "        // Pad dataBlocks up so that `metaBase = (dataBlocks + 63) * BlockSize`"
        step3 = '''        // ---- 3. Logical offsets + Packizard canonical DATA stream. ------------------------------------\n        // Ordinary filesystem boundaries stay visible to inode/fidx metadata but do NOT manufacture\n        // compression blocks. Raw/module files are explicit codec barriers.\n        long cursor = 0;\n        var afidOffsets = new long[afidOrder.Count];\n        foreach (var f in afidOrder)\n        {\n            f.LogicalOffset = cursor;\n            afidOffsets[f.Afid] = cursor;\n            cursor = checked(cursor + f.DataLength);\n            ProsperoInnerFilePolicy policy = f.Policy\n                ?? ProsperoInnerFileClassifier.Classify(f.Header);\n            f.StoreRaw = policy == ProsperoInnerFilePolicy.StoreVerbatim\n                || policy == ProsperoInnerFilePolicy.RequiresModuleConversion;\n            f.SceSys = f.FullPath.StartsWith("/sce_sys/", StringComparison.Ordinal);\n            f.WholeBlockRaw = IsKeystone(f.FullPath);\n        }\n\n        string nativeDataPath = temps.Create();\n        var nativeSources = afidOrder.Select(f => new PackizardLogicalDataSource\n        {\n            Path = f.FullPath,\n            LogicalOffset = f.LogicalOffset,\n            Length = f.DataLength,\n            Data = f.Data,\n            DataPath = f.DataPath,\n            ForceRaw = f.StoreRaw,\n            WholeBlockRaw = f.WholeBlockRaw,\n            OwnerFlag = f.Afid == 0 ? 0u : 1u,\n        }).ToArray();\n        PackizardNativeDataStreamResult dataStream =\n            PackizardNativeDataStream.Build(nativeSources, nativeDataPath);\n        if (dataStream.LogicalLength != cursor)\n            throw new InvalidOperationException(\n                $"Packizard DATA logical length mismatch: {dataStream.LogicalLength:N0}/{cursor:N0}.");\n\n        // File-level placements are introspection/SI metadata only. NAPS consumes DataBlocks directly.\n        // A file may share its first/last DATA block with neighbouring ordinary files.\n        foreach (var f in afidOrder)\n        {\n            f.OnDiskOffset = PackizardNativeDataStream.PhysicalAnchorForLogical(\n                dataStream.Blocks, f.LogicalOffset, dataStream.LogicalLength);\n            if (f.DataLength == 0)\n            {\n                f.OnDiskLength = 0;\n                continue;\n            }\n\n            long fileEnd = checked(f.LogicalOffset + f.DataLength);\n            PackizardInnerDataBlock[] overlap = dataStream.Blocks\n                .Where(b => b.LogicalOffset < fileEnd\n                    && checked(b.LogicalOffset + b.UncompressedSize) > f.LogicalOffset)\n                .ToArray();\n            if (overlap.Length == 0)\n                throw new InvalidOperationException(\n                    $"Packizard DATA has no coding block covering non-empty file {f.FullPath}.");\n            f.OnDiskOffset = overlap[0].OnDiskOffset;\n            PackizardInnerDataBlock last = overlap[^1];\n            f.OnDiskLength = checked(last.OnDiskOffset + last.CompressedSize - f.OnDiskOffset);\n        }\n\n        // Mount geometry is LOGICAL. EncodedLength is only a physical pfs_image.dat coordinate.\n        long dataBlocks = RoundUp(dataStream.LogicalLength, BlockSize) / BlockSize;\n\n'''
        text = _replace_between(text, step3_start, step3_end, step3, "assembler canonical DATA step")

        old_result = '''            Placements = placements,\n            BlockInfoOnDiskOffset = blockInfoOnDisk,\n'''
        new_result = '''            Placements = placements,\n            DataBlocks = dataStream.Blocks,\n            BlockInfoOnDiskOffset = blockInfoOnDisk,\n'''
        text = _replace_once(text, old_result, new_result, "DataBlocks result propagation")

    # Normalize the assembly call independent of the evolving upstream BuildImage signature.
    if "byte[] image = BuildNativeImage(" not in text:
        anchor = "        byte[] image = BuildImage("
        start = text.find(anchor)
        if start < 0:
            raise RuntimeError("Could not locate upstream inner-image assembly call")
        end = text.find(");", start)
        if end < 0:
            raise RuntimeError("Could not locate end of upstream inner-image assembly call")
        end += 2
        replacement = '''        byte[] image = BuildNativeImage(\n            afidOrder, dataStream, metaPlain,\n            out long blockInfoOnDisk, out long metadataOnDisk,\n            out byte[] compressedMeta, out var metaBlocks,\n            out string? imageFilePath, out long imageLength, temps);'''
        text = text[:start] + replacement + text[end:]

    signature = (
        "private byte[] BuildNativeImage(List<FileNode> afidOrder, "
        "PackizardNativeDataStreamResult dataStream, byte[] metaPlain"
    )
    if signature not in text:
        candidates = [
            "    private byte[] BuildImage(List<FileNode> afidOrder,",
            "    /// <summary>\n    /// PFSv3 build/SDK version stamped into every block-75 entry",
        ]
        positions = [text.find(marker) for marker in candidates]
        positions = [p for p in positions if p >= 0]
        if not positions:
            raise RuntimeError("Could not find insertion point for BuildNativeImage")
        pos = min(positions)
        method = '''    // Packizard-native physical writer. Logical mount geometry was already fixed above; this\n    // routine only places the encoded DATA bytes, block-info table and compressed metadata on disk.\n    private byte[] BuildNativeImage(List<FileNode> afidOrder, PackizardNativeDataStreamResult dataStream, byte[] metaPlain,\n        out long blockInfoOnDisk, out long metadataOnDisk, out byte[] compressedMeta,\n        out IReadOnlyList<ProsperoInnerMetaBlockChunk> metaBlocks,\n        out string? imageFilePath, out long imageLength, ProsperoBuildTempFiles temps)\n    {\n        const int BLK = ProsperoPs5InnerImageBuilder.BlockSize;\n        static long AlignUp(long v, long a) => (v + a - 1) & ~(a - 1);\n\n        var payloads = new List<ProsperoPs5InnerPayload>();\n        if (dataStream.EncodedLength > 0)\n        {\n            payloads.Add(new ProsperoPs5InnerPayload\n            {\n                DataPath = dataStream.EncodedPath,\n                StoreRaw = true,\n                BlockAligned = false,\n            });\n        }\n\n        long urootSize = 0;\n        foreach (var f in afidOrder)\n            if (!f.SceSys) urootSize = checked(urootSize + f.DataLength);\n        byte[] blockInfo = BuildBlockInfoTable(urootSize);\n        blockInfoOnDisk = AlignUp(dataStream.EncodedLength, BLK);\n        payloads.Add(new ProsperoPs5InnerPayload\n        {\n            Data = blockInfo, StoreRaw = true, BlockAligned = true,\n        });\n\n        compressedMeta = ProsperoPs5InnerImageBuilder.CompressPayload(\n            metaPlain, storeRaw: false, out var metaPf);\n        metaBlocks = metaPf is null\n            ? Array.Empty<ProsperoInnerMetaBlockChunk>()\n            : metaPf.Blocks.Select(b => new ProsperoInnerMetaBlockChunk(\n                b.CompressedSize, b.UncompressedSize, b.IsMultiChunk,\n                b.FirstChunkCompressedSize)).ToArray();\n\n        metadataOnDisk = AlignUp(blockInfoOnDisk + blockInfo.LongLength, BLK);\n        payloads.Add(new ProsperoPs5InnerPayload\n        {\n            Data = compressedMeta, StoreRaw = true, BlockAligned = true,\n        });\n\n        imageLength = checked(metadataOnDisk + compressedMeta.LongLength);\n        string builtPath = temps.Create();\n        long written = new ProsperoPs5InnerImageBuilder().BuildToFile(payloads, builtPath);\n        if (written != imageLength)\n            throw new InvalidOperationException(\n                $"Packizard native inner-image length mismatch: planned {imageLength:N0}, wrote {written:N0}.");\n\n        bool canReturnMemory = imageLength < 64L * 1024 * 1024\n            && afidOrder.All(f => f.DataPath is null);\n        if (canReturnMemory)\n        {\n            imageFilePath = null;\n            return File.ReadAllBytes(builtPath);\n        }\n\n        imageFilePath = builtPath;\n        return Array.Empty<byte>();\n    }\n\n'''
        text = text[:pos] + method + text[pos:]

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
    replacement = '''    private static List<Meta18Block> BuildInnerBlocks(LibProsperoPkg.PFS.ProsperoPs5InnerImageResult inner)\n    {\n        // Packizard canonical DATA blocks for naps_meta_18. Ordinary file boundaries are irrelevant here.\n        var blocks = new List<Meta18Block>();\n        foreach (LibProsperoPkg.PFS.PackizardInnerDataBlock d in inner.DataBlocks)\n        {\n            uint cs = checked((uint)d.CompressedSize);\n            uint ps = checked((uint)d.UncompressedSize);\n            uint c0 = d.IsStored\n                ? cs\n                : checked((uint)(d.IsMultiChunk ? d.FirstChunkCompressedSize : d.CompressedSize));\n            uint c1 = d.IsStored || !d.IsMultiChunk ? 0u : checked(cs - c0);\n            blocks.Add(new Meta18Block(\n                Co: checked((ulong)d.OnDiskOffset), Cs: cs, Ps: ps, C0: c0, C1: c1,\n                Flag: 0x40090000u, IsHole: false, OwnerFlag: d.OwnerFlag, Tail: 0,\n                OnDiskOffset: d.OnDiskOffset, OnDiskLen: cs));\n        }\n\n        long dataCoverageEnd = inner.DataEndLogical;\n        long padding = inner.MetaBaseLogical - dataCoverageEnd;\n        if (padding < 0)\n            throw new InvalidOperationException(\n                $"Packizard naps_meta_18 DATA overlaps metadata by {-padding:N0} logical bytes.");\n        if (padding > 0)\n        {\n            int nblk = checked((int)((padding + Meta18UBlock - 1) / Meta18UBlock));\n            var holeCo = new Dictionary<uint, ulong>();\n            ulong cursor = checked((ulong)inner.BlockInfoOnDiskOffset);\n            for (int k = 0; k < nblk; k++)\n            {\n                uint ps = checked((uint)Math.Min(Meta18UBlock, padding - (long)k * Meta18UBlock));\n                if (!holeCo.TryGetValue(ps, out ulong co))\n                {\n                    co = cursor;\n                    holeCo[ps] = co;\n                    cursor += 0x10;\n                }\n                blocks.Add(new Meta18Block(\n                    Co: co, Cs: 0x10, Ps: ps, C0: 8, C1: 8, Flag: 0x40110000u,\n                    IsHole: true, OwnerFlag: 0, Tail: 0, OnDiskOffset: 0, OnDiskLen: 0));\n            }\n        }\n\n        IReadOnlyList<LibProsperoPkg.PFS.ProsperoInnerMetaBlockChunk> metaChunks = inner.MetadataBlocks;\n        if (metaChunks.Count == 0 && inner.MetadataPlaintext.Length > 0)\n        {\n            var mf = LibProsperoPkg.PFS.Compression.ProsperoCompressedPfsFile.Parse(\n                LibProsperoPkg.PFS.Compression.ProsperoCompressedPfsImage.Pack(\n                    inner.MetadataPlaintext, 7, (int)Meta18UBlock));\n            metaChunks = mf.Blocks.Select(b => new LibProsperoPkg.PFS.ProsperoInnerMetaBlockChunk(\n                b.CompressedSize, b.UncompressedSize, b.IsMultiChunk, b.FirstChunkCompressedSize)).ToArray();\n        }\n        ulong metaCursor = checked((ulong)inner.MetadataOnDiskOffset);\n        foreach (LibProsperoPkg.PFS.ProsperoInnerMetaBlockChunk m in metaChunks)\n        {\n            uint cs = checked((uint)m.CompressedSize);\n            uint c0 = m.IsMultiChunk ? checked((uint)m.FirstChunkCompressedSize) : cs;\n            uint c1 = m.IsMultiChunk ? cs - c0 : 0;\n            uint flag = c1 > 0 ? 0x40450000u : 0x40050000u;\n            blocks.Add(new Meta18Block(\n                Co: metaCursor, Cs: cs, Ps: checked((uint)m.UncompressedSize), C0: c0, C1: c1, Flag: flag,\n                IsHole: false, OwnerFlag: 0, Tail: Meta300KindId,\n                OnDiskOffset: checked((long)metaCursor), OnDiskLen: cs));\n            metaCursor += cs;\n        }\n        return blocks;\n    }\n\n'''
    text = _replace_between(text, start, end, replacement, "naps_meta_18 native block map")
    path.write_text(text, encoding="utf-8", newline="\n")


def _patch_si_archive(root: Path) -> None:
    path = root / SI_ARCHIVE
    text = path.read_text(encoding="utf-8")
    old = '''        // File mount-logical offset -> on-disk (packed data-region) offset for the <file offset="..."> value.\n        var onDiskByLogical = new Dictionary<ulong, long>();\n        foreach (var p in inner.Placements)\n            onDiskByLogical[(ulong)p.LogicalOffset] = p.OnDiskOffset;\n'''
    new = '''        // File logical offset -> physical anchor of the Packizard DATA block containing its first byte.\n        // Several ordinary files may intentionally share one encoded DATA block.\n        var onDiskByLogical = new Dictionary<ulong, long>();\n        foreach (var p in inner.Placements)\n            onDiskByLogical[(ulong)p.LogicalOffset] = PackizardNativeDataStream.PhysicalAnchorForLogical(\n                inner.DataBlocks, p.LogicalOffset, inner.DataEndLogical);\n'''
    if new not in text:
        text = _replace_once(text, old, new, "nested-image physical anchor map")
    path.write_text(text, encoding="utf-8", newline="\n")


def _validate_native_route(root: Path) -> None:
    assembler = (root / ASSEMBLER).read_text(encoding="utf-8")
    pkg = (root / PKG_BUILDER).read_text(encoding="utf-8")
    required = [
        "Packizard canonical DATA block map",
        "RoundUp(dataStream.LogicalLength, BlockSize)",
        "WholeBlockRaw = f.WholeBlockRaw",
        "byte[] image = BuildNativeImage(",
        "private byte[] BuildNativeImage(",
    ]
    for needle in required:
        if needle not in assembler:
            raise RuntimeError(f"Packizard native assembler route is missing: {needle}")
    if "PackizardNativeNapsEngine.Generate(asmResult)" not in pkg:
        raise RuntimeError("Packizard PKG builder is not routed to PackizardNativeNapsEngine")
    if "ProsperoNwonlyNapsGenerator.Generate(asmResult)" in pkg:
        raise RuntimeError("Legacy NAPS topology generator leaked into native PKG path")
    print("Validated Packizard native route: cross-file DATA blocks -> native planner/validator/writer")


def apply(root: Path) -> None:
    root = Path(root)
    _copy_native_sources(root)
    _patch_assembler(root)
    _patch_pkg_builder(root)
    _patch_naps_meta(root)
    _patch_si_archive(root)
    _validate_native_route(root)
    print("Applied Packizard-native DATA/NAPS engine")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="build-src")
    args = parser.parse_args()
    apply(Path(args.root))


if __name__ == "__main__":
    main()
