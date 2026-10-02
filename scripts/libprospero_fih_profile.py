from __future__ import annotations

from pathlib import Path

FIH_BUILDER_RELATIVE = Path("src/LibProsperoPkg/PKG/ProsperoFihBuilder.cs")
PKG_BUILDER_RELATIVE = Path("src/LibProsperoPkg/PKG/ProsperoPkgBuilder.cs")
PACKAGE_BUILDER_RELATIVE = Path("src/LibProsperoPkg/ProsperoPackageBuilder.cs")
OUTER_PFS_BUILDER_RELATIVE = Path("src/LibProsperoPkg/PFS/ProsperoOuterPfsBuilder.cs")
INNER_ASSEMBLER_RELATIVE = Path("src/LibProsperoPkg/PFS/ProsperoPs5InnerImageAssembler.cs")
INNER_READER_RELATIVE = Path("src/LibProsperoPkg/PFS/ProsperoPs5InnerImageReader.cs")

_FIH_ORIGINAL = """                uint metaOrInodes = nwonly ? (uint)nwonlyInnerContentInodes : (uint)(totalBlocks - innerBlocks);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageBlockCountField), innerBlocks);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountField), metaOrInodes);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountMirrorField), metaOrInodes);\n"""

_FIH_PATCHED = """                uint metaOrInodes = nwonly ? (uint)nwonlyInnerContentInodes : (uint)(totalBlocks - innerBlocks);\n                // Known-good debug FIH references distinguish the two nwonly inode counters:\n                //   0x94 = content inodes below uroot\n                //   0x98 = the same count including uroot itself\n                uint rootInclusiveInodes = nwonly\n                    ? checked((uint)nwonlyInnerContentInodes + 1U)\n                    : metaOrInodes;\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageBlockCountField), innerBlocks);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountField), metaOrInodes);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountMirrorField), rootInclusiveInodes);\n"""

_FIH_BLOCK_GEOMETRY_ORIGINAL = """                bool nwonly = nwonlyInnerContentInodes > 0;\n                uint innerBlocks = (uint)(sbBlockIndex - 1);\n"""

_FIH_BLOCK_GEOMETRY_PATCHED = """                bool nwonly = nwonlyInnerContentInodes > 0;\n                // The outer data-first order is [pfs_image.dat][naps_pkg_layout.dat][superblock].\n                // 0x90 is the pfs_image.dat block count, so subtract the complete NAPS span rather\n                // than a hard-coded single block. Reference packages exercise multi-block NAPS files.\n                long napsBlocks = nwonly && nestedImageSize > 0\n                    ? checked((nestedImageSize + blockSize - 1) / blockSize)\n                    : 1;\n                if (napsBlocks <= 0 || napsBlocks > sbBlockIndex)\n                    throw new InvalidDataException(\"Invalid nwonly NAPS/FIH block geometry.\");\n                uint innerBlocks = checked((uint)(sbBlockIndex - napsBlocks));\n"""

_FIH_SIGNATURE_ORIGINAL = """        uint nwonlyContentVersionHi = 0, int nwonlyInnerContentInodes = 0, int nwonlyAppFileCount = 0,\n        Func<string, byte[]>? siArchivePathFactory = null)\n"""
_FIH_SIGNATURE_PATCHED = """        uint nwonlyContentVersionHi = 0, int nwonlyInnerContentInodes = 0, int nwonlyAppFileCount = 0,\n        long nwonlyNdblock = 0, Func<string, byte[]>? siArchivePathFactory = null)\n"""

_FIH_LARGE_CALL_ORIGINAL = """                nwonlyContentVersionHi, nwonlyInnerContentInodes, nwonlyAppFileCount,\n                siArchivePathFactory);\n"""
_FIH_LARGE_CALL_PATCHED = """                nwonlyContentVersionHi, nwonlyInnerContentInodes, nwonlyAppFileCount,\n                nwonlyNdblock, siArchivePathFactory);\n"""

_FIH_SMALL_HEADER_ORIGINAL = """            nwonlyContentVersionHi: nwonlyContentVersionHi,\n            nwonlyInnerContentInodes: nwonlyInnerContentInodes,\n            nwonlyAppFileCount: nwonlyAppFileCount);\n"""
_FIH_SMALL_HEADER_PATCHED = """            nwonlyContentVersionHi: nwonlyContentVersionHi,\n            nwonlyInnerContentInodes: nwonlyInnerContentInodes,\n            nwonlyAppFileCount: nwonlyAppFileCount,\n            nwonlyNdblock: nwonlyNdblock);\n"""

_FIH_LARGE_SIGNATURE_ORIGINAL = """        long nestedImageSize, long nestedMetaBaseBlocks, uint nwonlyContentVersionHi,\n        int nwonlyInnerContentInodes, int nwonlyAppFileCount,\n        Func<string, byte[]>? siArchivePathFactory)\n"""
_FIH_LARGE_SIGNATURE_PATCHED = """        long nestedImageSize, long nestedMetaBaseBlocks, uint nwonlyContentVersionHi,\n        int nwonlyInnerContentInodes, int nwonlyAppFileCount, long nwonlyNdblock,\n        Func<string, byte[]>? siArchivePathFactory)\n"""

_FIH_LARGE_HEADER_ORIGINAL = """            nwonlyContentVersionHi: nwonlyContentVersionHi,\n            nwonlyInnerContentInodes: nwonlyInnerContentInodes,\n            nwonlyAppFileCount: nwonlyAppFileCount,\n            sblockOffsetOverride: sbOffset,\n"""
_FIH_LARGE_HEADER_PATCHED = """            nwonlyContentVersionHi: nwonlyContentVersionHi,\n            nwonlyInnerContentInodes: nwonlyInnerContentInodes,\n            nwonlyAppFileCount: nwonlyAppFileCount,\n            nwonlyNdblock: nwonlyNdblock,\n            sblockOffsetOverride: sbOffset,\n"""

_PACKAGE_FINALIZER_ORIGINAL = """            nwonlyContentVersionHi: nwonlyFih?.ContentVersionHi ?? 0,\n            nwonlyInnerContentInodes: nwonlyFih?.InnerContentInodes ?? 0,\n            nwonlyAppFileCount: nwonlyFih?.AppFileCount ?? 0,\n            siArchivePathFactory: siPathFactory);\n"""
_PACKAGE_FINALIZER_PATCHED = """            nwonlyContentVersionHi: nwonlyFih?.ContentVersionHi ?? 0,\n            nwonlyInnerContentInodes: nwonlyFih?.InnerContentInodes ?? 0,\n            nwonlyAppFileCount: nwonlyFih?.AppFileCount ?? 0,\n            nwonlyNdblock: nwonlyFih?.Ndblock ?? 0,\n            siArchivePathFactory: siPathFactory);\n"""

_CNT_FLAGS_ORIGINAL = """    // The PS5 Flags1 word for each entry id.\n    private static uint Flags1For(uint id) => id switch\n    {\n        (uint)ProsperoCntEntryId.DIGESTS => 0x40000000,\n        (uint)ProsperoCntEntryId.ENTRY_KEYS => 0x60000000,\n        (uint)ProsperoCntEntryId.IMAGE_KEY => 0x60000000,        // image key is not entry-encrypted.\n        (uint)ProsperoCntEntryId.GENERAL_DIGESTS => 0x60000000,\n        (uint)ProsperoCntEntryId.METAS => 0x60000000,\n        (uint)ProsperoCntEntryId.ENTRY_NAMES => 0x40000000,\n        0x2000 => 0x00000000,                          // param.json\n        _ => 0x08000000,                               // media / data entries\n    };\n\n    // No CNT entries in this package class are entry-encrypted, so Flags2 is always zero.\n    private static uint Flags2For(uint id) => 0u;\n"""

_CNT_FLAGS_PATCHED = """    // The PS5 Flags1 word for each entry id.\n    private static uint Flags1For(uint id) => id switch\n    {\n        (uint)ProsperoCntEntryId.DIGESTS => 0x40000000,\n        (uint)ProsperoCntEntryId.ENTRY_KEYS => 0x60000000,\n        (uint)ProsperoCntEntryId.IMAGE_KEY => 0x60000000,        // image key is not entry-encrypted.\n        (uint)ProsperoCntEntryId.GENERAL_DIGESTS => 0x60000000,\n        (uint)ProsperoCntEntryId.METAS => 0x60000000,\n        (uint)ProsperoCntEntryId.ENTRY_NAMES => 0x40000000,\n        (uint)ProsperoCntEntryId.LICENSE_DAT => 0x80000000,\n        (uint)ProsperoCntEntryId.LICENSE_INFO => 0x80000000,\n        (uint)ProsperoCntEntryId.NPTITLE_DAT => 0x80000000,\n        (uint)ProsperoCntEntryId.NPBIND_DAT => 0x80000000,\n        0x2020 => 0x80000000,\n        0x2021 => 0x80000000,\n        0x2000 => 0x00000000,\n        _ => 0x08000000,\n    };\n\n    private static uint Flags2For(uint id) => id switch\n    {\n        (uint)ProsperoCntEntryId.LICENSE_DAT => 0x00003000,\n        (uint)ProsperoCntEntryId.LICENSE_INFO => 0x00004000,\n        (uint)ProsperoCntEntryId.NPTITLE_DAT => 0x00003000,\n        (uint)ProsperoCntEntryId.NPBIND_DAT => 0x00003000,\n        0x2020 => 0x00003000,\n        0x2021 => 0x00003000,\n        _ => 0u,\n    };\n"""

_OUTER_ENCRYPT_ORIGINAL = """        var (tweak, data) = ProsperoPfsKeys.DeriveImageEncryptionKeys(ekpfs, seed);\n        Encrypt(build, tweak, data);\n\n        return new ProsperoOuterPackageImage\n"""
_OUTER_ENCRYPT_PATCHED = """        // Known-good FullDebug FIH references keep the finalized outer PFS on disk in plaintext.\n        // BuildPlaintext has already produced the signed PFS structure and all integrity material above;\n        // applying AES-XTS here turns pfs_image.dat, NAPS and structural metadata into ciphertext that\n        // sceNpDrmContentCheckImage rejects before /app0 can mount.\n\n        return new ProsperoOuterPackageImage\n"""

_OUTER_STREAM_ENCRYPT_ORIGINAL = """                xts.CryptSector(block, sector, encrypt: true);\n                fs.Position = checked((long)i * BlockSize);\n                fs.Write(block, 0, block.Length);\n"""
_OUTER_STREAM_ENCRYPT_PATCHED = """                // FullDebug references store the finalized outer-PFS block bytes as built.\n                // The streaming path must match the in-memory path and must not AES-XTS transform them.\n                fs.Position = checked((long)i * BlockSize);\n                fs.Write(block, 0, block.Length);\n"""

_INNER_AFID_ORIGINAL = """        var afidOrder = new List<FileNode>();\n        Dir? sceSys = uroot.SubDirs.FirstOrDefault(d => d.Name == SceSysDir);\n        if (sceSys != null) CollectFilesPreOrder(sceSys, afidOrder);\n        foreach (var d in dirsPreOrder)\n"""
_INNER_AFID_PATCHED = """        var afidOrder = new List<FileNode>();\n        Dir? sceSys = uroot.SubDirs.FirstOrDefault(d => d.Name == SceSysDir);\n        if (sceSys != null)\n        {\n            var sceSysFiles = new List<FileNode>();\n            CollectFilesPreOrder(sceSys, sceSysFiles);\n            FileNode? keystone = sceSysFiles.FirstOrDefault(f => IsKeystone(f.FullPath));\n            if (keystone is not null)\n                afidOrder.Add(keystone);\n            foreach (var f in sceSysFiles)\n                if (!ReferenceEquals(f, keystone))\n                    afidOrder.Add(f);\n        }\n        foreach (var d in dirsPreOrder)\n"""

_INNER_READER_DATA_END_ORIGINAL = """        long metaBase = boundaries.LastOrDefault(v => v < mountSize);\n\n        var mount = new byte[mountSize];\n"""
_INNER_READER_DATA_END_PATCHED = """        long metaBase = boundaries.LastOrDefault(v => v < mountSize);\n        long dataEnd = boundaries.LastOrDefault(v => v < metaBase);\n        if (metaBase <= 0 || dataEnd < 0 || dataEnd > metaBase)\n            throw new InvalidOperationException(\"NAPS fidx does not contain coherent data/meta mount boundaries.\");\n\n        var mount = new byte[mountSize];\n"""

_INNER_READER_LENGTH_ORIGINAL = """            long fileEnd = NextBoundary(boundaries, uncompOff, mountSize);\n            long uncompLen = Math.Min(Ublock256K, fileEnd - uncompOff);\n            if (uncompLen <= 0 || i + 1 >= cb.Count)\n                break;\n\n            int evenComp = (int)(e.ClenEvenMinus1 / 2 + 1);\n"""
_INNER_READER_LENGTH_PATCHED = """            // CblockInfo describes compression blocks, not individual files. A single 256K DATA\n            // block may span several fidx boundaries, so cutting at the next file start desynchronizes\n            // CblockInfo and eventually loses the metadata superblock. Use the writer's block semantics:\n            // Kde=0 is an exact raw tail/small block, normal DATA/metadata blocks are <=256K, and the\n            // one logical DATA->metadata hole spans dataEnd..metaBase without consuming payload bytes.\n            bool logicalHole = uncompOff == dataEnd && metaBase > dataEnd;\n            long regionEnd = uncompOff < dataEnd ? dataEnd : mountSize;\n            long uncompLen = logicalHole\n                ? metaBase - dataEnd\n                : e.KdePredictor == 0\n                    ? Math.Min((long)(e.ClenEvenMinus1 / 2 + 1), regionEnd - uncompOff)\n                    : Math.Min(Ublock256K, regionEnd - uncompOff);\n            if (uncompLen <= 0 || i + 1 >= cb.Count)\n                break;\n\n            int evenComp = (int)(e.ClenEvenMinus1 / 2 + 1);\n"""

_INNER_READER_DECODE_ORIGINAL = """            DecodeBlockInto(innerArr, onDisk, totalComp, evenComp, (int)uncompLen, kraken,\n                            mount, (int)uncompOff);\n\n            uncompOff += uncompLen;\n            onDisk += kraken ? totalComp : uncompLen;\n"""
_INNER_READER_DECODE_PATCHED = """            if (!logicalHole)\n            {\n                DecodeBlockInto(innerArr, onDisk, totalComp, evenComp, (int)uncompLen, kraken,\n                                mount, (int)uncompOff);\n            }\n\n            uncompOff += uncompLen;\n            if (!logicalHole)\n                onDisk += kraken ? totalComp : uncompLen;\n"""


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


def _patch_if_present(path: Path, original: str, patched: str, label: str, *, strict: bool = False) -> bool:
    if not path.is_file():
        if strict:
            raise RuntimeError(f"LibProsperoPKG {label} is missing: {path}")
        return False
    text = path.read_text(encoding="utf-8")
    if patched in text:
        return False
    if original not in text:
        if strict:
            raise RuntimeError(f"Pinned LibProsperoPKG {label} no longer matches the Packizard reference profile preimage.")
        return False
    path.write_text(text.replace(original, patched, 1), encoding="utf-8")
    return True


def apply_fih_reference_profile(vendor_dir: str | Path) -> bool:
    vendor = Path(vendor_dir)
    fih = vendor / FIH_BUILDER_RELATIVE
    outer = vendor / OUTER_PFS_BUILDER_RELATIVE
    inner_reader = vendor / INNER_READER_RELATIVE
    changed = False

    changed |= _patch_exact(fih, _FIH_ORIGINAL, _FIH_PATCHED, "FIH inode profile")
    changed |= _patch_if_present(fih, _FIH_BLOCK_GEOMETRY_ORIGINAL, _FIH_BLOCK_GEOMETRY_PATCHED, "FIH NAPS block geometry", strict=True)
    changed |= _patch_if_present(fih, _FIH_SIGNATURE_ORIGINAL, _FIH_SIGNATURE_PATCHED, "FIH finalizer Ndblock signature", strict=True)
    changed |= _patch_if_present(fih, _FIH_LARGE_CALL_ORIGINAL, _FIH_LARGE_CALL_PATCHED, "FIH large-finalizer Ndblock call", strict=True)
    changed |= _patch_if_present(fih, _FIH_SMALL_HEADER_ORIGINAL, _FIH_SMALL_HEADER_PATCHED, "FIH small-header Ndblock call", strict=True)
    changed |= _patch_if_present(fih, _FIH_LARGE_SIGNATURE_ORIGINAL, _FIH_LARGE_SIGNATURE_PATCHED, "FIH large-finalizer Ndblock signature", strict=True)
    changed |= _patch_if_present(fih, _FIH_LARGE_HEADER_ORIGINAL, _FIH_LARGE_HEADER_PATCHED, "FIH large-header Ndblock call", strict=True)

    changed |= _patch_exact(vendor / PKG_BUILDER_RELATIVE, _CNT_FLAGS_ORIGINAL, _CNT_FLAGS_PATCHED, "CNT package builder")
    changed |= _patch_if_present(vendor / PACKAGE_BUILDER_RELATIVE, _PACKAGE_FINALIZER_ORIGINAL, _PACKAGE_FINALIZER_PATCHED, "package finalizer Ndblock threading", strict=True)

    changed |= _patch_exact(outer, _OUTER_ENCRYPT_ORIGINAL, _OUTER_ENCRYPT_PATCHED, "outer PFS package builder")
    changed |= _patch_if_present(outer, _OUTER_STREAM_ENCRYPT_ORIGINAL, _OUTER_STREAM_ENCRYPT_PATCHED, "outer PFS streaming builder")
    changed |= _patch_if_present(vendor / INNER_ASSEMBLER_RELATIVE, _INNER_AFID_ORIGINAL, _INNER_AFID_PATCHED, "inner AFID ordering", strict=True)

    changed |= _patch_if_present(inner_reader, _INNER_READER_DATA_END_ORIGINAL, _INNER_READER_DATA_END_PATCHED, "inner reader data/meta geometry", strict=True)
    changed |= _patch_if_present(inner_reader, _INNER_READER_LENGTH_ORIGINAL, _INNER_READER_LENGTH_PATCHED, "inner reader Cblock lengths", strict=True)
    changed |= _patch_if_present(inner_reader, _INNER_READER_DECODE_ORIGINAL, _INNER_READER_DECODE_PATCHED, "inner reader logical hole", strict=True)
    return changed
