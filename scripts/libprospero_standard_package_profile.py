from __future__ import annotations

from pathlib import Path

PKG_BUILDER = Path("src/LibProsperoPkg/PKG/ProsperoPkgBuilder.cs")
HIGH_LEVEL_BUILDER = Path("src/LibProsperoPkg/ProsperoPackageBuilder.cs")
INNER_ASSEMBLER = Path("src/LibProsperoPkg/PFS/ProsperoPs5InnerImageAssembler.cs")

# MkPFS.CSharp's PS5PkgTool-parity path confirms that the pinned LibProsperoPKG
# architecture we already start from is the correct base:
#
#   data-first inner image + naps_pkg_layout.dat
#       -> SHA3 signed / AES-XTS encrypted outer PFS
#       -> imagedigs.dat from plaintext outer blocks
#       -> CNT / FIH / SI
#
# Do NOT replace that path with a conventional superblock-first PFS + PFSC
# nested image. The ImageProfile option remains part of Packizard's bridge
# contract so old requests keep working, but Standard intentionally preserves
# the pinned package builder's native data-first/NAPS implementation.

_LOW_LEVEL_PROP_MARKER = """    /// <summary>The volume timestamp written into the PFS inode table.</summary>
    public DateTime TimeStamp { get; init; } = DateTime.UnixEpoch;
"""
_LOW_LEVEL_PROP_PATCHED = """    /// <summary>The volume timestamp written into the PFS inode table.</summary>
    public DateTime TimeStamp { get; init; } = DateTime.UnixEpoch;

    /// <summary>
    /// Package-image profile selected by Packizard. Standard preserves the pinned
    /// PS5PkgTool/MkPFS-compatible data-first + NAPS + encrypted outer-PFS path.
    /// Nwonly is retained only as a request/API compatibility label.
    /// </summary>
    public LibProsperoPkg.ProsperoPackageImageProfile ImageProfile { get; init; } =
        LibProsperoPkg.ProsperoPackageImageProfile.Standard;

    /// <summary>Optional deterministic 16-byte outer-PFS seed used by parity tests.</summary>
    public byte[]? OuterSeed { get; init; }

    /// <summary>When true, emit the inner image without Kraken compression.</summary>
    public bool StoreInnerImage { get; init; }
"""

_HIGH_ENUM_MARKER = """/// <summary>Options describing the PS5 package to build.</summary>
public sealed class ProsperoBuildOptions
"""
_HIGH_ENUM_PATCHED = """/// <summary>
/// Package image profile. Standard is the PS5PkgTool/MkPFS parity path:
/// data-first inner image + NAPS inside a SHA3-signed/AES-XTS outer PFS.
/// </summary>
public enum ProsperoPackageImageProfile
{
    Standard,
    Nwonly,
}

/// <summary>Options describing the PS5 package to build.</summary>
public sealed class ProsperoBuildOptions
"""

_HIGH_PROP_MARKER = """    public ProsperoOutputFormat OutputFormat { get; set; } = ProsperoOutputFormat.DebugImage;

    /// <summary>Folder whose contents become the package image (must contain <c>sce_sys/</c>).</summary>
"""
_HIGH_PROP_PATCHED = """    public ProsperoOutputFormat OutputFormat { get; set; } = ProsperoOutputFormat.DebugImage;

    /// <summary>
    /// Image layout profile. Standard preserves the pinned package builder's
    /// PS5PkgTool/MkPFS-compatible data-first/NAPS outer-PFS pipeline.
    /// </summary>
    public ProsperoPackageImageProfile ImageProfile { get; set; } = ProsperoPackageImageProfile.Standard;

    /// <summary>Optional deterministic 16-byte outer-PFS seed used by parity tests.</summary>
    public byte[]? OuterSeed { get; set; }

    /// <summary>When true, emit the inner image without Kraken compression (parity/stored mode).</summary>
    public bool StoreInnerImage { get; set; }

    /// <summary>Folder whose contents become the package image (must contain <c>sce_sys/</c>).</summary>
"""

_BUILD_PROPS_MARKER = """            VolumeType = ProsperoVolumeTypeForMode(options.Mode),
        };
"""
_BUILD_PROPS_PATCHED = """            VolumeType = ProsperoVolumeTypeForMode(options.Mode),
            ImageProfile = options.ImageProfile,
            OuterSeed = options.OuterSeed,
            StoreInnerImage = options.StoreInnerImage,
        };
"""


def _replace(path: Path, old: str, new: str, label: str) -> bool:
    if not path.is_file():
        raise RuntimeError(f"LibProsperoPKG {label} is missing: {path}")
    text = path.read_text(encoding="utf-8")
    if new in text:
        return False
    if old not in text:
        raise RuntimeError(
            f"Pinned LibProsperoPKG {label} no longer matches the parity-profile preimage; "
            "review the pinned engine before updating it."
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def apply_standard_package_profile(vendor_dir: str | Path) -> bool:
    """Expose Packizard's profile option without replacing the native image pipeline."""
    vendor = Path(vendor_dir)
    low = vendor / PKG_BUILDER
    high = vendor / HIGH_LEVEL_BUILDER
    changed = False
    changed |= _replace(low, _LOW_LEVEL_PROP_MARKER, _LOW_LEVEL_PROP_PATCHED, "parity profile property")
    changed |= _replace(
        low,
        "byte[] outerSeed = System.Security.Cryptography.RandomNumberGenerator.GetBytes(16);",
        "byte[] outerSeed = props.OuterSeed is { Length: 16 } ? (byte[])props.OuterSeed.Clone() : System.Security.Cryptography.RandomNumberGenerator.GetBytes(16);",
        "deterministic outer seed",
    )
    changed |= _replace(
        low,
        "new LibProsperoPkg.PFS.ProsperoPs5InnerImageAssembler(fileTime, 0)",
        "new LibProsperoPkg.PFS.ProsperoPs5InnerImageAssembler(fileTime, 0, compress: !props.StoreInnerImage)",
        "inner compression selection",
    )
    changed |= _replace(high, _HIGH_ENUM_MARKER, _HIGH_ENUM_PATCHED, "parity profile enum")
    changed |= _replace(high, _HIGH_PROP_MARKER, _HIGH_PROP_PATCHED, "parity profile option")
    changed |= _replace(high, _BUILD_PROPS_MARKER, _BUILD_PROPS_PATCHED, "parity profile propagation")

    assembler = vendor / INNER_ASSEMBLER
    changed |= _replace(
        assembler,
        "    private readonly uint _timeNsec;\n",
        "    private readonly uint _timeNsec;\n    private readonly bool _compress;\n",
        "inner compression field",
    )
    changed |= _replace(
        assembler,
        "    public ProsperoPs5InnerImageAssembler(long buildTimeSec, uint buildTimeNsec)\n    {\n        _timeSec = buildTimeSec;\n        _timeNsec = buildTimeNsec;\n    }",
        "    public ProsperoPs5InnerImageAssembler(long buildTimeSec, uint buildTimeNsec, bool compress = true)\n    {\n        _timeSec = buildTimeSec;\n        _timeNsec = buildTimeNsec;\n        _compress = compress;\n    }",
        "inner compression constructor",
    )
    changed |= _replace(
        assembler,
        "            ProsperoInnerFilePolicy policy = f.Policy\n                ?? ProsperoInnerFileClassifier.Classify(\n                    f.Data.AsSpan(0, Math.Min(f.Data.Length, ProsperoInnerFileClassifier.HeaderLength)));\n            // An unsigned executable image is meant to become a signed module before it reaches the\n            // image; the caller owns that conversion. Reaching here with one is not an error, so it is\n            // stored as it stands rather than failing a build that would otherwise succeed.\n            if (policy == ProsperoInnerFilePolicy.StoreVerbatim\n                || policy == ProsperoInnerFilePolicy.RequiresModuleConversion)",
        "            ProsperoInnerFilePolicy policy = f.Policy\n                ?? ProsperoInnerFileClassifier.Classify(\n                    f.Data.AsSpan(0, Math.Min(f.Data.Length, ProsperoInnerFileClassifier.HeaderLength)));\n            // Stored parity mode keeps every file raw. Otherwise preserve the normal classifier.\n            if (!_compress || policy == ProsperoInnerFilePolicy.StoreVerbatim\n                || policy == ProsperoInnerFilePolicy.RequiresModuleConversion)",
        "stored file payloads",
    )
    changed |= _replace(
        assembler,
        "        compressedMeta = ProsperoPs5InnerImageBuilder.CompressPayload(metaPlain, storeRaw: false, out var metaPf);",
        "        compressedMeta = ProsperoPs5InnerImageBuilder.CompressPayload(metaPlain, storeRaw: !_compress, out var metaPf);",
        "stored metadata payload",
    )
    return changed
