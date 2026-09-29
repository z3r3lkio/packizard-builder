using LibProsperoPkg.PFS;
using LibProsperoPkg.PKG;

static void Check(bool condition, string message)
{
    if (!condition) throw new Exception(message);
}

static long AlignUp(long value, long alignment) => (value + alignment - 1) & ~(alignment - 1);

static void CheckDataBlocksEquivalent(
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
        byte[] expected = ProsperoPs5InnerImageBuilder.CompressPayload(
            plain, b.ForceRaw, out var pf);
        ReadOnlySpan<byte> actual = encoded.AsSpan((int)b.OnDiskOffset, b.CompressedSize);
        Check(expected.AsSpan().SequenceEqual(actual),
            $"DATA block {b.BlockIndex} encoded bytes differ from canonical encoder output");
        Check(expected.Length == b.CompressedSize,
            $"DATA block {b.BlockIndex} encoded size mismatch");

        if (b.ForceRaw)
        {
            Check(pf is null, $"Raw DATA block {b.BlockIndex} unexpectedly produced PFSC geometry");
            Check(b.IsStored && b.CompressedSize == b.UncompressedSize,
                $"Raw DATA block {b.BlockIndex} is not verbatim");
            continue;
        }

        Check(pf is not null && pf.Blocks.Count == 1,
            $"Canonical DATA block {b.BlockIndex} did not produce exactly one PFSC block");
        var pb = pf!.Blocks[0];
        Check(pb.CompressedSize == b.CompressedSize,
            $"DATA block {b.BlockIndex} PFSC compressed size differs");
        Check(pb.UncompressedSize == b.UncompressedSize,
            $"DATA block {b.BlockIndex} PFSC logical size differs");
        Check(pb.IsStored == b.IsStored,
            $"DATA block {b.BlockIndex} stored/Kraken decision differs");
        Check(pb.IsMultiChunk == b.IsMultiChunk,
            $"DATA block {b.BlockIndex} multi-chunk decision differs");
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

static NapsLayoutDocument ValidateParsedNaps(byte[] naps)
{
    NapsLayoutDocument parsed = ProsperoNapsLayout.Parse(naps);
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

string scratch = Path.Combine(Path.GetTempPath(), $"packizard-regression-{Guid.NewGuid():N}");
Directory.CreateDirectory(scratch);
string? oldTmp = Environment.GetEnvironmentVariable("TMP");
string? oldTemp = Environment.GetEnvironmentVariable("TEMP");
string? oldTmpDir = Environment.GetEnvironmentVariable("TMPDIR");
Environment.SetEnvironmentVariable("TMP", scratch);
Environment.SetEnvironmentVariable("TEMP", scratch);
Environment.SetEnvironmentVariable("TMPDIR", scratch);
try
{
    // Ordinary files share canonical DATA blocks. Cblock density follows logical bytes, not object count.
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
    string memoryEncoded = Path.Combine(scratch, "native-memory.data");
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
    string diskEncoded = Path.Combine(scratch, "native-disk.data");
    var diskData = PackizardNativeDataStream.Build(diskSources, diskEncoded);
    Check(File.ReadAllBytes(memoryEncoded).AsSpan().SequenceEqual(File.ReadAllBytes(diskEncoded)),
        "Native DATA differs between memory and disk sources");
    CheckDataBlocksEquivalent(memoryData.Blocks, diskData.Blocks);
    int canonicalCount = (sample.Length + PackizardNativeDataStream.UBlockSize - 1)
        / PackizardNativeDataStream.UBlockSize;
    Check(memoryData.Blocks.Count == canonicalCount,
        $"Ordinary file boundary manufactured DATA blocks: {memoryData.Blocks.Count}/{canonicalCount}");
    Check(memoryData.Blocks.Any(b => b.ContainsFileBoundary && b.FirstFileIndex == 0 && b.LastFileIndex == 1),
        "No canonical DATA block crossed the a.bin/b.bin boundary");
    VerifyCanonicalEncoding(memoryEncoded, memoryData.Blocks, sample);
    Console.WriteLine("PASS cross-file canonical DATA memory/disk/encoder equivalence");

    // Raw/signed-module payload is a codec barrier, but neighbouring normal files are not.
    byte[] n0 = Enumerable.Repeat((byte)0x11, 96 * 1024).ToArray();
    byte[] raw = Enumerable.Repeat((byte)0x42, 24 * 1024).ToArray();
    byte[] n1 = Enumerable.Repeat((byte)0x33, 96 * 1024).ToArray();
    byte[] barrierExpected = n0.Concat(raw).Concat(n1).ToArray();
    string barrierPath = Path.Combine(scratch, "barrier.data");
    var barrier = PackizardNativeDataStream.Build(new[]
    {
        new PackizardLogicalDataSource { Path="/n0", LogicalOffset=0, Length=n0.Length, Data=n0 },
        new PackizardLogicalDataSource { Path="/module", LogicalOffset=n0.Length, Length=raw.Length, Data=raw, ForceRaw=true },
        new PackizardLogicalDataSource { Path="/n1", LogicalOffset=n0.Length + raw.Length, Length=n1.Length, Data=n1 },
    }, barrierPath);
    Check(barrier.Blocks.Count == 3, $"Raw barrier topology unexpected: {barrier.Blocks.Count} blocks");
    Check(barrier.Blocks[1].ForceRaw && barrier.Blocks[1].IsStored,
        "Raw barrier was not stored verbatim");
    VerifyCanonicalEncoding(barrierPath, barrier.Blocks, barrierExpected);
    Console.WriteLine("PASS raw/module barrier preserves exact canonical encoder output");

    // End-to-end assembler: memory/file-backed input must generate identical bytes, block map and NAPS.
    var inputs = new[]
    {
        new ProsperoPs5InnerFile { Path = "/a.bin", Data = sample[..aLength] },
        new ProsperoPs5InnerFile { Path = "/b.bin", Data = sample[aLength..] },
        new ProsperoPs5InnerFile { Path = "/empty.bin", Data = Array.Empty<byte>() },
    };
    var assembler = new ProsperoPs5InnerImageAssembler(0, 0);
    var memory = assembler.Build(inputs);
    var onDisk = inputs.Select((file, i) =>
    {
        string path = Path.Combine(scratch, $"source-{i}");
        File.WriteAllBytes(path, file.Data);
        return new ProsperoPs5InnerFile { Path = file.Path, DataPath = path };
    }).ToArray();
    var streamed = assembler.Build(onDisk);
    Check(streamed.ImageFilePath is not null && streamed.Image.Length == 0,
        "Expected a file-backed inner image");
    Check(memory.Image.AsSpan().SequenceEqual(File.ReadAllBytes(streamed.ImageFilePath!)),
        "Inner image differs between memory/file-backed assembly");
    Check(memory.ImageLength == streamed.ImageLength, "Inner image length differs");
    CheckDataBlocksEquivalent(memory.DataBlocks, streamed.DataBlocks);
    byte[] memoryNaps = PackizardNativeNapsEngine.Generate(memory);
    byte[] streamedNaps = PackizardNativeNapsEngine.Generate(streamed);
    Check(memoryNaps.AsSpan().SequenceEqual(streamedNaps),
        "Native NAPS differs for file-backed input");
    ValidateParsedNaps(memoryNaps);
    File.Delete(streamed.ImageFilePath!);
    Console.WriteLine("PASS native assembler + NAPS deterministic memory/file-backed equivalence");

    // Exact hostile class behind the real delta=19945 failure: 20,000 tiny files in ~1.2 MiB.
    const int tinyFileCount = 20000;
    const int tinySize = 64;
    var tinySources = new List<PackizardLogicalDataSource>(tinyFileCount);
    long tinyLogical = 0;
    var tinyExpected = new byte[tinyFileCount * tinySize];
    for (int i = 0; i < tinyFileCount; i++)
    {
        byte[] bytes = new byte[tinySize];
        bytes[0] = (byte)i;
        bytes[^1] = (byte)(i >> 8);
        Buffer.BlockCopy(bytes, 0, tinyExpected, i * tinySize, tinySize);
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
    int expectedTinyBlocks = checked((int)((tinyLogical + 0x3ffff) / 0x40000));
    Check(tiny.Blocks.Count == expectedTinyBlocks,
        $"Dense tiny files created {tiny.Blocks.Count} DATA blocks; expected {expectedTinyBlocks}");
    Check(tiny.Blocks.All(b => b.ContainsFileBoundary),
        "Dense canonical blocks did not record crossed file boundaries");
    VerifyCanonicalEncoding(tinyPath, tiny.Blocks, tinyExpected);

    byte[] denseNaps = PackizardNativeNapsEngine.Generate(
        Synthetic(tiny.Blocks, tinyLogical, tiny.EncodedLength));
    NapsLayoutDocument denseDoc = ValidateParsedNaps(denseNaps);
    Check(denseDoc.CblockInfos.Count < 64,
        $"Dense 20k-file topology still inflated CblockInfo to {denseDoc.CblockInfos.Count}");
    Console.WriteLine($"PASS 20k tiny files -> {tiny.Blocks.Count} DATA blocks, {denseDoc.CblockInfos.Count} CblockInfos, native NAPS succeeds");

    // Exercise the upper byte of uint24 u2c bases without exceeding the local 8-bit deltas.
    const int wideCount = 65552;
    var wideBlocks = new PackizardInnerDataBlock[wideCount];
    long widePhysical = 0;
    for (int i = 0; i < wideBlocks.Length; i++)
    {
        wideBlocks[i] = new PackizardInnerDataBlock(
            LogicalOffset: (long)i * 0x40000,
            UncompressedSize: 0x40000,
            OnDiskOffset: widePhysical,
            CompressedSize: 0x100,
            IsStored: false,
            IsMultiChunk: false,
            FirstChunkCompressedSize: 0x100,
            ForceRaw: false,
            OwnerFlag: 1,
            BlockIndex: i,
            FirstFileIndex: 0,
            LastFileIndex: 0,
            ContainsFileBoundary: false);
        widePhysical += 0x100;
    }
    byte[] wideNaps = PackizardNativeNapsEngine.Generate(
        Synthetic(wideBlocks, (long)wideCount * 0x40000, widePhysical));
    NapsLayoutDocument wideDoc = ValidateParsedNaps(wideNaps);
    Check(wideDoc.CblockInfoOffsetByUblock.Any(entry => entry.InfoOffset9BBase > 0xFFFF),
        "Native NAPS never exercised the upper byte of a 24-bit u2c base");
    Console.WriteLine("PASS native u2c uint24 base + seven uint8 deltas beyond 0xffff");

    // Physical compression must never pull metadata into the logical DATA address space.
    byte[] veryCompressible = new byte[24 * 0x40000];
    var geometry = assembler.Build(new[]
    {
        new ProsperoPs5InnerFile { Path = "/compressible.bin", Data = veryCompressible },
    });
    Check(geometry.MetaBaseLogical >= geometry.DataEndLogical,
        $"Metadata overlaps logical DATA: meta=0x{geometry.MetaBaseLogical:X}, dataEnd=0x{geometry.DataEndLogical:X}");
    Check(geometry.ImageLength < geometry.MetaBaseLogical,
        "Geometry regression did not exercise physical compression below logical mount size");
    ValidateParsedNaps(PackizardNativeNapsEngine.Generate(geometry));
    if (geometry.ImageFilePath is not null) File.Delete(geometry.ImageFilePath);
    Console.WriteLine("PASS logical metadata geometry is independent of compressed physical size");

    // Partial and exact-multiple-of-eight u2c tails are both serialized/parsed by the native writer.
    foreach (int count in new[] { 7, 8, 9, 16 })
    {
        var blocks = new PackizardInnerDataBlock[count];
        for (int i = 0; i < count; i++)
        {
            blocks[i] = new PackizardInnerDataBlock(
                LogicalOffset: (long)i * 0x40000,
                UncompressedSize: 0x40000,
                OnDiskOffset: (long)i * 0x100,
                CompressedSize: 0x100,
                IsStored: false,
                IsMultiChunk: false,
                FirstChunkCompressedSize: 0x100,
                ForceRaw: false,
                OwnerFlag: 1,
                BlockIndex: i,
                FirstFileIndex: 0,
                LastFileIndex: 0,
                ContainsFileBoundary: false);
        }
        NapsLayoutDocument doc = ValidateParsedNaps(PackizardNativeNapsEngine.Generate(
            Synthetic(blocks, (long)count * 0x40000, (long)count * 0x100)));
        Check(doc.CblockInfoOffsetByUblock.Count == (doc.Counts.NumUBlocks + 8) >> 3,
            $"u2c group count mismatch for {count} DATA U-blocks");
    }
    Console.WriteLine("PASS native partial/exact-multiple-of-eight u2c terminal groups");

    // 64-bit geometry regression without writing gigabytes: header/u2c planning must accept a logical
    // region above 2 GiB while physical offsets stay compact.
    const int bigLogicalBlocks = 9000; // >2 GiB logical
    var big = new PackizardInnerDataBlock[bigLogicalBlocks];
    long compactPhysical = 0;
    for (int i = 0; i < big.Length; i++)
    {
        big[i] = new PackizardInnerDataBlock(
            LogicalOffset: (long)i * 0x40000,
            UncompressedSize: 0x40000,
            OnDiskOffset: compactPhysical,
            CompressedSize: 0x80,
            IsStored: false,
            IsMultiChunk: false,
            FirstChunkCompressedSize: 0x80,
            ForceRaw: false,
            OwnerFlag: 1,
            BlockIndex: i,
            FirstFileIndex: 0,
            LastFileIndex: 0,
            ContainsFileBoundary: false);
        compactPhysical += 0x80;
    }
    Check((long)bigLogicalBlocks * 0x40000 > int.MaxValue,
        "64-bit geometry fixture is not larger than 2 GiB");
    ValidateParsedNaps(PackizardNativeNapsEngine.Generate(
        Synthetic(big, (long)bigLogicalBlocks * 0x40000, compactPhysical)));
    Console.WriteLine("PASS >2 GiB logical native NAPS geometry without payload-sized allocation");
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
