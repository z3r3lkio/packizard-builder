from __future__ import annotations

from pathlib import Path

FIH_BUILDER_RELATIVE = Path("src/LibProsperoPkg/PKG/ProsperoFihBuilder.cs")
PKG_BUILDER_RELATIVE = Path("src/LibProsperoPkg/PKG/ProsperoPkgBuilder.cs")
OUTER_PFS_BUILDER_RELATIVE = Path("src/LibProsperoPkg/PFS/ProsperoOuterPfsBuilder.cs")
INNER_ASSEMBLER_RELATIVE = Path("src/LibProsperoPkg/PFS/ProsperoPs5InnerImageAssembler.cs")

_FIH_ORIGINAL = """                uint metaOrInodes = nwonly ? (uint)nwonlyInnerContentInodes : (uint)(totalBlocks - innerBlocks);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageBlockCountField), innerBlocks);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountField), metaOrInodes);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountMirrorField), metaOrInodes);\n"""

_FIH_PATCHED = """                uint metaOrInodes = nwonly ? (uint)nwonlyInnerContentInodes : (uint)(totalBlocks - innerBlocks);\n                // Known-good debug FIH references distinguish the two nwonly inode counters:\n                //   0x94 = content inodes below uroot\n                //   0x98 = the same count including uroot itself\n                // The pinned upstream revision mirrors 0x94 into 0x98, which loses that root inode.\n                uint rootInclusiveInodes = nwonly\n                    ? checked((uint)nwonlyInnerContentInodes + 1U)\n                    : metaOrInodes;\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageBlockCountField), innerBlocks);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountField), metaOrInodes);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountMirrorField), rootInclusiveInodes);\n"""

_CNT_FLAGS_ORIGINAL = """    // The PS5 Flags1 word for each entry id.\n    private static uint Flags1For(uint id) => id switch\n    {\n        (uint)ProsperoCntEntryId.DIGESTS => 0x40000000,\n        (uint)ProsperoCntEntryId.ENTRY_KEYS => 0x60000000,\n        (uint)ProsperoCntEntryId.IMAGE_KEY => 0x60000000,        // image key is not entry-encrypted.\n        (uint)ProsperoCntEntryId.GENERAL_DIGESTS => 0x60000000,\n        (uint)ProsperoCntEntryId.METAS => 0x60000000,\n        (uint)ProsperoCntEntryId.ENTRY_NAMES => 0x40000000,\n        0x2000 => 0x00000000,                          // param.json\n        _ => 0x08000000,                               // media / data entries\n    };\n\n    // No CNT entries in this package class are entry-encrypted, so Flags2 is always zero.\n    private static uint Flags2For(uint id) => 0u;\n"""

_CNT_FLAGS_PATCHED = """    // The PS5 Flags1 word for each entry id.\n    private static uint Flags1For(uint id) => id switch\n    {\n        (uint)ProsperoCntEntryId.DIGESTS => 0x40000000,\n        (uint)ProsperoCntEntryId.ENTRY_KEYS => 0x60000000,\n        (uint)ProsperoCntEntryId.IMAGE_KEY => 0x60000000,        // image key is not entry-encrypted.\n        (uint)ProsperoCntEntryId.GENERAL_DIGESTS => 0x60000000,\n        (uint)ProsperoCntEntryId.METAS => 0x60000000,\n        (uint)ProsperoCntEntryId.ENTRY_NAMES => 0x40000000,\n        (uint)ProsperoCntEntryId.LICENSE_DAT => 0x80000000,\n        (uint)ProsperoCntEntryId.LICENSE_INFO => 0x80000000,\n        (uint)ProsperoCntEntryId.NPTITLE_DAT => 0x80000000,\n        (uint)ProsperoCntEntryId.NPBIND_DAT => 0x80000000,\n        0x2020 => 0x80000000,                         // uds/npbind.dat\n        0x2021 => 0x80000000,                         // trophy2/npbind.dat\n        0x2000 => 0x00000000,                          // param.json\n        _ => 0x08000000,                               // media / data entries\n    };\n\n    // Reference debug CNTs distinguish backend-authored system-file classes in Flags2.\n    // 0x3000 is used for license.dat, nptitle.dat and npbind.dat; license.info uses 0x4000.\n    private static uint Flags2For(uint id) => id switch\n    {\n        (uint)ProsperoCntEntryId.LICENSE_DAT => 0x00003000,\n        (uint)ProsperoCntEntryId.LICENSE_INFO => 0x00004000,\n        (uint)ProsperoCntEntryId.NPTITLE_DAT => 0x00003000,\n        (uint)ProsperoCntEntryId.NPBIND_DAT => 0x00003000,\n        0x2020 => 0x00003000,                         // uds/npbind.dat\n        0x2021 => 0x00003000,                         // trophy2/npbind.dat\n        _ => 0u,\n    };\n"""

_OUTER_ENCRYPT_ORIGINAL = """        var (tweak, data) = ProsperoPfsKeys.DeriveImageEncryptionKeys(ekpfs, seed);\n        Encrypt(build, tweak, data);\n\n        return new ProsperoOuterPackageImage\n"""

_OUTER_ENCRYPT_PATCHED = """        // Known-good FullDebug FIH references keep the finalized outer PFS on disk in plaintext.\n        // BuildPlaintext has already produced the signed PFS structure and all integrity material above;\n        // applying AES-XTS here turns pfs_image.dat, NAPS and structural metadata into ciphertext that\n        // sceNpDrmContentCheckImage rejects before /app0 can mount. Keep the generic Encrypt/Transform\n        // APIs intact for explicit keyed/retail use, but do not encrypt the FullDebug package build path.\n\n        return new ProsperoOuterPackageImage\n"""

# Large package builds use a separate file-backed/streaming path. The first plaintext fix only
# covered BuildForPackage(), so images large enough to enter BuildForPackageToFile() were still
# AES-XTS transformed block-by-block. Keep this rewrite independent so small and large FullDebug
# packages produce the same on-disk outer-PFS representation.
_OUTER_STREAM_ENCRYPT_ORIGINAL = """                xts.CryptSector(block, sector, encrypt: true);\n                fs.Position = checked((long)i * BlockSize);\n                fs.Write(block, 0, block.Length);\n"""

_OUTER_STREAM_ENCRYPT_PATCHED = """                // FullDebug references store the finalized outer-PFS block bytes as built.\n                // The streaming path must match the in-memory path and must not AES-XTS transform them.\n                fs.Position = checked((long)i * BlockSize);\n                fs.Write(block, 0, block.Length);\n"""

# NAPS assigns owner flag 0 to AFID 0 and explicitly documents AFID 0 as the DRM keystone.
# The pinned assembler currently sorts the entire sce_sys subtree, which lets files such as
# appinfo/version metadata precede /sce_sys/keystone. Known-good references begin the data-first
# image with keystone, so force that single invariant and preserve the relative order of everything else.
_INNER_AFID_ORIGINAL = """        var afidOrder = new List<FileNode>();\n        Dir? sceSys = uroot.SubDirs.FirstOrDefault(d => d.Name == SceSysDir);\n        if (sceSys != null) CollectFilesPreOrder(sceSys, afidOrder);\n        foreach (var d in dirsPreOrder)\n"""

_INNER_AFID_PATCHED = """        var afidOrder = new List<FileNode>();\n        Dir? sceSys = uroot.SubDirs.FirstOrDefault(d => d.Name == SceSysDir);\n        if (sceSys != null)\n        {\n            var sceSysFiles = new List<FileNode>();\n            CollectFilesPreOrder(sceSys, sceSysFiles);\n            FileNode? keystone = sceSysFiles.FirstOrDefault(f => IsKeystone(f.FullPath));\n            if (keystone is not null)\n                afidOrder.Add(keystone);\n            foreach (var f in sceSysFiles)\n                if (!ReferenceEquals(f, keystone))\n                    afidOrder.Add(f);\n        }\n        foreach (var d in dirsPreOrder)\n"""


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


def _patch_streaming_outer_if_present(path: Path) -> bool:
    """Patch the pinned large-package streaming encryptor when that path is present.

    Synthetic unit-test fixtures created before the streaming regression was discovered do not
    contain BuildForPackageToFile(), so absence is allowed there. The real pinned vendor source
    contains the exact preimage and is rewritten during bridge preparation.
    """
    if not path.is_file():
        raise RuntimeError(f"LibProsperoPKG outer PFS streaming package builder is missing: {path}")
    text = path.read_text(encoding="utf-8")
    if _OUTER_STREAM_ENCRYPT_PATCHED in text:
        return False
    if _OUTER_STREAM_ENCRYPT_ORIGINAL not in text:
        return False
    path.write_text(
        text.replace(_OUTER_STREAM_ENCRYPT_ORIGINAL, _OUTER_STREAM_ENCRYPT_PATCHED, 1),
        encoding="utf-8",
    )
    return True


def _patch_inner_afid_if_present(path: Path) -> bool:
    """Keep the nwonly DRM keystone at AFID 0 when the inner assembler is present."""
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if _INNER_AFID_PATCHED in text:
        return False
    if _INNER_AFID_ORIGINAL not in text:
        raise RuntimeError(
            "Pinned LibProsperoPKG inner-image AFID ordering no longer matches the Packizard "
            "reference profile preimage; review the assembler before updating the pin."
        )
    path.write_text(text.replace(_INNER_AFID_ORIGINAL, _INNER_AFID_PATCHED, 1), encoding="utf-8")
    return True


def apply_fih_reference_profile(vendor_dir: str | Path) -> bool:
    """Apply Packizard's reference-backed FIH/CNT/outer-PFS/inner-image profile.

    Returns True when any pinned source file was changed and False when the
    complete profile was already applied. Every mandatory rewrite uses an exact preimage
    so an upstream pin change cannot silently receive a stale patch.
    """

    vendor = Path(vendor_dir)
    outer_builder = vendor / OUTER_PFS_BUILDER_RELATIVE
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
    changed |= _patch_exact(
        outer_builder,
        _OUTER_ENCRYPT_ORIGINAL,
        _OUTER_ENCRYPT_PATCHED,
        "outer PFS package builder",
    )
    changed |= _patch_streaming_outer_if_present(outer_builder)
    changed |= _patch_inner_afid_if_present(vendor / INNER_ASSEMBLER_RELATIVE)
    return changed
