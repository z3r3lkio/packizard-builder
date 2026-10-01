import tempfile
import unittest
from pathlib import Path

from scripts.stamp_build_version import compute_version, write_version


class BuildVersionTests(unittest.TestCase):
    def test_feature_increments_patch_only(self):
        self.assertEqual(
            compute_version("feature", main_promotions=0, uat_promotions=0, feature_commits=1),
            "0.2.1",
        )
        self.assertEqual(
            compute_version("feature", main_promotions=0, uat_promotions=0, feature_commits=9),
            "0.2.9",
        )

    def test_uat_increments_middle_and_resets_patch(self):
        self.assertEqual(
            compute_version("uat", main_promotions=0, uat_promotions=1, feature_commits=42),
            "0.3.0",
        )

    def test_main_increments_major_and_resets_lower_components(self):
        self.assertEqual(
            compute_version("main", main_promotions=1, uat_promotions=99, feature_commits=99),
            "1.0.0",
        )
        self.assertEqual(
            compute_version("main", main_promotions=2, uat_promotions=3, feature_commits=7),
            "2.0.0",
        )

    def test_uat_counter_restarts_after_main_promotion(self):
        self.assertEqual(
            compute_version("uat", main_promotions=1, uat_promotions=0),
            "1.0.0",
        )
        self.assertEqual(
            compute_version("uat", main_promotions=1, uat_promotions=2),
            "1.2.0",
        )

    def test_write_version_bakes_value_into_runtime_module(self):
        with tempfile.TemporaryDirectory() as td:
            path = write_version(Path(td) / "version.py", "3.4.5", "feature")
            text = path.read_text(encoding="utf-8")
            self.assertIn('VERSION = "3.4.5"', text)
            self.assertIn('BUILD_CHANNEL = "feature"', text)


if __name__ == "__main__":
    unittest.main()
