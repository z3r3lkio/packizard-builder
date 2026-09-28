using LibProsperoPkg.PFS;
using LibProsperoPkg.PKG;

static void Check(bool condition, string message)
{
    if (!condition) throw new Exception(message);
}

static void CheckPlacementsEquivalent(
    IReadOnlyList<ProsperoPs5InnerPlacement> left,
    IReadOnlyList<ProsperoPs5InnerPlacement> right)
{
    Check(left.Count == right.Count, "Placement count differs");
    for (int i = 0; i < left.Count; i++)
    {
        var a = left[i];
        var b = right[i];
        Check(a.OnDiskOffset == b.OnDiskOffset, $"Placement {i} on-disk offset differs");
        Check(a.LogicalOffset == b.LogicalOffset, $"Placement {i} logical offset differs");
        Check(a.OnDiskSize == b.OnDiskSize, $"Placement {i} on-disk size differs");
        Check(a.UncompressedSize == b.UncompressedSize, $"Placement {i} logical size differs");
        Check(a.StoreRaw == b.StoreRaw, $"Placement {i} storage policy differs");
        Check(a.CompressedBlocks.Count == b.CompressedBlocks.Count, $"Placement {i} block-map count differs");
        for (int j = 0; j < a.CompressedBlocks.Count; j++)
            Check(a.CompressedBlocks[j].Equals(b.CompressedBlocks[j]), $"Placement {i} block-map entry {j} differs");
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
    // Compare the exact bytes at block boundaries and verify that the streaming path captures the
    // same per-256KiB geometry that NAPS later consumes.
    foreach (int size in new[] { 0, 1, 0x3ffff, 0x40000, 0x40001, 0x80017 })
    {
        byte[] data = new byte[size];
        new Random(size).NextBytes(data);
        if (size > 0x40000) Array.Clear(data, 0x40000, Math.Min(0x40000, size - 0x40000));
        byte[] expected = ProsperoPs5InnerImageBuilder.CompressPayload(data, false);
        using var source = new MemoryStream(data);
        using var output = new MemoryStream();
        var blockMap = new List<ProsperoInnerDataBlockChunk>();
        ProsperoPs5InnerImageBuilder.CompressPayloadToStream(source, output, data.LongLength, blockMap);
        Check(expected.AsSpan().SequenceEqual(output.ToArray()), $"Compression differs at {size} bytes");
        int expectedBlocks = size == 0 ? 0 : (size + 0x3ffff) / 0x40000;
        Check(blockMap.Count == expectedBlocks, $"Block-map count differs at {size} bytes");
        Check(blockMap.Sum(b => (long)b.UncompressedSize) == size, $"Block-map logical size differs at {size} bytes");
        Check(blockMap.Sum(b => (long)b.CompressedSize) == output.Length, $"Block-map stored size differs at {size} bytes");
    }
    Console.WriteLine("PASS block compression equivalence + captured per-block geometry (6 boundary sizes)");

    byte[] sample = new byte[0x40017];
    new Random(17).NextBytes(sample);
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
    Check(streamed.ImageFilePath is not null && streamed.Image.Length == 0, "Expected a file-backed image");
    Check(memory.Image.AsSpan().SequenceEqual(File.ReadAllBytes(streamed.ImageFilePath!)), "Inner image differs");
    Check(memory.ImageLength == streamed.ImageLength, "Image length differs");
    CheckPlacementsEquivalent(memory.Placements, streamed.Placements);
    Check(memory.Placements.Any(p => !p.StoreRaw && p.CompressedBlocks.Count > 0), "Compressed placement lost its encoder block map");
    Check(ProsperoNwonlyNapsGenerator.Generate(memory).AsSpan().SequenceEqual(
        ProsperoNwonlyNapsGenerator.Generate(streamed)), "NAPS differs for a file-backed image");
    File.Delete(streamed.ImageFilePath!);
    Check(!Directory.EnumerateFiles(scratch, "libprospero-*.tmp").Any(), "Compression intermediates leaked");
    Console.WriteLine("PASS inner image, per-block placements and NAPS equivalence");

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
    Console.WriteLine("PASS cleanup after inner build, outer build and completion callback failures");

    // Exercise the terminal group and both upper bytes of the next-group base.
    foreach (int count in new[] { 8, 16, 264, 65552 })
    {
        var blocks = Enumerable.Range(0, count + 1).Select(i => new NapsCblockPlanEntry
        {
            LogicalOffset = (long)i * 0x40000,
            OnDiskOffset = (long)i * 0x40000,
            EvenChunkCompressedLength = 0x40000,
            StreamLength = 0x40000,
            Terminator = i == count,
        }).ToArray();
        var layout = ProsperoNapsLayoutBuilder.BuildDocument(new NapsGenerationRequest
        {
            NumUBlocks = count,
            NumOuterBlocks = count * 4,
            FileLogicalOffsets = new long[] { 0, (long)count * 0x40000 },
            Blocks = blocks,
        });
        for (int group = 0; group < layout.CblockInfoOffsetByUblock.Count; group++)
        {
            byte[] entry = ProsperoNapsLayout.EncodeU2cEntry(layout.CblockInfoOffsetByUblock[group]);
            int expectedBase = 8 * group + 8 < count ? 8 * group + 8 : 0;
            Check((entry[4] | entry[5] << 8 | entry[6] << 16) == expectedBase, "NAPS base truncated");
        }
    }
    Console.WriteLine("PASS NAPS base widths and terminal groups");

    // Reproduce the real-world failure class: one large encoded file containing hundreds of 256 KiB
    // logical blocks. Collapsing this into one CblockInfo produces huge u2c deltas; the captured block
    // map keeps each group locally addressable and also adds the periodic RUN re-anchors.
    const int mappedBlockCount = 600;
    const int encodedBlockSize = 0x18000;
    const int logicalBlockSize = 0x40000;
    var mappedBlocks = Enumerable.Range(0, mappedBlockCount)
        .Select(_ => new NapsFileBlockPlacement(
            encodedBlockSize, logicalBlockSize, IsStored: false,
            IsMultiChunk: false, FirstChunkCompressedSize: encodedBlockSize))
        .ToArray();
    var mappedRunStarts = new HashSet<long> { 0 };
    long mappedOnDisk = 0;
    for (int i = 0; i < mappedBlocks.Length; i++)
    {
        if (i > 0 && i % 11 == 0) mappedRunStarts.Add(mappedOnDisk);
        mappedOnDisk += mappedBlocks[i].CompressedSize;
    }
    long mappedLogicalSize = (long)mappedBlockCount * logicalBlockSize;
    var mappedLayout = ProsperoNapsLayoutBuilder.BuildFromInnerImage(
        numUBlocks: mappedBlockCount,
        numOuterBlocks: checked((int)((mappedOnDisk + 0xffff) / 0x10000)),
        files: new[]
        {
            new NapsFilePlacement
            {
                OnDiskOffset = 0,
                LogicalOffset = 0,
                OnDiskSize = mappedOnDisk,
                UncompressedSize = mappedLogicalSize,
                StoreRaw = false,
                CompressedKde = 2,
                Blocks = mappedBlocks,
            }
        },
        runStartOnDiskOffsets: mappedRunStarts,
        tailBlocks: new[]
        {
            new NapsCblockPlanEntry
            {
                StartRun = true,
                OnDiskOffset = mappedOnDisk,
                LogicalOffset = mappedLogicalSize,
                Terminator = true,
            }
        },
        fileLogicalOffsets: new long[] { 0, mappedLogicalSize });
    Check(mappedLayout.CblockInfos.Count > mappedBlockCount,
        "Mapped NAPS did not emit per-block CblockInfo records/RUN anchors");
    foreach (var u2cEntry in mappedLayout.CblockInfoOffsetByUblock)
        Check(u2cEntry.DeltaFromBase.All(delta => delta <= 255), "Mapped NAPS emitted an invalid u2c delta");
    Console.WriteLine("PASS 600-block compressed-file NAPS map without real-u2c overflow");

    if (args.Contains("--large"))
    {
        // A single source larger than the CLR array limit, with bounded payload memory.
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
        Check(GC.GetTotalAllocatedBytes() - allocatedBefore < 512L * 1024 * 1024,
            "Large input unexpectedly allocated payload-sized buffers");
        using (var file = File.OpenRead(large.ImageFilePath!))
        {
            file.Position = large.Placements[0].OnDiskOffset;
            Check(file.ReadByte() == 0x42, "Large payload start differs");
            file.Position = large.Placements[0].OnDiskOffset + length - 1;
            Check(file.ReadByte() == 0x7e, "Large payload end differs");
        }
        Check(ProsperoNwonlyNapsGenerator.Generate(large).Length > 0, "Large NAPS is empty");
        File.Delete(large.ImageFilePath!);
        Console.WriteLine("PASS single file larger than 2 GiB");
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
