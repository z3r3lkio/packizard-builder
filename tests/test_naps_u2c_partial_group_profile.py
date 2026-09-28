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
        self.assertIn("from packizard_native_naps_profile import apply", text)
        self.assertNotIn("numCblockInfo - 1", text)

    def test_native_data_stream_is_file_count_independent(self):
        text = DATA.read_text(encoding="utf-8")
        self.assertIn("exactly one Kraken/stored decision per U-block", text)
        self.assertIn("PackizardInnerDataBlock", text)
        self.assertIn("FlushBlock", text)
        self.assertIn("ForceRaw", text)

    def test_native_naps_has_budget_and_field_guards(self):
        text = NAPS.read_text(encoding="utf-8")
        self.assertIn("PackizardNapsBudgetReport", text)
        self.assertIn("span={bad.Span}", text)
        self.assertIn("0xFFFFFF", text)
        self.assertIn("DeltaByte", text)
        self.assertNotIn("% 256", text)

    def test_profile_bypasses_legacy_naps_generator(self):
        text = PROFILE.read_text(encoding="utf-8")
        self.assertIn("PackizardNativeNapsEngine.Generate", text)
        self.assertIn("DataBlocks = dataStream.Blocks", text)
        self.assertIn("PackizardNativeDataStream.Build", text)


if __name__ == "__main__":
    unittest.main()
