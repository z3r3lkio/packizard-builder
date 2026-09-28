#!/usr/bin/env python3
"""Apply Packizard AMPR/LZ4 compatibility behavior to reconstructed LibProsperoPKG.

The compact repository reconstructs the runtime source tree in CI. Keep the
AMPR-specific delta here rather than forking the entire upstream engine: normal
LibProsperoPKG package builds retain their existing behavior, while a prepared
Packizard AMPR tree is detected automatically and gets the compatibility policy
validated during the PPSA09806 investigation.
"""
from __future__ import annotations

from pathlib import Path


ASSEMBLER_REL = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PFS/ProsperoPs5InnerImageAssembler.cs")
PKG_BUILDER_REL = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PKG/ProsperoPkgBuilder.cs")


def _replace_once(path: Path, text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"AMPR compatibility patch expected exactly one {label} in {path}, found {count}. "
            "The pinned LibProsperoPKG override changed and the profile must be rebased explicitly."
        )
    return text.replace(old, new, 1)


def _patch_assembler(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "Packizard AMPR compatibility: preserve CNT metadata in the inner image" in text:
        return

    old_bridge = '''    public ProsperoPs5InnerImageResult BuildFromFsTree(ProsperoFsDir uroot)
    {
        ArgumentNullException.ThrowIfNull(uroot);
        using var temps = new ProsperoBuildTempFiles();
        var files = new List<ProsperoPs5InnerFile>();
        foreach (var f in uroot.GetAllChildrenFiles())
        {
            if (IsExcludedFromInner(f.FullPath())) continue;
            string path = temps.Create();
            using (var output = new FileStream(path, FileMode.Truncate, FileAccess.Write, FileShare.None))
            {
                f.Write(output);
                if (output.Length != f.Size)
                    throw new IOException($"Source size changed while reading {f.FullPath()}.");
            }
            files.Add(new ProsperoPs5InnerFile { Path = f.FullPath(), DataPath = path });
        }
        return Build(files);
    }
'''
    new_bridge = '''    public ProsperoPs5InnerImageResult BuildFromFsTree(
        ProsperoFsDir uroot,
        bool preserveCntMetadataInInner = false,
        bool storeAmprCompatibilityPathsRaw = false)
    {
        ArgumentNullException.ThrowIfNull(uroot);
        using var temps = new ProsperoBuildTempFiles();
        var files = new List<ProsperoPs5InnerFile>();
        foreach (var f in uroot.GetAllChildrenFiles())
        {
            string fullPath = f.FullPath();
            // Packizard AMPR compatibility: preserve CNT metadata in the inner image as well as
            // emitting the normal CNT payload. The direct Shadowmount/LZ tree exposes these files
            // through /app0 and some titles depend on that view during common-dialog startup.
            // Stale PlayGo descriptors are the exception: they describe the original package's
            // chunk layout and must never be copied into the rebuilt unified PKG image.
            if (preserveCntMetadataInInner && IsPackizardStalePlayGoPath(fullPath)) continue;
            if (!preserveCntMetadataInInner && IsExcludedFromInner(fullPath)) continue;
            string path = temps.Create();
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
        }
        return Build(files);
    }
'''
    text = _replace_once(path, text, old_bridge, new_bridge, "BuildFromFsTree bridge")

    old_exclusion = '''    private static bool IsExcludedFromInner(string fullPath)
    {
        const string prefix = "/sce_sys/";
        if (!fullPath.StartsWith(prefix, StringComparison.Ordinal)) return false;
        string rel = fullPath.Substring(prefix.Length);
        return rel == "param.json" || PKG.ProsperoCntEntryNames.NameToId.ContainsKey(rel);
    }
'''
    new_exclusion = '''    private static bool IsExcludedFromInner(string fullPath)
    {
        const string prefix = "/sce_sys/";
        if (!fullPath.StartsWith(prefix, StringComparison.Ordinal)) return false;
        string rel = fullPath.Substring(prefix.Length);
        return rel == "param.json" || PKG.ProsperoCntEntryNames.NameToId.ContainsKey(rel);
    }

    // Source PlayGo data describes the dump/original package. A rebuilt PKG has a different
    // mount image, so carrying these descriptors into /app0/sce_sys can make PlayGo reject the
    // package before eboot.bin is executed (for example SCE_KERNEL_ERROR_EINVAL / 0x80020016).
    private static bool IsPackizardStalePlayGoPath(string fullPath)
    {
        const string prefix = "/sce_sys/playgo";
        return fullPath.StartsWith(prefix, StringComparison.OrdinalIgnoreCase);
    }

    // AMPR/LZ4 volumes already contain independently addressable compressed chunks. Re-wrapping the
    // root AMPR payloads in Kraken changes their random-access backing semantics, so the Packizard AMPR
    // profile stores those files verbatim. sce_sys and sce_module are also kept raw to mirror the
    // compatibility layout used by the package-tool reference. Normal package builds never enable
    // this policy and therefore retain the upstream classifier unchanged.
    private static bool IsAmprCompatibilityStoredPath(string fullPath)
    {
        if (fullPath.StartsWith("/sce_sys/", StringComparison.Ordinal)
            || fullPath.StartsWith("/sce_module/", StringComparison.Ordinal))
            return true;

        if (fullPath is "/eboot.bin" or "/eboot.bin.bak")
            return true;

        // Only root-level AMPR control/index/volume files are forced raw. Do not match Media/** or
        // arbitrary nested files that happen to contain an AMPR-like name.
        if (!fullPath.StartsWith("/", StringComparison.Ordinal)
            || fullPath.IndexOf('/', 1) >= 0)
            return false;

        string name = fullPath[1..];
        if (name is "ampr_assets.index" or "ampr_assets.index.crc" or "ampr_assets.index.runtime" or "ampr_emu.index")
            return true;

        return name.StartsWith("ampr_assets-", StringComparison.Ordinal)
            && name.EndsWith(".pak", StringComparison.Ordinal);
    }
'''
    text = _replace_once(path, text, old_exclusion, new_exclusion, "inner exclusion policy")
    path.write_text(text, encoding="utf-8", newline="\n")


def _patch_pkg_builder(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "Packizard AMPR/LZ4 compatibility profile enabled" in text:
        return

    old_source = '''        string sourceFolder = Path.GetFullPath(props.SourceFolder);

        // EKPFS (index 1) from content id + passcode. PS5 outer PFS uses the SHA3-256 key ladder
'''
    new_source = '''        string sourceFolder = Path.GetFullPath(props.SourceFolder);
        bool packizardAmprProfile = IsPackizardAmprTree(sourceFolder);
        if (packizardAmprProfile)
            log("Packizard AMPR/LZ4 compatibility profile enabled: preserving AMPR payloads raw, dropping stale PlayGo descriptors, and sanitizing PKG launch metadata.");

        // EKPFS (index 1) from content id + passcode. PS5 outer PFS uses the SHA3-256 key ladder
'''
    text = _replace_once(path, text, old_source, new_source, "source-folder profile detection")

    old_call = '''            LibProsperoPkg.PFS.ProsperoPs5InnerImageResult asmResult =
                new LibProsperoPkg.PFS.ProsperoPs5InnerImageAssembler(fileTime, 0).BuildFromFsTree(innerRoot);
'''
    new_call = '''            LibProsperoPkg.PFS.ProsperoPs5InnerImageResult asmResult =
                new LibProsperoPkg.PFS.ProsperoPs5InnerImageAssembler(fileTime, 0).BuildFromFsTree(
                    innerRoot,
                    preserveCntMetadataInInner: packizardAmprProfile,
                    storeAmprCompatibilityPathsRaw: packizardAmprProfile);
'''
    text = _replace_once(path, text, old_call, new_call, "inner assembler invocation")

    old_param_reader = '''    private static byte[] ReadParamJson(string sourceFolder)
    {
        var path = Path.Combine(sourceFolder, "sce_sys", "param.json");
        if (!File.Exists(path))
            throw new FileNotFoundException("sce_sys/param.json is required to build a PS5 package.", path);
        return NormalizeParamJson(File.ReadAllBytes(path));
    }
'''
    new_param_reader = '''    private static byte[] ReadParamJson(string sourceFolder)
    {
        var path = Path.Combine(sourceFolder, "sce_sys", "param.json");
        if (!File.Exists(path))
            throw new FileNotFoundException("sce_sys/param.json is required to build a PS5 package.", path);
        return NormalizeParamJson(File.ReadAllBytes(path), IsPackizardAmprTree(sourceFolder));
    }
'''
    text = _replace_once(path, text, old_param_reader, new_param_reader, "param.json reader")

    old_normalizer = '''    private static byte[] NormalizeParamJson(byte[] paramJson)
    {
        if (paramJson.Length == 0)
            return paramJson;
        string text;
        try { text = Encoding.UTF8.GetString(paramJson); }
        catch { return paramJson; }

        string updated = PromoteZeroVersion(text, "sdkVersion");
        updated = PromoteZeroVersion(updated, "requiredSystemSoftwareVersion");
        return ReferenceEquals(updated, text) || updated == text ? paramJson : Encoding.UTF8.GetBytes(updated);
    }
'''
    new_normalizer = '''    private static byte[] NormalizeParamJson(byte[] paramJson, bool packizardAmprProfile = false)
    {
        if (paramJson.Length == 0)
            return paramJson;
        string text;
        try { text = Encoding.UTF8.GetString(paramJson); }
        catch { return paramJson; }

        string updated = PromoteZeroVersion(text, "sdkVersion");
        updated = PromoteZeroVersion(updated, "requiredSystemSoftwareVersion");

        if (packizardAmprProfile)
        {
            // The rebuilt FPKG owns its PlayGo metadata. Do not keep the source package's update URI
            // or attribute3 flags: both can make PlayGo treat the regenerated single-image package as
            // if it still had the original publisher chunk topology, causing an application error before
            // /app0 is mounted. This rewrite is in-memory; the source param.json is never modified.
            updated = ClearJsonString(updated, "versionFileUri");
            updated = ClearJsonInteger(updated, "attribute3");
        }

        return ReferenceEquals(updated, text) || updated == text ? paramJson : Encoding.UTF8.GetBytes(updated);
    }

    private static string ClearJsonString(string json, string key)
    {
        var rx = new Regex("(\\\"" + Regex.Escape(key) + "\\\"\\s*:\\s*\\\")[^\\\"]*(\\\")");
        return rx.Replace(json, "${1}${2}", 1);
    }

    private static string ClearJsonInteger(string json, string key)
    {
        var rx = new Regex("(\\\"" + Regex.Escape(key) + "\\\"\\s*:\\s*)(?:-?[0-9]+|\\\"(?:0x[0-9A-Fa-f]+|[0-9]+)\\\")");
        return rx.Replace(json, "${1}0", 1);
    }
'''
    text = _replace_once(path, text, old_normalizer, new_normalizer, "AMPR param.json normalization")

    marker = '''    /// <summary>The content-type code for a PS5 volume kind.</summary>
    public static uint ContentTypeFor(ProsperoVolumeType type) => type switch
'''
    helper = '''    // A Packizard-compressed tree is self-identifying: the AMPR indexes and at least one root
    // volume are emitted only after a successful LZ4/AMPR stage. Detection here makes both entry
    // points (Compress -> PKG and manual Build PKG) use the same engine/profile without a second UI
    // switch or an external helper-specific flag.
    private static bool IsPackizardAmprTree(string sourceFolder)
    {
        if (!File.Exists(Path.Combine(sourceFolder, "ampr_assets.index"))
            || !File.Exists(Path.Combine(sourceFolder, "ampr_emu.index")))
            return false;

        return Directory.EnumerateFiles(sourceFolder, "ampr_assets-*.pak", SearchOption.TopDirectoryOnly).Any();
    }

    /// <summary>The content-type code for a PS5 volume kind.</summary>
    public static uint ContentTypeFor(ProsperoVolumeType type) => type switch
'''
    text = _replace_once(path, text, marker, helper, "AMPR detector insertion point")
    path.write_text(text, encoding="utf-8", newline="\n")


def apply(root: Path) -> None:
    """Patch the reconstructed engine in-place and fail closed on an upstream drift."""
    root = Path(root)
    assembler = root / ASSEMBLER_REL
    pkg_builder = root / PKG_BUILDER_REL
    for path in (assembler, pkg_builder):
        if not path.is_file():
            raise RuntimeError(f"Missing reconstructed LibProsperoPKG source for AMPR profile: {path}")

    _patch_assembler(assembler)
    _patch_pkg_builder(pkg_builder)
    print("Applied Packizard AMPR/LZ4 integrated-PKG compatibility profile")
