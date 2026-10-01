// Packizard Builder - native NAPS DATA stream geometry.
// This implementation is Packizard-owned.  It deliberately separates filesystem boundaries from
// NAPS compression-block boundaries so a tree containing thousands of tiny files does not manufacture
// thousands of CblockInfo records inside one logical U-block window.
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

    /// <summary>
    /// Signed modules and other payloads that must stay byte-for-byte raw.  A raw source is a deliberate
    /// codec barrier; ordinary file boundaries are not.
    /// </summary>
    public bool ForceRaw { get; init; }

    /// <summary>Keystone-style raw source which also preserves the historical 64 KiB physical fence.</summary>
    public bool WholeBlockRaw { get; init; }

    public uint OwnerFlag { get; init; }
}

/// <summary>
/// Exact physical/logical geometry of one Packizard DATA coding block.  Ordinary files are allowed to
/// share a block; only codec barriers (raw/module payloads) split the canonical stream early.
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
    int BlockIndex,
    int FirstFileIndex,
    int LastFileIndex,
    bool ContainsFileBoundary);

public sealed class PackizardNativeDataStreamResult
{
    public required string EncodedPath { get; init; }
    public required long EncodedLength { get; init; }
    public required long LogicalLength { get; init; }
    public required IReadOnlyList<PackizardInnerDataBlock> Blocks { get; init; }
}

/// <summary>
/// Builds the physical DATA stream from the logical concatenation of all files.
///
/// Normal files are coalesced into canonical blocks of at most 256 KiB even when a block crosses many
/// file boundaries.  This makes CblockInfo density a function of logical DATA size rather than file count.
/// Raw/module files remain explicit codec barriers so their bytes and known alignment semantics are not
/// changed.  A raw barrier can therefore create a short block, but a normal file boundary never does.
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

        long logicalLength = ValidateSources(sources);
        long estimatedBlocks = logicalLength == 0
            ? 0
            : checked((logicalLength + UBlockSize - 1) / UBlockSize + sources.Count);
        if (estimatedBlocks > int.MaxValue)
            throw new NotSupportedException(
                $"Packizard DATA could require {estimatedBlocks:N0} coding blocks; the in-memory map cannot index that many.");

        var blocks = new List<PackizardInnerDataBlock>((int)Math.Min(estimatedBlocks, 1_000_000));
        long physical = 0;
        long emittedLogical = 0;

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

        void EmitBlock(
            ReadOnlySpan<byte> plain,
            long logicalOffset,
            bool forceRaw,
            uint ownerFlag,
            int firstFileIndex,
            int lastFileIndex,
            bool containsFileBoundary)
        {
            if (plain.Length <= 0 || plain.Length > UBlockSize)
                throw new InvalidOperationException(
                    $"Packizard DATA attempted to emit an invalid block of {plain.Length:N0} bytes.");
            if (logicalOffset != emittedLogical)
                throw new InvalidOperationException(
                    $"Packizard DATA logical discontinuity before block {blocks.Count}: " +
                    $"expected 0x{emittedLogical:X}, got 0x{logicalOffset:X}.");

            byte[] encoded;
            bool stored;
            bool multi;
            int firstChunk;
            if (forceRaw)
            {
                encoded = plain.ToArray();
                stored = true;
                multi = false;
                firstChunk = Math.Min(plain.Length, 0x20000);
            }
            else
            {
                byte[] raw = plain.ToArray();
                encoded = ProsperoPs5InnerImageBuilder.CompressPayload(raw, storeRaw: false, out var pf);
                if (pf is null || pf.Blocks.Count != 1)
                    throw new InvalidDataException(
                        $"Packizard expected exactly one PFSC block for canonical DATA block {blocks.Count}.");
                PfsBlock b = pf.Blocks[0];
                if (b.UncompressedSize != raw.Length || b.CompressedSize != encoded.Length)
                    throw new InvalidDataException(
                        $"Kraken geometry mismatch for canonical DATA block {blocks.Count}: " +
                        $"plain={b.UncompressedSize:N0}/{raw.Length:N0}, " +
                        $"encoded={b.CompressedSize:N0}/{encoded.Length:N0}.");
                stored = b.IsStored;
                multi = b.IsMultiChunk;
                firstChunk = b.FirstChunkCompressedSize;
            }

            long onDisk = physical;
            output.Write(encoded);
            physical = checked(physical + encoded.Length);
            blocks.Add(new PackizardInnerDataBlock(
                LogicalOffset: logicalOffset,
                UncompressedSize: plain.Length,
                OnDiskOffset: onDisk,
                CompressedSize: encoded.Length,
                IsStored: stored,
                IsMultiChunk: multi,
                FirstChunkCompressedSize: firstChunk,
                ForceRaw: forceRaw,
                OwnerFlag: ownerFlag,
                BlockIndex: blocks.Count,
                FirstFileIndex: firstFileIndex,
                LastFileIndex: lastFileIndex,
                ContainsFileBoundary: containsFileBoundary));
            emittedLogical = checked(emittedLogical + plain.Length);
        }

        var pending = new byte[UBlockSize];
        int pendingCount = 0;
        long pendingLogical = 0;
        int pendingFirstFile = -1;
        int pendingLastFile = -1;
        uint pendingOwner = 0;
        bool pendingCrossesBoundary = false;

        void FlushPending()
        {
            if (pendingCount == 0) return;
            EmitBlock(
                pending.AsSpan(0, pendingCount),
                pendingLogical,
                forceRaw: false,
                pendingOwner,
                pendingFirstFile,
                pendingLastFile,
                pendingCrossesBoundary);
            pendingCount = 0;
            pendingFirstFile = -1;
            pendingLastFile = -1;
            pendingCrossesBoundary = false;
        }

        for (int fileIndex = 0; fileIndex < sources.Count; fileIndex++)
        {
            PackizardLogicalDataSource source = sources[fileIndex];
            if (source.Length == 0)
                continue;

            using Stream input = OpenSource(source);

            if (source.ForceRaw)
            {
                // A raw source is an intentional codec barrier.  Flush any ordinary bytes accumulated
                // before it, then preserve the legacy physical alignment rule at the barrier itself.
                FlushPending();
                if (emittedLogical != source.LogicalOffset)
                    throw new InvalidOperationException(
                        $"Packizard raw barrier {source.Path} begins at 0x{source.LogicalOffset:X}, " +
                        $"but the emitted logical cursor is 0x{emittedLogical:X}.");

                long rem64 = physical % PhysicalBlockSize;
                bool alignBefore = source.WholeBlockRaw ||
                    (rem64 != 0 && source.Length > PhysicalBlockSize - rem64);
                if (alignBefore)
                    PadPhysicalTo(AlignUp(physical, PhysicalBlockSize));

                long left = source.Length;
                long local = 0;
                var rawBuffer = new byte[UBlockSize];
                while (left > 0)
                {
                    int take = checked((int)Math.Min(left, UBlockSize));
                    input.ReadExactly(rawBuffer.AsSpan(0, take));
                    EmitBlock(
                        rawBuffer.AsSpan(0, take),
                        checked(source.LogicalOffset + local),
                        forceRaw: true,
                        source.OwnerFlag,
                        fileIndex,
                        fileIndex,
                        containsFileBoundary: false);
                    local = checked(local + take);
                    left -= take;
                }

                if (source.WholeBlockRaw)
                    PadPhysicalTo(AlignUp(physical, PhysicalBlockSize));
                continue;
            }

            long remaining = source.Length;
            long sourceLocal = 0;
            while (remaining > 0)
            {
                if (pendingCount == 0)
                {
                    pendingLogical = checked(source.LogicalOffset + sourceLocal);
                    if (pendingLogical != emittedLogical)
                        throw new InvalidOperationException(
                            $"Packizard canonical block starts at 0x{pendingLogical:X}, " +
                            $"expected 0x{emittedLogical:X} before {source.Path}.");
                    pendingFirstFile = fileIndex;
                    pendingLastFile = fileIndex;
                    pendingOwner = source.OwnerFlag;
                    pendingCrossesBoundary = false;
                }
                else if (pendingLastFile != fileIndex)
                {
                    pendingLastFile = fileIndex;
                    pendingCrossesBoundary = true;
                }

                int take = checked((int)Math.Min(remaining, UBlockSize - pendingCount));
                input.ReadExactly(pending.AsSpan(pendingCount, take));
                pendingCount += take;
                sourceLocal = checked(sourceLocal + take);
                remaining -= take;

                if (pendingCount == UBlockSize)
                    FlushPending();
            }
        }

        FlushPending();
        output.Flush();

        if (emittedLogical != logicalLength)
            throw new InvalidOperationException(
                $"Packizard DATA logical length mismatch: emitted {emittedLogical:N0}, expected {logicalLength:N0}.");
        if (physical != output.Length)
            throw new InvalidOperationException(
                $"Packizard DATA stream length mismatch: planned {physical:N0}, wrote {output.Length:N0}.");

        ValidateBlockMap(blocks, logicalLength, physical);

        return new PackizardNativeDataStreamResult
        {
            EncodedPath = outputPath,
            EncodedLength = physical,
            LogicalLength = logicalLength,
            Blocks = blocks,
        };
    }

    private static long ValidateSources(IReadOnlyList<PackizardLogicalDataSource> sources)
    {
        long expected = 0;
        for (int i = 0; i < sources.Count; i++)
        {
            PackizardLogicalDataSource source = sources[i];
            if (source.LogicalOffset != expected)
                throw new InvalidOperationException(
                    $"Packizard DATA source map is not contiguous before {source.Path}: " +
                    $"expected 0x{expected:X}, got 0x{source.LogicalOffset:X}.");
            if (source.Length < 0)
                throw new InvalidOperationException($"Negative source length for {source.Path}.");
            if (source.DataPath is null && source.Data.LongLength != source.Length)
                throw new InvalidOperationException(
                    $"In-memory source length changed for {source.Path}: " +
                    $"{source.Data.LongLength:N0}/{source.Length:N0}.");
            if (source.DataPath is not null)
            {
                long actual = new FileInfo(source.DataPath).Length;
                if (actual != source.Length)
                    throw new IOException(
                        $"Source size changed for {source.Path}: {actual:N0}/{source.Length:N0}.");
            }
            expected = checked(expected + source.Length);
        }
        return expected;
    }

    private static Stream OpenSource(PackizardLogicalDataSource source) =>
        source.DataPath is not null
            ? new FileStream(source.DataPath, FileMode.Open, FileAccess.Read, FileShare.Read, 1024 * 1024, FileOptions.SequentialScan)
            : new MemoryStream(source.Data, writable: false);

    private static void ValidateBlockMap(
        IReadOnlyList<PackizardInnerDataBlock> blocks,
        long logicalLength,
        long encodedLength)
    {
        long logical = 0;
        long physicalEnd = 0;
        for (int i = 0; i < blocks.Count; i++)
        {
            PackizardInnerDataBlock b = blocks[i];
            if (b.BlockIndex != i)
                throw new InvalidOperationException(
                    $"Packizard DATA block index mismatch at {i}: {b.BlockIndex}.");
            if (b.LogicalOffset != logical)
                throw new InvalidOperationException(
                    $"Packizard DATA block {i} is not logically contiguous: " +
                    $"0x{b.LogicalOffset:X}/0x{logical:X}.");
            if (b.UncompressedSize <= 0 || b.UncompressedSize > UBlockSize)
                throw new InvalidOperationException(
                    $"Packizard DATA block {i} has invalid logical size {b.UncompressedSize:N0}.");
            if (b.OnDiskOffset < physicalEnd)
                throw new InvalidOperationException(
                    $"Packizard DATA block {i} overlaps the previous physical block.");
            if (b.CompressedSize <= 0)
                throw new InvalidOperationException(
                    $"Packizard DATA block {i} has invalid encoded size {b.CompressedSize:N0}.");
            logical = checked(logical + b.UncompressedSize);
            physicalEnd = checked(b.OnDiskOffset + b.CompressedSize);
        }
        if (logical != logicalLength)
            throw new InvalidOperationException(
                $"Packizard DATA block map covers {logical:N0}/{logicalLength:N0} logical bytes.");
        if (blocks.Count == 0)
        {
            if (logicalLength != 0 || encodedLength != 0)
                throw new InvalidOperationException("Empty Packizard DATA map has non-empty geometry.");
        }
        else if (physicalEnd > encodedLength)
        {
            throw new InvalidOperationException(
                $"Packizard DATA blocks extend past the encoded stream: {physicalEnd:N0}/{encodedLength:N0}.");
        }
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
                hi = mid - 1;
            else if (logicalOffset >= end)
                lo = mid + 1;
            else
                return b.OnDiskOffset;
        }

        if (logicalOffset == logicalLength)
        {
            PackizardInnerDataBlock last = blocks[^1];
            return checked(last.OnDiskOffset + last.CompressedSize);
        }

        if (lo < blocks.Count)
            return blocks[lo].OnDiskOffset;
        PackizardInnerDataBlock tail = blocks[^1];
        return checked(tail.OnDiskOffset + tail.CompressedSize);
    }
}
