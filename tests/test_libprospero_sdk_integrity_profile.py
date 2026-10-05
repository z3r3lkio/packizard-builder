import tempfile
import unittest
from pathlib import Path

from scripts.libprospero_sdk_integrity_profile import apply_sdk_integrity_profile


PROFILED_FIH = """class F {
    void Build() {
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


class SdkIntegrityProfileTests(unittest.TestCase):
    def _vendor(self, root: Path, source: str = PROFILED_FIH) -> Path:
        vendor = root / "LibProsperoPKG"
        path = vendor / "src/LibProsperoPkg/PKG/ProsperoFihBuilder.cs"
        path.parent.mkdir(parents=True)
        path.write_text(source, encoding="utf-8")
        return vendor

    def test_enforces_sdk_reference_fih_geometry(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td))
            self.assertTrue(apply_sdk_integrity_profile(vendor))
            text = (vendor / "src/LibProsperoPkg/PKG/ProsperoFihBuilder.cs").read_text(encoding="utf-8")

            self.assertNotIn("rootInclusiveInodes", text)
            self.assertIn(
                "FihMetaBlockCountMirrorField), metaOrInodes",
                text,
            )
            self.assertNotIn("nwonlyNdblock > 0", text)
            self.assertIn(
                "innerImageFieldValue = (ulong)innerBlocks * (ulong)blockSize",
                text,
            )

    def test_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td))
            self.assertTrue(apply_sdk_integrity_profile(vendor))
            self.assertFalse(apply_sdk_integrity_profile(vendor))

    def test_refuses_unknown_preimage(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td), "// changed upstream\n")
            with self.assertRaises(RuntimeError):
                apply_sdk_integrity_profile(vendor)


if __name__ == "__main__":
    unittest.main()
