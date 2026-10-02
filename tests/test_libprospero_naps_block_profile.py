import tempfile
import unittest
from pathlib import Path

from scripts.libprospero_naps_block_profile import apply_naps_block_profile


GENERATOR = """class G {
    void X() {
        var doc = ProsperoNapsLayoutBuilder.BuildFromInnerImage(
            numUBlocks: numUBlocks,
            numOuterBlocks: numOuterBlocks,
            files: files,
            runStartOnDiskOffsets: runSet,
            tailBlocks: tail,
            fileLogicalOffsets: fidx);

        return ProsperoNapsLayout.BuildLayout(doc);
    }
}
"""

READER = """class R {
    void X() {
            // CblockInfo describes compression blocks, not individual files. A single 256K DATA
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
            NapsCblockInfoEntry next = cb[i + 1];
            long thisRel = e.CoffsetStartMod256K;
            long nextRel = next.IsRunBase ? next.CoffsetEndMod256K : next.CoffsetStartMod256K;
            int totalComp = (int)(nextRel - thisRel);
            bool kraken = e.KdePredictor == 2;
    }
}
"""


class NapsBlockProfileTests(unittest.TestCase):
    def _vendor(self, root: Path) -> Path:
        vendor = root / "LibProsperoPKG"
        pkg = vendor / "src/LibProsperoPkg/PKG"
        pfs = vendor / "src/LibProsperoPkg/PFS"
        pkg.mkdir(parents=True)
        pfs.mkdir(parents=True)
        (pkg / "ProsperoNwonlyNapsGenerator.cs").write_text(GENERATOR, encoding="utf-8")
        (pfs / "ProsperoPs5InnerImageReader.cs").write_text(READER, encoding="utf-8")
        return vendor

    def test_uses_canonical_data_blocks_and_modular_cursor(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td))
            self.assertTrue(apply_naps_block_profile(vendor))
            generator = (vendor / "src/LibProsperoPkg/PKG/ProsperoNwonlyNapsGenerator.cs").read_text(encoding="utf-8")
            reader = (vendor / "src/LibProsperoPkg/PFS/ProsperoPs5InnerImageReader.cs").read_text(encoding="utf-8")

            self.assertIn("foreach (PackizardInnerDataBlock blk in result.DataBlocks)", generator)
            self.assertIn("StartRun = true", generator)
            self.assertIn("Blocks = blocks", generator)
            self.assertNotIn("BuildFromInnerImage(", generator)

            self.assertIn("Math.Min(Ublock256K, dataEnd - uncompOff)", reader)
            self.assertIn("(nextRel - thisRel) & 0x3FFFF", reader)
            self.assertIn("compDelta == 0 ? Ublock256K", reader)

    def test_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td))
            self.assertTrue(apply_naps_block_profile(vendor))
            self.assertFalse(apply_naps_block_profile(vendor))


if __name__ == "__main__":
    unittest.main()
