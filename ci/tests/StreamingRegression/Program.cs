using LibProsperoPkg.PFS;
using LibProsperoPkg.PKG;

static void Check(bool condition, string message)
{
    if (!condition) throw new Exception(message);
}

static long AlignUp(long value, long alignment) => (value + alignment - 1) & ~(alignment - 1);

static void CheckBlocks(
    IReadOnlyList<PackizardInnerDataBlock> left,
    IReadOnlyList<PackizardInnerDataBlock> right)
{
    Check(left.Count == right.Count, "DATA block count differs");
    for (int i = 0; i < left.Count; i++)
        Check(left[i].Equals(right[i]), $"DATA block {i} differs");
}

static void VerifyCanonicalEncoding(
    string encodedPath,
    IReadOnlyList<PackizardInnerDataBlock> blocks,
    byte[] logical)
{
    byte[] encoded = File.ReadAllBytes(encodedPath);
    foreach (PackizardInnerDataBlock b in blocks)
    {
        Check(b.LogicalOffset >= 0 && b.LogicalOffset + b.UncompressedSize <= logical.LongLength,
            $"DATA block {b.BlockIndex} is outside logical stream");
        Check(b.OnDiskOffset >= 0 && b.OnDiskOffset + b.CompressedSize <= encoded.LongLength,
            $"DATA block {b.BlockIndex} is outside encoded stream");

        byte[] plain = logical.AsSpan((int)b.LogicalOffset, b.UncompressedSize).ToArray();
        byte[] expected = ProsperoPs5InnerImageBuilder.CompressPayload(plain, b.ForceRaw, out var pf);
        ReadOnlySpan<byte> actual = encoded.AsSpan((int)b.OnDiskOffset, b.CompressedSize);
        Check(expected.AsSpan().SequenceEqual(actual),
            $"DATA block {b.BlockIndex} differs from canonical encoder output");
        Check(expected.Length == b.CompressedSize,
            $"DATA block {b.BlockIndex} encoded-size mismatch");

        if (b.ForceRaw)
        {
            Check(pf is null && b.IsStored && b.CompressedSize == b.UncompressedSize,
                $"Raw DATA block {b.BlockIndex} is not verbatim");
            continue;
        }

        Check(pf is not null && pf.Blocks.Count == 1,
            $"DATA block {b.BlockIndex} did not produce exactly one PFSC block");
        var pb = pf!.Blocks[0];
        Check(pb.CompressedSize == b.CompressedSize, $"DATA block {b.BlockIndex} compressed size differs");
        Check(pb.UncompressedSize == b.UncompressedSize, $"DATA block {b.BlockIndex} logical size differs");
        Check(pb.IsStored == b.IsStored, $"DATA block {b.BlockIndex} stored/Kraken choice differs");
        Check(pb.IsMultiChunk == b.IsMultiChunk, $"DATA block {b.BlockIndex} multi-chunk choice differs");
        Check(pb.FirstChunkCompressedSize == b.FirstChunkCompressedSize,
            $"DATA block {b.BlockIndex} first-chunk size differs");
    }
}

static ProsperoPs5InnerImageResult Synthetic(
    IReadOnlyList<PackizardInnerDataBlock> data,
    long dataEnd,
    long encodedLength,
    IReadOnlyList<long>? afids = null)
{
    const long B64 = 0x10000;
    const long U = 0x40000;
    long metaBase = AlignUp(dataEnd, U) + 4 * U;
    long blockInfo = AlignUp(encodedLength, B64);
    long metaOnDisk = AlignUp(blockInfo + 32, B64);
    long mountSize = metaBase + U;
    return new ProsperoPs5InnerImageResult
    {
        Image = Array.Empty<byte>(),
        ImageFilePath = null,
        ImageLength = metaOnDisk + 0x1000,
        MetadataPlaintext = new byte[U],
        Nodes = Array.Empty<ProsperoPs5MetaNode>(),
        Ndblock = mountSize / B64,
        AfidLogicalOffsets = afids ?? new long[] { 0 },
        DataBlocks = data,
        BlockInfoOnDiskOffset = blockInfo,
        MetadataOnDiskOffset = metaOnDisk,
        CompressedMetadata = new byte[0x1000],
        MetadataBlocks = new[] { new ProsperoInnerMetaBlockChunk(0x1000, (int)U, false, 0x1000) },
        DataEndLogical = dataEnd,
        MetaBaseLogical = metaBase,
    };
}

static NapsLayoutDocument ValidateNativeNaps(byte[] naps)
{
    // Use Packizard's exact fidx contract rather than upstream's blob-length heuristic. The latter can
    // mistake 6/12 bytes of normal final alignment padding for additional six-byte fidx rows.
    NapsLayoutDocument parsed = PackizardNativeNapsReader.Parse(naps);
    PackizardNativeNapsValidator.ValidateDocument(parsed);
    foreach (NapsU2cEntry u in parsed.CblockInfoOffsetByUblock)
    {
        Check(u.DeltaFromBase.Length == 7, "u2c did not round-trip seven deltas");
        foreach (byte delta in u.DeltaFromBase)
            Check(u.InfoOffset9BBase + delta < parsed.CblockInfos.Count,
                "u2c points outside CblockInfo table");
    }
    return parsed;
}

static PackizardInnerDataBlock[] SyntheticBlocks(int count, int encodedSize = 0x100)
{
    var result = new PackizardInnerDataBlock[count];
    long physical = 0;
    for (int i = 0; i < count; i++)
    {
        result[i] = new PackizardInnerDataBlock(
            LogicalOffset: (long)i * 0x40000,
            UncompressedSize: 0x40000,
            OnDiskOffset: physical,
            CompressedSize: encodedSize,
            IsStored: false,
            IsMultiChunk: false,
            FirstChunkCompressedSize: encodedSize,
            ForceRaw: false,
            OwnerFlag: 1,
            BlockIndex: i,
            FirstFileIndex: 0,
            LastFileIndex: 0,
            ContainsFileBoundary: false);
        physical += encodedSize;
    }
    return result;
}

string scratch = Path.Combine(Path.GetTempPath(), $"packizard-native-naps-{Guid.NewGuid():N}");
Directory.CreateDirectory(scratch);
string? oldTmp = Environment.GetEnvironmentVariable("TMP");
string? oldTemp = Environment.GetEnvironmentVariable("TEMP");
string? oldTmpDir = Environment.GetEnvironmentVariable("TMPDIR");
Environment.SetEnvironmentVariable("TMP", scratch);
Environment.SetEnvironmentVariable("TEMP", scratch);
Environment.SetEnvironmentVariable("TMPDIR", scratch);

try
{
    // 1. Normal files are a logical byte stream, not compression-block boundaries.
    byte[] sample = new byte[0x90017];
    new Random(17).NextBytes(sample);
    Array.Clear(sample, 0x40000, 0x30000);
    int aLength = 0x21003;
    int bLength = sample.Length - aLength;
    var memorySources = new[]
    {
        new PackizardLogicalDataSource
        {
            Path = "/a.bin", LogicalOffset = 0, Length = aLength,
            Data = sample[..aLength], OwnerFlag = 0,
        },
        new PackizardLogicalDataSource
        {
            Path = "/b.bin", LogicalOffset = aLength, Length = bLength,
            Data = sample[aLength..], OwnerFlag = 1,
        },
    };
    string memoryEncoded = Path.Combine(scratch, "memory.data");
    var memoryData = PackizardNativeDataStream.Build(memorySources, memoryEncoded);

    string srcA = Path.Combine(scratch, "a.bin");
    string srcB = Path.Combine(scratch, "b.bin");
    File.WriteAllBytes(srcA, sample[..aLength]);
    File.WriteAllBytes(srcB, sample[aLength..]);
    var diskSources = new[]
    {
        new PackizardLogicalDataSource
        {
            Path = "/a.bin", LogicalOffset = 0, Length = aLength,
            DataPath = srcA, OwnerFlag = 0,
        },
        new PackizardLogicalDataSource
        {
            Path = "/b.bin", LogicalOffset = aLength, Length = bLength,
            DataPath = srcB, OwnerFlag = 1,
        },
    };
    string diskEncoded = Path.Combine(scratch, "disk.data");
    var diskData = PackizardNativeDataStream.Build(diskSources, diskEncoded);
    Check(File.ReadAllBytes(memoryEncoded).AsSpan().SequenceEqual(File.ReadAllBytes(diskEncoded)),
        "Native DATA differs for memory/file-backed sources");
    CheckBlocks(memoryData.Blocks, diskData.Blocks);
    int canonicalCount = (sample.Length + PackizardNativeDataStream.UBlockSize - 1)
        / PackizardNativeDataStream.UBlockSize;
    Check(memoryData.Blocks.Count == canonicalCount,
        $"File boundary created extra DATA blocks: {memoryData.Blocks.Count}/{canonicalCount}");
    Check(memoryData.Blocks.Any(b => b.ContainsFileBoundary && b.FirstFileIndex == 0 && b.LastFileIndex == 1),
        "No canonical block crossed a.bin/b.bin boundary");
    VerifyCanonicalEncoding(memoryEncoded, memoryData.Blocks, sample);
    Console.WriteLine("PASS cross-file canonical DATA memory/disk/encoder equivalence");

    // 2. Raw/signed-module payload is a codec barrier, not every normal file.
    byte[] n0 = Enumerable.Repeat((byte)0x11, 96 * 1024).ToArray();
    byte[] raw = Enumerable.Repeat((byte)0x42, 24 * 1024).ToArray();
    byte[] n1 = Enumerable.Repeat((byte)0x33, 96 * 1024).ToArray();
    byte[] barrierLogical = n0.Concat(raw).Concat(n1).ToArray();
    string barrierPath = Path.Combine(scratch, "barrier.data");
    var barrier = PackizardNativeDataStream.Build(new[]
    {
        new PackizardLogicalDataSource { Path="/n0", LogicalOffset=0, Length=n0.Length, Data=n0 },
        new PackizardLogicalDataSource { Path="/module", LogicalOffset=n0.Length, Length=raw.Length, Data=raw, ForceRaw=true },
        new PackizardLogicalDataSource { Path="/n1", LogicalOffset=n0.Length + raw.Length, Length=n1.Length, Data=n1 },
    }, barrierPath);
    Check(barrier.Blocks.Count == 3, $"Raw barrier topology unexpected: {barrier.Blocks.Count}");
    Check(barrier.Blocks[1].ForceRaw && barrier.Blocks[1].IsStored, "Raw barrier was not verbatim");
    VerifyCanonicalEncoding(barrierPath, barrier.Blocks, barrierLogical);
    Console.WriteLine("PASS raw/module codec barrier");

    // 3. Real assembler must be deterministic for memory and file-backed inputs.
    var inputs = new[]
    {
        new ProsperoPs5InnerFile { Path = "/a.bin", Data = sample[..aLength] },
        new ProsperoPs5InnerFile { Path = "/b.bin", Data = sample[aLength..] },
        new ProsperoPs5InnerFile { Path = "/empty.bin", Data = Array.Empty<byte>() },
    };
    var assembler = new ProsperoPs5InnerImageAssembler(0, 0);
    var assembledMemory = assembler.Build(inputs);
    var fileInputs = inputs.Select((file, i) =>
    {
        string path = Path.Combine(scratch, $"source-{i}");
        File.WriteAllBytes(path, file.Data);
        return new ProsperoPs5InnerFile { Path = file.Path, DataPath = path };
    }).ToArray();
    var assembledDisk = assembler.Build(fileInputs);
    Check(assembledDisk.ImageFilePath is not null && assembledDisk.Image.Length == 0,
        "Expected file-backed inner image");
    Check(assembledMemory.Image.AsSpan().SequenceEqual(File.ReadAllBytes(assembledDisk.ImageFilePath!)),
        "Inner image differs for memory/file-backed input");
    Check(assembledMemory.ImageLength == assembledDisk.ImageLength, "Inner image length differs");
    CheckBlocks(assembledMemory.DataBlocks, assembledDisk.DataBlocks);
    byte[] nMem = PackizardNativeNapsEngine.Generate(assembledMemory);
    byte[] nDisk = PackizardNativeNapsEngine.Generate(assembledDisk);
    Check(nMem.AsSpan().SequenceEqual(nDisk), "Native NAPS differs for memory/file-backed input");
    ValidateNativeNaps(nMem);
    File.Delete(assembledDisk.ImageFilePath!);
    Console.WriteLine("PASS native assembler/NAPS deterministic round trip");

    // 4. Exact hostile class behind the real delta=19945: 20k tiny files in ~1.2 MiB.
    const int tinyFileCount = 20000;
    const int tinySize = 64;
    var tinySources = new List<PackizardLogicalDataSource>(tinyFileCount);
    var tinyLogicalBytes = new byte[tinyFileCount * tinySize];
    long tinyLogical = 0;
    for (int i = 0; i < tinyFileCount; i++)
    {
        byte[] bytes = new byte[tinySize];
        bytes[0] = (byte)i;
        bytes[^1] = (byte)(i >> 8);
        Buffer.BlockCopy(bytes, 0, tinyLogicalBytes, i * tinySize, tinySize);
        tinySources.Add(new PackizardLogicalDataSource
        {
            Path = $"/tiny/{i:D5}.bin",
            LogicalOffset = tinyLogical,
            Length = tinySize,
            Data = bytes,
            OwnerFlag = i == 0 ? 0u : 1u,
        });
        tinyLogical += tinySize;
    }
    string tinyPath = Path.Combine(scratch, "tiny.data");
    var tiny = PackizardNativeDataStream.Build(tinySources, tinyPath);
    int expectedTinyBlocks = checked((int)((tinyLogical + 0x3FFFF) / 0x40000));
    Check(tiny.Blocks.Count == expectedTinyBlocks,
        $"Dense files created {tiny.Blocks.Count} DATA blocks, expected {expectedTinyBlocks}");
    Check(tiny.Blocks.All(b => b.ContainsFileBoundary), "Dense blocks did not record crossed boundaries");
    VerifyCanonicalEncoding(tinyPath, tiny.Blocks, tinyLogicalBytes);
    NapsLayoutDocument dense = ValidateNativeNaps(PackizardNativeNapsEngine.Generate(
        Synthetic(tiny.Blocks, tinyLogical, tiny.EncodedLength)));
    Check(dense.CblockInfos.Count < 64,
        $"20k-file topology still inflated CblockInfo to {dense.CblockInfos.Count}");
    Console.WriteLine($"PASS 20k tiny files -> {tiny.Blocks.Count} DATA blocks, {dense.CblockInfos.Count} CblockInfos");

    // 5. Exercise real uint24 u2c base values above 0xffff.
    const int wideCount = 65552;
    PackizardInnerDataBlock[] wide = SyntheticBlocks(wideCount);
    long widePhysical = (long)wideCount * 0x100;
    NapsLayoutDocument wideDoc = ValidateNativeNaps(PackizardNativeNapsEngine.Generate(
        Synthetic(wide, (long)wideCount * 0x40000, widePhysical)));
    Check(wideDoc.CblockInfoOffsetByUblock.Any(x => x.InfoOffset9BBase > 0xFFFF),
        "Did not exercise upper uint24 u2c base byte");
    Console.WriteLine("PASS uint24 u2c bases above 0xffff");

    // 6. Logical metadata placement is independent of compressed physical DATA size.
    byte[] compressible = new byte[24 * 0x40000];
    var geometry = assembler.Build(new[]
    {
        new ProsperoPs5InnerFile { Path = "/compressible.bin", Data = compressible },
    });
    Check(geometry.MetaBaseLogical >= geometry.DataEndLogical,
        $"Metadata overlaps logical DATA: 0x{geometry.MetaBaseLogical:X}/0x{geometry.DataEndLogical:X}");
    Check(geometry.ImageLength < geometry.MetaBaseLogical,
        "Fixture did not produce physical size below logical mount position");
    ValidateNativeNaps(PackizardNativeNapsEngine.Generate(geometry));
    if (geometry.ImageFilePath is not null) File.Delete(geometry.ImageFilePath);
    Console.WriteLine("PASS logical/physical geometry separation");

    // 7. Partial and exact-multiple-of-eight u2c terminal groups.
    foreach (int count in new[] { 7, 8, 9, 16 })
    {
        PackizardInnerDataBlock[] blocks = SyntheticBlocks(count);
        NapsLayoutDocument doc = ValidateNativeNaps(PackizardNativeNapsEngine.Generate(
            Synthetic(blocks, (long)count * 0x40000, (long)count * 0x100)));
        Check(doc.CblockInfoOffsetByUblock.Count == (doc.Counts.NumUBlocks + 8) >> 3,
            $"u2c group count mismatch for fixture {count}");
    }
    Console.WriteLine("PASS partial/exact-multiple-of-eight u2c tails");

    // 8. >2 GiB logical geometry without allocating a >2 GiB payload.
    const int bigLogicalBlocks = 9000;
    PackizardInnerDataBlock[] big = SyntheticBlocks(bigLogicalBlocks, encodedSize: 0x80);
    long bigLogical = (long)bigLogicalBlocks * 0x40000;
    Check(bigLogical > int.MaxValue, "64-bit geometry fixture is not >2 GiB");
    ValidateNativeNaps(PackizardNativeNapsEngine.Generate(
        Synthetic(big, bigLogical, (long)bigLogicalBlocks * 0x80)));
    Console.WriteLine("PASS >2 GiB logical native NAPS geometry");
}
catch (Exception error)
{
    Console.Error.WriteLine(error);
    Environment.ExitCode = 1;
}
finally
{
    Environment.SetEnvironmentVariable("TMP", oldTmp);
    Environment.SetEnvironmentVariable("TEMP", oldTemp);
    Environment.SetEnvironmentVariable("TMPDIR", oldTmpDir);
    if (Directory.Exists(scratch)) Directory.Delete(scratch, recursive: true);
}
