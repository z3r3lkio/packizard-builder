from __future__ import annotations

from pathlib import Path

GENERATOR_RELATIVE = Path("src/LibProsperoPkg/PKG/ProsperoNwonlyNapsGenerator.cs")
READER_RELATIVE = Path("src/LibProsperoPkg/PFS/ProsperoPs5InnerImageReader.cs")

_GENERATOR_FINAL_OLD = """        var doc = ProsperoNapsLayoutBuilder.BuildFromInnerImage(
            numUBlocks: numUBlocks,
            numOuterBlocks: numOuterBlocks,
            files: files,
            runStartOnDiskOffsets: runSet,
            tailBlocks: tail,
            fileLogicalOffsets: fidx);

        return ProsperoNapsLayout.BuildLayout(doc);
"""

_GENERATOR_FINAL_NEW = """        // NAPS is a compression-block map, not a file-placement map. The native DATA
        // encoder already captured the exact <=256 KiB coding blocks, including blocks that span
        // ordinary file boundaries. Re-deriving CblockInfo from Placements collapses a multi-block
        // Kraken file into one STD record and desynchronizes the logical cursor before metadata.
        var blocks = new List<NapsCblockPlanEntry>(result.DataBlocks.Count + tail.Count);
        foreach (PackizardInnerDataBlock blk in result.DataBlocks)
        {
            bool raw = blk.IsStored;
            bool fullRaw = raw && blk.UncompressedSize == Ublock256K;
            int evenComp = blk.IsMultiChunk ? blk.FirstChunkCompressedSize : blk.CompressedSize;
            blocks.Add(new NapsCblockPlanEntry
            {
                // Re-anchor every canonical coding block. This makes the compressed cursor explicit
                // and removes any dependency on file boundaries or implicit modulo carry state.
                StartRun = true,
                OnDiskOffset = blk.OnDiskOffset,
                LogicalOffset = blk.LogicalOffset,
                EvenChunkCompressedLength = fullRaw
                    ? 0x10000
                    : raw
                        ? blk.UncompressedSize
                        : evenComp,
                StreamLength = fullRaw ? 0x80000 : blk.CompressedSize,
                Even = (byte)(fullRaw ? 1 : 0),
                Odd = 1,
                KdePredictor = (byte)(raw ? (fullRaw ? 4 : 0) : 2),
                ShuffleIndex = 0,
            });
        }
        blocks.AddRange(tail);

        var doc = ProsperoNapsLayoutBuilder.BuildDocument(new NapsGenerationRequest
        {
            NumUBlocks = numUBlocks,
            NumOuterBlocks = numOuterBlocks,
            FileLogicalOffsets = fidx,
            Blocks = blocks,
        });

        return ProsperoNapsLayout.BuildLayout(doc);
"""

_READER_LENGTH_OLD = """            // CblockInfo describes compression blocks, not individual files. A single 256K DATA
            // block may span several fidx boundaries, so cutting at the next file start desynchronizes
            // CblockInfo and eventually loses the metadata superblock. Use the writer's block semantics:
            // Kde=0 is an exact raw tail/small block, normal DATA/metadata blocks are <=256K, and the
            // one logical DATA->metadata hole spans dataEnd..metaBase without consuming payload bytes.
            bool logicalHole = uncompOff == dataEnd && metaBase > dataEnd;
            long regionEnd = uncompOff < dataEnd ? dataEnd : mountSize;
            long uncompLen = logicalHole
                ? metaBase - dataEnd
                : e.KdePredictor == 0
                    ? Math.Min((long)(e.ClenEvenMinus1 / 2 + 1), regionEnd - uncompOff)
                    : Math.Min(Ublock256K, regionEnd - uncompOff);
            if (uncompLen <= 0 || i + 1 >= cb.Count)
                break;

            int evenComp = (int)(e.ClenEvenMinus1 / 2 + 1);
"""

_READER_LENGTH_NEW = """            // CblockInfo describes canonical coding blocks, not files. DATA blocks advance
            // by at most one 256 KiB logical block regardless of how many file boundaries they span.
            // The one DATA->metadata hole is logical only and consumes no pfs_image.dat bytes.
            bool logicalHole = uncompOff == dataEnd && metaBase > dataEnd;
            long uncompLen = logicalHole
                ? metaBase - dataEnd
                : uncompOff < dataEnd
                    ? Math.Min(Ublock256K, dataEnd - uncompOff)
                    : Math.Min(Ublock256K, mountSize - uncompOff);
            if (uncompLen <= 0 || i + 1 >= cb.Count)
                break;

            int evenComp = (int)(e.ClenEvenMinus1 / 2 + 1);
"""

_READER_COMP_OLD = """            NapsCblockInfoEntry next = cb[i + 1];
            long thisRel = e.CoffsetStartMod256K;
            long nextRel = next.IsRunBase ? next.CoffsetEndMod256K : next.CoffsetStartMod256K;
            int totalComp = (int)(nextRel - thisRel);
            bool kraken = e.KdePredictor == 2;
"""

_READER_COMP_NEW = """            NapsCblockInfoEntry next = cb[i + 1];
            long thisRel = e.CoffsetStartMod256K;
            long nextRel = next.IsRunBase ? next.CoffsetEndMod256K : next.CoffsetStartMod256K;
            bool kraken = e.KdePredictor == 2;
            // coffset fields are 18-bit modulo-256 KiB cursors. A linear subtraction becomes
            // negative whenever a compressed stream crosses the 0x40000 wrap and silently drops
            // the block. Recover the modular stream length instead; zero means a full 256 KiB
            // compressed span for a real Kraken block.
            long compDelta = (nextRel - thisRel) & 0x3FFFF;
            int totalComp = checked((int)(kraken && compDelta == 0 ? Ublock256K : compDelta));
"""


def _patch_exact(path: Path, original: str, patched: str, label: str) -> bool:
    if not path.is_file():
        raise RuntimeError(f"LibProsperoPKG {label} is missing: {path}")
    text = path.read_text(encoding="utf-8")
    if patched in text:
        return False
    if original not in text:
        raise RuntimeError(
            f"Pinned LibProsperoPKG {label} no longer matches the Packizard NAPS block-profile preimage."
        )
    path.write_text(text.replace(original, patched, 1), encoding="utf-8")
    return True


def apply_naps_block_profile(vendor_dir: str | Path) -> bool:
    vendor = Path(vendor_dir)
    generator = vendor / GENERATOR_RELATIVE
    reader = vendor / READER_RELATIVE

    changed = False
    changed |= _patch_exact(generator, _GENERATOR_FINAL_OLD, _GENERATOR_FINAL_NEW, "canonical DATA CblockInfo generation")
    changed |= _patch_exact(reader, _READER_LENGTH_OLD, _READER_LENGTH_NEW, "canonical DATA logical block decode")
    changed |= _patch_exact(reader, _READER_COMP_OLD, _READER_COMP_NEW, "18-bit compressed cursor wrap decode")
    return changed
