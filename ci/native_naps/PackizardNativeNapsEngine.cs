// Packizard Builder - native NAPS planner/generator.
//
// Packizard owns DATA-block topology, RUN scheduling, logical interval coverage, u2c budgeting and the
// final binary writer.  LibProsperoPkg model types are DTOs only; neither ProsperoNwonlyNapsGenerator,
// ProsperoNapsLayoutBuilder nor ProsperoNapsLayout.BuildLayout is called by this path.
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

/// <summary>Packizard-owned NAPS planner and generator.</summary>
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
        public long LogicalLength;
        public long EvenChunkCompressedLength;
        public long StreamLength;
        public byte Even;
        public byte Odd;
        public byte Kde;
        public byte Shuffle;
        public bool Terminator;
        public string Region = "data";

        public long LogicalEnd => checked(LogicalOffset + LogicalLength);
    }

    private readonly record struct EntryRef(
        int Index,
        long LogicalStart,
        long LogicalEnd,
        bool IsRun,
        bool Terminator,
        string Region);

    public static byte[] Generate(ProsperoPs5InnerImageResult result)
    {
        ArgumentNullException.ThrowIfNull(result);

        long mountSize = checked(result.Ndblock * Block64K);
        long metaBase = result.MetaBaseLogical;
        long dataEnd = result.DataEndLogical;
        IReadOnlyList<PackizardInnerDataBlock> data = result.DataBlocks;

        ValidateLogicalGeometry(data, dataEnd, metaBase, mountSize);

        var blocks = new List<Block>(data.Count + result.MetadataBlocks.Count + 8);
        BuildDataPlan(data, blocks);

        // One logical hole descriptor spans the fixed reserve between DATA and metadata.  It starts at the
        // true DATA end (not align-down), so it never overlaps a final partial DATA block.  u2c interval
        // coverage may map many U-blocks to this one descriptor without manufacturing CblockInfo density.
        if (dataEnd < metaBase)
        {
            blocks.Add(new Block
            {
                StartRun = false,
                OnDiskOffset = result.BlockInfoOnDiskOffset,
                LogicalOffset = dataEnd,
                LogicalLength = checked(metaBase - dataEnd),
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
                LogicalLength = m.UncompressedSize,
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

        if (metaLogical != mountSize)
            throw new InvalidOperationException(
                $"Packizard metadata logical coverage mismatch: end=0x{metaLogical:X}, mount=0x{mountSize:X}. " +
                "The metadata interval must terminate exactly at the mount boundary.");

        blocks.Add(new Block
        {
            StartRun = true,
            OnDiskOffset = metaPhysical,
            LogicalOffset = mountSize,
            LogicalLength = 0,
            Terminator = true,
            Region = "terminator",
        });

        ValidateIntervals(blocks, mountSize);

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

        return PackizardNativeNapsWriter.Serialize(doc);
    }

    private static void BuildDataPlan(
        IReadOnlyList<PackizardInnerDataBlock> data,
        List<Block> blocks)
    {
        long expectedLogical = 0;
        long previousPhysicalEnd = 0;
        bool? previousStored = null;
        int blocksSinceRun = 0;

        for (int i = 0; i < data.Count; i++)
        {
            PackizardInnerDataBlock d = data[i];
            if (d.BlockIndex != i)
                throw new InvalidOperationException(
                    $"Packizard DATA block index mismatch at {i}: {d.BlockIndex}.");
            if (d.UncompressedSize <= 0 || d.UncompressedSize > UBlock)
                throw new InvalidOperationException(
                    $"Packizard DATA block {i} has invalid logical size {d.UncompressedSize:N0}.");
            if (d.CompressedSize <= 0)
                throw new InvalidOperationException(
                    $"Packizard DATA block {i} has invalid encoded size {d.CompressedSize:N0}.");
            if (d.LogicalOffset != expectedLogical)
                throw new InvalidOperationException(
                    $"Packizard DATA logical map is not contiguous at block {i}: " +
                    $"expected 0x{expectedLogical:X}, got 0x{d.LogicalOffset:X}.");
            if (d.OnDiskOffset < previousPhysicalEnd)
                throw new InvalidOperationException(
                    $"Packizard DATA physical map overlaps/moves backwards at block {i}: " +
                    $"previousEnd=0x{previousPhysicalEnd:X}, next=0x{d.OnDiskOffset:X}.");

            bool physicalGap = i > 0 && d.OnDiskOffset != previousPhysicalEnd;
            bool storageTransition = i > 0 && previousStored.HasValue && previousStored.Value != d.IsStored;
            bool periodicReanchor = i > 0 && blocksSinceRun >= 11;
            bool startRun = i == 0 || physicalGap || storageTransition || periodicReanchor;
            if (startRun)
                blocksSinceRun = 0;

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

            string sourceRange = d.FirstFileIndex == d.LastFileIndex
                ? $"file={d.FirstFileIndex}"
                : $"files={d.FirstFileIndex}..{d.LastFileIndex}";
            blocks.Add(new Block
            {
                StartRun = startRun,
                OnDiskOffset = d.OnDiskOffset,
                LogicalOffset = d.LogicalOffset,
                LogicalLength = d.UncompressedSize,
                EvenChunkCompressedLength = evenLength,
                StreamLength = streamLength,
                Even = (byte)(storedFull ? 1 : 0),
                Odd = 1,
                Kde = (byte)(storedFull ? 4 : storedTail ? 0 : 2),
                Shuffle = 0,
                Region = d.ForceRaw
                    ? $"data/raw/{sourceRange}/block={i}"
                    : d.IsStored
                        ? $"data/stored/{sourceRange}/block={i}"
                        : $"data/kraken/{sourceRange}/block={i}",
            });

            expectedLogical = checked(expectedLogical + d.UncompressedSize);
            previousPhysicalEnd = checked(d.OnDiskOffset + d.CompressedSize);
            previousStored = d.IsStored;
            blocksSinceRun++;
        }
    }

    private static void ValidateLogicalGeometry(
        IReadOnlyList<PackizardInnerDataBlock> data,
        long dataEnd,
        long metaBase,
        long mountSize)
    {
        if (dataEnd < 0 || metaBase < 0 || mountSize <= 0)
            throw new InvalidOperationException(
                $"Packizard NAPS invalid logical geometry: dataEnd={dataEnd}, " +
                $"metaBase={metaBase}, mount={mountSize}.");
        if (metaBase < dataEnd)
            throw new InvalidOperationException(
                $"Packizard NAPS metadata overlaps DATA: metaBase=0x{metaBase:X}, dataEnd=0x{dataEnd:X}. " +
                "Compressed physical geometry must never drive logical mount geometry.");
        if (mountSize < metaBase)
            throw new InvalidOperationException(
                $"Packizard NAPS mount ends before metadata: mount=0x{mountSize:X}, metaBase=0x{metaBase:X}.");

        long covered = 0;
        foreach (PackizardInnerDataBlock b in data)
        {
            if (b.LogicalOffset != covered)
                throw new InvalidOperationException(
                    $"Packizard DATA interval gap/overlap at 0x{covered:X}: next block starts 0x{b.LogicalOffset:X}.");
            covered = checked(covered + b.UncompressedSize);
        }
        if (covered != dataEnd)
            throw new InvalidOperationException(
                $"Packizard DATA intervals cover 0x{covered:X}, but DataEndLogical is 0x{dataEnd:X}.");
    }

    private static void ValidateIntervals(IReadOnlyList<Block> blocks, long mountSize)
    {
        long expected = 0;
        bool sawTerminator = false;
        foreach (Block b in blocks)
        {
            if (b.Terminator)
            {
                if (sawTerminator)
                    throw new InvalidOperationException("Packizard NAPS contains multiple terminators.");
                if (b.LogicalOffset != mountSize)
                    throw new InvalidOperationException(
                        $"Packizard terminator is at 0x{b.LogicalOffset:X}, expected mount end 0x{mountSize:X}.");
                sawTerminator = true;
                continue;
            }
            if (sawTerminator)
                throw new InvalidOperationException("Packizard NAPS emitted data after the terminator.");
            if (b.LogicalLength <= 0)
                throw new InvalidOperationException(
                    $"Packizard NAPS region {b.Region} has non-positive logical length {b.LogicalLength}.");
            if (b.LogicalOffset != expected)
                throw new InvalidOperationException(
                    $"Packizard NAPS logical interval gap/overlap: expected 0x{expected:X}, " +
                    $"{b.Region} starts at 0x{b.LogicalOffset:X}.");
            expected = b.LogicalEnd;
        }
        if (!sawTerminator || expected != mountSize)
            throw new InvalidOperationException(
                $"Packizard NAPS logical intervals end at 0x{expected:X}, mount=0x{mountSize:X}, " +
                $"terminator={sawTerminator}.");
    }

    private static NapsLayoutDocument BuildDocument(
        IReadOnlyList<Block> blocks,
        int numUBlocks,
        int numOuterBlocks,
        IReadOnlyList<long> fileLogicalOffsets,
        out PackizardNapsBudgetReport budget)
    {
        (List<NapsCblockInfoEntry> entries, List<EntryRef> logical) = Walk(blocks);
        if (entries.Count > 0x1000001)
            throw new NotSupportedException(
                $"Packizard NAPS has {entries.Count:N0} CblockInfo entries; the header minus-two field cannot encode it.");

        int numGroups = (numUBlocks + 8) >> 3;
        List<NapsU2cEntry> u2c = BuildU2c(
            logical,
            numUBlocks,
            entries.Count,
            numGroups,
            out budget);

        if (fileLogicalOffsets.Count is < 1 or > 0x1000000)
            throw new NotSupportedException(
                $"Packizard NAPS has {fileLogicalOffsets.Count:N0} fidx-authored entries; NumFiles cannot encode it.");

        var counts = new NapsLayoutCounts(
            NumFiles: fileLogicalOffsets.Count,
            CompressionType: 2,
            NumKeys: 1,
            NumShufflePatterns: 0,
            NumUBlocks: numUBlocks,
            NumOuterBlocks: numOuterBlocks,
            NumCblockInfo: entries.Count);

        var offsets = new List<NapsFileOffsetEntry>(fileLogicalOffsets.Count + 1);
        long previous = 0;
        for (int i = 0; i < fileLogicalOffsets.Count; i++)
        {
            long value = fileLogicalOffsets[i];
            if (value < previous)
                throw new InvalidOperationException(
                    $"Packizard fidx moved backwards at {i}: 0x{value:X} < 0x{previous:X}.");
            if (value < 0 || value > 0xFFFFFFFFFFL)
                throw new NotSupportedException(
                    $"Packizard NAPS fidx offset 0x{value:X} exceeds the 40-bit field.");
            offsets.Add(new NapsFileOffsetEntry(
                i == fileLogicalOffsets.Count - 1 ? (byte)0x40 : (byte)0,
                checked((ulong)value)));
            previous = value;
        }
        offsets.Add(DecodeTrailer(DefaultTrailer));

        // Reuse a single immutable zero digest instance; the writer copies it for each outer block.  This
        // avoids millions of tiny allocations on very large packages.
        byte[] zeroDigest = new byte[8];
        byte[][] digests = Enumerable.Repeat(zeroDigest, numOuterBlocks).ToArray();

        return new NapsLayoutDocument
        {
            Counts = counts,
            Map = default,
            OuterBlockDigests = digests,
            ShufflePatterns = Array.Empty<byte[]>(),
            FileOffsets = offsets,
            CblockInfoOffsetByUblock = u2c,
            CblockInfos = entries,
        };
    }

    private static NapsFileOffsetEntry DecodeTrailer(ReadOnlySpan<byte> raw)
    {
        ulong offset = 0;
        for (int i = 0; i < 5; i++)
            offset |= (ulong)raw[i] << (8 * i);
        return new NapsFileOffsetEntry(raw[5], offset);
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
                    Raw = Array.Empty<byte>(),
                    IsRunBase = true,
                    CoffsetEndMod256K = coffEnd,
                    TweakIdxStart = checked((uint)tweakLong),
                    KeyTableIdx = 0,
                    CoffsetStart256K = checked((uint)c256),
                });
                refs.Add(new EntryRef(
                    runIndex,
                    b.LogicalOffset,
                    b.Terminator ? b.LogicalOffset : b.LogicalEnd,
                    IsRun: true,
                    b.Terminator,
                    b.Region));
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
                        $"Packizard NAPS block at 0x{b.LogicalOffset:X} ({b.Region}) has invalid even length " +
                        $"{b.EvenChunkCompressedLength}.");
                long rawClen = checked((b.EvenChunkCompressedLength - 1) * 2);
                clen = checked((uint)Math.Min(rawClen, ClenEvenCap));
            }

            int stdIndex = entries.Count;
            entries.Add(new NapsCblockInfoEntry
            {
                Raw = Array.Empty<byte>(),
                IsRunBase = false,
                CoffsetStartMod256K = coffMod,
                UoffsetStart = uoff,
                ClenEvenMinus1 = clen,
                Even = b.Terminator ? (byte)0 : b.Even,
                Odd = b.Terminator ? (byte)0 : b.Odd,
                KdePredictor = b.Terminator ? (byte)0 : b.Kde,
                ShuffleIdx = b.Terminator ? (byte)0 : b.Shuffle,
            });
            refs.Add(new EntryRef(
                stdIndex,
                b.LogicalOffset,
                b.Terminator ? b.LogicalOffset : b.LogicalEnd,
                IsRun: false,
                b.Terminator,
                b.Region));

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
        EntryRef[] std = refs.Where(x => !x.IsRun).ToArray();
        if (std.Length == 0)
            throw new InvalidOperationException("Packizard NAPS has no STD CblockInfo entries.");
        if (!std[^1].Terminator)
            throw new InvalidOperationException("Packizard NAPS final STD is not the terminator.");

        int terminator = std[^1].Index;
        int[] first = new int[numUBlocks];
        string[] region = new string[numUBlocks];
        int p = 0;
        long previousEnd = 0;
        for (int s = 0; s < std.Length - 1; s++)
        {
            EntryRef x = std[s];
            if (x.LogicalStart != previousEnd)
                throw new InvalidOperationException(
                    $"Packizard NAPS STD intervals are not contiguous before {x.Region}: " +
                    $"expected 0x{previousEnd:X}, got 0x{x.LogicalStart:X}.");
            if (x.LogicalEnd <= x.LogicalStart)
                throw new InvalidOperationException(
                    $"Packizard NAPS STD interval {x.Region} is empty/reversed.");
            previousEnd = x.LogicalEnd;
        }

        // u2c maps each logical U-block start to the STD interval that actually covers that byte.  This
        // is intentionally interval-based: a block may start before an U-block boundary, and one padding
        // STD may span many U-blocks.  "first STD whose start >= target" is not equivalent and caused the
        // 524/19945 discontinuities seen in real packages.
        for (int u = 0; u < numUBlocks; u++)
        {
            long target = checked((long)u * UBlock);
            while (p < std.Length - 1 && std[p].LogicalEnd <= target)
                p++;
            if (p >= std.Length - 1 ||
                std[p].LogicalStart > target || target >= std[p].LogicalEnd)
            {
                string near = p < std.Length ? std[p].Region : "<end>";
                throw new InvalidOperationException(
                    $"Packizard NAPS has no STD interval covering U-block {u} at 0x{target:X}; " +
                    $"nearest={near}.");
            }
            first[u] = std[p].Index;
            region[u] = std[p].Region;
        }

        var groups = new List<PackizardNapsBudgetGroup>(numGroups);
        int[] runPrefix = new int[numCblockInfo + 1];
        int[] stdPrefix = new int[numCblockInfo + 1];
        foreach (EntryRef r in refs)
        {
            if (r.Index < 0 || r.Index >= numCblockInfo) continue;
            if (r.IsRun) runPrefix[r.Index + 1]++;
            else stdPrefix[r.Index + 1]++;
        }
        for (int i = 1; i < runPrefix.Length; i++)
        {
            runPrefix[i] += runPrefix[i - 1];
            stdPrefix[i] += stdPrefix[i - 1];
        }

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
                if (first[u] < min) min = first[u];
                if (first[u] > max)
                {
                    max = first[u];
                    maxU = u;
                }
            }

            int lo = Math.Max(0, min);
            int hi = Math.Min(numCblockInfo - 1, max);
            int runCount = hi >= lo ? runPrefix[hi + 1] - runPrefix[lo] : 0;
            int stdCount = hi >= lo ? stdPrefix[hi + 1] - stdPrefix[lo] : 0;
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
                "This is a topology failure; Packizard will not clamp, wrap or modulo the delta.");

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
                if (u >= numUBlocks)
                {
                    deltas[j - 1] = 0;
                    continue;
                }
                int delta = first[u] - baseIndex;
                if (delta is < 0 or > 255)
                    throw new NotSupportedException(
                        $"Packizard NAPS u2c delta {delta} is not encodable " +
                        $"(group={g}, ublock={u}, base={baseIndex}, target={first[u]}). " +
                        "The planner must change; lossy serialization is forbidden.");
                deltas[j - 1] = (byte)delta;
            }
            result.Add(new NapsU2cEntry(checked((uint)baseIndex), deltas));
        }

        return result;
    }
}
