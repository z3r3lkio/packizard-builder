#!/usr/bin/env python3
"""Add low-overhead progress telemetry and AMPR direct-I/O to the reconstructed PKG engine.

This profile is applied after the generic large-package overrides and the AMPR compatibility
profile. It keeps the bridge protocol unchanged: LibProsperoPKG progress is emitted through the
existing logger, which Packizard.PkgBridge already forwards to the GUI.
"""
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

    old_class = '''public class ProsperoFsFile : ProsperoFsNode
{
    /// <summary>
    /// Creates an FSFile from a real on-disk file.
'''
    new_class = '''public class ProsperoFsFile : ProsperoFsNode
{
    /// <summary>
    /// Packizard direct-I/O source path. Non-null only for nodes created from a real on-disk file;
    /// generated/in-memory nodes keep using the writer delegate and are materialized as before.
    /// </summary>
    public string SourcePath { get; private set; }

    /// <summary>
    /// Creates an FSFile from a real on-disk file.
'''
    text = _replace_once(path, text, old_class, new_class, "ProsperoFsFile source-path property")

    old_ctor = '''    public ProsperoFsFile(string origFileName)
    {
        Write = s => { using (var f = File.OpenRead(origFileName)) f.CopyTo(s); };
'''
    new_ctor = '''    public ProsperoFsFile(string origFileName)
    {
        SourcePath = Path.GetFullPath(origFileName);
        Write = s => { using (var f = File.OpenRead(origFileName)) f.CopyTo(s); };
'''
    text = _replace_once(path, text, old_ctor, new_ctor, "ProsperoFsFile source-path capture")
    path.write_text(text, encoding="utf-8", newline="\n")


def _patch_image_builder(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "PackizardProgressCallback" in text:
        return

    old_usings = '''using System;
using System.Collections.Generic;
using System.IO;
'''
    new_usings = '''using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
'''
    text = _replace_once(path, text, old_usings, new_usings, "diagnostics using")

    old_path = '''    /// <summary>Optional already-encoded file payload for the disk-backed writer.</summary>
    public string? DataPath;

    /// <summary>When true the payload is stored raw (never compressed) and is placed block-aligned.</summary>
'''
    new_path = '''    /// <summary>Optional already-encoded file payload for the disk-backed writer.</summary>
    public string? DataPath;

    /// <summary>Display path used only for build progress diagnostics.</summary>
    public string? DisplayName;

    /// <summary>When true the payload is stored raw (never compressed) and is placed block-aligned.</summary>
'''
    text = _replace_once(path, text, old_path, new_path, "payload display name")

    old_sig = '''    public long BuildToFile(IReadOnlyList<ProsperoPs5InnerPayload> payloads, string outputPath)
    {
'''
    new_sig = '''    public delegate void PackizardProgressCallback(long completedBytes, long totalBytes, string? currentPath);

    // Keep the original public API for callers that do not need telemetry.
    public long BuildToFile(IReadOnlyList<ProsperoPs5InnerPayload> payloads, string outputPath)
        => BuildToFile(payloads, outputPath, null);

    public long BuildToFile(
        IReadOnlyList<ProsperoPs5InnerPayload> payloads,
        string outputPath,
        PackizardProgressCallback? progress)
    {
'''
    text = _replace_once(path, text, old_sig, new_sig, "BuildToFile progress signature")

    old_setup = '''        using var fs = new FileStream(
            outputPath, FileMode.Create, FileAccess.ReadWrite, FileShare.None,
            1024 * 1024, FileOptions.SequentialScan);

        long pos = 0;
        foreach (var p in payloads)
        {
'''
    new_setup = '''        using var fs = new FileStream(
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
            // At most one line per second, plus a 3-second heartbeat if the integer percentage
            // has not advanced (large files / slow disks). This keeps the GUI informative without spam.
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
'''
    text = _replace_once(path, text, old_setup, new_setup, "BuildToFile progress setup")

    old_copy = '''            if (p.DataPath is not null)
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
'''
    new_copy = '''            if (p.DataPath is not null)
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
'''
    text = _replace_once(path, text, old_copy, new_copy, "stream copy progress")

    old_end = '''        fs.SetLength(pos);
        fs.Flush();
        return pos;
'''
    new_end = '''        fs.SetLength(pos);
        fs.Flush();
        workDone = totalWork;
        Report(null, force: true);
        return pos;
'''
    text = _replace_once(path, text, old_end, new_end, "BuildToFile completion progress")
    path.write_text(text, encoding="utf-8", newline="\n")


def _patch_assembler(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "Inner image write:" in text:
        return

    old_usings = '''using System.Collections.Generic;
using System.Linq;
using System.IO;
'''
    new_usings = '''using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.IO;
'''
    text = _replace_once(path, text, old_usings, new_usings, "assembler diagnostics using")

    old_bridge_sig = '''    public ProsperoPs5InnerImageResult BuildFromFsTree(
        ProsperoFsDir uroot,
        bool preserveCntMetadataInInner = false,
        bool storeAmprCompatibilityPathsRaw = false)
'''
    new_bridge_sig = '''    public ProsperoPs5InnerImageResult BuildFromFsTree(
        ProsperoFsDir uroot,
        bool preserveCntMetadataInInner = false,
        bool storeAmprCompatibilityPathsRaw = false,
        Action<string>? logger = null)
'''
    text = _replace_once(path, text, old_bridge_sig, new_bridge_sig, "BuildFromFsTree logger parameter")

    old_materialize = '''            string path = temps.Create();
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
'''
    new_materialize = '''            // AMPR trees are already made of large, immutable on-disk volumes. Keep their real
            // source path instead of first cloning every file into a temporary staging tree; the old
            // path doubled disk I/O before image writing and looked like a hang on large titles.
            string? dataPath = storeAmprCompatibilityPathsRaw ? f.SourcePath : null;
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
'''
    text = _replace_once(path, text, old_materialize, new_materialize, "AMPR direct source I/O")

    old_return = '''        return Build(files);
    }
'''
    new_return = '''        long inputBytes = files.Sum(f => f.DataPath is { Length: > 0 } ? new FileInfo(f.DataPath).Length : f.Data.LongLength);
        logger?.Invoke($"Inner image input: {files.Count:N0} files, {inputBytes / (1024d * 1024d * 1024d):F2} GiB. " +
            (storeAmprCompatibilityPathsRaw ? "AMPR direct-I/O enabled; redundant staging copy skipped." : "Preparing file-backed layout."));
        return Build(files, logger);
    }
'''
    text = _replace_once(path, text, old_return, new_return, "BuildFromFsTree progress handoff")

    old_build_sig = '''    public ProsperoPs5InnerImageResult Build(IReadOnlyList<ProsperoPs5InnerFile> files)
    {
'''
    new_build_sig = '''    public ProsperoPs5InnerImageResult Build(IReadOnlyList<ProsperoPs5InnerFile> files, Action<string>? logger = null)
    {
'''
    text = _replace_once(path, text, old_build_sig, new_build_sig, "assembler Build logger parameter")

    old_build_image_call = '''        byte[] image = BuildImage(afidOrder, metaPlain, out long blockInfoOnDisk, out long metadataOnDisk,
            out byte[] compressedMeta, out var metaBlocks, out string? imageFilePath, out long imageLength, temps);
'''
    new_build_image_call = '''        byte[] image = BuildImage(afidOrder, metaPlain, out long blockInfoOnDisk, out long metadataOnDisk,
            out byte[] compressedMeta, out var metaBlocks, out string? imageFilePath, out long imageLength, temps, logger);
'''
    text = _replace_once(path, text, old_build_image_call, new_build_image_call, "BuildImage logger handoff")

    old_build_image_sig = '''    private byte[] BuildImage(List<FileNode> afidOrder, byte[] metaPlain,
        out long blockInfoOnDisk, out long metadataOnDisk, out byte[] compressedMeta,
        out IReadOnlyList<ProsperoInnerMetaBlockChunk> metaBlocks,
        out string? imageFilePath, out long imageLength, ProsperoBuildTempFiles temps)
'''
    new_build_image_sig = '''    private byte[] BuildImage(List<FileNode> afidOrder, byte[] metaPlain,
        out long blockInfoOnDisk, out long metadataOnDisk, out byte[] compressedMeta,
        out IReadOnlyList<ProsperoInnerMetaBlockChunk> metaBlocks,
        out string? imageFilePath, out long imageLength, ProsperoBuildTempFiles temps, Action<string>? logger)
'''
    text = _replace_once(path, text, old_build_image_sig, new_build_image_sig, "BuildImage logger parameter")

    old_payload = '''                Data = f.OnDiskData ?? Array.Empty<byte>(),
                DataPath = f.OnDiskPath,
                StoreRaw = true,
'''
    new_payload = '''                Data = f.OnDiskData ?? Array.Empty<byte>(),
                DataPath = f.OnDiskPath,
                DisplayName = f.FullPath,
                StoreRaw = true,
'''
    text = _replace_once(path, text, old_payload, new_payload, "payload progress name")

    old_write = '''            imageFilePath = temps.Create();
            long written = new ProsperoPs5InnerImageBuilder().BuildToFile(payloads, imageFilePath);
            if (written != imageLength)
'''
    new_write = '''            imageFilePath = temps.Create();
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
'''
    text = _replace_once(path, text, old_write, new_write, "disk-backed inner image progress")
    path.write_text(text, encoding="utf-8", newline="\n")


def _patch_pkg_builder(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "logger: log" in text and "Inner image ready:" in text:
        return

    old_call = '''                    innerRoot,
                    preserveCntMetadataInInner: packizardAmprProfile,
                    storeAmprCompatibilityPathsRaw: packizardAmprProfile);
            temps.Own(asmResult.ImageFilePath);
'''
    new_call = '''                    innerRoot,
                    preserveCntMetadataInInner: packizardAmprProfile,
                    storeAmprCompatibilityPathsRaw: packizardAmprProfile,
                    logger: log);
            temps.Own(asmResult.ImageFilePath);
            log($"Inner image ready: {asmResult.ImageLength / (1024d * 1024d * 1024d):F2} GiB; generating NAPS metadata.");
'''
    text = _replace_once(path, text, old_call, new_call, "package-builder progress logger")
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
    print("Applied Packizard integrated-PKG direct-I/O and progress telemetry")
