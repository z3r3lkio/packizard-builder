import tempfile
import unittest
from pathlib import Path

from scripts.libprospero_fih_extract_fix import apply_fih_extract_fix


FIH_OLD_PROFILE = """class F {
    void A() {
                uint metaOrInodes = nwonly ? (uint)nwonlyInnerContentInodes : (uint)(totalBlocks - innerBlocks);
                // Known-good debug FIH references distinguish the two nwonly inode counters:
                //   0x94 = content inodes below uroot
                //   0x98 = the same count including uroot itself
                uint rootInclusiveInodes = nwonly
                    ? checked((uint)nwonlyInnerContentInodes + 1U)
                    : metaOrInodes;
                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageBlockCountField), innerBlocks);
                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountField), metaOrInodes);
                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountMirrorField), rootInclusiveInodes);
                ulong innerImageFieldValue = nwonlyNdblock > 0
                    ? (ulong)nwonlyNdblock * (ulong)blockSize
                    : (ulong)innerBlocks * (ulong)blockSize;
                BinaryPrimitives.WriteUInt64LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageSizeField), innerImageFieldValue);
    }
}
"""


EXTRACTOR_ORIGINAL = """class E {
    void Extract() {
        var outerState = PeekOuterState(new LibProsperoPkg.Util.StreamReader(pkgStream, pfsOffset));
        var candidates = key.ResolveEkpfsCandidates(contentId);

        byte[]? usedEkpfs = null;
        ProsperoPfsReader outer;
        if (outerState == OuterPfsState.Plaintext)
        {
            log(\"Opening outer PFS (plaintext)...\");
            outer = new ProsperoPfsReader(new LibProsperoPkg.Util.StreamReader(pkgStream, pfsOffset), 0);
        }
        else if (candidates.Count == 0)
    }

    void ListFiles() {
        var outerState = PeekOuterState(new LibProsperoPkg.Util.StreamReader(pkgStream, pfsOffset));
        var candidates = key.ResolveEkpfsCandidates(contentId);

        byte[]? usedEkpfs = null;
        ProsperoPfsReader outer;
        if (outerState == OuterPfsState.Plaintext)
            outer = new ProsperoPfsReader(new LibProsperoPkg.Util.StreamReader(pkgStream, pfsOffset), 0);
        else if (candidates.Count == 0)
    }

    private static ProsperoPfsReader? OpenOuterWithCandidates(
        Stream pkgStream, long pfsOffset, IReadOnlyList<byte[]> candidates, out byte[]? used)
    {
        return null;
    }
}
"""


class LibProsperoFihExtractFixTests(unittest.TestCase):
    def _vendor(self, root: Path, fih: str = FIH_OLD_PROFILE, extractor: str = EXTRACTOR_ORIGINAL) -> Path:
        vendor = root / "LibProsperoPKG"
        pkg = vendor / "src" / "LibProsperoPkg" / "PKG"
        pkg.mkdir(parents=True)
        (pkg / "ProsperoFihBuilder.cs").write_text(fih, encoding="utf-8")
        (pkg / "ProsperoPackageExtractor.cs").write_text(extractor, encoding="utf-8")
        return vendor

    def test_enforces_fih_mirrors_and_size_invariant(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td))
            self.assertTrue(apply_fih_extract_fix(vendor))
            text = (vendor / "src/LibProsperoPkg/PKG/ProsperoFihBuilder.cs").read_text(encoding="utf-8")

            self.assertNotIn("rootInclusiveInodes", text)
            self.assertIn("FihMetaBlockCountMirrorField), metaOrInodes", text)
            self.assertNotIn("nwonlyNdblock > 0", text)
            self.assertIn("checked((ulong)innerBlocks * (ulong)blockSize)", text)

    def test_adds_plaintext_data_first_before_key_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td))
            self.assertTrue(apply_fih_extract_fix(vendor))
            text = (vendor / "src/LibProsperoPkg/PKG/ProsperoPackageExtractor.cs").read_text(encoding="utf-8")

            self.assertEqual(text.count("OpenPlainDataFirstOuter(pkgStream, pfsOffset, pfsSize, superblockAbs)"), 2)
            self.assertIn("Opening outer PFS (plaintext data-first)...", text)
            self.assertIn("sbRel, skipDecryption: true", text)
            self.assertLess(text.index("plainDataFirst is not null"), text.index("candidates.Count == 0"))

    def test_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td))
            self.assertTrue(apply_fih_extract_fix(vendor))
            self.assertFalse(apply_fih_extract_fix(vendor))

    def test_refuses_unknown_preimage(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td), fih="// changed upstream\n")
            with self.assertRaises(RuntimeError):
                apply_fih_extract_fix(vendor)


if __name__ == "__main__":
    unittest.main()
