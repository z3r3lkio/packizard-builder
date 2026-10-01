import tempfile
import unittest
from pathlib import Path

from scripts.libprospero_fih_profile import apply_fih_reference_profile


ORIGINAL_SNIPPET = """using System;\nnamespace LibProsperoPkg.PKG;\nclass X {\n    void Y() {\n                uint metaOrInodes = nwonly ? (uint)nwonlyInnerContentInodes : (uint)(totalBlocks - innerBlocks);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageBlockCountField), innerBlocks);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountField), metaOrInodes);\n                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountMirrorField), metaOrInodes);\n    }\n}\n"""


class LibProsperoFihProfileTests(unittest.TestCase):
    def _vendor_with_builder(self, root: Path, content: str = ORIGINAL_SNIPPET) -> Path:
        vendor = root / "LibProsperoPKG"
        target = vendor / "src" / "LibProsperoPkg" / "PKG" / "ProsperoFihBuilder.cs"
        target.parent.mkdir(parents=True)
        target.write_text(content, encoding="utf-8")
        return vendor

    def test_applies_reference_inode_split(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor_with_builder(Path(td))
            self.assertTrue(apply_fih_reference_profile(vendor))
            text = (vendor / "src" / "LibProsperoPkg" / "PKG" / "ProsperoFihBuilder.cs").read_text(encoding="utf-8")
            self.assertIn("rootInclusiveInodes", text)
            self.assertIn("nwonlyInnerContentInodes + 1U", text)
            self.assertIn("FihMetaBlockCountField), metaOrInodes", text)
            self.assertIn("FihMetaBlockCountMirrorField), rootInclusiveInodes", text)

    def test_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor_with_builder(Path(td))
            self.assertTrue(apply_fih_reference_profile(vendor))
            self.assertFalse(apply_fih_reference_profile(vendor))

    def test_refuses_unknown_upstream_preimage(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor_with_builder(Path(td), "// changed upstream\n")
            with self.assertRaises(RuntimeError):
                apply_fih_reference_profile(vendor)


if __name__ == "__main__":
    unittest.main()
