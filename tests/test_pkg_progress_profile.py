import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / "ci"


class PkgProgressProfileTests(unittest.TestCase):
    def test_profile_contains_direct_io_and_progress_contract(self):
        source = (CI / "pkg_progress_profile.py").read_text(encoding="utf-8")
        self.assertIn("AMPR direct-I/O enabled; redundant staging copy skipped.", source)
        self.assertIn("Inner preparation:", source)
        self.assertIn("Inner preparation complete:", source)
        self.assertIn("KRAKEN", source)
        self.assertIn("Inner metadata plaintext ready:", source)
        self.assertIn("Inner image metadata encoded:", source)
        self.assertIn("Inner image write starting:", source)
        self.assertIn("Inner image write:", source)
        self.assertIn("NAPS layout generated:", source)
        self.assertIn("MiB/s", source)
        self.assertIn("ETA", source)
        self.assertIn("PackizardProgressCallback", source)
        self.assertIn(
            "public long BuildToFile(IReadOnlyList<ProsperoPs5InnerPayload> payloads, string outputPath)",
            source,
        )

    def test_bootstrap_applies_progress_after_ampr_profile(self):
        source = (CI / "bootstrap_source.py").read_text(encoding="utf-8")
        ampr = source.index("ampr_profile.apply(root)")
        progress = source.index("progress_profile.apply(root)")
        self.assertGreater(progress, ampr)


if __name__ == "__main__":
    unittest.main()
