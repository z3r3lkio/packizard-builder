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
    int RunCount);

public sealed class PackizardNapsBudgetReport
{
    public required int NumUBlocks { get; init; }
    public required int NumCblockInfo { get; init; }
    public required IReadOnlyList<PackizardNapsBudgetGroup> Groups { get; init; }
    public int MaxSpan => Groups.Count == 0 ? 0 : Groups.Max(g => g.Span);
    public PackizardNapsBudgetGroup Worst => Groups.Count == 0 ? default : Groups.MaxBy(g => g.Span);
}

/// <summary>
/// Packizard-native NAPS generator. Its principal invariant is that DATA CblockInfo topology is
/// proportional to logical 256 KiB U-blocks, never to file count. The engine validates every field
/// width and every u2c group before it serializes a byte.
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

    public static byte[] Generate(ProsperoPs5InnerImageResult result)
    {
        ArgumentNullException.ThrowIfNull(result);
        long mountSize = checked(result.Ndblock * Block64K);
        long metaBase = result.MetaBaseLogical;
        long dataEnd = result.DataEndLogical;
        IReadOnlyList<PackizardInnerDataBlock> data = result.DataBlocks;

        if (dataEnd < 0 || metaBase < 0 || mountSize <= 0)
            throw new InvalidOperationException(
                $"Packizard NAPS invalid logical geometry: dataEnd={dataEnd}, metaBase={metaBase}, mount={mountSize}.");
        if (metaBase < dataEnd)
            throw new InvalidOperationException(
                $"Packizard NAPS metadata overlaps DATA: metaBase=0x{metaBase:X}, dataEnd=0x{dataEnd:X}. " +
                "Logical mount geometry must never be derived from compressed physical DATA size.");
        if (mountSize < metaBase)
            throw new InvalidOperationException(
                $"Packizard NAPS mount ends before metadata: mount=0x{mountSize:X}, metaBase=0x{metaBase:X}.");

        int expectedDataBlocks = dataEnd == 0
            ? 0
            : checked((int)((dataEnd + UBlock - 1) / UBlock));
        if (data.Count != expectedDataBlocks)
            throw new InvalidOperationException(
                $"Packizard NAPS DATA map count mismatch: {data.Count:N0}/{expectedDataBlocks:N0} " +
                $"for logical data length {dataEnd:N0}.");

        var blocks = new List<Block>(data.Count + result.MetadataBlocks.Count + 8);
        long expectedLogical = 0;
        long expectedPhysical = 0;
        bool? previousStored = null;
        for (int i = 0; i < data.Count; i++)
        {
            PackizardInnerDataBlock d = data[i];
            if (d.LogicalOffset != expectedLogical)
                throw new InvalidOperationException(
                    $"Packizard NAPS non-contiguous DATA logical map at block {i}: " +
                    $"0x{d.LogicalOffset:X}/0x{expectedLogical:X}.");
            if (d.OnDiskOffset != expectedPhysical)
                throw new InvalidOperationException(
                    $"Packizard NAPS non-contiguous DATA physical map at block {i}: " +
                    $"0x{d.OnDiskOffset:X}/0x{expectedPhysical:X}.");
            if (d.UncompressedSize != UBlock)
                throw new InvalidOperationException(
                    $"Packizard DATA block {i} covers {d.UncompressedSize:N0} bytes; canonical blocks must cover 256 KiB.");
            if (d.CompressedSize <= 0)
                throw new InvalidOperationException($"Packizard DATA block {i} has an empty encoded span.");

            bool stored = d.IsStored;
            bool reanchor = i > 0 && (i % 11 == 0 || previousStored != stored);
            blocks.Add(new Block
            {
                StartRun = reanchor,
                OnDiskOffset = d.OnDiskOffset,
                LogicalOffset = d.LogicalOffset,
                EvenChunkCompressedLength = stored
                    ? 0x10000
                    : d.IsMultiChunk ? d.FirstChunkCompressedSize : d.CompressedSize,
                StreamLength = stored ? 0x80000 : d.CompressedSize,
                Even = (byte)(stored ? 1 : 0),
                Odd = 1,
                Kde = (byte)(stored ? 4 : 2),
                Shuffle = 0,
                Region = d.ForceRaw ? "data/raw-forced" : stored ? "data/stored" : "data/kraken",
            });

            expectedLogical = checked(expectedLogical + UBlock);
            expectedPhysical = checked(expectedPhysical + d.CompressedSize);
            previousStored = stored;
        }

        // The final DATA block is zero-padded by PackizardNativeDataStream, so the hole starts at the
        // next U-block instead of overlapping the last DATA Cblock at floor(dataEnd/UBlock).
        long dataCoverageEnd = checked((long)data.Count * UBlock);
        if (dataCoverageEnd > metaBase)
            throw new InvalidOperationException(
                $"Packizard DATA coverage 0x{dataCoverageEnd:X} overlaps metadata base 0x{metaBase:X}.");
        if (dataCoverageEnd < metaBase)
        {
            blocks.Add(new Block
            {
                StartRun = false,
                OnDiskOffset = result.BlockInfoOnDiskOffset,
                LogicalOffset = dataCoverageEnd,
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
                Region = "metadata",
            });
            metaPhysical = checked(metaPhysical + m.CompressedSize);
            metaLogical = checked(metaLogical + m.UncompressedSize);
        }

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
                $"ublocks={w.FirstUBlock}..{w.LastUBlock}, base={w.BaseIndex}, min={w.MinIndex}, " +
                $"max={w.MaxIndex}, span={w.Span}, std={w.StdCount}, run={w.RunCount}, " +
                $"numUBlocks={budget.NumUBlocks}, numCblockInfo={budget.NumCblockInfo}.");
        }
        return ProsperoNapsLayout.BuildLayout(doc);
    }

    private static NapsLayoutDocument BuildDocument(
        IReadOnlyList<Block> blocks,
        int numUBlocks,
        int numOuterBlocks,
        IReadOnlyList<long> fileLogicalOffsets,
        out PackizardNapsBudgetReport budget)
    {
        (List<NapsCblockInfoEntry> entries, List<(int Index, long Logical, bool IsRun)> logical) = Walk(blocks);
        if (entries.Count > 0xFFFFFF)
            throw new NotSupportedException(
                $"Packizard NAPS has {entries.Count:N0} CblockInfo entries; the header/base index fields only carry 24 bits.");

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
            if (fileLogicalOffsets[i] < 0 || fileLogicalOffsets[i] > 0xFFFFFFFFFFL)
                throw new NotSupportedException(
                    $"Packizard NAPS fidx offset 0x{fileLogicalOffsets[i]:X} exceeds the 40-bit field.");
            offsets.Add(new NapsFileOffsetEntry(
                i == fileLogicalOffsets.Count - 1 ? (byte)0x40 : (byte)0,
                checked((ulong)fileLogicalOffsets[i])));
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

    private static (List<NapsCblockInfoEntry>, List<(int Index, long Logical, bool IsRun)>) Walk(
        IReadOnlyList<Block> blocks)
    {
        var entries = new List<NapsCblockInfoEntry>(blocks.Count * 2);
        var logical = new List<(int, long, bool)>(blocks.Count * 2);
        long cursor = 0;
        long previousLogical = -1;

        foreach (Block b in blocks)
        {
            if (!b.Terminator && b.LogicalOffset < previousLogical)
                throw new InvalidOperationException(
                    $"Packizard NAPS block order moved backwards: 0x{b.LogicalOffset:X} after 0x{previousLogical:X} ({b.Region}).");
            if (!b.Terminator) previousLogical = b.LogicalOffset;

            if (b.StartRun)
            {
                if (b.OnDiskOffset < 0)
                    throw new InvalidOperationException("Negative NAPS RUN physical offset.");
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
                logical.Add((runIndex, b.LogicalOffset, true));
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
                        $"Packizard NAPS block at 0x{b.LogicalOffset:X} has invalid even length {b.EvenChunkCompressedLength}.");
                long rawClen = checked((b.EvenChunkCompressedLength - 1) * 2);
                if (rawClen > ClenEvenCap)
                    rawClen = ClenEvenCap;
                clen = checked((uint)rawClen);
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
            logical.Add((stdIndex, b.LogicalOffset, false));
            if (!b.Terminator) cursor = checked(cursor + b.StreamLength);
        }

        return (entries, logical);
    }

    private static List<NapsU2cEntry> BuildU2c(
        List<(int Index, long Logical, bool IsRun)> logical,
        int numUBlocks,
        int numCblockInfo,
        int numGroups,
        out PackizardNapsBudgetReport report)
    {
        // I[u] = the first STD CblockInfo whose logical start is at or beyond u*256KiB.
        // RUN records occupy the same CblockInfo index space, so their presence naturally increases
        // deltas, but a RUN is never itself selected as I[u].
        (int Index, long Logical)[] std = logical
            .Where(x => !x.IsRun)
            .Select(x => (x.Index, x.Logical))
            .OrderBy(x => x.Logical)
            .ThenBy(x => x.Index)
            .ToArray();
        if (std.Length == 0)
            throw new InvalidOperationException("Packizard NAPS has no STD CblockInfo entries.");

        int terminator = numCblockInfo - 1;
        int[] first = new int[numUBlocks];
        int p = 0;
        for (int u = 0; u < numUBlocks; u++)
        {
            long target = checked((long)u * UBlock);
            while (p < std.Length && std[p].Logical < target)
                p++;
            first[u] = p < std.Length ? std[p].Index : terminator;
        }

        var groups = new List<PackizardNapsBudgetGroup>(numGroups);
        for (int g = 0; g < numGroups; g++)
        {
            int firstU = checked(8 * g);
            if (firstU >= numUBlocks)
            {
                groups.Add(new PackizardNapsBudgetGroup(
                    g, firstU, firstU - 1, terminator, terminator, terminator, 0, 0, 0));
                continue;
            }

            int lastU = Math.Min(numUBlocks - 1, firstU + 7);
            int baseIndex = first[firstU];
            int min = baseIndex;
            int max = baseIndex;
            for (int u = firstU; u <= lastU; u++)
            {
                min = Math.Min(min, first[u]);
                max = Math.Max(max, first[u]);
            }
            int lo = min;
            int hi = max;
            int runCount = logical.Count(x => x.IsRun && x.Index >= lo && x.Index <= hi);
            int stdCount = logical.Count(x => !x.IsRun && x.Index >= lo && x.Index <= hi);
            groups.Add(new PackizardNapsBudgetGroup(
                g, firstU, lastU, baseIndex, min, max, max - baseIndex, stdCount, runCount));
        }

        report = new PackizardNapsBudgetReport
        {
            NumUBlocks = numUBlocks,
            NumCblockInfo = numCblockInfo,
            Groups = groups,
        };

        PackizardNapsBudgetGroup bad = groups.FirstOrDefault(x => x.Span > 255 || x.MinIndex < x.BaseIndex);
        if (bad.Span > 255 || bad.MinIndex < bad.BaseIndex)
            throw new NotSupportedException(
                $"Packizard NAPS u2c group overflow/non-monotonicity: group={bad.Group}, " +
                $"ublocks={bad.FirstUBlock}..{bad.LastUBlock}, base={bad.BaseIndex}, min={bad.MinIndex}, " +
                $"max={bad.MaxIndex}, span={bad.Span}, std={bad.StdCount}, run={bad.RunCount}, " +
                $"numCblockInfo={numCblockInfo}.");

        static byte DeltaByte(int value, int group, int ublock)
        {
            if (value is >= 0 and <= 255)
                return (byte)value;
            throw new NotSupportedException(
                $"Packizard NAPS u2c delta {value} is not encodable (group={group}, ublock={ublock}).");
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
                // Unused slots in a partial final group are zero. They do not describe a real U-block
                // and therefore must never be forced to point at a distant terminator.
                deltas[j - 1] = u < numUBlocks
                    ? DeltaByte(first[u] - baseIndex, g, u)
                    : (byte)0;
            }
            result.Add(new NapsU2cEntry(checked((uint)baseIndex), deltas));
        }

        return result;
    }
}
