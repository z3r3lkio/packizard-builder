from __future__ import annotations

from pathlib import Path

PKG_BUILDER_RELATIVE = Path("src/LibProsperoPkg/PKG/ProsperoPkgBuilder.cs")

_BUILD_CONTAINER_ORIGINAL = """    {
        uint contentType = ContentTypeFor(props.VolumeType);
        var pkg = new ProsperoCnt
"""
_BUILD_CONTAINER_PATCHED = """    {
        uint contentType = ContentTypeFor(props.VolumeType);
        // The CNT DRM header must describe the same application DRM bucket as param.json.
        // A same-title Publishing Tools/AMPR reference for PPSA02801 uses drm_type=0x10 and
        // content_flags bit 0x08000000 for applicationDrmType=standard. Free/debug content
        // keeps the entitlement-free zero values.
        string applicationDrmType = ReadParamJsonInfo(sourceFolder).ApplicationDrmType;
        bool standardDrm = string.Equals(
            applicationDrmType, "standard", StringComparison.OrdinalIgnoreCase);
        var pkg = new ProsperoCnt
"""

_HEADER_DRM_ORIGINAL = """                drm_type = DrmTypeNone,
                content_type = contentType,
                content_flags = ContentFlagsFor(props.VolumeType),
"""
_HEADER_DRM_PATCHED = """                drm_type = standardDrm ? 0x10u : DrmTypeNone,
                content_type = contentType,
                content_flags = ContentFlagsFor(props.VolumeType)
                    | (standardDrm ? ProsperoCntContentFlags.Unk_x8000000 : (ProsperoCntContentFlags)0),
"""

_LAYOUT_CALL_ORIGINAL = """        LayOutEntries(pkg, paramJson);
        return pkg;
"""
_LAYOUT_CALL_PATCHED = """        LayOutEntries(pkg, paramJson, standardDrm);
        return pkg;
"""

_FLAGS1_SIGNATURE_ORIGINAL = """    private static uint Flags1For(uint id) => id switch
"""
_FLAGS1_SIGNATURE_PATCHED = """    private static uint Flags1For(uint id, bool standardDrm) => id switch
"""

_FLAGS1_SYSTEM_ORIGINAL = """        (uint)ProsperoCntEntryId.LICENSE_DAT => 0x80000000,
        (uint)ProsperoCntEntryId.LICENSE_INFO => 0x80000000,
        (uint)ProsperoCntEntryId.NPTITLE_DAT => 0x80000000,
        (uint)ProsperoCntEntryId.NPBIND_DAT => 0x80000000,
        0x2020 => 0x80000000,
        0x2021 => 0x80000000,
"""
_FLAGS1_SYSTEM_PATCHED = """        (uint)ProsperoCntEntryId.LICENSE_DAT => standardDrm ? 0u : 0x80000000,
        (uint)ProsperoCntEntryId.LICENSE_INFO => standardDrm ? 0u : 0x80000000,
        (uint)ProsperoCntEntryId.NPTITLE_DAT => standardDrm ? 0u : 0x80000000,
        (uint)ProsperoCntEntryId.NPBIND_DAT => standardDrm ? 0u : 0x80000000,
        0x2020 => standardDrm ? 0u : 0x80000000,
        0x2021 => standardDrm ? 0u : 0x80000000,
"""

_FLAGS2_SIGNATURE_ORIGINAL = """    private static uint Flags2For(uint id) => id switch
"""
_FLAGS2_SIGNATURE_PATCHED = """    private static uint Flags2For(uint id, bool standardDrm) => id switch
"""

_FLAGS2_SYSTEM_ORIGINAL = """        (uint)ProsperoCntEntryId.LICENSE_DAT => 0x00003000,
        (uint)ProsperoCntEntryId.LICENSE_INFO => 0x00004000,
        (uint)ProsperoCntEntryId.NPTITLE_DAT => 0x00003000,
        (uint)ProsperoCntEntryId.NPBIND_DAT => 0x00003000,
        0x2020 => 0x00003000,
        0x2021 => 0x00003000,
"""
_FLAGS2_SYSTEM_PATCHED = """        (uint)ProsperoCntEntryId.LICENSE_DAT => standardDrm ? 0u : 0x00003000,
        (uint)ProsperoCntEntryId.LICENSE_INFO => standardDrm ? 0u : 0x00004000,
        (uint)ProsperoCntEntryId.NPTITLE_DAT => standardDrm ? 0u : 0x00003000,
        (uint)ProsperoCntEntryId.NPBIND_DAT => standardDrm ? 0u : 0x00003000,
        0x2020 => standardDrm ? 0u : 0x00003000,
        0x2021 => standardDrm ? 0u : 0x00003000,
"""

_LAYOUT_SIGNATURE_ORIGINAL = """    private static void LayOutEntries(ProsperoCnt pkg, byte[] paramJson)
"""
_LAYOUT_SIGNATURE_PATCHED = """    private static void LayOutEntries(ProsperoCnt pkg, byte[] paramJson, bool standardDrm)
"""

_LAYOUT_FLAGS_ORIGINAL = """                Flags1 = Flags1For((uint)entry.Id),
                Flags2 = Flags2For((uint)entry.Id),
"""
_LAYOUT_FLAGS_PATCHED = """                Flags1 = Flags1For((uint)entry.Id, standardDrm),
                Flags2 = Flags2For((uint)entry.Id, standardDrm),
"""


def _patch_exact(text: str, original: str, patched: str, label: str) -> tuple[str, bool]:
    if patched in text:
        return text, False
    if original not in text:
        raise RuntimeError(
            f"Pinned LibProsperoPKG {label} no longer matches the Packizard DRM profile preimage."
        )
    return text.replace(original, patched, 1), True


def apply_cnt_drm_profile(vendor_dir: str | Path) -> bool:
    """Align CNT entitlement metadata with the normalized param.json DRM bucket."""
    path = Path(vendor_dir) / PKG_BUILDER_RELATIVE
    if not path.is_file():
        raise RuntimeError(f"LibProsperoPKG CNT package builder is missing: {path}")
    text = path.read_text(encoding="utf-8")
    changed = False
    for original, patched, label in (
        (_BUILD_CONTAINER_ORIGINAL, _BUILD_CONTAINER_PATCHED, "build-container DRM detection"),
        (_HEADER_DRM_ORIGINAL, _HEADER_DRM_PATCHED, "CNT DRM header"),
        (_LAYOUT_CALL_ORIGINAL, _LAYOUT_CALL_PATCHED, "CNT layout call"),
        (_FLAGS1_SIGNATURE_ORIGINAL, _FLAGS1_SIGNATURE_PATCHED, "CNT Flags1 signature"),
        (_FLAGS1_SYSTEM_ORIGINAL, _FLAGS1_SYSTEM_PATCHED, "CNT standard-DRM Flags1 system entries"),
        (_FLAGS2_SIGNATURE_ORIGINAL, _FLAGS2_SIGNATURE_PATCHED, "CNT Flags2 signature"),
        (_FLAGS2_SYSTEM_ORIGINAL, _FLAGS2_SYSTEM_PATCHED, "CNT standard-DRM Flags2 system entries"),
        (_LAYOUT_SIGNATURE_ORIGINAL, _LAYOUT_SIGNATURE_PATCHED, "CNT layout signature"),
        (_LAYOUT_FLAGS_ORIGINAL, _LAYOUT_FLAGS_PATCHED, "CNT layout flags"),
    ):
        text, did_change = _patch_exact(text, original, patched, label)
        changed |= did_change
    path.write_text(text, encoding="utf-8")
    return changed
