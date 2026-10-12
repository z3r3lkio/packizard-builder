from __future__ import annotations

from pathlib import Path

PKG_BUILDER = Path("src/LibProsperoPkg/PKG/ProsperoPkgBuilder.cs")
HIGH_LEVEL_BUILDER = Path("src/LibProsperoPkg/ProsperoPackageBuilder.cs")

# Parity architecture: data-first inner image + naps_pkg_layout.dat
# -> SHA3 signed / AES-XTS encrypted outer PFS -> imagedigs.dat -> CNT/FIH/SI.
# The PS5 inner assembler itself is owned as a deterministic Packizard override
# copied by prepare_pkg_bridge.py before these high/low-level profile changes run.


def _load(path: Path, label: str) -> str:
    if not path.is_file():
        raise RuntimeError(f"LibProsperoPKG {label} is missing: {path}")
    return path.read_text(encoding="utf-8")


def _write_if_changed(path: Path, before: str, after: str) -> bool:
    if before == after:
        return False
    path.write_text(after, encoding="utf-8")
    return True


def _insert_after_once(text: str, anchor: str, addition: str, present: str, label: str) -> str:
    if present in text:
        return text
    if anchor not in text:
        raise RuntimeError(f"Pinned LibProsperoPKG {label} anchor not found.")
    return text.replace(anchor, anchor + addition, 1)


def _replace_token_once(text: str, old: str, new: str, present: str, label: str) -> str:
    if present in text:
        return text
    if old not in text:
        raise RuntimeError(f"Pinned LibProsperoPKG {label} token not found.")
    return text.replace(old, new, 1)


def apply_standard_package_profile(vendor_dir: str | Path) -> bool:
    """Apply Packizard's high/low-level MkPFS parity controls idempotently.

    The inner assembler is not text-patched here. Packizard owns a deterministic
    override copied by prepare_pkg_bridge.py before the remaining vendor profiles run.
    """
    vendor = Path(vendor_dir)
    low = vendor / PKG_BUILDER
    high = vendor / HIGH_LEVEL_BUILDER
    changed = False

    # ---- low-level ProsperoPkgBuildProperties / package builder -------------------
    before = _load(low, "package builder")
    text = before

    low_time = "    public DateTime TimeStamp { get; init; } = DateTime.UnixEpoch;\n"
    low_props = """
    /// <summary>
    /// Package-image profile selected by Packizard. Standard preserves the pinned
    /// PS5PkgTool/MkPFS-compatible data-first + NAPS + encrypted outer-PFS path.
    /// </summary>
    public LibProsperoPkg.ProsperoPackageImageProfile ImageProfile { get; init; } =
        LibProsperoPkg.ProsperoPackageImageProfile.Standard;

    /// <summary>Optional deterministic 16-byte outer-PFS seed used by parity tests.</summary>
    public byte[]? OuterSeed { get; init; }

    /// <summary>When true, emit the inner image without Kraken compression.</summary>
    public bool StoreInnerImage { get; init; }
"""
    text = _insert_after_once(
        text,
        low_time,
        low_props,
        "public bool StoreInnerImage { get; init; }",
        "low-level parity properties",
    )

    text = _replace_token_once(
        text,
        "byte[] outerSeed = System.Security.Cryptography.RandomNumberGenerator.GetBytes(16);",
        "byte[] outerSeed = props.OuterSeed is { Length: 16 } "
        "? (byte[])props.OuterSeed.Clone() "
        ": System.Security.Cryptography.RandomNumberGenerator.GetBytes(16);",
        "props.OuterSeed is { Length: 16 }",
        "deterministic outer seed",
    )

    text = _replace_token_once(
        text,
        "new LibProsperoPkg.PFS.ProsperoPs5InnerImageAssembler(fileTime, 0)",
        "new LibProsperoPkg.PFS.ProsperoPs5InnerImageAssembler("
        "fileTime, 0, compress: !props.StoreInnerImage)",
        "compress: !props.StoreInnerImage",
        "inner compression selection",
    )

    changed |= _write_if_changed(low, before, text)

    # ---- high-level public build API ----------------------------------------------
    before = _load(high, "high-level package builder")
    text = before

    enum_anchor = (
        "/// <summary>Options describing the PS5 package to build.</summary>\n"
        "public sealed class ProsperoBuildOptions\n"
    )
    enum_text = """/// <summary>
/// Package image profile. Standard is the PS5PkgTool/MkPFS parity path.
/// </summary>
public enum ProsperoPackageImageProfile
{
    Standard,
    Nwonly,
}

"""
    if "public enum ProsperoPackageImageProfile" not in text:
        if enum_anchor not in text:
            raise RuntimeError("Pinned LibProsperoPKG parity profile enum anchor not found.")
        text = text.replace(enum_anchor, enum_text + enum_anchor, 1)

    output_prop = (
        "    public ProsperoOutputFormat OutputFormat { get; set; } = "
        "ProsperoOutputFormat.DebugImage;\n"
    )
    high_props = """
    /// <summary>Image layout profile used by Packizard.</summary>
    public ProsperoPackageImageProfile ImageProfile { get; set; } = ProsperoPackageImageProfile.Standard;

    /// <summary>Optional deterministic 16-byte outer-PFS seed used by parity tests.</summary>
    public byte[]? OuterSeed { get; set; }

    /// <summary>When true, emit the inner image without Kraken compression.</summary>
    public bool StoreInnerImage { get; set; }
"""
    text = _insert_after_once(
        text,
        output_prop,
        high_props,
        "public bool StoreInnerImage { get; set; }",
        "high-level parity properties",
    )

    volume_line = "            VolumeType = ProsperoVolumeTypeForMode(options.Mode),\n"
    build_props = (
        "            ImageProfile = options.ImageProfile,\n"
        "            OuterSeed = options.OuterSeed,\n"
        "            StoreInnerImage = options.StoreInnerImage,\n"
    )
    text = _insert_after_once(
        text,
        volume_line,
        build_props,
        "StoreInnerImage = options.StoreInnerImage",
        "parity property propagation",
    )

    changed |= _write_if_changed(high, before, text)
    return changed
