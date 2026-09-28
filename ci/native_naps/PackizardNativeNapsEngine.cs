// Packizard Builder - native NAPS layout generator.
// All topology, budgeting and u2c generation here is Packizard-owned and does not call
// ProsperoNapsLayoutBuilder/ProsperoNwonlyNapsGenerator.
#nullable enable
using LibProsperoPkg.PFS;
using LibProsperoPkg.PFS.Compression;
using System;
using System.Collections.Generic;
using System.Linq;

namespace LibProsperoPkg.PKG;

public readonly record struct PackizardNapsBudgetGroup(
    int Group,
    int FirstUBlock,
    int LastUBlock,
    int BaseIndex,
    int MinIndex,
    int MaxIndex,
    int Span,
    int StdCount,
    int RunCount,
    string BaseRegion,
    string MaxRegion);

public sealed class PackizardNapsBudgetReport
{
    public required int NumUBlocks { get; init; }
    public required int NumCblockInfo { get; init; }
    public required IReadOnlyList<PackizardNapsBudgetGroup> Groups { get; init; }
    public int MaxSpan => Groups.Count == 0 ? 0 : Groups.Max(g => g.Span);
    public PackizardNapsBudgetGroup Worst => Groups.Count == 0 ? default : Groups.MaxBy(g => g.Span);
}

/// <summary>
/// Packizard-native NAPS planner/generator. File boundaries remain part of the format semantics,
/// while logical mount coordinates and compressed physical coordinates are kept strictly separate.
/// Every u2c group is budgeted before serialization; no delta is ever truncated or saturated.
/// </summary>
public static class PackizardNativeNapsEngine
{
    private const long Block64K = 0x10000;
    private const long UBlock = 0x40000;
    private const uint Mod256K = 0x3FFFF;
    private const uint ClenEvenCap = 0x1FFFE;
    private static readonly byte[] DefaultTrailer = { 0x01, 0x00, 0x00, 0x05, 0x06, 0x07 };

    private sealed class Block
    {
        public bool StartRun;
        public long OnDiskOffset;
        public long LogicalOffset;
        public long EvenChunkCompressedLength;
        public long StreamLength;
        public byte Even;
        public byte Odd;
        public byte Kde;
        public byte Shuffle;
        public bool Terminator;
        public string Region = "data";
    }

    private readonly record struct EntryRef(int Index, long Logical, bool IsRun, string Region);

    public static byte[] Generate(ProsperoPs5InnerImageResult result)
    {
        ArgumentNullException.ThrowIfNull(result);

        long mountSize = checked(result.Ndblock * Block64K);
        long metaBase = result.MetaBaseLogical;
        long dataEnd = result.DataEndLogical;
        IReadOnlyList<PackizardInnerDataBlock> data = result.DataBlocks;

        ValidateLogicalGeometry(dataEnd, metaBase, mountSize);

        var blocks = new List<Block>(data.Count + result.MetadataBlocks.Count + 8);
        long expectedLogical = 0;
        long previousPhysicalEnd = 0;
        bool? previousStored = null;
        int previousFile = -1;

        for (int i = 0; i < data.Count; i++)
        {
            PackizardInnerDataBlock d = data[i];
            if (d.UncompressedSize <= 0 || d.UncompressedSize > UBlock)
                throw new InvalidOperationException(
                    $"Packizard DATA block {i} has invalid logical size {d.UncompressedSize:N0}; " +
                    "file-local blocks must be in 1..256 KiB.");
            if (d.CompressedSize <= 0)
                throw new InvalidOperationException(
                    $"Packizard DATA block {i} has invalid encoded size {d.CompressedSize:N0}.");
            if (d.LogicalOffset != expectedLogical)
                throw new InvalidOperationException(
                    $"Packizard DATA logical map is not contiguous at block {i}: " +
                    $"expected 0x{expectedLogical:X}, got 0x{d.LogicalOffset:X} " +
                    $"(file={d.FileIndex}, block={d.BlockIndexInFile}).");
            if (d.OnDiskOffset < previousPhysicalEnd)
                throw new InvalidOperationException(
                    $"Packizard DATA physical map overlaps/moves backwards at block {i}: " +
                    $"previousEnd=0x{previousPhysicalEnd:X}, next=0x{d.OnDiskOffset:X} " +
                    $"(file={d.FileIndex}, block={d.BlockIndexInFile}).");
            if (d.FileStart != (d.BlockIndexInFile == 0))
                throw new InvalidOperationException(
                    $"Packizard DATA file-start marker disagrees with block index at block {i}.");
            if (!d.FileStart && d.FileIndex != previousFile)
                throw new InvalidOperationException(
                    $"Packizard DATA changed file without a file-start marker at block {i}: " +
                    $"{previousFile}->{d.FileIndex}.");

            bool physicalGap = d.OnDiskOffset != previousPhysicalEnd;
            bool storageTransition = !d.FileStart && previousStored.HasValue && previousStored.Value != d.IsStored;
            bool periodicReanchor = d.BlockIndexInFile > 0 && d.BlockIndexInFile % 11 == 0;
            bool startRun = d.FileStart || physicalGap || storageTransition || periodicReanchor;

            bool storedFull = d.IsStored && d.UncompressedSize == UBlock;
            bool storedTail = d.IsStored && !storedFull;
            long evenLength = storedFull
                ? 0x10000
                : storedTail
                    ? d.UncompressedSize
                    : d.IsMultiChunk
                        ? d.FirstChunkCompressedSize
                        : d.CompressedSize;
            long streamLength = storedFull
                ? 0x80000
                : storedTail
                    ? d.UncompressedSize
                    : d.CompressedSize;

            blocks.Add(new Block
            {
                StartRun = startRun,
                OnDiskOffset = d.OnDiskOffset,
                LogicalOffset = d.LogicalOffset,
                EvenChunkCompressedLength = evenLength,
                StreamLength = streamLength,
                Even = (byte)(storedFull ? 1 : 0),
                Odd = 1,
                Kde = (byte)(storedFull ? 4 : storedTail ? 0 : 2),
                Shuffle = 0,
                Region = d.ForceRaw
                    ? $"data/raw/file={d.FileIndex}/block={d.BlockIndexInFile}"
                    : d.IsStored
                        ? $"data/stored/file={d.FileIndex}/block={d.BlockIndexInFile}"
                        : $"data/kraken/file={d.FileIndex}/block={d.BlockIndexInFile}",
            });

            expectedLogical = checked(expectedLogical + d.UncompressedSize);
            previousPhysicalEnd = checked(d.OnDiskOffset + d.CompressedSize);
            previousStored = d.IsStored;
            previousFile = d.FileIndex;
        }

        if (expectedLogical != dataEnd)
            throw new InvalidOperationException(
                $"Packizard DATA logical coverage mismatch: blocks end at 0x{expectedLogical:X}, " +
                $"DataEndLogical=0x{dataEnd:X}.");
        if (data.Count == 0 && dataEnd != 0)
            throw new InvalidOperationException(
                $"Packizard DATA has no block map but DataEndLogical is 0x{dataEnd:X}.");

        // Preserve the currently reverse-validated padding topology: one bare STD anchored at the
        // block-info region and logically associated with the U-block containing dataEnd. Crucially,
        // metaBase itself is calculated from LOGICAL DATA size, never from compressed physical size.
        if (dataEnd < metaBase)
        {
            long paddingStart = dataEnd & ~(UBlock - 1);
            blocks.Add(new Block
            {
                StartRun = false,
                OnDiskOffset = result.BlockInfoOnDiskOffset,
                LogicalOffset = paddingStart,
                EvenChunkCompressedLength = 8,
                StreamLength = 0x10,
                Even = 0,
                Odd = 1,
                Kde = 4,
                Shuffle = 0,
                Region = "padding",
            });
        }

        IReadOnlyList<ProsperoInnerMetaBlockChunk> metaChunks = result.MetadataBlocks;
        if (metaChunks.Count == 0 && result.MetadataPlaintext.Length > 0)
        {
            var metaFile = ProsperoCompressedPfsFile.Parse(
                ProsperoCompressedPfsImage.Pack(result.MetadataPlaintext, 7, (int)UBlock));
            metaChunks = metaFile.Blocks.Select(b => new ProsperoInnerMetaBlockChunk(
                b.CompressedSize,
                b.UncompressedSize,
                b.IsMultiChunk,
                b.FirstChunkCompressedSize)).ToArray();
        }

        bool metaCompressed = result.CompressedMetadata.Length < result.MetadataPlaintext.Length;
        long metaPhysical = result.MetadataOnDiskOffset;
        long metaLogical = metaBase;
        for (int i = 0; i < metaChunks.Count; i++)
        {
            ProsperoInnerMetaBlockChunk m = metaChunks[i];
            if (m.CompressedSize <= 0 || m.UncompressedSize <= 0 || m.UncompressedSize > UBlock)
                throw new InvalidOperationException(
                    $"Packizard metadata block {i} has invalid geometry " +
                    $"encoded={m.CompressedSize:N0}, logical={m.UncompressedSize:N0}.");
            int even = m.IsMultiChunk ? m.FirstChunkCompressedSize : m.CompressedSize;
            blocks.Add(new Block
            {
                StartRun = i == 0,
                OnDiskOffset = metaPhysical,
                LogicalOffset = metaLogical,
                EvenChunkCompressedLength = metaCompressed ? even : m.UncompressedSize,
                StreamLength = m.CompressedSize,
                Even = 0,
                Odd = 1,
                Kde = (byte)(metaCompressed ? 2 : 4),
                Shuffle = (byte)(metaCompressed && i < metaChunks.Count - 1 ? 2 : 0),
                Region = $"metadata/block={i}",
            });
            metaPhysical = checked(metaPhysical + m.CompressedSize);
            metaLogical = checked(metaLogical + m.UncompressedSize);
        }

        if (metaLogical > mountSize)
            throw new InvalidOperationException(
                $"Packizard metadata extends beyond the logical mount: metaEnd=0x{metaLogical:X}, " +
                $"mount=0x{mountSize:X}.");

        blocks.Add(new Block
        {
            StartRun = true,
            OnDiskOffset = metaPhysical,
            LogicalOffset = mountSize,
            Terminator = true,
            Region = "terminator",
        });

        int numUBlocks = checked((int)((mountSize + UBlock - 1) / UBlock));
        if (numUBlocks > 0xFFFFFF)
            throw new NotSupportedException(
                $"Packizard NAPS has {numUBlocks:N0} U-blocks; the header only carries 24 bits.");
        int numOuterBlocks = checked((int)((result.ImageLength + Block64K - 1) / Block64K));
        if (numOuterBlocks > 0xFFFFFF)
            throw new NotSupportedException(
                $"Packizard NAPS has {numOuterBlocks:N0} outer blocks; the header only carries 24 bits.");

        var fidx = new List<long>(result.AfidLogicalOffsets.Count + 3);
        fidx.AddRange(result.AfidLogicalOffsets);
        fidx.Add(dataEnd);
        fidx.Add(metaBase);
        fidx.Add(mountSize);

        NapsLayoutDocument doc = BuildDocument(
            blocks,
            numUBlocks,
            numOuterBlocks,
            fidx,
            out PackizardNapsBudgetReport budget);

        if (budget.MaxSpan > 255)
        {
            PackizardNapsBudgetGroup w = budget.Worst;
            throw new NotSupportedException(
                $"Packizard NAPS budget violation before serialization: group={w.Group}, " +
                $"ublocks={w.FirstUBlock}..{w.LastUBlock}, base={w.BaseIndex}({w.BaseRegion}), " +
                $"min={w.MinIndex}, max={w.MaxIndex}({w.MaxRegion}), span={w.Span}, " +
                $"std={w.StdCount}, run={w.RunCount}, numUBlocks={budget.NumUBlocks}, " +
                $"numCblockInfo={budget.NumCblockInfo}.");
        }

        return ProsperoNapsLayout.BuildLayout(doc);
    }

    private static void ValidateLogicalGeometry(long dataEnd, long metaBase, long mountSize)
    {
        if (dataEnd < 0 || metaBase < 0 || mountSize <= 0)
            throw new InvalidOperationException(
                $"Packizard NAPS invalid logical geometry: dataEnd={dataEnd}, " +
                $"metaBase={metaBase}, mount={mountSize}.");
        if (metaBase < dataEnd)
            throw new InvalidOperationException(
                $"Packizard NAPS metadata overlaps DATA: metaBase=0x{metaBase:X}, dataEnd=0x{dataEnd:X}. " +
                "This is the compressed-physical-vs-logical-mount geometry bug; refusing to serialize.");
        if (mountSize < metaBase)
            throw new InvalidOperationException(
                $"Packizard NAPS mount ends before metadata: mount=0x{mountSize:X}, metaBase=0x{metaBase:X}.");
    }

    private static NapsLayoutDocument BuildDocument(
        IReadOnlyList<Block> blocks,
        int numUBlocks,
        int numOuterBlocks,
        IReadOnlyList<long> fileLogicalOffsets,
        out PackizardNapsBudgetReport budget)
    {
        (List<NapsCblockInfoEntry> entries, List<EntryRef> logical) = Walk(blocks);
        if (entries.Count > 0xFFFFFF)
            throw new NotSupportedException(
                $"Packizard NAPS has {entries.Count:N0} CblockInfo entries; " +
                "the header/base index fields only carry 24 bits.");

        // Keep the currently modeled NAPS table count: floor(numUBlocks/8)+1. This yields one trailing
        // entry for exact multiples of eight, and one partially-used final entry otherwise.
        int numGroups = (numUBlocks + 8) >> 3;
        List<NapsU2cEntry> u2c = BuildU2c(
            logical,
            numUBlocks,
            entries.Count,
            numGroups,
            out budget);

        var counts = new NapsLayoutCounts(
            NumFiles: fileLogicalOffsets.Count,
            CompressionType: 2,
            NumKeys: 1,
            NumShufflePatterns: 0,
            NumUBlocks: numUBlocks,
            NumOuterBlocks: numOuterBlocks,
            NumCblockInfo: entries.Count);

        var offsets = new List<NapsFileOffsetEntry>(fileLogicalOffsets.Count + 1);
        for (int i = 0; i < fileLogicalOffsets.Count; i++)
        {
            long value = fileLogicalOffsets[i];
            if (value < 0 || value > 0xFFFFFFFFFFL)
                throw new NotSupportedException(
                    $"Packizard NAPS fidx offset 0x{value:X} exceeds the 40-bit field.");
            offsets.Add(new NapsFileOffsetEntry(
                i == fileLogicalOffsets.Count - 1 ? (byte)0x40 : (byte)0,
                checked((ulong)value)));
        }
        offsets.Add(ProsperoNapsLayout.DecodeFileOffsetEntry(DefaultTrailer));

        return new NapsLayoutDocument
        {
            Counts = counts,
            Map = ProsperoNapsLayout.SectionMap(counts),
            OuterBlockDigests = Enumerable.Range(0, numOuterBlocks)
                .Select(_ => new byte[ProsperoNapsLayout.OuterBlockDigestStride]).ToArray(),
            ShufflePatterns = Array.Empty<byte[]>(),
            FileOffsets = offsets,
            CblockInfoOffsetByUblock = u2c,
            CblockInfos = entries,
        };
    }

    private static (List<NapsCblockInfoEntry> Entries, List<EntryRef> Refs) Walk(
        IReadOnlyList<Block> blocks)
    {
        var entries = new List<NapsCblockInfoEntry>(blocks.Count * 2);
        var refs = new List<EntryRef>(blocks.Count * 2);
        long cursor = 0;

        foreach (Block b in blocks)
        {
            if (b.StartRun)
            {
                if (b.OnDiskOffset < 0)
                    throw new InvalidOperationException(
                        $"Negative NAPS RUN physical offset at {b.Region}.");

                uint coffEnd = checked((uint)(cursor & Mod256K));
                long q = b.OnDiskOffset / UBlock;
                long c256 = checked(2 * q);
                if (c256 > 0xFFFFFF)
                    throw new NotSupportedException(
                        $"Packizard NAPS RUN CoffsetStart256K 0x{c256:X} exceeds 24 bits at {b.Region}.");
                long tweakLong = b.Terminator ? 0 : b.OnDiskOffset >> 15;
                if (tweakLong > 0x0FFFFFFF)
                    throw new NotSupportedException(
                        $"Packizard NAPS tweak index 0x{tweakLong:X} exceeds 28 bits at {b.Region}.");

                long baseC = checked(2 * q * UBlock);
                long rem = b.OnDiskOffset % UBlock;
                cursor = checked(baseC + rem);

                int runIndex = entries.Count;
                entries.Add(new NapsCblockInfoEntry
                {
                    Raw = new byte[ProsperoNapsLayout.CblockInfoStride],
                    IsRunBase = true,
                    CoffsetEndMod256K = coffEnd,
                    TweakIdxStart = checked((uint)tweakLong),
                    KeyTableIdx = 0,
                    CoffsetStart256K = checked((uint)c256),
                });
                refs.Add(new EntryRef(runIndex, b.LogicalOffset, true, b.Region));
            }

            uint coffMod = checked((uint)(cursor & Mod256K));
            uint uoff = b.Terminator
                ? 1u
                : checked((uint)(((b.LogicalOffset & Mod256K) * 2) & Mod256K));
            uint clen;
            if (b.Terminator)
            {
                clen = 1;
            }
            else
            {
                if (b.EvenChunkCompressedLength <= 0)
                    throw new InvalidOperationException(
                        $"Packizard NAPS block at 0x{b.LogicalOffset:X} ({b.Region}) has invalid " +
                        $"even length {b.EvenChunkCompressedLength}.");
                long rawClen = checked((b.EvenChunkCompressedLength - 1) * 2);
                clen = checked((uint)Math.Min(rawClen, ClenEvenCap));
            }

            int stdIndex = entries.Count;
            entries.Add(new NapsCblockInfoEntry
            {
                Raw = new byte[ProsperoNapsLayout.CblockInfoStride],
                IsRunBase = false,
                CoffsetStartMod256K = coffMod,
                UoffsetStart = uoff,
                ClenEvenMinus1 = clen,
                Even = b.Terminator ? (byte)0 : b.Even,
                Odd = b.Terminator ? (byte)0 : b.Odd,
                KdePredictor = b.Terminator ? (byte)0 : b.Kde,
                ShuffleIdx = b.Terminator ? (byte)0 : b.Shuffle,
            });
            refs.Add(new EntryRef(stdIndex, b.LogicalOffset, false, b.Region));

            if (!b.Terminator)
                cursor = checked(cursor + b.StreamLength);
        }

        return (entries, refs);
    }

    private static List<NapsU2cEntry> BuildU2c(
        List<EntryRef> refs,
        int numUBlocks,
        int numCblockInfo,
        int numGroups,
        out PackizardNapsBudgetReport report)
    {
        // I[u] = index of the first STD whose logical start is >= u*256KiB. RUN records share the
        // CblockInfo index space but are never selected directly by u2c.
        EntryRef[] std = refs
            .Where(x => !x.IsRun)
            .OrderBy(x => x.Logical)
            .ThenBy(x => x.Index)
            .ToArray();
        if (std.Length == 0)
            throw new InvalidOperationException("Packizard NAPS has no STD CblockInfo entries.");

        int terminator = numCblockInfo - 1;
        int[] first = new int[numUBlocks];
        string[] region = new string[numUBlocks];
        int p = 0;
        for (int u = 0; u < numUBlocks; u++)
        {
            long target = checked((long)u * UBlock);
            while (p < std.Length && std[p].Logical < target)
                p++;
            if (p < std.Length)
            {
                first[u] = std[p].Index;
                region[u] = std[p].Region;
            }
            else
            {
                first[u] = terminator;
                region[u] = "terminator";
            }
        }

        var groups = new List<PackizardNapsBudgetGroup>(numGroups);
        for (int g = 0; g < numGroups; g++)
        {
            int firstU = checked(8 * g);
            if (firstU >= numUBlocks)
            {
                groups.Add(new PackizardNapsBudgetGroup(
                    g, firstU, firstU - 1,
                    terminator, terminator, terminator, 0, 0, 0,
                    "terminator", "terminator"));
                continue;
            }

            int lastU = Math.Min(numUBlocks - 1, firstU + 7);
            int baseIndex = first[firstU];
            int min = baseIndex;
            int max = baseIndex;
            int maxU = firstU;
            for (int u = firstU; u <= lastU; u++)
            {
                if (first[u] < min)
                    min = first[u];
                if (first[u] > max)
                {
                    max = first[u];
                    maxU = u;
                }
            }

            int runCount = refs.Count(x => x.IsRun && x.Index >= min && x.Index <= max);
            int stdCount = refs.Count(x => !x.IsRun && x.Index >= min && x.Index <= max);
            groups.Add(new PackizardNapsBudgetGroup(
                g, firstU, lastU,
                baseIndex, min, max, max - baseIndex,
                stdCount, runCount,
                region[firstU], region[maxU]));
        }

        report = new PackizardNapsBudgetReport
        {
            NumUBlocks = numUBlocks,
            NumCblockInfo = numCblockInfo,
            Groups = groups,
        };

        PackizardNapsBudgetGroup bad = groups.FirstOrDefault(
            x => x.Span > 255 || x.MinIndex < x.BaseIndex);
        if (bad.Span > 255 || bad.MinIndex < bad.BaseIndex)
            throw new NotSupportedException(
                $"Packizard NAPS u2c group overflow/non-monotonicity: group={bad.Group}, " +
                $"ublocks={bad.FirstUBlock}..{bad.LastUBlock}, " +
                $"base={bad.BaseIndex}({bad.BaseRegion}), min={bad.MinIndex}, " +
                $"max={bad.MaxIndex}({bad.MaxRegion}), span={bad.Span}, " +
                $"std={bad.StdCount}, run={bad.RunCount}, numCblockInfo={numCblockInfo}. " +
                "This is a topology failure; Packizard will not clamp or modulo the delta.");

        static byte DeltaByte(int value, int group, int ublock)
        {
            if (value is >= 0 and <= 255)
                return (byte)value;
            throw new NotSupportedException(
                $"Packizard NAPS u2c delta {value} is not encodable " +
                $"(group={group}, ublock={ublock}); refusing lossy serialization.");
        }

        var result = new List<NapsU2cEntry>(numGroups);
        for (int g = 0; g < numGroups; g++)
        {
            int groupStart = checked(8 * g);
            if (groupStart >= numUBlocks)
            {
                if (terminator > 0xFFFFFF)
                    throw new NotSupportedException(
                        $"Packizard NAPS u2c trailing base {terminator} exceeds 24 bits at group {g}.");
                result.Add(new NapsU2cEntry(checked((uint)terminator), new byte[7]));
                continue;
            }

            int baseIndex = first[groupStart];
            if (baseIndex is < 0 or > 0xFFFFFF)
                throw new NotSupportedException(
                    $"Packizard NAPS u2c base {baseIndex} exceeds 24 bits at group {g}.");

            var deltas = new byte[7];
            for (int j = 1; j < 8; j++)
            {
                int u = groupStart + j;
                deltas[j - 1] = u < numUBlocks
                    ? DeltaByte(first[u] - baseIndex, g, u)
                    : (byte)0;
            }
            result.Add(new NapsU2cEntry(checked((uint)baseIndex), deltas));
        }

        return result;
    }
}
