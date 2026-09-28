// Packizard Builder - native NAPS data-stream geometry.
// This file is copied into LibProsperoPkg at build time, but the implementation is Packizard-owned.
#nullable enable
using LibProsperoPkg.PFS.Compression;
using System;
using System.Collections.Generic;
using System.IO;

namespace LibProsperoPkg.PFS;

/// <summary>
/// One logical content file presented to Packizard's canonical DATA-stream encoder.
/// File boundaries remain metadata/fidx boundaries; they do not create compression blocks.
/// </summary>
public sealed class PackizardLogicalDataSource
{
    public required string Path { get; init; }
    public required long LogicalOffset { get; init; }
    public required long Length { get; init; }
    public byte[] Data { get; init; } = Array.Empty<byte>();
    public string? DataPath { get; init; }
    public bool ForceRaw { get; init; }
    public uint OwnerFlag { get; init; }
}

/// <summary>
/// Exact physical/logical geometry of one Packizard DATA U-block.  Every non-empty DATA region is
/// represented by one record per 256 KiB logical block, independently of the number of files that
/// intersect the block.
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
    uint OwnerFlag);

public sealed class PackizardNativeDataStreamResult
{
    public required string EncodedPath { get; init; }
    public required long EncodedLength { get; init; }
    public required long LogicalLength { get; init; }
    public required IReadOnlyList<PackizardInnerDataBlock> Blocks { get; init; }
}

/// <summary>
/// Builds the physical DATA region as a canonical logical stream.  The old implementation compressed
/// each file independently, which made CblockInfo density proportional to file count.  This encoder
/// instead concatenates the logical file bytes, splits that stream into 256 KiB U-blocks, and makes
/// exactly one Kraken/stored decision per U-block.
/// </summary>
public static class PackizardNativeDataStream
{
    public const int UBlockSize = 0x40000;

    public static PackizardNativeDataStreamResult Build(
        IReadOnlyList<PackizardLogicalDataSource> sources,
        string outputPath)
    {
        ArgumentNullException.ThrowIfNull(sources);
        ArgumentException.ThrowIfNullOrWhiteSpace(outputPath);

        string? directory = Path.GetDirectoryName(Path.GetFullPath(outputPath));
        if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);

        long expectedLogical = 0;
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
        }

        var blocks = new List<PackizardInnerDataBlock>(
            expectedLogical == 0 ? 0 : checked((int)Math.Min(int.MaxValue, (expectedLogical + UBlockSize - 1) / UBlockSize)));
        var plain = new byte[UBlockSize];
        int plainCount = 0;
        bool forceRaw = false;
        uint ownerFlag = 0;
        bool ownerAssigned = false;
        long logicalBlockStart = 0;
        long physical = 0;

        using var output = new FileStream(
            outputPath, FileMode.Create, FileAccess.Write, FileShare.None,
            1024 * 1024, FileOptions.SequentialScan);

        void FlushBlock(bool final)
        {
            if (plainCount == 0) return;

            // A partial final DATA block owns the zero-filled remainder up to the next U-block boundary.
            // This removes the old duplicate last-data/padding Cblock start and gives NAPS one canonical
            // owner for every DATA U-block.
            if (final && plainCount < UBlockSize)
                Array.Clear(plain, plainCount, UBlockSize - plainCount);

            byte[] encoded;
            bool stored;
            bool multi;
            int firstChunk;

            if (forceRaw)
            {
                encoded = plain.AsSpan(0, UBlockSize).ToArray();
                stored = true;
                multi = false;
                firstChunk = 0x20000;
            }
            else
            {
                byte[] raw = plain.AsSpan(0, UBlockSize).ToArray();
                encoded = ProsperoPs5InnerImageBuilder.CompressPayload(raw, storeRaw: false, out var pf);
                if (pf is null || pf.Blocks.Count != 1)
                    throw new InvalidDataException(
                        $"Packizard expected one PFSC block for DATA U-block at 0x{logicalBlockStart:X}.");
                PfsBlock block = pf.Blocks[0];
                if (block.UncompressedSize != UBlockSize || block.CompressedSize != encoded.Length)
                    throw new InvalidDataException(
                        $"Kraken geometry mismatch at DATA U-block 0x{logicalBlockStart:X}: " +
                        $"plain={block.UncompressedSize:N0}, encoded={block.CompressedSize:N0}/{encoded.Length:N0}.");
                stored = block.IsStored;
                multi = block.IsMultiChunk;
                firstChunk = block.FirstChunkCompressedSize;
            }

            output.Write(encoded);
            blocks.Add(new PackizardInnerDataBlock(
                LogicalOffset: logicalBlockStart,
                UncompressedSize: UBlockSize,
                OnDiskOffset: physical,
                CompressedSize: encoded.Length,
                IsStored: stored,
                IsMultiChunk: multi,
                FirstChunkCompressedSize: firstChunk,
                ForceRaw: forceRaw,
                OwnerFlag: ownerAssigned ? ownerFlag : 0));

            physical = checked(physical + encoded.Length);
            logicalBlockStart = checked(logicalBlockStart + UBlockSize);
            plainCount = 0;
            forceRaw = false;
            ownerFlag = 0;
            ownerAssigned = false;
        }

        foreach (PackizardLogicalDataSource source in sources)
        {
            if (source.Length == 0) continue;
            using Stream input = source.DataPath is not null
                ? File.OpenRead(source.DataPath)
                : new MemoryStream(source.Data, writable: false);

            long remaining = source.Length;
            while (remaining > 0)
            {
                int take = (int)Math.Min(remaining, UBlockSize - plainCount);
                input.ReadExactly(plain.AsSpan(plainCount, take));
                if (!ownerAssigned)
                {
                    ownerFlag = source.OwnerFlag;
                    ownerAssigned = true;
                }
                if (source.ForceRaw) forceRaw = true;
                plainCount += take;
                remaining -= take;
                if (plainCount == UBlockSize) FlushBlock(final: false);
            }
        }

        FlushBlock(final: true);
        output.Flush();

        if (physical != output.Length)
            throw new InvalidOperationException(
                $"Packizard DATA stream length mismatch: planned {physical:N0}, wrote {output.Length:N0}.");

        int expectedBlocks = expectedLogical == 0 ? 0 : checked((int)((expectedLogical + UBlockSize - 1) / UBlockSize));
        if (blocks.Count != expectedBlocks)
            throw new InvalidOperationException(
                $"Packizard DATA U-block count mismatch: {blocks.Count:N0}/{expectedBlocks:N0}.");

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
        if (blocks.Count == 0) return 0;
        if (logicalOffset < 0 || logicalOffset > logicalLength)
            throw new ArgumentOutOfRangeException(nameof(logicalOffset));
        long index = logicalOffset / UBlockSize;
        if (index >= blocks.Count) index = blocks.Count - 1;
        return blocks[checked((int)index)].OnDiskOffset;
    }
}
