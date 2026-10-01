// LibProsperoPkg - A library for building and inspecting PS5 packages.
// Copyright (C) 2026 SvenGDK
//
// ---------------------------------------------------------------------------------------------------
// PS5 nwonly INNER pfs_image.dat assembler. Lays out the inner files data-first (raw files block-aligned,
// compressed files packed), followed by the block-info table and the Kraken-compressed metadata block.
// ---------------------------------------------------------------------------------------------------
#nullable enable
using LibProsperoPkg.PFS.Compression;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;

namespace LibProsperoPkg.PFS;

/// <summary>One inner-image payload (a file's data or the metadata block) with its resolved on-disk placement.</summary>
public sealed class ProsperoPs5InnerPayload
{
    /// <summary>The uncompressed payload bytes.</summary>
    public byte[] Data = Array.Empty<byte>();

    /// <summary>Optional already-encoded file payload for the disk-backed writer.</summary>
    public string? DataPath;

    /// <summary>Display path used only for build progress diagnostics.</summary>
    public string? DisplayName;

    /// <summary>When true the payload is stored raw (never compressed) and is placed block-aligned.</summary>
    public bool StoreRaw;

    /// <summary>When true the payload is placed at the next 64 KiB block boundary; otherwise packed contiguously.</summary>
    public bool BlockAligned;

    /// <summary>When true the on-disk cursor is advanced to the next 64 KiB block boundary <em>after</em> this
    /// payload, so it occupies whole blocks and the following payload starts block-aligned. Used for the
    /// sce_sys subtree, which forms a fully block-aligned region.</summary>
    public bool BlockAlignedAfter;
}

/// <summary>
/// Assembles the inner <c>pfs_image.dat</c>: data-first per-file layout (raw files block-aligned,
/// compressed files packed), a 32-byte block-info table, then the compressed metadata.
/// </summary>
public sealed class ProsperoPs5InnerImageBuilder
{
    /// <summary>The inner-image block size (64 KiB).</summary>
    public const int BlockSize = 0x10000;

    /// <summary>The per-file Kraken compression block size (256 KiB).</summary>
    public const int CompressBlockSize = 0x40000;

    private static int AlignUp(int v, int a) => (v + a - 1) & ~(a - 1);

    /// <summary>
    /// Compresses a payload into its concatenated on-disk bytes (256 KiB blocks), or returns the caller's
    /// own array unchanged when <paramref name="storeRaw"/> is set.
    /// </summary>
    public static byte[] CompressPayload(byte[] raw, bool storeRaw)
        => CompressPayload(raw, storeRaw, out _);

    /// <summary>
    /// As <see cref="CompressPayload(byte[], bool)"/>, but also returns the parsed
    /// <see cref="ProsperoCompressedPfsFile"/> (its per-block chunk table) when the payload is stored
    /// compressed, so callers that need the block boundaries (e.g. the naps generator) do not have to
    /// Kraken-pack the same buffer a second time. <paramref name="compressedFile"/> is <see langword="null"/>
    /// when the payload is stored raw (either <paramref name="storeRaw"/> or the 6.25% keep rule fell back).
    /// </summary>
    public static byte[] CompressPayload(byte[] raw, bool storeRaw, out ProsperoCompressedPfsFile? compressedFile)
    {
        compressedFile = null;
        if (storeRaw) return raw;
        var pf = ProsperoCompressedPfsFile.Parse(ProsperoCompressedPfsImage.Pack(raw, 7, CompressBlockSize));
        using var ms = new MemoryStream();
        foreach (var b in pf.Blocks)
        {
            var d = b.CompressedData.ToArray();
            ms.Write(d, 0, d.Length);
        }
        byte[] comp = ms.ToArray();
        // Each block has already made its own store decision, so the compressed form never exceeds the
        // raw form and there is no file-level threshold on top of it.
        compressedFile = pf;
        return comp;
    }

    /// <summary>Compresses independent 256 KiB blocks without retaining the whole source.</summary>
    public static void CompressPayloadToStream(Stream source, Stream destination, long length)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(length);
        var buffer = new byte[CompressBlockSize];
        long remaining = length;
        while (remaining > 0)
        {
            int count = (int)Math.Min(remaining, buffer.Length);
            source.ReadExactly(buffer.AsSpan(0, count));
            byte[] block = count == buffer.Length ? buffer : buffer.AsSpan(0, count).ToArray();
            byte[] encoded = CompressPayload(block, storeRaw: false);
            destination.Write(encoded);
            remaining -= count;
        }
    }

    /// <summary>
    /// Assembles the inner image. <paramref name="payloads"/> are, in on-disk order, the data files followed by
    /// the block-info table payload and the metadata block. Each payload is compressed per its flags and placed
    /// block-aligned or packed. Returns the block-aligned-tail on-disk image.
    /// </summary>
    public byte[] Build(IReadOnlyList<ProsperoPs5InnerPayload> payloads)
    {
        // First pass: compress + resolve offsets.
        var chunks = new List<(int offset, byte[] data)>();
        int pos = 0;
        foreach (var p in payloads)
        {
            if (p.DataPath is not null)
                throw new ArgumentException("File-backed payloads require BuildToFile.", nameof(payloads));
            byte[] data = CompressPayload(p.Data, p.StoreRaw);
            if (p.BlockAligned)
                pos = AlignUp(pos, BlockSize);
            chunks.Add((pos, data));
            pos += data.Length;
            if (p.BlockAlignedAfter)
                pos = AlignUp(pos, BlockSize);
        }

        byte[] img = new byte[pos];
        foreach (var (offset, data) in chunks)
            Array.Copy(data, 0, img, offset, data.Length);
        return img;
    }

    /// <summary>
    /// Assembles the inner image directly into a file using 64-bit offsets. This is the
    /// disk-backed equivalent of <see cref="Build"/> and avoids the CLR single-array size limit.
    /// </summary>
    public delegate void PackizardProgressCallback(long completedBytes, long totalBytes, string? currentPath);

    // Keep the original public API for callers that do not need telemetry.
    public long BuildToFile(IReadOnlyList<ProsperoPs5InnerPayload> payloads, string outputPath)
        => BuildToFile(payloads, outputPath, null);

    public long BuildToFile(
        IReadOnlyList<ProsperoPs5InnerPayload> payloads,
        string outputPath,
        PackizardProgressCallback? progress)
    {
        ArgumentNullException.ThrowIfNull(payloads);
        ArgumentException.ThrowIfNullOrWhiteSpace(outputPath);

        static long AlignUpLong(long v, long a) => checked((v + a - 1) & ~(a - 1));

        string? directory = Path.GetDirectoryName(Path.GetFullPath(outputPath));
        if (!string.IsNullOrEmpty(directory))
            Directory.CreateDirectory(directory);

        using var fs = new FileStream(
            outputPath, FileMode.Create, FileAccess.ReadWrite, FileShare.None,
            1024 * 1024, FileOptions.SequentialScan);

        long totalWork = 0;
        foreach (var item in payloads)
        {
            long size = item.DataPath is { Length: > 0 }
                ? new FileInfo(item.DataPath).Length
                : item.Data.LongLength;
            totalWork = checked(totalWork + size);
        }

        long workDone = 0;
        var progressWatch = Stopwatch.StartNew();
        long lastProgressMs = -1000;
        int lastProgressPercent = -1;
        void Report(string? currentPath, bool force = false)
        {
            if (progress is null) return;
            long now = progressWatch.ElapsedMilliseconds;
            int percent = totalWork <= 0 ? 100 : (int)Math.Min(100L, workDone * 100L / totalWork);
            if (!force && now - lastProgressMs < 1000) return;
            if (!force && percent == lastProgressPercent && now - lastProgressMs < 3000) return;
            lastProgressMs = now;
            lastProgressPercent = percent;
            progress(workDone, totalWork, currentPath);
        }

        Report(payloads.Count > 0 ? payloads[0].DisplayName : null, force: true);
        byte[] copyBuffer = new byte[4 * 1024 * 1024];
        long pos = 0;
        foreach (var p in payloads)
        {
            Report(p.DisplayName);
            if (p.BlockAligned)
                pos = AlignUpLong(pos, BlockSize);

            fs.Position = pos;
            if (p.DataPath is not null)
            {
                using var input = File.OpenRead(p.DataPath);
                if (p.StoreRaw)
                {
                    int read;
                    while ((read = input.Read(copyBuffer, 0, copyBuffer.Length)) > 0)
                    {
                        fs.Write(copyBuffer, 0, read);
                        workDone = checked(workDone + read);
                        Report(p.DisplayName);
                    }
                }
                else
                {
                    long inputLength = input.Length;
                    CompressPayloadToStream(input, fs, inputLength);
                    workDone = checked(workDone + inputLength);
                    Report(p.DisplayName);
                }
            }
            else
            {
                byte[] data = CompressPayload(p.Data, p.StoreRaw);
                fs.Write(data);
                workDone = checked(workDone + p.Data.LongLength);
                Report(p.DisplayName);
            }
            pos = fs.Position;

            if (p.BlockAlignedAfter)
                pos = AlignUpLong(pos, BlockSize);
        }

        fs.SetLength(pos);
        fs.Flush();
        workDone = totalWork;
        Report(null, force: true);
        return pos;
    }
}
