// Packizard Builder - native NAPS data-stream geometry.
// This file is copied into LibProsperoPkg at build time, but the implementation is Packizard-owned.
#nullable enable
using LibProsperoPkg.PFS.Compression;
using System;
using System.Collections.Generic;
using System.IO;

namespace LibProsperoPkg.PFS;

/// <summary>One logical content file presented to Packizard's DATA encoder.</summary>
public sealed class PackizardLogicalDataSource
{
    public required string Path { get; init; }
    public required long LogicalOffset { get; init; }
    public required long Length { get; init; }
    public byte[] Data { get; init; } = Array.Empty<byte>();
    public string? DataPath { get; init; }
    public bool ForceRaw { get; init; }
    public bool WholeBlockRaw { get; init; }
    public uint OwnerFlag { get; init; }
}

/// <summary>
/// Exact physical/logical geometry of one file-local DATA block. A block never crosses a file
/// boundary. Partial final blocks retain their real logical size instead of absorbing bytes from the
/// following file.
/// </summary>
public readonly record struct PackizardInnerDataBlock(
    long LogicalOffset,
    int UncompressedSize,
    long OnDiskOffset,
    int CompressedSize,
    bool IsStored,
    bool IsMultiChunk,
    int FirstChunkCompressedSize,
    bool ForceRaw,
    uint OwnerFlag,
    int FileIndex,
    int BlockIndexInFile,
    bool FileStart);

public sealed class PackizardNativeDataStreamResult
{
    public required string EncodedPath { get; init; }
    public required long EncodedLength { get; init; }
    public required long LogicalLength { get; init; }
    public required IReadOnlyList<PackizardInnerDataBlock> Blocks { get; init; }
}

/// <summary>
/// Builds the physical DATA region while preserving file boundaries. Logical bytes are packed exactly
/// as the inode/fidx layer sees them; physical bytes may contain 64 KiB alignment gaps for raw/module
/// files. Compression remains 256 KiB block-local inside each file.
/// </summary>
public static class PackizardNativeDataStream
{
    public const int UBlockSize = 0x40000;
    public const int PhysicalBlockSize = 0x10000;

    public static PackizardNativeDataStreamResult Build(
        IReadOnlyList<PackizardLogicalDataSource> sources,
        string outputPath)
    {
        ArgumentNullException.ThrowIfNull(sources);
        ArgumentException.ThrowIfNullOrWhiteSpace(outputPath);

        string? directory = Path.GetDirectoryName(Path.GetFullPath(outputPath));
        if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);

        long expectedLogical = 0;
        long estimatedBlocks = 0;
        foreach (PackizardLogicalDataSource source in sources)
        {
            if (source.LogicalOffset != expectedLogical)
                throw new InvalidOperationException(
                    $"Packizard DATA stream is not contiguous before {source.Path}: expected logical " +
                    $"0x{expectedLogical:X}, got 0x{source.LogicalOffset:X}.");
            if (source.Length < 0)
                throw new InvalidOperationException($"Negative source length for {source.Path}.");
            if (source.DataPath is null && source.Data.LongLength != source.Length)
                throw new InvalidOperationException(
                    $"In-memory source length changed for {source.Path}: {source.Data.LongLength:N0}/{source.Length:N0}.");
            if (source.DataPath is not null)
            {
                long actual = new FileInfo(source.DataPath).Length;
                if (actual != source.Length)
                    throw new IOException(
                        $"Source size changed for {source.Path}: {actual:N0}/{source.Length:N0}.");
            }
            expectedLogical = checked(expectedLogical + source.Length);
            if (source.Length > 0)
                estimatedBlocks = checked(estimatedBlocks + (source.Length + UBlockSize - 1) / UBlockSize);
        }
        if (estimatedBlocks > int.MaxValue)
            throw new NotSupportedException(
                $"Packizard DATA requires {estimatedBlocks:N0} file-local blocks; the in-memory map cannot index that many.");

        var blocks = new List<PackizardInnerDataBlock>((int)estimatedBlocks);
        long physical = 0;

        using var output = new FileStream(
            outputPath,
            FileMode.Create,
            FileAccess.Write,
            FileShare.None,
            1024 * 1024,
            FileOptions.SequentialScan);

        static long AlignUp(long value, long alignment) =>
            checked((value + alignment - 1) & ~(alignment - 1));

        void PadPhysicalTo(long aligned)
        {
            if (aligned < physical)
                throw new InvalidOperationException("Packizard physical DATA cursor moved backwards.");
            long gap = aligned - physical;
            if (gap == 0) return;
            Span<byte> zero = stackalloc byte[4096];
            while (gap > 0)
            {
                int take = (int)Math.Min(gap, zero.Length);
                output.Write(zero[..take]);
                gap -= take;
            }
            physical = aligned;
        }

        for (int fileIndex = 0; fileIndex < sources.Count; fileIndex++)
        {
            PackizardLogicalDataSource source = sources[fileIndex];
            if (source.Length == 0)
                continue;

            // Reproduce the known data-first physical rule without making it control logical geometry:
            // keystone-like whole-block raw files align before+after; other raw modules move to the next
            // 64 KiB block only when they do not fit in the current block remainder.
            long physicalRemainder = physical % PhysicalBlockSize;
            bool alignBefore = source.WholeBlockRaw ||
                (source.ForceRaw && physicalRemainder != 0 &&
                 source.Length > PhysicalBlockSize - physicalRemainder);
            if (alignBefore)
                PadPhysicalTo(AlignUp(physical, PhysicalBlockSize));

            using Stream input = source.DataPath is not null
                ? File.OpenRead(source.DataPath)
                : new MemoryStream(source.Data, writable: false);

            long logicalInFile = 0;
            int blockIndex = 0;
            var plain = new byte[UBlockSize];
            while (logicalInFile < source.Length)
            {
                int plainSize = checked((int)Math.Min(UBlockSize, source.Length - logicalInFile));
                input.ReadExactly(plain.AsSpan(0, plainSize));

                byte[] encoded;
                bool stored;
                bool multi;
                int firstChunk;
                if (source.ForceRaw)
                {
                    encoded = plain.AsSpan(0, plainSize).ToArray();
                    stored = true;
                    multi = false;
                    firstChunk = Math.Min(plainSize, 0x20000);
                }
                else
                {
                    byte[] raw = plain.AsSpan(0, plainSize).ToArray();
                    encoded = ProsperoPs5InnerImageBuilder.CompressPayload(raw, storeRaw: false, out var pf);
                    if (pf is null || pf.Blocks.Count != 1)
                        throw new InvalidDataException(
                            $"Packizard expected one PFSC block for {source.Path} block {blockIndex}.");
                    PfsBlock block = pf.Blocks[0];
                    if (block.UncompressedSize != plainSize || block.CompressedSize != encoded.Length)
                        throw new InvalidDataException(
                            $"Kraken geometry mismatch for {source.Path} block {blockIndex}: " +
                            $"plain={block.UncompressedSize:N0}/{plainSize:N0}, " +
                            $"encoded={block.CompressedSize:N0}/{encoded.Length:N0}.");
                    stored = block.IsStored;
                    multi = block.IsMultiChunk;
                    firstChunk = block.FirstChunkCompressedSize;
                }

                long onDisk = physical;
                output.Write(encoded);
                physical = checked(physical + encoded.Length);
                blocks.Add(new PackizardInnerDataBlock(
                    LogicalOffset: checked(source.LogicalOffset + logicalInFile),
                    UncompressedSize: plainSize,
                    OnDiskOffset: onDisk,
                    CompressedSize: encoded.Length,
                    IsStored: stored,
                    IsMultiChunk: multi,
                    FirstChunkCompressedSize: firstChunk,
                    ForceRaw: source.ForceRaw,
                    OwnerFlag: source.OwnerFlag,
                    FileIndex: fileIndex,
                    BlockIndexInFile: blockIndex,
                    FileStart: blockIndex == 0));

                logicalInFile = checked(logicalInFile + plainSize);
                blockIndex++;
            }

            if (source.WholeBlockRaw)
                PadPhysicalTo(AlignUp(physical, PhysicalBlockSize));
        }

        output.Flush();
        if (physical != output.Length)
            throw new InvalidOperationException(
                $"Packizard DATA stream length mismatch: planned {physical:N0}, wrote {output.Length:N0}.");
        if (blocks.Count != estimatedBlocks)
            throw new InvalidOperationException(
                $"Packizard DATA block count mismatch: {blocks.Count:N0}/{estimatedBlocks:N0}.");

        return new PackizardNativeDataStreamResult
        {
            EncodedPath = outputPath,
            EncodedLength = physical,
            LogicalLength = expectedLogical,
            Blocks = blocks,
        };
    }

    public static long PhysicalAnchorForLogical(
        IReadOnlyList<PackizardInnerDataBlock> blocks,
        long logicalOffset,
        long logicalLength)
    {
        if (logicalOffset < 0 || logicalOffset > logicalLength)
            throw new ArgumentOutOfRangeException(nameof(logicalOffset));
        if (blocks.Count == 0) return 0;

        int lo = 0;
        int hi = blocks.Count - 1;
        while (lo <= hi)
        {
            int mid = lo + ((hi - lo) >> 1);
            PackizardInnerDataBlock b = blocks[mid];
            long end = checked(b.LogicalOffset + b.UncompressedSize);
            if (logicalOffset < b.LogicalOffset)
            {
                hi = mid - 1;
            }
            else if (logicalOffset >= end)
            {
                lo = mid + 1;
            }
            else
            {
                return b.OnDiskOffset;
            }
        }

        if (logicalOffset == logicalLength)
        {
            PackizardInnerDataBlock last = blocks[^1];
            return checked(last.OnDiskOffset + last.CompressedSize);
        }

        // Zero-length files can share a logical offset with the following non-empty file. If the binary
        // search did not land inside a block, anchor to the next block start when available.
        if (lo < blocks.Count)
            return blocks[lo].OnDiskOffset;
        PackizardInnerDataBlock tail = blocks[^1];
        return checked(tail.OnDiskOffset + tail.CompressedSize);
    }
}
