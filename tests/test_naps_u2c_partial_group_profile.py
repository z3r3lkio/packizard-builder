import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "ci" / "packizard_native_naps_profile.py"
DATA = ROOT / "ci" / "native_naps" / "PackizardNativeDataStream.cs"
NAPS = ROOT / "ci" / "native_naps" / "PackizardNativeNapsEngine.cs"
WRITER = ROOT / "ci" / "native_naps" / "PackizardNativeNapsWriter.cs"
VALIDATOR = ROOT / "ci" / "native_naps" / "PackizardNativeNapsValidator.cs"
SHIM = ROOT / "ci" / "naps_u2c_partial_group_profile.py"


class PackizardNativeNapsSourceTests(unittest.TestCase):
    def test_legacy_entry_point_is_only_a_native_delegate(self):
        text = SHIM.read_text(encoding="utf-8")
        self.assertIn("import packizard_native_naps_profile as native", text)
        self.assertIn("native.apply(Path(args.root))", text)
        self.assertNotIn("_fix_file_local_data_geometry", text)
        self.assertNotIn("numCblockInfo - 1", text)

    def test_native_data_stream_coalesces_ordinary_file_boundaries(self):
        text = DATA.read_text(encoding="utf-8")
        # Contract, not prose: ordinary sources feed a shared pending U-block buffer and file changes
        # mark diagnostics instead of flushing the block. Only ForceRaw calls FlushPending at a boundary.
        self.assertIn("var pending = new byte[UBlockSize]", text)
        self.assertIn("pendingLastFile != fileIndex", text)
        self.assertIn("pendingCrossesBoundary = true", text)
        self.assertIn("ContainsFileBoundary", text)
        self.assertIn("FirstFileIndex", text)
        self.assertIn("LastFileIndex", text)
        self.assertIn("if (source.ForceRaw)", text)
        self.assertIn("FlushPending();", text)
        self.assertIn("WholeBlockRaw", text)
        self.assertNotIn("BlockIndexInFile", text)
        self.assertNotIn("FileStart", text)

    def test_native_naps_uses_interval_mapping_and_budget_guards(self):
        text = NAPS.read_text(encoding="utf-8")
        self.assertIn("PackizardNapsBudgetReport", text)
        self.assertIn("span={bad.Span}", text)
        self.assertIn("BaseRegion", text)
        self.assertIn("0xFFFFFF", text)
        self.assertIn("0xFFFFFFFFFFL", text)
        self.assertIn("LogicalEnd", text)
        self.assertIn("std[p].LogicalStart > target || target >= std[p].LogicalEnd", text)
        self.assertIn("metadata overlaps DATA", text)
        self.assertIn("This is a topology failure", text)
        self.assertIn("PackizardNativeNapsWriter.Serialize(doc)", text)
        # Comments may name the implementation being replaced; only executable calls are forbidden.
        self.assertNotIn("ProsperoNapsLayoutBuilder.Build", text)
        self.assertNotIn("ProsperoNwonlyNapsGenerator.Generate", text)
        self.assertNotIn("ProsperoNapsLayout.BuildLayout(", text)
        self.assertNotIn("% 256", text)

    def test_packizard_owns_binary_writer_and_validator(self):
        writer = WRITER.read_text(encoding="utf-8")
        validator = VALIDATOR.read_text(encoding="utf-8")
        self.assertIn("PackizardNativeNapsValidator.ValidateDocument(document)", writer)
        self.assertIn("WriteHeader", writer)
        self.assertIn("WriteU2c", writer)
        self.assertIn("WriteCblock", writer)
        self.assertNotIn("ProsperoNapsLayout.BuildLayout(", writer)
        self.assertIn("0xFFFFFF", validator)
        self.assertIn("0xFFFFFFFFFFUL", validator)
        self.assertIn("u2c", validator)

    def test_profile_bypasses_legacy_naps_generator_and_uses_logical_mount_geometry(self):
        text = PROFILE.read_text(encoding="utf-8")
        self.assertIn("PackizardNativeNapsEngine.Generate", text)
        self.assertIn("DataBlocks = dataStream.Blocks", text)
        self.assertIn("PackizardNativeDataStream.Build", text)
        self.assertIn("RoundUp(dataStream.LogicalLength, BlockSize)", text)
        self.assertIn("WholeBlockRaw = f.WholeBlockRaw", text)
        self.assertIn("inner.DataEndLogical", text)
        self.assertIn("BuildNativeImage", text)
        self.assertIn("PackizardNativeNapsWriter.cs", text)
        self.assertIn("PackizardNativeNapsValidator.cs", text)


if __name__ == "__main__":
    unittest.main()
