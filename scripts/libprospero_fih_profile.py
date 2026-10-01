from __future__ import annotations

from pathlib import Path

FIH_BUILDER_RELATIVE = Path("src/LibProsperoPkg/PKG/ProsperoFihBuilder.cs")
PKG_BUILDER_RELATIVE = Path("src/LibProsperoPkg/PKG/ProsperoPkgBuilder.cs")

_FIH_ORIGINAL = """                uint metaOrInodes = nwonly ? (uint)nwonlyInnerContentInodes : (uint)(totalBlocks - innerBlocks);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageBlockCountField), innerBlocks);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountField), metaOrInodes);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountMirrorField), metaOrInodes);\n"""

_FIH_PATCHED = """                uint metaOrInodes = nwonly ? (uint)nwonlyInnerContentInodes : (uint)(totalBlocks - innerBlocks);\n                // Known-good debug FIH references distinguish the two nwonly inode counters:\n                //   0x94 = content inodes below uroot\n                //   0x98 = the same count including uroot itself\n                // The pinned upstream revision mirrors 0x94 into 0x98, which loses that root inode.\n                uint rootInclusiveInodes = nwonly\n                    ? checked((uint)nwonlyInnerContentInodes + 1U)\n                    : metaOrInodes;\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageBlockCountField), innerBlocks);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountField), metaOrInodes);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountMirrorField), rootInclusiveInodes);\n"""

_CNT_FLAGS_ORIGINAL = """    // The PS5 Flags1 word for each entry id.\n    private static uint Flags1For(uint id) => id switch\n    {\n        (uint)ProsperoCntEntryId.DIGESTS => 0x40000000,\n        (uint)ProsperoCntEntryId.ENTRY_KEYS => 0x60000000,\n        (uint)ProsperoCntEntryId.IMAGE_KEY => 0x60000000,        // image key is not entry-encrypted.\n        (uint)ProsperoCntEntryId.GENERAL_DIGESTS => 0x60000000,\n        (uint)ProsperoCntEntryId.METAS => 0x60000000,\n        (uint)ProsperoCntEntryId.ENTRY_NAMES => 0x40000000,\n        0x2000 => 0x00000000,                          // param.json\n        _ => 0x08000000,                               // media / data entries\n    };\n\n    // No CNT entries in this package class are entry-encrypted, so Flags2 is always zero.\n    private static uint Flags2For(uint id) => 0u;\n"""

_CNT_FLAGS_PATCHED = """    // The PS5 Flags1 word for each entry id.\n    private static uint Flags1For(uint id) => id switch\n    {\n        (uint)ProsperoCntEntryId.DIGESTS => 0x40000000,\n        (uint)ProsperoCntEntryId.ENTRY_KEYS => 0x60000000,\n        (uint)ProsperoCntEntryId.IMAGE_KEY => 0x60000000,        // image key is not entry-encrypted.\n        (uint)ProsperoCntEntryId.GENERAL_DIGESTS => 0x60000000,\n        (uint)ProsperoCntEntryId.METAS => 0x60000000,\n        (uint)ProsperoCntEntryId.ENTRY_NAMES => 0x40000000,\n        (uint)ProsperoCntEntryId.LICENSE_DAT => 0x80000000,\n        (uint)ProsperoCntEntryId.LICENSE_INFO => 0x80000000,\n        (uint)ProsperoCntEntryId.NPTITLE_DAT => 0x80000000,\n        (uint)ProsperoCntEntryId.NPBIND_DAT => 0x80000000,\n        0x2020 => 0x80000000,                         // uds/npbind.dat\n        0x2021 => 0x80000000,                         // trophy2/npbind.dat\n        0x2000 => 0x00000000,                          // param.json\n        _ => 0x08000000,                               // media / data entries\n    };\n\n    // Reference debug CNTs distinguish backend-authored system-file classes in Flags2.\n    // 0x3000 is used for license.dat, nptitle.dat and npbind.dat; license.info uses 0x4000.\n    private static uint Flags2For(uint id) => id switch\n    {\n        (uint)ProsperoCntEntryId.LICENSE_DAT => 0x00003000,\n        (uint)ProsperoCntEntryId.LICENSE_INFO => 0x00004000,\n        (uint)ProsperoCntEntryId.NPTITLE_DAT => 0x00003000,\n        (uint)ProsperoCntEntryId.NPBIND_DAT => 0x00003000,\n        0x2020 => 0x00003000,                         // uds/npbind.dat\n        0x2021 => 0x00003000,                         // trophy2/npbind.dat\n        _ => 0u,\n    };\n"""


def _patch_exact(path: Path, original: str, patched: str, label: str) -> bool:
    if not path.is_file():
        raise RuntimeError(f"LibProsperoPKG {label} is missing: {path}")
    text = path.read_text(encoding="utf-8")
    if patched in text:
        return False
    if original not in text:
        raise RuntimeError(
            f"Pinned LibProsperoPKG {label} no longer matches the Packizard reference profile preimage; "
            "review the upstream implementation before updating the pin."
        )
    path.write_text(text.replace(original, patched, 1), encoding="utf-8")
    return True


def apply_fih_reference_profile(vendor_dir: str | Path) -> bool:
    """Apply Packizard's reference-backed FIH/CNT image-validation profile.

    Returns True when any pinned source file was changed and False when the
    complete profile was already applied. Every rewrite uses an exact preimage
    so an upstream pin change cannot silently receive a stale patch.
    """

    vendor = Path(vendor_dir)
    changed = False
    changed |= _patch_exact(
        vendor / FIH_BUILDER_RELATIVE,
        _FIH_ORIGINAL,
        _FIH_PATCHED,
        "FIH builder",
    )
    changed |= _patch_exact(
        vendor / PKG_BUILDER_RELATIVE,
        _CNT_FLAGS_ORIGINAL,
        _CNT_FLAGS_PATCHED,
        "CNT package builder",
    )
    return changed
