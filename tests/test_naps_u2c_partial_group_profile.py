import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "ci" / "packizard_native_naps_profile.py"
DATA = ROOT / "ci" / "native_naps" / "PackizardNativeDataStream.cs"
NAPS = ROOT / "ci" / "native_naps" / "PackizardNativeNapsEngine.cs"
SHIM = ROOT / "ci" / "naps_u2c_partial_group_profile.py"


class PackizardNativeNapsSourceTests(unittest.TestCase):
    def test_legacy_entry_point_delegates_to_native_profile(self):
        text = SHIM.read_text(encoding="utf-8")
        self.assertIn("import packizard_native_naps_profile as native", text)
        self.assertIn("native.apply(root)", text)
        self.assertIn("_fix_file_local_data_geometry(root)", text)
        self.assertIn("_fix_naps_meta_geometry(root)", text)
        self.assertIn("_fix_logical_mount_geometry(root)", text)
        self.assertNotIn("numCblockInfo - 1", text)

    def test_native_data_stream_preserves_file_boundaries(self):
        text = DATA.read_text(encoding="utf-8")
        self.assertIn("A block never crosses a file", text)
        self.assertIn("FileIndex", text)
        self.assertIn("BlockIndexInFile", text)
        self.assertIn("FileStart", text)
        self.assertIn("WholeBlockRaw", text)
        self.assertIn("ForceRaw", text)

    def test_native_naps_has_budget_geometry_and_field_guards(self):
        text = NAPS.read_text(encoding="utf-8")
        self.assertIn("PackizardNapsBudgetReport", text)
        self.assertIn("span={bad.Span}", text)
        self.assertIn("baseregion", text.lower())
        self.assertIn("0xFFFFFF", text)
        self.assertIn("0xFFFFFFFFFFL", text)
        self.assertIn("DeltaByte", text)
        self.assertIn("metadata overlaps DATA", text)
        self.assertIn("This is a topology failure", text)
        self.assertNotIn("% 256", text)

    def test_profile_bypasses_legacy_naps_generator(self):
        text = PROFILE.read_text(encoding="utf-8")
        self.assertIn("PackizardNativeNapsEngine.Generate", text)
        self.assertIn("DataBlocks = dataStream.Blocks", text)
        self.assertIn("PackizardNativeDataStream.Build", text)

    def test_shim_separates_logical_mount_from_physical_data_size(self):
        text = SHIM.read_text(encoding="utf-8")
        self.assertIn("dataStream.LogicalLength", text)
        self.assertIn("WholeBlockRaw = f.WholeBlockRaw", text)
        self.assertIn("b.FileIndex == fileIndex", text)
        self.assertIn("inner.DataEndLogical", text)
        self.assertIn("_ensure_native_image_writer", text)
        self.assertIn("BuildNativeImage", text)
        self.assertIn("dataStream.EncodedLength", text)


if __name__ == "__main__":
    unittest.main()
