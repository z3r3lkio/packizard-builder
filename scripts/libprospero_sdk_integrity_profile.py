from __future__ import annotations

from pathlib import Path

FIH_BUILDER_RELATIVE = Path("src/LibProsperoPkg/PKG/ProsperoFihBuilder.cs")

# apply_fih_reference_profile() runs first and currently differentiates 0x94/0x98.
# Same-title known-good debug packages and Publishing Tools output keep these fields mirrored.
_META_COUNTS_PROFILED = """                uint metaOrInodes = nwonly ? (uint)nwonlyInnerContentInodes : (uint)(totalBlocks - innerBlocks);\n                // Known-good debug FIH references distinguish the two nwonly inode counters:\n                //   0x94 = content inodes below uroot\n                //   0x98 = the same count including uroot itself\n                uint rootInclusiveInodes = nwonly\n                    ? checked((uint)nwonlyInnerContentInodes + 1U)\n                    : metaOrInodes;\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageBlockCountField), innerBlocks);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountField), metaOrInodes);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountMirrorField), rootInclusiveInodes);\n"""

_META_COUNTS_SDK = """                uint metaOrInodes = nwonly ? (uint)nwonlyInnerContentInodes : (uint)(totalBlocks - innerBlocks);\n                // Publishing Tools / same-title known-good FIH images keep 0x94 and 0x98 mirrored.\n                // They are part of the finalized-image geometry, not two independent inode counters.\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageBlockCountField), innerBlocks);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountField), metaOrInodes);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountMirrorField), metaOrInodes);\n"""

# The pinned engine threads Ndblock into the FIH and then prefers it for +0xA0. That makes +0xA0
# describe a different logical extent than +0x90. The console/reference invariant is instead exact:
#     FIH[0xA0] == FIH[0x90] * 0x10000
# NAPS logical size remains in +0xA8 and must not change the +0xA0 physical block geometry.
_INNER_SIZE_NDBLOCK = """                ulong innerImageFieldValue = nwonlyNdblock > 0\n                    ? (ulong)nwonlyNdblock * (ulong)blockSize\n                    : (ulong)innerBlocks * (ulong)blockSize;\n                BinaryPrimitives.WriteUInt64LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageSizeField), innerImageFieldValue);\n"""

_INNER_SIZE_SDK = """                // SDK/reference invariant: +0xA0 is the byte form of the +0x90 block count.\n                // Do not substitute Ndblock here; that describes a different logical extent.\n                ulong innerImageFieldValue = (ulong)innerBlocks * (ulong)blockSize;\n                BinaryPrimitives.WriteUInt64LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageSizeField), innerImageFieldValue);\n"""


def _patch_exact(path: Path, original: str, patched: str, label: str) -> bool:
    if not path.is_file():
        raise RuntimeError(f"LibProsperoPKG {label} is missing: {path}")
    text = path.read_text(encoding="utf-8")
    if patched in text:
        return False
    if original not in text:
        raise RuntimeError(
            f"Pinned LibProsperoPKG {label} no longer matches the SDK-integrity profile preimage; "
            "review the upstream implementation before updating the pin."
        )
    path.write_text(text.replace(original, patched), encoding="utf-8")
    return True


def apply_sdk_integrity_profile(vendor_dir: Path) -> bool:
    """Apply FIH geometry proven by Publishing Tools and same-title known-good packages.

    This patch intentionally changes only structural finalized-image fields. It does not copy SDK
    binaries, keys, signatures, certificates, or authentication material.
    """
    path = vendor_dir / FIH_BUILDER_RELATIVE
    changed = _patch_exact(path, _META_COUNTS_PROFILED, _META_COUNTS_SDK, "FIH mirrored counts")
    changed |= _patch_exact(path, _INNER_SIZE_NDBLOCK, _INNER_SIZE_SDK, "FIH inner-image size")
    return changed
