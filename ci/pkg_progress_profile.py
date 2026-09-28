#!/usr/bin/env python3
"""Add AMPR direct-I/O plus detailed integrated-PKG progress telemetry."""
from __future__ import annotations

from pathlib import Path


FS_TREE_REL = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PFS/ProsperoFsTree.cs")
IMAGE_BUILDER_REL = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PFS/ProsperoPs5InnerImageBuilder.cs")
ASSEMBLER_REL = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PFS/ProsperoPs5InnerImageAssembler.cs")
PKG_BUILDER_REL = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PKG/ProsperoPkgBuilder.cs")


def _replace_once(path: Path, text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"PKG progress patch expected exactly one {label} in {path}, found {count}. "
            "The pinned LibProsperoPKG source changed and the profile must be rebased explicitly."
        )
    return text.replace(old, new, 1)


def _patch_fs_tree(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "Packizard direct-I/O source path" in text:
        return

    text = _replace_once(
        path,
        text,
        '''public class ProsperoFsFile : ProsperoFsNode
{
    /// <summary>
    /// Creates an FSFile from a real on-disk file.
''',
        '''public class ProsperoFsFile : ProsperoFsNode
{
    /// <summary>
    /// Packizard direct-I/O source path. Non-null only for nodes created from a real on-disk file;
    /// generated/in-memory nodes keep using the writer delegate and are materialized as before.
    /// </summary>
    public string SourcePath { get; private set; }

    /// <summary>
    /// Creates an FSFile from a real on-disk file.
''',
        "ProsperoFsFile source-path property",
    )
    text = _replace_once(
        path,
        text,
        '''    public ProsperoFsFile(string origFileName)
    {
        Write = s => { using (var f = File.OpenRead(origFileName)) f.CopyTo(s); };
''',
        '''    public ProsperoFsFile(string origFileName)
    {
        SourcePath = Path.GetFullPath(origFileName);
        Write = s => { using (var f = File.OpenRead(origFileName)) f.CopyTo(s); };
''',
        "ProsperoFsFile source-path capture",
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def _patch_image_builder(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "PackizardProgressCallback" in text:
        return

    text = _replace_once(
        path,
        text,
        '''using System;
using System.Collections.Generic;
using System.IO;
''',
        '''using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
''',
        "diagnostics using",
    )
    text = _replace_once(
        path,
        text,
        '''    /// <summary>Optional already-encoded file payload for the disk-backed writer.</summary>
    public string? DataPath;

    /// <summary>When true the payload is stored raw (never compressed) and is placed block-aligned.</summary>
''',
        '''    /// <summary>Optional already-encoded file payload for the disk-backed writer.</summary>
    public string? DataPath;

    /// <summary>Display path used only for build progress diagnostics.</summary>
    public string? DisplayName;

    /// <summary>When true the payload is stored raw (never compressed) and is placed block-aligned.</summary>
''',
        "payload display name",
    )
    text = _replace_once(
        path,
        text,
        '''    public long BuildToFile(IReadOnlyList<ProsperoPs5InnerPayload> payloads, string outputPath)
    {
''',
        '''    public delegate void PackizardProgressCallback(long completedBytes, long totalBytes, string? currentPath);

    // Keep the original public API for callers that do not need telemetry.
    public long BuildToFile(IReadOnlyList<ProsperoPs5InnerPayload> payloads, string outputPath)
        => BuildToFile(payloads, outputPath, null);

    public long BuildToFile(
        IReadOnlyList<ProsperoPs5InnerPayload> payloads,
        string outputPath,
        PackizardProgressCallback? progress)
    {
''',
        "BuildToFile progress signature",
    )
    text = _replace_once(
        path,
        text,
        '''        using var fs = new FileStream(
            outputPath, FileMode.Create, FileAccess.ReadWrite, FileShare.None,
            1024 * 1024, FileOptions.SequentialScan);

        long pos = 0;
        foreach (var p in payloads)
        {
''',
        '''        using var fs = new FileStream(
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
''',
        "BuildToFile progress setup",
    )
    text = _replace_once(
        path,
        text,
        '''            if (p.DataPath is not null)
            {
                using var input = File.OpenRead(p.DataPath);
                if (p.StoreRaw) input.CopyTo(fs, 1024 * 1024);
                else CompressPayloadToStream(input, fs, input.Length);
            }
            else
            {
                byte[] data = CompressPayload(p.Data, p.StoreRaw);
                fs.Write(data);
            }
''',
        '''            if (p.DataPath is not null)
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
''',
        "stream copy progress",
    )
    text = _replace_once(
        path,
        text,
        '''        fs.SetLength(pos);
        fs.Flush();
        return pos;
''',
        '''        fs.SetLength(pos);
        fs.Flush();
        workDone = totalWork;
        Report(null, force: true);
        return pos;
''',
        "BuildToFile completion progress",
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def _patch_assembler(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "Inner preparation complete:" in text:
        return

    text = _replace_once(
        path,
        text,
        '''using System.Collections.Generic;
using System.Linq;
using System.IO;
''',
        '''using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.IO;
''',
        "assembler diagnostics using",
    )
    text = _replace_once(
        path,
        text,
        '''    public ProsperoPs5InnerImageResult BuildFromFsTree(
        ProsperoFsDir uroot,
        bool preserveCntMetadataInInner = false,
        bool storeAmprCompatibilityPathsRaw = false)
''',
        '''    public ProsperoPs5InnerImageResult BuildFromFsTree(
        ProsperoFsDir uroot,
        bool preserveCntMetadataInInner = false,
        bool storeAmprCompatibilityPathsRaw = false,
        Action<string>? logger = null)
''',
        "BuildFromFsTree logger parameter",
    )
    text = _replace_once(
        path,
        text,
        '''            string path = temps.Create();
            using (var output = new FileStream(path, FileMode.Truncate, FileAccess.Write, FileShare.None))
            {
                f.Write(output);
                if (output.Length != f.Size)
                    throw new IOException($"Source size changed while reading {fullPath}.");
            }
            files.Add(new ProsperoPs5InnerFile
            {
                Path = fullPath,
                DataPath = path,
                Policy = storeAmprCompatibilityPathsRaw && IsAmprCompatibilityStoredPath(fullPath)
                    ? ProsperoInnerFilePolicy.StoreVerbatim
                    : null,
            });
''',
        '''            string? dataPath = storeAmprCompatibilityPathsRaw ? f.SourcePath : null;
            if (string.IsNullOrEmpty(dataPath) || !File.Exists(dataPath))
            {
                dataPath = temps.Create();
                using var output = new FileStream(dataPath, FileMode.Truncate, FileAccess.Write, FileShare.None);
                f.Write(output);
                if (output.Length != f.Size)
                    throw new IOException($"Source size changed while reading {fullPath}.");
            }
            files.Add(new ProsperoPs5InnerFile
            {
                Path = fullPath,
                DataPath = dataPath,
                Policy = storeAmprCompatibilityPathsRaw && IsAmprCompatibilityStoredPath(fullPath)
                    ? ProsperoInnerFilePolicy.StoreVerbatim
                    : null,
            });
''',
        "AMPR direct source I/O",
    )
    text = _replace_once(
        path,
        text,
        '''        return Build(files);
    }
''',
        '''        long inputBytes = files.Sum(f => f.DataPath is { Length: > 0 } ? new FileInfo(f.DataPath).Length : f.Data.LongLength);
        logger?.Invoke($"Inner image input: {files.Count:N0} files, {inputBytes / (1024d * 1024d * 1024d):F2} GiB. " +
            (storeAmprCompatibilityPathsRaw ? "AMPR direct-I/O enabled; redundant staging copy skipped." : "Preparing file-backed layout."));
        return Build(files, logger);
    }
''',
        "BuildFromFsTree progress handoff",
    )
    text = _replace_once(
        path,
        text,
        '''    public ProsperoPs5InnerImageResult Build(IReadOnlyList<ProsperoPs5InnerFile> files)
    {
''',
        '''    public ProsperoPs5InnerImageResult Build(IReadOnlyList<ProsperoPs5InnerFile> files, Action<string>? logger = null)
    {
''',
        "assembler Build logger parameter",
    )

    old_prepare = '''        // ---- 3. Logical offsets (packed, in afid order) + store rule. -----------------------------
        long cursor = 0;
        var afidOffsets = new long[afidOrder.Count];
        foreach (var f in afidOrder)
        {
            f.LogicalOffset = cursor;
            afidOffsets[f.Afid] = cursor;
            cursor = checked(cursor + f.DataLength);
            ProsperoInnerFilePolicy policy = f.Policy
                ?? ProsperoInnerFileClassifier.Classify(f.Header);
            f.StoreRaw = policy == ProsperoInnerFilePolicy.StoreVerbatim
                || policy == ProsperoInnerFilePolicy.RequiresModuleConversion;
            if (f.DataPath is not null)
            {
                if (f.StoreRaw)
                {
                    f.OnDiskPath = f.DataPath;
                    f.OnDiskLength = f.DataLength;
                }
                else
                {
                    f.OnDiskPath = temps.Create();
                    using var input = File.OpenRead(f.DataPath);
                    using var output = new FileStream(f.OnDiskPath, FileMode.Truncate, FileAccess.Write);
                    ProsperoPs5InnerImageBuilder.CompressPayloadToStream(input, output, f.DataLength);
                    f.OnDiskLength = output.Length;
                }
            }
            else
            {
                f.OnDiskData = ProsperoPs5InnerImageBuilder.CompressPayload(f.Data, f.StoreRaw);
                f.OnDiskLength = f.OnDiskData.LongLength;
            }
            f.SceSys = f.FullPath.StartsWith("/sce_sys/", StringComparison.Ordinal);
            f.WholeBlockRaw = IsKeystone(f.FullPath);
        }
'''
    new_prepare = '''        // ---- 3. Logical offsets (packed, in afid order) + store rule. -----------------------------
        logger?.Invoke($"Inner preparation: classifying and encoding {afidOrder.Count:N0} payload files...");
        var prepareWatch = Stopwatch.StartNew();
        int preparedFiles = 0;
        int rawFiles = 0;
        int krakenFiles = 0;
        long preparedInputBytes = 0;
        long preparedStoredBytes = 0;
        long cursor = 0;
        var afidOffsets = new long[afidOrder.Count];
        foreach (var f in afidOrder)
        {
            f.LogicalOffset = cursor;
            afidOffsets[f.Afid] = cursor;
            cursor = checked(cursor + f.DataLength);
            ProsperoInnerFilePolicy policy = f.Policy
                ?? ProsperoInnerFileClassifier.Classify(f.Header);
            f.StoreRaw = policy == ProsperoInnerFilePolicy.StoreVerbatim
                || policy == ProsperoInnerFilePolicy.RequiresModuleConversion;

            int ordinal = preparedFiles + 1;
            string mode = f.StoreRaw ? "RAW" : "KRAKEN";
            logger?.Invoke($"  [{ordinal,4}/{afidOrder.Count}] {mode,-6} {f.DataLength / (1024d * 1024d),10:F2} MiB  {f.FullPath}");
            var fileWatch = Stopwatch.StartNew();

            if (f.DataPath is not null)
            {
                if (f.StoreRaw)
                {
                    f.OnDiskPath = f.DataPath;
                    f.OnDiskLength = f.DataLength;
                }
                else
                {
                    f.OnDiskPath = temps.Create();
                    using var input = File.OpenRead(f.DataPath);
                    using var output = new FileStream(f.OnDiskPath, FileMode.Truncate, FileAccess.Write);
                    ProsperoPs5InnerImageBuilder.CompressPayloadToStream(input, output, f.DataLength);
                    f.OnDiskLength = output.Length;
                }
            }
            else
            {
                f.OnDiskData = ProsperoPs5InnerImageBuilder.CompressPayload(f.Data, f.StoreRaw);
                f.OnDiskLength = f.OnDiskData.LongLength;
            }

            preparedFiles++;
            preparedInputBytes = checked(preparedInputBytes + f.DataLength);
            preparedStoredBytes = checked(preparedStoredBytes + f.OnDiskLength);
            if (f.StoreRaw)
            {
                rawFiles++;
            }
            else
            {
                krakenFiles++;
                double ratio = f.DataLength <= 0 ? 100.0 : f.OnDiskLength * 100.0 / f.DataLength;
                double seconds = Math.Max(0.001, fileWatch.Elapsed.TotalSeconds);
                double speed = f.DataLength / seconds / (1024d * 1024d);
                logger?.Invoke($"       -> {f.OnDiskLength / (1024d * 1024d):F2} MiB ({ratio:F1}% of source) in {seconds:F1}s @ {speed:F1} MiB/s");
            }

            f.SceSys = f.FullPath.StartsWith("/sce_sys/", StringComparison.Ordinal);
            f.WholeBlockRaw = IsKeystone(f.FullPath);
        }
        double prepareSeconds = Math.Max(0.001, prepareWatch.Elapsed.TotalSeconds);
        double aggregateSpeed = preparedInputBytes / prepareSeconds / (1024d * 1024d);
        logger?.Invoke($"Inner preparation complete: {preparedFiles:N0} files ({rawFiles:N0} raw, {krakenFiles:N0} Kraken), " +
            $"{preparedInputBytes / (1024d * 1024d * 1024d):F2} GiB input -> {preparedStoredBytes / (1024d * 1024d * 1024d):F2} GiB stored " +
            $"in {prepareSeconds:F1}s @ {aggregateSpeed:F1} MiB/s.");
'''
    text = _replace_once(path, text, old_prepare, new_prepare, "verbose inner preparation")

    text = _replace_once(
        path,
        text,
        '''        // ---- 4. Dirents (with byte offsets). -------------------------------------------------------
        BuildDirents(uroot);

        // ---- 5. Build the metadata nodes in inode order. ------------------------------------------
''',
        '''        // ---- 4. Dirents (with byte offsets). -------------------------------------------------------
        logger?.Invoke($"Inner metadata: data region = {dataBlocks:N0} blocks; building dirents, inodes and AFID tables...");
        BuildDirents(uroot);

        // ---- 5. Build the metadata nodes in inode order. ------------------------------------------
''',
        "metadata stage log",
    )
    text = _replace_once(
        path,
        text,
        '''        byte[] metaPlain = BuildMetadataPlaintext(nodes, dirsPreOrder, fileNodes, afidOrder, ndblock,
            inodeFltInode, aprFltInode, afidTableInode, uroot);

        // ---- 7. Assemble the data-first image. ----------------------------------------------------
''',
        '''        byte[] metaPlain = BuildMetadataPlaintext(nodes, dirsPreOrder, fileNodes, afidOrder, ndblock,
            inodeFltInode, aprFltInode, afidTableInode, uroot);
        logger?.Invoke($"Inner metadata plaintext ready: {metaPlain.Length / 1024d:F1} KiB, Ndblock={ndblock:N0}. Assembling data-first image...");

        // ---- 7. Assemble the data-first image. ----------------------------------------------------
''',
        "metadata completion log",
    )
    text = _replace_once(
        path,
        text,
        '''        byte[] image = BuildImage(afidOrder, metaPlain, out long blockInfoOnDisk, out long metadataOnDisk,
            out byte[] compressedMeta, out var metaBlocks, out string? imageFilePath, out long imageLength, temps);
''',
        '''        byte[] image = BuildImage(afidOrder, metaPlain, out long blockInfoOnDisk, out long metadataOnDisk,
            out byte[] compressedMeta, out var metaBlocks, out string? imageFilePath, out long imageLength, temps, logger);
''',
        "BuildImage logger handoff",
    )
    text = _replace_once(
        path,
        text,
        '''    private byte[] BuildImage(List<FileNode> afidOrder, byte[] metaPlain,
        out long blockInfoOnDisk, out long metadataOnDisk, out byte[] compressedMeta,
        out IReadOnlyList<ProsperoInnerMetaBlockChunk> metaBlocks,
        out string? imageFilePath, out long imageLength, ProsperoBuildTempFiles temps)
''',
        '''    private byte[] BuildImage(List<FileNode> afidOrder, byte[] metaPlain,
        out long blockInfoOnDisk, out long metadataOnDisk, out byte[] compressedMeta,
        out IReadOnlyList<ProsperoInnerMetaBlockChunk> metaBlocks,
        out string? imageFilePath, out long imageLength, ProsperoBuildTempFiles temps, Action<string>? logger)
''',
        "BuildImage logger parameter",
    )
    text = _replace_once(
        path,
        text,
        '''                Data = f.OnDiskData ?? Array.Empty<byte>(),
                DataPath = f.OnDiskPath,
                StoreRaw = true,
''',
        '''                Data = f.OnDiskData ?? Array.Empty<byte>(),
                DataPath = f.OnDiskPath,
                DisplayName = f.FullPath,
                StoreRaw = true,
''',
        "payload progress name",
    )
    text = _replace_once(
        path,
        text,
        '''        compressedMeta = ProsperoPs5InnerImageBuilder.CompressPayload(metaPlain, storeRaw: false, out var metaPf);
''',
        '''        logger?.Invoke($"Inner image metadata: Kraken-encoding {metaPlain.Length / 1024d:F1} KiB metadata region...");
        compressedMeta = ProsperoPs5InnerImageBuilder.CompressPayload(metaPlain, storeRaw: false, out var metaPf);
        logger?.Invoke($"Inner image metadata encoded: {metaPlain.Length / 1024d:F1} KiB -> {compressedMeta.Length / 1024d:F1} KiB.");
''',
        "metadata Kraken progress",
    )
    text = _replace_once(
        path,
        text,
        '''            imageFilePath = temps.Create();
            long written = new ProsperoPs5InnerImageBuilder().BuildToFile(payloads, imageFilePath);
            if (written != imageLength)
''',
        '''            imageFilePath = temps.Create();
            logger?.Invoke($"Inner image write starting: {imageLength / (1024d * 1024d * 1024d):F2} GiB planned across {payloads.Count:N0} payloads.");
            var imageWriteWatch = Stopwatch.StartNew();
            long written = new ProsperoPs5InnerImageBuilder().BuildToFile(
                payloads,
                imageFilePath,
                (completed, total, currentPath) =>
                {
                    if (logger is null) return;
                    double pct = total <= 0 ? 100.0 : completed * 100.0 / total;
                    double seconds = Math.Max(0.001, imageWriteWatch.Elapsed.TotalSeconds);
                    double bytesPerSecond = completed / seconds;
                    double mibPerSecond = bytesPerSecond / (1024d * 1024d);
                    string eta = bytesPerSecond > 0 && completed < total
                        ? TimeSpan.FromSeconds((total - completed) / bytesPerSecond).ToString(@"hh\\:mm\\:ss")
                        : "00:00:00";
                    string current = string.IsNullOrEmpty(currentPath) ? string.Empty : $" — {currentPath}";
                    logger($"Inner image write: {pct:F1}% — {completed / (1024d * 1024d * 1024d):F2} / {total / (1024d * 1024d * 1024d):F2} GiB — {mibPerSecond:F1} MiB/s — ETA {eta}{current}");
                });
            string elapsed = imageWriteWatch.Elapsed.ToString(@"hh\\:mm\\:ss");
            logger?.Invoke($"Inner image write complete: {written / (1024d * 1024d * 1024d):F2} GiB in {elapsed}.");
            if (written != imageLength)
''',
        "disk-backed inner image progress",
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def _patch_pkg_builder(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "NAPS layout generated:" in text and "Inner image ready:" in text:
        return

    text = _replace_once(
        path,
        text,
        '''                    innerRoot,
                    preserveCntMetadataInInner: packizardAmprProfile,
                    storeAmprCompatibilityPathsRaw: packizardAmprProfile);
            temps.Own(asmResult.ImageFilePath);
''',
        '''                    innerRoot,
                    preserveCntMetadataInInner: packizardAmprProfile,
                    storeAmprCompatibilityPathsRaw: packizardAmprProfile,
                    logger: log);
            temps.Own(asmResult.ImageFilePath);
            log($"Inner image ready: {asmResult.ImageLength / (1024d * 1024d * 1024d):F2} GiB; generating NAPS metadata.");
''',
        "package-builder progress logger",
    )
    text = _replace_once(
        path,
        text,
        '''            byte[] nwonlyNaps = ProsperoNwonlyNapsGenerator.Generate(asmResult);
''',
        '''            byte[] nwonlyNaps = ProsperoNwonlyNapsGenerator.Generate(asmResult);
            log($"NAPS layout generated: {nwonlyNaps.Length:N0} bytes; calculating PlayGo/FIH metadata.");
''',
        "NAPS completion log",
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def apply(root: Path) -> None:
    root = Path(root)
    paths = [root / rel for rel in (FS_TREE_REL, IMAGE_BUILDER_REL, ASSEMBLER_REL, PKG_BUILDER_REL)]
    for path in paths:
        if not path.is_file():
            raise RuntimeError(f"Missing reconstructed LibProsperoPKG source for PKG progress profile: {path}")

    _patch_fs_tree(root / FS_TREE_REL)
    _patch_image_builder(root / IMAGE_BUILDER_REL)
    _patch_assembler(root / ASSEMBLER_REL)
    _patch_pkg_builder(root / PKG_BUILDER_REL)
    print("Applied Packizard integrated-PKG direct-I/O and detailed progress telemetry")
