from __future__ import annotations

from pathlib import Path

FIH_BUILDER_RELATIVE = Path("src/LibProsperoPkg/PKG/ProsperoFihBuilder.cs")

_ORIGINAL = """                uint metaOrInodes = nwonly ? (uint)nwonlyInnerContentInodes : (uint)(totalBlocks - innerBlocks);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageBlockCountField), innerBlocks);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountField), metaOrInodes);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountMirrorField), metaOrInodes);\n"""

_PATCHED = """                uint metaOrInodes = nwonly ? (uint)nwonlyInnerContentInodes : (uint)(totalBlocks - innerBlocks);\n                // Known-good debug FIH references distinguish the two nwonly inode counters:\n                //   0x94 = content inodes below uroot\n                //   0x98 = the same count including uroot itself\n                // The pinned upstream revision mirrors 0x94 into 0x98, which loses that root inode.\n                uint rootInclusiveInodes = nwonly\n                    ? checked((uint)nwonlyInnerContentInodes + 1U)\n                    : metaOrInodes;\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageBlockCountField), innerBlocks);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountField), metaOrInodes);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountMirrorField), rootInclusiveInodes);\n"""


def apply_fih_reference_profile(vendor_dir: str | Path) -> bool:
    """Apply Packizard's reference-backed nwonly FIH field profile.

    Returns True when the pinned source was changed and False when it was already
    patched. Refuses unknown source text so an upstream pin change cannot silently
    receive a stale source rewrite.
    """

    vendor = Path(vendor_dir)
    path = vendor / FIH_BUILDER_RELATIVE
    if not path.is_file():
        raise RuntimeError(f"LibProsperoPKG FIH builder is missing: {path}")

    text = path.read_text(encoding="utf-8")
    if _PATCHED in text:
        return False
    if _ORIGINAL not in text:
        raise RuntimeError(
            "Pinned LibProsperoPKG FIH builder no longer matches the Packizard reference profile preimage; "
            "review the upstream FIH 0x94/0x98 implementation before updating the pin."
        )

    path.write_text(text.replace(_ORIGINAL, _PATCHED, 1), encoding="utf-8")
    return True
