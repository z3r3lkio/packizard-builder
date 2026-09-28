#!/usr/bin/env python3
"""Preserve the real per-256KiB data-block map when generating NAPS.

LibProsperoPKG's data-first writer encodes ordinary files as independent 256 KiB
Kraken/stored blocks, but the legacy NAPS model collapsed a compressed file into
one CblockInfo entry. Large files then leave long logical U-block ranges without
matching CblockInfo records and can overflow the one-byte u2c delta field.

This profile is applied after Packizard's AMPR/progress overlays. It records the
block decisions made by the actual encoder and threads that geometry into NAPS,
so the layout describes the bytes that were really written.
"""
from __future__ import annotations

from pathlib import Path


IMAGE_BUILDER_REL = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PFS/ProsperoPs5InnerImageBuilder.cs")
ASSEMBLER_REL = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PFS/ProsperoPs5InnerImageAssembler.cs")
NAPS_LAYOUT_REL = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PKG/ProsperoNapsLayoutBuilder.cs")
NAPS_GENERATOR_REL = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PKG/ProsperoNwonlyNapsGenerator.cs")


def _replace_once(path: Path, text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"NAPS data-block map profile expected exactly one {label} in {path}, found {count}. "
            "Rebase the profile against the pinned reconstructed LibProsperoPKG source."
        )
    return text.replace(old, new, 1)


def _patch_image_builder(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    marker = "Packizard per-data-block NAPS map"
    if marker in text:
        return

    text = _replace_once(
        path,
        text,
        "public sealed class ProsperoPs5InnerImageBuilder\n{\n",
        '''// Packizard per-data-block NAPS map: this is the exact storage decision made for one\n// 256 KiB logical data block by the Kraken encoder.\npublic readonly record struct ProsperoInnerDataBlockChunk(\n    int CompressedSize, int UncompressedSize, bool IsStored,\n    bool IsMultiChunk, int FirstChunkCompressedSize);\n\npublic sealed class ProsperoPs5InnerImageBuilder\n{\n''',
        "data-block map record",
    )

    old_method = '''    /// <summary>Compresses independent 256 KiB blocks without retaining the whole source.</summary>\n    public static void CompressPayloadToStream(Stream source, Stream destination, long length)\n    {\n        ArgumentOutOfRangeException.ThrowIfNegative(length);\n        var buffer = new byte[CompressBlockSize];\n        long remaining = length;\n        while (remaining > 0)\n        {\n            int count = (int)Math.Min(remaining, buffer.Length);\n            source.ReadExactly(buffer.AsSpan(0, count));\n            byte[] block = count == buffer.Length ? buffer : buffer.AsSpan(0, count).ToArray();\n            byte[] encoded = CompressPayload(block, storeRaw: false);\n            destination.Write(encoded);\n            remaining -= count;\n        }\n    }\n'''
    new_method = '''    /// <summary>\n    /// Compresses independent 256 KiB blocks without retaining the whole source. When\n    /// <paramref name="blockMap"/> is supplied, records the exact per-block Kraken/stored\n    /// decision used for the emitted byte stream so NAPS can describe the same geometry.\n    /// </summary>\n    public static void CompressPayloadToStream(\n        Stream source, Stream destination, long length,\n        IList<ProsperoInnerDataBlockChunk>? blockMap = null)\n    {\n        ArgumentOutOfRangeException.ThrowIfNegative(length);\n        var buffer = new byte[CompressBlockSize];\n        long remaining = length;\n        while (remaining > 0)\n        {\n            int count = (int)Math.Min(remaining, buffer.Length);\n            source.ReadExactly(buffer.AsSpan(0, count));\n            byte[] block = count == buffer.Length ? buffer : buffer.AsSpan(0, count).ToArray();\n            byte[] encoded = CompressPayload(block, storeRaw: false, out var compressedFile);\n            destination.Write(encoded);\n\n            if (blockMap is not null)\n            {\n                if (compressedFile is null || compressedFile.Blocks.Count != 1)\n                    throw new InvalidDataException(\n                        $"Expected exactly one PFSC block for a {count:N0}-byte data chunk.");\n                var encodedBlock = compressedFile.Blocks[0];\n                if (encodedBlock.CompressedSize != encoded.Length\n                    || encodedBlock.UncompressedSize != count)\n                    throw new InvalidDataException(\n                        "Kraken block-map geometry does not match the bytes emitted to the inner image.");\n                blockMap.Add(new ProsperoInnerDataBlockChunk(\n                    encodedBlock.CompressedSize,\n                    encodedBlock.UncompressedSize,\n                    encodedBlock.IsStored,\n                    encodedBlock.IsMultiChunk,\n                    encodedBlock.FirstChunkCompressedSize));\n            }\n\n            remaining -= count;\n        }\n    }\n'''
    text = _replace_once(path, text, old_method, new_method, "streaming compressor block-map capture")
    path.write_text(text, encoding="utf-8", newline="\n")


def _patch_assembler(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    marker = "CompressedBlocks = f.CompressedBlocks.ToArray()"
    if marker in text:
        return

    text = _replace_once(
        path,
        text,
        '''    /// <summary>True when stored raw (block-split), false when Kraken-compressed.</summary>\n    public bool StoreRaw { get; init; }\n}\n''',
        '''    /// <summary>True when stored raw (block-split), false when Kraken-compressed.</summary>\n    public bool StoreRaw { get; init; }\n    /// <summary>Exact 256 KiB Kraken/stored block map for an encoded file; empty for raw files.</summary>\n    public IReadOnlyList<ProsperoInnerDataBlockChunk> CompressedBlocks { get; init; }\n        = Array.Empty<ProsperoInnerDataBlockChunk>();\n}\n''',
        "placement block-map property",
    )
    text = _replace_once(
        path,
        text,
        '''        public string? OnDiskPath;\n        public long OnDiskLength;\n        public Dir Parent = null!;\n''',
        '''        public string? OnDiskPath;\n        public long OnDiskLength;\n        public readonly List<ProsperoInnerDataBlockChunk> CompressedBlocks = new();\n        public Dir Parent = null!;\n''',
        "file-node block map",
    )
    text = _replace_once(
        path,
        text,
        '''                    ProsperoPs5InnerImageBuilder.CompressPayloadToStream(input, output, f.DataLength);\n                    f.OnDiskLength = output.Length;\n''',
        '''                    ProsperoPs5InnerImageBuilder.CompressPayloadToStream(\n                        input, output, f.DataLength, f.CompressedBlocks);\n                    f.OnDiskLength = output.Length;\n''',
        "file-backed block-map capture",
    )
    text = _replace_once(
        path,
        text,
        '''                f.OnDiskData = ProsperoPs5InnerImageBuilder.CompressPayload(f.Data, f.StoreRaw);\n                f.OnDiskLength = f.OnDiskData.LongLength;\n''',
        '''                f.OnDiskData = ProsperoPs5InnerImageBuilder.CompressPayload(\n                    f.Data, f.StoreRaw, out var compressedFile);\n                f.OnDiskLength = f.OnDiskData.LongLength;\n                if (!f.StoreRaw && compressedFile is not null)\n                {\n                    foreach (var encodedBlock in compressedFile.Blocks)\n                    {\n                        f.CompressedBlocks.Add(new ProsperoInnerDataBlockChunk(\n                            encodedBlock.CompressedSize,\n                            encodedBlock.UncompressedSize,\n                            encodedBlock.IsStored,\n                            encodedBlock.IsMultiChunk,\n                            encodedBlock.FirstChunkCompressedSize));\n                    }\n                }\n''',
        "in-memory block-map capture",
    )
    text = _replace_once(
        path,
        text,
        '''            UncompressedSize = f.DataLength,\n            StoreRaw = f.StoreRaw,\n        }).ToList();\n''',
        '''            UncompressedSize = f.DataLength,\n            StoreRaw = f.StoreRaw,\n            CompressedBlocks = f.CompressedBlocks.ToArray(),\n        }).ToList();\n''',
        "placement block-map propagation",
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def _patch_naps_layout(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    marker = "NapsFileBlockPlacement"
    if marker in text:
        return

    text = _replace_once(
        path,
        text,
        '''/// <summary>\n/// One placed DATA-region file, as laid out by <c>ProsperoPs5InnerImageAssembler</c>. The naps builder\n''',
        '''/// <summary>Exact storage geometry for one 256 KiB logical block of an encoded data file.</summary>\npublic readonly record struct NapsFileBlockPlacement(\n    int CompressedSize, int UncompressedSize, bool IsStored,\n    bool IsMultiChunk, int FirstChunkCompressedSize);\n\n/// <summary>\n/// One placed DATA-region file, as laid out by <c>ProsperoPs5InnerImageAssembler</c>. The naps builder\n''',
        "NAPS file-block record",
    )
    text = _replace_once(
        path,
        text,
        '''    /// <summary>KDE predictor for a compressed file's block (default 2 = Kraken).</summary>\n    public byte CompressedKde { get; init; } = 2;\n}\n''',
        '''    /// <summary>KDE predictor for a compressed file's block (default 2 = Kraken).</summary>\n    public byte CompressedKde { get; init; } = 2;\n\n    /// <summary>\n    /// Exact per-256KiB encoder map. Required for multi-block compressed files so u2c indexes\n    /// the real CblockInfo topology instead of collapsing the whole file into one record.\n    /// </summary>\n    public IReadOnlyList<NapsFileBlockPlacement> Blocks { get; init; }\n        = Array.Empty<NapsFileBlockPlacement>();\n}\n''',
        "NAPS file-placement block map",
    )

    old_branch = '''            else\n            {\n                blocks.Add(new NapsCblockPlanEntry\n                {\n                    StartRun = runSet.Contains(f.OnDiskOffset),\n                    OnDiskOffset = f.OnDiskOffset,\n                    LogicalOffset = f.LogicalOffset,\n                    EvenChunkCompressedLength = f.OnDiskSize,\n                    StreamLength = f.OnDiskSize,\n                    Even = 0,\n                    Odd = 1,\n                    KdePredictor = f.CompressedKde,\n                    ShuffleIndex = 0,\n                });\n            }\n'''
    new_branch = '''            else\n            {\n                // A compressed file is physically encoded as independent 256 KiB blocks. The old\n                // implementation represented the entire file with one CblockInfo entry; for large\n                // files that leaves hundreds of logical U-blocks pointing at the next file and can\n                // make the one-byte u2c delta overflow. Describe the exact encoder block map instead.\n                if (f.Blocks.Count == 0)\n                    throw new InvalidOperationException(\n                        $"Compressed NAPS placement at logical 0x{f.LogicalOffset:X} has no encoder block map.");\n\n                long blockOnDisk = f.OnDiskOffset;\n                long blockLogical = f.LogicalOffset;\n                long encodedTotal = 0;\n                long logicalTotal = 0;\n                foreach (NapsFileBlockPlacement block in f.Blocks)\n                {\n                    bool storedFull = block.IsStored && block.UncompressedSize == UBlock;\n                    bool storedTail = block.IsStored && !storedFull;\n                    blocks.Add(new NapsCblockPlanEntry\n                    {\n                        StartRun = runSet.Contains(blockOnDisk),\n                        OnDiskOffset = blockOnDisk,\n                        LogicalOffset = blockLogical,\n                        EvenChunkCompressedLength = storedFull\n                            ? 0x10000\n                            : storedTail\n                                ? block.UncompressedSize\n                                : block.IsMultiChunk\n                                    ? block.FirstChunkCompressedSize\n                                    : block.CompressedSize,\n                        StreamLength = storedFull\n                            ? 0x80000\n                            : storedTail ? block.UncompressedSize : block.CompressedSize,\n                        Even = (byte)(storedFull ? 1 : 0),\n                        Odd = 1,\n                        KdePredictor = (byte)(storedFull ? 4 : storedTail ? 0 : f.CompressedKde),\n                        ShuffleIndex = 0,\n                    });\n                    blockOnDisk = checked(blockOnDisk + block.CompressedSize);\n                    blockLogical = checked(blockLogical + block.UncompressedSize);\n                    encodedTotal = checked(encodedTotal + block.CompressedSize);\n                    logicalTotal = checked(logicalTotal + block.UncompressedSize);\n                }\n\n                if (encodedTotal != f.OnDiskSize || logicalTotal != f.UncompressedSize)\n                    throw new InvalidOperationException(\n                        $"NAPS block map disagrees with file placement: encoded {encodedTotal:N0}/{f.OnDiskSize:N0}, " +\n                        $"logical {logicalTotal:N0}/{f.UncompressedSize:N0} bytes.");\n            }\n'''
    text = _replace_once(path, text, old_branch, new_branch, "compressed-file NAPS expansion")
    path.write_text(text, encoding="utf-8", newline="\n")


def _patch_naps_generator(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    marker = "CompressedBlocks.Select"
    if marker in text:
        return

    text = _replace_once(
        path,
        text,
        '''            StoreRaw = p.StoreRaw,\n            CompressedKde = 2,\n        }).ToList();\n''',
        '''            StoreRaw = p.StoreRaw,\n            CompressedKde = 2,\n            Blocks = p.CompressedBlocks.Select(b => new NapsFileBlockPlacement(\n                b.CompressedSize, b.UncompressedSize, b.IsStored,\n                b.IsMultiChunk, b.FirstChunkCompressedSize)).ToArray(),\n        }).ToList();\n''',
        "NAPS block-map projection",
    )

    old_runs = '''                if (placements[i].StoreRaw)\n                {\n                    long ublocks = (placements[i].UncompressedSize + Ublock256K - 1) / Ublock256K;\n                    for (long m = 11; m < ublocks; m += 11)\n                        runSet.Add(placements[i].OnDiskOffset + m * Ublock256K);\n                }\n'''
    new_runs = '''                if (placements[i].StoreRaw)\n                {\n                    long ublocks = (placements[i].UncompressedSize + Ublock256K - 1) / Ublock256K;\n                    for (long m = 11; m < ublocks; m += 11)\n                        runSet.Add(placements[i].OnDiskOffset + m * Ublock256K);\n                }\n                else if (placements[i].CompressedBlocks.Count > 0)\n                {\n                    // The same periodic compressed-cursor rebase applies inside a long encoded file.\n                    // Unlike a raw file, block starts are variable, so derive them from the captured map.\n                    long blockOnDisk = placements[i].OnDiskOffset;\n                    for (int block = 0; block < placements[i].CompressedBlocks.Count; block++)\n                    {\n                        if (block > 0 && block % 11 == 0)\n                            runSet.Add(blockOnDisk);\n                        blockOnDisk += placements[i].CompressedBlocks[block].CompressedSize;\n                    }\n                }\n'''
    text = _replace_once(path, text, old_runs, new_runs, "periodic encoded-file RUN schedule")
    path.write_text(text, encoding="utf-8", newline="\n")


def apply(root: Path) -> None:
    root = Path(root)
    paths = [root / p for p in (IMAGE_BUILDER_REL, ASSEMBLER_REL, NAPS_LAYOUT_REL, NAPS_GENERATOR_REL)]
    for path in paths:
        if not path.is_file():
            raise RuntimeError(f"Missing reconstructed LibProsperoPKG source for NAPS block-map profile: {path}")

    _patch_image_builder(root / IMAGE_BUILDER_REL)
    _patch_assembler(root / ASSEMBLER_REL)
    _patch_naps_layout(root / NAPS_LAYOUT_REL)
    _patch_naps_generator(root / NAPS_GENERATOR_REL)
    print("Applied Packizard per-data-block Kraken/NAPS geometry profile")
