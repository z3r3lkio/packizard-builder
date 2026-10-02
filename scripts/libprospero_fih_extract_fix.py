from __future__ import annotations

from pathlib import Path

FIH_BUILDER_RELATIVE = Path("src/LibProsperoPkg/PKG/ProsperoFihBuilder.cs")
EXTRACTOR_RELATIVE = Path("src/LibProsperoPkg/PKG/ProsperoPackageExtractor.cs")

_FIH_INODE_OLD_PROFILE = """                uint metaOrInodes = nwonly ? (uint)nwonlyInnerContentInodes : (uint)(totalBlocks - innerBlocks);
                // Known-good debug FIH references distinguish the two nwonly inode counters:
                //   0x94 = content inodes below uroot
                //   0x98 = the same count including uroot itself
                uint rootInclusiveInodes = nwonly
                    ? checked((uint)nwonlyInnerContentInodes + 1U)
                    : metaOrInodes;
                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageBlockCountField), innerBlocks);
                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountField), metaOrInodes);
                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountMirrorField), rootInclusiveInodes);
"""

_FIH_INODE_FIXED = """                uint metaOrInodes = nwonly ? (uint)nwonlyInnerContentInodes : (uint)(totalBlocks - innerBlocks);
                // Same-title PPSA02801 references mirror the nwonly inode count in 0x94 and 0x98.
                // Do not synthesize a root-inclusive +1 value: the console-facing fields are identical.
                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageBlockCountField), innerBlocks);
                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountField), metaOrInodes);
                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountMirrorField), metaOrInodes);
"""

_FIH_SIZE_OLD_PROFILE = """                ulong innerImageFieldValue = nwonlyNdblock > 0
                    ? (ulong)nwonlyNdblock * (ulong)blockSize
                    : (ulong)innerBlocks * (ulong)blockSize;
                BinaryPrimitives.WriteUInt64LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageSizeField), innerImageFieldValue);
"""

_FIH_SIZE_FIXED = """                // 0xA0 is the byte form of 0x90. Keep a single source of truth so NAPS
                // geometry changes cannot leave the block count and byte size inconsistent.
                ulong innerImageFieldValue = checked((ulong)innerBlocks * (ulong)blockSize);
                BinaryPrimitives.WriteUInt64LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageSizeField), innerImageFieldValue);
"""

_EXTRACT_OPEN_ORIGINAL = """        var outerState = PeekOuterState(new LibProsperoPkg.Util.StreamReader(pkgStream, pfsOffset));
        var candidates = key.ResolveEkpfsCandidates(contentId);

        byte[]? usedEkpfs = null;
        ProsperoPfsReader outer;
        if (outerState == OuterPfsState.Plaintext)
        {
            log("Opening outer PFS (plaintext)...");
            outer = new ProsperoPfsReader(new LibProsperoPkg.Util.StreamReader(pkgStream, pfsOffset), 0);
        }
        else if (candidates.Count == 0)
"""

_EXTRACT_OPEN_FIXED = """        var outerState = PeekOuterState(new LibProsperoPkg.Util.StreamReader(pkgStream, pfsOffset));
        var candidates = key.ResolveEkpfsCandidates(contentId);
        var plainDataFirst = OpenPlainDataFirstOuter(pkgStream, pfsOffset, pfsSize, superblockAbs);

        byte[]? usedEkpfs = null;
        ProsperoPfsReader outer;
        if (outerState == OuterPfsState.Plaintext)
        {
            log("Opening outer PFS (plaintext)...");
            outer = new ProsperoPfsReader(new LibProsperoPkg.Util.StreamReader(pkgStream, pfsOffset), 0);
        }
        else if (plainDataFirst is not null)
        {
            log("Opening outer PFS (plaintext data-first)...");
            outer = plainDataFirst;
        }
        else if (candidates.Count == 0)
"""

_LIST_OPEN_ORIGINAL = """        var outerState = PeekOuterState(new LibProsperoPkg.Util.StreamReader(pkgStream, pfsOffset));
        var candidates = key.ResolveEkpfsCandidates(contentId);

        byte[]? usedEkpfs = null;
        ProsperoPfsReader outer;
        if (outerState == OuterPfsState.Plaintext)
            outer = new ProsperoPfsReader(new LibProsperoPkg.Util.StreamReader(pkgStream, pfsOffset), 0);
        else if (candidates.Count == 0)
"""

_LIST_OPEN_FIXED = """        var outerState = PeekOuterState(new LibProsperoPkg.Util.StreamReader(pkgStream, pfsOffset));
        var candidates = key.ResolveEkpfsCandidates(contentId);
        var plainDataFirst = OpenPlainDataFirstOuter(pkgStream, pfsOffset, pfsSize, superblockAbs);

        byte[]? usedEkpfs = null;
        ProsperoPfsReader outer;
        if (outerState == OuterPfsState.Plaintext)
            outer = new ProsperoPfsReader(new LibProsperoPkg.Util.StreamReader(pkgStream, pfsOffset), 0);
        else if (plainDataFirst is not null)
            outer = plainDataFirst;
        else if (candidates.Count == 0)
"""

_HELPER_MARKER = """    private static ProsperoPfsReader? OpenOuterWithCandidates(
"""

_HELPER_FIXED = """    // Opens a data-first outer PFS whose superblock is plaintext at FIH[0x20] and whose
    // remaining blocks are also stored as-built. The regular peek starts at pfsOffset, which is
    // file data for this layout and must not be mistaken for ciphertext.
    private static ProsperoPfsReader? OpenPlainDataFirstOuter(
        Stream pkgStream, long imageOffset, long imageSize, long superblockAbs)
    {
        const int BS = ProsperoOuterPfsImage.DefaultBlockSize;
        if (imageSize <= 0 || (imageSize % BS) != 0)
            return null;

        long sbRel = superblockAbs - imageOffset;
        if (sbRel <= 0 || (sbRel % BS) != 0 || sbRel >= imageSize)
            return null;

        try
        {
            // The superblock itself must be readable in clear. Its mode may still carry the
            // encrypted bit from the logical PFS format, so only Unreadable rules this path out.
            var sbState = PeekOuterState(new LibProsperoPkg.Util.StreamReader(pkgStream, superblockAbs));
            if (sbState == OuterPfsState.Unreadable)
                return null;

            var reader = new ProsperoPfsReader(
                new LibProsperoPkg.Util.StreamReader(pkgStream, imageOffset),
                0, null, null, null, sbRel, skipDecryption: true);
            _ = reader.GetAllFiles().Any();
            return reader;
        }
        catch
        {
            // An encrypted data-first image has a plaintext superblock but encrypted metadata/data.
            // Parsing it without decryption fails here and the caller continues to the key paths.
            return null;
        }
    }

    private static ProsperoPfsReader? OpenOuterWithCandidates(
"""


def _patch_exact(path: Path, original: str, patched: str, label: str) -> bool:
    if not path.is_file():
        raise RuntimeError(f"LibProsperoPKG {label} is missing: {path}")
    text = path.read_text(encoding="utf-8")
    if patched in text:
        return False
    if original not in text:
        raise RuntimeError(
            f"Pinned LibProsperoPKG {label} no longer matches the Packizard fix preimage."
        )
    path.write_text(text.replace(original, patched, 1), encoding="utf-8")
    return True


def apply_fih_extract_fix(vendor_dir: str | Path) -> bool:
    vendor = Path(vendor_dir)
    fih = vendor / FIH_BUILDER_RELATIVE
    extractor = vendor / EXTRACTOR_RELATIVE

    changed = False
    changed |= _patch_exact(fih, _FIH_INODE_OLD_PROFILE, _FIH_INODE_FIXED, "FIH 0x94/0x98 mirror")
    changed |= _patch_exact(fih, _FIH_SIZE_OLD_PROFILE, _FIH_SIZE_FIXED, "FIH 0x90/0xA0 invariant")
    changed |= _patch_exact(extractor, _EXTRACT_OPEN_ORIGINAL, _EXTRACT_OPEN_FIXED, "extract plaintext data-first dispatch")
    changed |= _patch_exact(extractor, _LIST_OPEN_ORIGINAL, _LIST_OPEN_FIXED, "list plaintext data-first dispatch")
    changed |= _patch_exact(extractor, _HELPER_MARKER, _HELPER_FIXED, "plaintext data-first opener")
    return changed
