using LibProsperoPkg.PFS;
using LibProsperoPkg.PFS.Compression.Oodle;
using LibProsperoPkg.PKG;

static void Check(bool condition, string message)
{
    if (!condition) throw new Exception(message);
}

static void CheckDataBlocksEquivalent(
    IReadOnlyList<PackizardInnerDataBlock> left,
    IReadOnlyList<PackizardInnerDataBlock> right)
{
    Check(left.Count == right.Count, "DATA block count differs");
    for (int i = 0; i < left.Count; i++)
        Check(left[i].Equals(right[i]), $"DATA block {i} differs");
}

static long AlignUp(long value, long alignment) => (value + alignment - 1) & ~(alignment - 1);

static int[] KrakenFlags(bool multi) => multi
    ? [0x22, 0x02, 0x12, 0x32, 0x23, 0x03, 0x13, 0x33, 0x00, 0x20]
    : [0x02, 0x00, 0x22, 0x20];

static byte[] DecodeCanonicalData(string encodedPath, IReadOnlyList<PackizardInnerDataBlock> blocks)
{
    byte[] encoded = File.ReadAllBytes(encodedPath);
    long logicalLength = blocks.Sum(b => (long)b.UncompressedSize);
    Check(logicalLength <= int.MaxValue, "Regression DATA is too large to decode in-memory");
    var result = new byte[(int)logicalLength];

    foreach (PackizardInnerDataBlock b in blocks)
    {
        Check(b.OnDiskOffset >= 0 && b.OnDiskOffset + b.CompressedSize <= encoded.LongLength,
            $"DATA block {b.BlockIndex} is outside encoded stream");
        var src = encoded.AsSpan((int)b.OnDiskOffset, b.CompressedSize);
        var dst = result.AsSpan((int)b.LogicalOffset, b.UncompressedSize);
        if (b.IsStored)
        {
            Check(b.CompressedSize == b.UncompressedSize,
                $"Stored block {b.BlockIndex} size mismatch");
            src.CopyTo(dst);
            continue;
        }

        bool decoded = false;
        int firstChunk = b.IsMultiChunk ? b.FirstChunkCompressedSize : 0;
        foreach (int flags in KrakenFlags(b.IsMultiChunk))
        {
            try
            {
                if (KrakenDecoder.DecodeBlock(src, flags, firstChunk, dst) == KrakenDecodeStatus.Success)
                {
                    decoded = true;
                    break;
                }
            }
            catch { }
        }
        Check(decoded, $"Could not decode canonical DATA block {b.BlockIndex}");
    }
    return result;
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

static void ValidateParsedNaps(byte[] naps)
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
    // Ordinary files must share canonical DATA blocks. This is the structural fix for dense-file u2c
    // overflow: Cblock density follows logical bytes, not filesystem object count.
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
    Check(DecodeCanonicalData(memoryEncoded, memoryData.Blocks).AsSpan().SequenceEqual(sample),
        "Canonical cross-file DATA did not decode back to the logical byte stream");
    Console.WriteLine("PASS cross-file canonical DATA memory/disk/decode equivalence");

    // A raw/module source is a codec barrier, but normal neighbours can still coalesce independently.
    byte[] n0 = Enumerable.Repeat((byte)0x11, 96 * 1024).ToArray();
    byte[] raw = Enumerable.Repeat((byte)0x42, 24 * 1024).ToArray();
    byte[] n1 = Enumerable.Repeat((byte)0x33, 96 * 1024).ToArray();
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
    byte[] barrierExpected = n0.Concat(raw).Concat(n1).ToArray();
    Check(DecodeCanonicalData(barrierPath, barrier.Blocks).AsSpan().SequenceEqual(barrierExpected),
        "Raw barrier DATA did not reconstruct exactly");
    Console.WriteLine("PASS raw/module barrier preserves exact bytes without per-file normal blocks");

    // End-to-end assembler: memory/file-backed builds must produce identical inner bytes, canonical map,
    // and native NAPS. The old reference ReconstructMount reader is intentionally NOT used here because
    // it splits every Cblock at fidx file boundaries and therefore cannot model cross-file DATA blocks.
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
    Check(memory.DataBlocks.Count < inputs.Sum(x => x.Data.Length == 0 ? 0 : 1) + 3,
        "Assembler reverted to one block per ordinary file");
    byte[] memoryNaps = PackizardNativeNapsEngine.Generate(memory);
    byte[] streamedNaps = PackizardNativeNapsEngine.Generate(streamed);
    Check(memoryNaps.AsSpan().SequenceEqual(streamedNaps),
        "Native NAPS differs for a file-backed image");
    ValidateParsedNaps(memoryNaps);
    File.Delete(streamed.ImageFilePath!);
    Console.WriteLine("PASS native assembler + NAPS deterministic memory/file-backed equivalence");

    // Exact hostile class behind the real delta=19945 failure: 20,000 tiny files occupy ~1.2 MiB.
    // They must collapse to five logical DATA blocks and BUILD SUCCESSFULLY, not be rejected.
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
    Check(DecodeCanonicalData(tinyPath, tiny.Blocks).AsSpan().SequenceEqual(tinyExpected),
        "Dense canonical DATA does not reconstruct the 20k-file logical stream");

    byte[] denseNaps = PackizardNativeNapsEngine.Generate(
        Synthetic(tiny.Blocks, tinyLogical, tiny.EncodedLength));
    NapsLayoutDocument denseDoc = ProsperoNapsLayout.Parse(denseNaps);
    PackizardNativeNapsValidator.ValidateDocument(denseDoc);
    Check(denseDoc.CblockInfos.Count < 64,
        $"Dense 20k-file topology still inflated CblockInfo to {denseDoc.CblockInfos.Count}");
    Check(denseDoc.CblockInfoOffsetByUblock.All(u => u.DeltaFromBase.All(d => d <= 255)),
        "Dense u2c emitted an impossible delta");
    Console.WriteLine($"PASS 20k tiny files -> {tiny.Blocks.Count} DATA blocks, {denseDoc.CblockInfos.Count} CblockInfos, native NAPS succeeds");

    // Exercise the upper byte of the uint24 u2c base without violating the 8-bit local delta budget.
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
    NapsLayoutDocument wideDoc = ProsperoNapsLayout.Parse(wideNaps);
    Check(wideDoc.CblockInfoOffsetByUblock.Any(entry => entry.InfoOffset9BBase > 0xFFFF),
        "Native NAPS never exercised the upper byte of a 24-bit u2c base");
    ValidateParsedNaps(wideNaps);
    Console.WriteLine("PASS native u2c uint24 base + seven deltas beyond 0xffff");

    // Highly compressible DATA: physical size may be tiny, but metadata logical placement must remain
    // beyond the full uncompressed DATA interval. This guards the geometry collapse behind huge jumps.
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

    // Source failures must still clean temporary files.
    var fsTree = new ProsperoFsDir();
    fsTree.Files.Add(new ProsperoFsFile(stream =>
    {
        stream.Write(new byte[100]);
        throw new IOException("injected source failure");
    }, "broken.bin", 100));
    try
    {
        assembler.BuildFromFsTree(fsTree);
        throw new Exception("Expected source failure");
    }
    catch (IOException e) when (e.Message == "injected source failure") { }
    Check(!Directory.EnumerateFiles(scratch, "libprospero-*.tmp").Any(),
        "Source failure leaked a temporary file");
    Console.WriteLine("PASS source failure cleanup");

    var outerFiles = new[]
    {
        new ProsperoOuterFile { Name = "pfs_image.dat", Data = sample, Signed = false },
        new ProsperoOuterFile { Name = "naps_pkg_layout.dat", Data = new byte[100], Signed = true },
    };
    var parameters = new ProsperoOuterPfsBuildParameters
    {
        Seed = new byte[16],
        TimestampSeconds = 0,
    };
    var outerMemory = ProsperoOuterPfsBuilder.BuildForPackage(outerFiles, parameters, new byte[32]);
    string outerPath = Path.Combine(scratch, "outer.img");
    var outerStreamed = ProsperoOuterPfsBuilder.BuildForPackageToFile(
        outerFiles, parameters, new byte[32], outerPath);
    Check(outerMemory.Ciphertext.AsSpan().SequenceEqual(File.ReadAllBytes(outerPath)),
        "Outer image differs");
    Check(outerMemory.ImageDigests.AsSpan().SequenceEqual(outerStreamed.ImageDigests),
        "Outer digests differ");
    Console.WriteLine("PASS outer image and digest equivalence");

    string packageSource = Path.Combine(scratch, "source");
    Directory.CreateDirectory(Path.Combine(packageSource, "sce_sys"));
    File.WriteAllText(Path.Combine(packageSource, "sce_sys", "param.json"), "{}");
    File.WriteAllBytes(Path.Combine(packageSource, "data.bin"), sample);
    var properties = new ProsperoPkgBuildProperties
    {
        SourceFolder = packageSource,
        ContentId = "UP9000-PPSA00000_00-PROSPERO00000000",
    };
    foreach (string stage in new[] { "Preparing PS5 outer PFS", "Writing outer PFS image", "Done:" })
    {
        try
        {
            ProsperoPkgBuilder.Build(properties, Path.Combine(scratch, "failed.pkg"), message =>
            {
                if (message.StartsWith(stage)) throw new IOException("injected package failure");
            });
            throw new Exception($"Expected failure at {stage}");
        }
        catch (IOException e) when (e.Message == "injected package failure") { }
        Check(!Directory.EnumerateFiles(scratch, "libprospero-*.tmp").Any(),
            $"Temporary file leaked at {stage}");
    }
    Console.WriteLine("PASS cleanup after package failure callbacks");

    if (args.Contains("--large"))
    {
        string largePath = Path.Combine(scratch, "large-input.bin");
        long length = (long)int.MaxValue + 65537;
        using (var file = File.Create(largePath))
        {
            file.SetLength(length);
            file.WriteByte(0x42);
            file.Position = length - 1;
            file.WriteByte(0x7e);
        }
        long allocatedBefore = GC.GetTotalAllocatedBytes();
        var large = assembler.Build(new[]
        {
            new ProsperoPs5InnerFile
            {
                Path = "/large.bin",
                DataPath = largePath,
                Policy = ProsperoInnerFilePolicy.StoreVerbatim,
            }
        });
        Check(large.ImageLength > int.MaxValue && large.Image.Length == 0,
            "Large image was not streamed");
        Check(large.Placements[0].UncompressedSize == length,
            "64-bit source length was truncated");
        Check(large.DataBlocks.Count == (length + 0x3ffff) / 0x40000,
            "Large canonical DATA block count is incorrect");
        Check(GC.GetTotalAllocatedBytes() - allocatedBefore < 512L * 1024 * 1024,
            "Large input unexpectedly allocated payload-sized buffers");
        ValidateParsedNaps(PackizardNativeNapsEngine.Generate(large));
        File.Delete(large.ImageFilePath!);
        Console.WriteLine("PASS single file larger than 2 GiB through native DATA/NAPS");
    }
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
    Directory.Delete(scratch, recursive: true);
}
