using LibProsperoPkg.PFS;
using LibProsperoPkg.PKG;

static void Check(bool condition, string message)
{
    if (!condition) throw new Exception(message);
}

static void CheckDataBlocksEquivalent(
    IReadOnlyList<PackizardInnerDataBlock> left,
    IReadOnlyList<PackizardInnerDataBlock> right)
{
    Check(left.Count == right.Count, "DATA U-block count differs");
    for (int i = 0; i < left.Count; i++)
        Check(left[i].Equals(right[i]), $"DATA U-block {i} differs");
}

static long AlignUp(long value, long alignment) => (value + alignment - 1) & ~(alignment - 1);

static ProsperoPs5InnerImageResult Synthetic(
    IReadOnlyList<PackizardInnerDataBlock> data,
    long dataEnd,
    long encodedLength,
    IReadOnlyList<long>? afids = null)
{
    const long B64 = 0x10000;
    const long U = 0x40000;
    long dataCoverage = (long)data.Count * U;
    long metaBase = dataCoverage + 4 * U;
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
    // Native DATA encoding must be independent of whether the exact same logical bytes come from
    // memory or disk-backed sources.
    byte[] sample = new byte[0x90017];
    new Random(17).NextBytes(sample);
    Array.Clear(sample, 0x40000, 0x30000);
    var memorySources = new[]
    {
        new PackizardLogicalDataSource { Path = "/a.bin", LogicalOffset = 0, Length = 0x21003,
            Data = sample[..0x21003], OwnerFlag = 0 },
        new PackizardLogicalDataSource { Path = "/b.bin", LogicalOffset = 0x21003, Length = sample.Length - 0x21003,
            Data = sample[0x21003..], OwnerFlag = 1 },
    };
    string memoryEncoded = Path.Combine(scratch, "native-memory.data");
    var memoryData = PackizardNativeDataStream.Build(memorySources, memoryEncoded);

    string srcA = Path.Combine(scratch, "a.bin");
    string srcB = Path.Combine(scratch, "b.bin");
    File.WriteAllBytes(srcA, sample[..0x21003]);
    File.WriteAllBytes(srcB, sample[0x21003..]);
    var diskSources = new[]
    {
        new PackizardLogicalDataSource { Path = "/a.bin", LogicalOffset = 0, Length = 0x21003,
            DataPath = srcA, OwnerFlag = 0 },
        new PackizardLogicalDataSource { Path = "/b.bin", LogicalOffset = 0x21003, Length = sample.Length - 0x21003,
            DataPath = srcB, OwnerFlag = 1 },
    };
    string diskEncoded = Path.Combine(scratch, "native-disk.data");
    var diskData = PackizardNativeDataStream.Build(diskSources, diskEncoded);
    Check(File.ReadAllBytes(memoryEncoded).AsSpan().SequenceEqual(File.ReadAllBytes(diskEncoded)),
        "Native DATA differs between memory and disk sources");
    CheckDataBlocksEquivalent(memoryData.Blocks, diskData.Blocks);
    Check(memoryData.Blocks.Count == (sample.Length + 0x3ffff) / 0x40000,
        "Native DATA did not produce one block per logical U-block");
    Console.WriteLine("PASS native DATA memory/disk equivalence");

    // End-to-end inner assembly must preserve the same canonical block map and native NAPS bytes.
    var inputs = new[]
    {
        new ProsperoPs5InnerFile { Path = "/sample.bin", Data = sample },
        new ProsperoPs5InnerFile { Path = "/nested/zeros.bin", Data = new byte[8192] },
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
    Check(streamed.ImageFilePath is not null && streamed.Image.Length == 0, "Expected a file-backed inner image");
    Check(memory.Image.AsSpan().SequenceEqual(File.ReadAllBytes(streamed.ImageFilePath!)), "Inner image differs");
    Check(memory.ImageLength == streamed.ImageLength, "Inner image length differs");
    CheckDataBlocksEquivalent(memory.DataBlocks, streamed.DataBlocks);
    Check(PackizardNativeNapsEngine.Generate(memory).AsSpan().SequenceEqual(
        PackizardNativeNapsEngine.Generate(streamed)), "Native NAPS differs for a file-backed image");
    File.Delete(streamed.ImageFilePath!);
    Console.WriteLine("PASS native inner image + NAPS equivalence");

    // The missing regression: a huge number of file boundaries inside only a handful of U-blocks.
    // The legacy file-centric topology could create thousands of CblockInfo records here.  Native DATA
    // must remain O(U-blocks), not O(files).
    const int tinyFileCount = 20000;
    const int tinySize = 64;
    var tinySources = new List<PackizardLogicalDataSource>(tinyFileCount);
    long tinyLogical = 0;
    for (int i = 0; i < tinyFileCount; i++)
    {
        byte[] bytes = new byte[tinySize];
        bytes[0] = (byte)i;
        tinySources.Add(new PackizardLogicalDataSource
        {
            Path = $"/tiny/{i:D5}.bin",
            LogicalOffset = tinyLogical,
            Length = tinySize,
            Data = bytes,
            ForceRaw = i % 997 == 0,
            OwnerFlag = i == 0 ? 0u : 1u,
        });
        tinyLogical += tinySize;
    }
    string tinyPath = Path.Combine(scratch, "tiny.data");
    var tiny = PackizardNativeDataStream.Build(tinySources, tinyPath);
    int tinyExpectedBlocks = checked((int)((tinyLogical + 0x3ffff) / 0x40000));
    Check(tiny.Blocks.Count == tinyExpectedBlocks,
        $"Dense-file DATA grew with file count: {tiny.Blocks.Count}/{tinyExpectedBlocks}");
    Check(tiny.Blocks.Count < 16, "Dense-file regression did not remain within a handful of U-blocks");
    byte[] tinyNaps = PackizardNativeNapsEngine.Generate(Synthetic(tiny.Blocks, tinyLogical, tiny.EncodedLength));
    var tinyDoc = ProsperoNapsLayout.Parse(tinyNaps);
    Check(tinyDoc.CblockInfos.Count < 64,
        $"Dense-file NAPS produced {tinyDoc.CblockInfos.Count} CblockInfo records for {tinyFileCount} files");
    Console.WriteLine($"PASS {tinyFileCount:N0} tiny files -> {tiny.Blocks.Count} DATA U-blocks without u2c density overflow");

    // Exercise 24-bit next-group bases well beyond 0xffff without manufacturing file boundaries.
    const int wideCount = 65552;
    var wideBlocks = new PackizardInnerDataBlock[wideCount];
    long widePhysical = 0;
    for (int i = 0; i < wideBlocks.Length; i++)
    {
        wideBlocks[i] = new PackizardInnerDataBlock(
            (long)i * 0x40000, 0x40000, widePhysical, 0x100,
            IsStored: false, IsMultiChunk: false, FirstChunkCompressedSize: 0x100,
            ForceRaw: false, OwnerFlag: 1);
        widePhysical += 0x100;
    }
    var wideSynthetic = Synthetic(wideBlocks, (long)wideCount * 0x40000, widePhysical);
    var wideDoc = ProsperoNapsLayout.Parse(PackizardNativeNapsEngine.Generate(wideSynthetic));
    bool sawHighBase = false;
    foreach (NapsU2cEntry entry in wideDoc.CblockInfoOffsetByUblock)
    {
        byte[] raw = ProsperoNapsLayout.EncodeU2cEntry(entry);
        int nextBase = raw[4] | raw[5] << 8 | raw[6] << 16;
        if (nextBase > 0xffff) sawHighBase = true;
    }
    Check(sawHighBase, "Native NAPS never exercised the upper byte of a 24-bit u2c base");
    Console.WriteLine("PASS native u2c 24-bit bases beyond 0xffff");

    // Verify the exact bug behind the 19945 failure cannot recur: logical metadata geometry must be
    // based on logical DATA length, not compressed physical length.
    byte[] veryCompressible = new byte[24 * 0x40000];
    var geometry = assembler.Build(new[]
    {
        new ProsperoPs5InnerFile { Path = "/compressible.bin", Data = veryCompressible },
    });
    Check(geometry.MetaBaseLogical >= geometry.DataEndLogical,
        $"Metadata overlaps logical DATA: meta=0x{geometry.MetaBaseLogical:X}, dataEnd=0x{geometry.DataEndLogical:X}");
    Check(geometry.ImageLength < geometry.MetaBaseLogical,
        "Geometry regression did not actually exercise physical compression below logical mount size");
    Check(PackizardNativeNapsEngine.Generate(geometry).Length > 0, "Native NAPS failed on compressed/logical geometry split");
    if (geometry.ImageFilePath is not null) File.Delete(geometry.ImageFilePath);
    Console.WriteLine("PASS logical metadata geometry is independent of compressed physical size");

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
    Check(!Directory.EnumerateFiles(scratch, "libprospero-*.tmp").Any(), "Source failure leaked a temporary file");
    Console.WriteLine("PASS source failure cleanup");

    var outerFiles = new[]
    {
        new ProsperoOuterFile { Name = "pfs_image.dat", Data = sample, Signed = false },
        new ProsperoOuterFile { Name = "naps_pkg_layout.dat", Data = new byte[100], Signed = true },
    };
    var parameters = new ProsperoOuterPfsBuildParameters { Seed = new byte[16], TimestampSeconds = 0 };
    var outerMemory = ProsperoOuterPfsBuilder.BuildForPackage(outerFiles, parameters, new byte[32]);
    string outerPath = Path.Combine(scratch, "outer.img");
    var outerStreamed = ProsperoOuterPfsBuilder.BuildForPackageToFile(outerFiles, parameters, new byte[32], outerPath);
    Check(outerMemory.Ciphertext.AsSpan().SequenceEqual(File.ReadAllBytes(outerPath)), "Outer image differs");
    Check(outerMemory.ImageDigests.AsSpan().SequenceEqual(outerStreamed.ImageDigests), "Outer digests differ");
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
        Check(!Directory.EnumerateFiles(scratch, "libprospero-*.tmp").Any(), $"Temporary file leaked at {stage}");
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
            new ProsperoPs5InnerFile { Path = "/large.bin", DataPath = largePath,
                Policy = ProsperoInnerFilePolicy.StoreVerbatim }
        });
        Check(large.ImageLength > int.MaxValue && large.Image.Length == 0, "Large image was not streamed");
        Check(large.Placements[0].UncompressedSize == length, "64-bit source length was truncated");
        Check(large.DataBlocks.Count == (length + 0x3ffff) / 0x40000,
            "Large DATA U-block count is incorrect");
        Check(GC.GetTotalAllocatedBytes() - allocatedBefore < 512L * 1024 * 1024,
            "Large input unexpectedly allocated payload-sized buffers");
        Check(PackizardNativeNapsEngine.Generate(large).Length > 0, "Large native NAPS is empty");
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
