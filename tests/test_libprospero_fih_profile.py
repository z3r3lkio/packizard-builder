import tempfile
import unittest
from pathlib import Path

from scripts.libprospero_fih_profile import apply_fih_reference_profile


FIH_ORIGINAL_SNIPPET = """using System;\nnamespace LibProsperoPkg.PKG;\nclass X {\n    void Y() {\n                uint metaOrInodes = nwonly ? (uint)nwonlyInnerContentInodes : (uint)(totalBlocks - innerBlocks);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageBlockCountField), innerBlocks);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountField), metaOrInodes);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountMirrorField), metaOrInodes);\n    }\n}\n"""

PKG_ORIGINAL_SNIPPET = """class P {\n    // The PS5 Flags1 word for each entry id.\n    private static uint Flags1For(uint id) => id switch\n    {\n        (uint)ProsperoCntEntryId.DIGESTS => 0x40000000,\n        (uint)ProsperoCntEntryId.ENTRY_KEYS => 0x60000000,\n        (uint)ProsperoCntEntryId.IMAGE_KEY => 0x60000000,        // image key is not entry-encrypted.\n        (uint)ProsperoCntEntryId.GENERAL_DIGESTS => 0x60000000,\n        (uint)ProsperoCntEntryId.METAS => 0x60000000,\n        (uint)ProsperoCntEntryId.ENTRY_NAMES => 0x40000000,\n        0x2000 => 0x00000000,                          // param.json\n        _ => 0x08000000,                               // media / data entries\n    };\n\n    // No CNT entries in this package class are entry-encrypted, so Flags2 is always zero.\n    private static uint Flags2For(uint id) => 0u;\n}\n"""


class LibProsperoFihProfileTests(unittest.TestCase):
    def _vendor(self, root: Path, fih: str = FIH_ORIGINAL_SNIPPET, pkg: str = PKG_ORIGINAL_SNIPPET) -> Path:
        vendor = root / "LibProsperoPKG"
        base = vendor / "src" / "LibProsperoPkg" / "PKG"
        base.mkdir(parents=True)
        (base / "ProsperoFihBuilder.cs").write_text(fih, encoding="utf-8")
        (base / "ProsperoPkgBuilder.cs").write_text(pkg, encoding="utf-8")
        return vendor

    def test_applies_reference_inode_split_and_system_entry_flags(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td))
            self.assertTrue(apply_fih_reference_profile(vendor))

            base = vendor / "src" / "LibProsperoPkg" / "PKG"
            fih = (base / "ProsperoFihBuilder.cs").read_text(encoding="utf-8")
            pkg = (base / "ProsperoPkgBuilder.cs").read_text(encoding="utf-8")

            self.assertIn("rootInclusiveInodes", fih)
            self.assertIn("nwonlyInnerContentInodes + 1U", fih)
            self.assertIn("FihMetaBlockCountField), metaOrInodes", fih)
            self.assertIn("FihMetaBlockCountMirrorField), rootInclusiveInodes", fih)

            self.assertIn("ProsperoCntEntryId.LICENSE_DAT => 0x80000000", pkg)
            self.assertIn("ProsperoCntEntryId.LICENSE_INFO => 0x80000000", pkg)
            self.assertIn("ProsperoCntEntryId.NPTITLE_DAT => 0x80000000", pkg)
            self.assertIn("ProsperoCntEntryId.NPBIND_DAT => 0x80000000", pkg)
            self.assertIn("ProsperoCntEntryId.LICENSE_INFO => 0x00004000", pkg)
            self.assertIn("ProsperoCntEntryId.NPTITLE_DAT => 0x00003000", pkg)
            self.assertIn("0x2020 => 0x00003000", pkg)
            self.assertIn("0x2021 => 0x00003000", pkg)

    def test_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td))
            self.assertTrue(apply_fih_reference_profile(vendor))
            self.assertFalse(apply_fih_reference_profile(vendor))

    def test_refuses_unknown_fih_preimage(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td), fih="// changed upstream\n")
            with self.assertRaises(RuntimeError):
                apply_fih_reference_profile(vendor)

    def test_refuses_unknown_pkg_preimage(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td), pkg="// changed upstream\n")
            with self.assertRaises(RuntimeError):
                apply_fih_reference_profile(vendor)


if __name__ == "__main__":
    unittest.main()
