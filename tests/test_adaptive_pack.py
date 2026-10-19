from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from packizard_engine import streaming_pack


class AdaptivePackingTests(unittest.TestCase):
    def test_sample_indices_span_large_file_deterministically(self):
        indices = streaming_pack._sample_block_indices(
            size=1024 * 1024,
            block_size=64 * 1024,
            max_blocks=4,
            max_bytes=4 * 64 * 1024,
        )
        self.assertEqual(indices, [0, 5, 10, 15])

    def test_io_neutral_threshold_keeps_raw_when_page_count_is_unchanged(self):
        policy = {
            "min_savings": 64,
            "min_ratio": 0.01,
            "neutral_savings": 8 * 1024,
            "neutral_ratio": 0.125,
            "io_page": 64 * 1024,
        }
        self.assertFalse(streaming_pack._encoded_is_worthwhile(64 * 1024, 60 * 1024, policy))
        self.assertTrue(streaming_pack._encoded_is_worthwhile(64 * 1024, 48 * 1024, policy))

    def test_auto_loose_rejects_incompressible_large_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "random.bin"
            source.write_bytes(os.urandom(256 * 1024))
            rule = {"compression_mode": "fast", "compression_level": 1}
            cfg = {
                "auto_loose_large_files": True,
                "auto_loose_min_file_size": "64KiB",
                "auto_loose_sample_blocks": 4,
                "auto_loose_sample_bytes": "256KiB",
                "auto_loose_min_savings_ratio": 0.05,
                "auto_loose_max_raw_ratio": 0.90,
            }
            use_loose, message = streaming_pack._auto_loose_decision(
                source, "random.bin", rule, 16, cfg, 64 * 1024
            )
            self.assertTrue(use_loose)
            self.assertIn("auto-loose: random.bin", message or "")

    def test_auto_loose_keeps_highly_compressible_file_packed(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "zeros.bin"
            source.write_bytes(b"\0" * (256 * 1024))
            rule = {"compression_mode": "fast", "compression_level": 1}
            cfg = {
                "auto_loose_large_files": True,
                "auto_loose_min_file_size": "64KiB",
                "auto_loose_sample_blocks": 4,
                "auto_loose_sample_bytes": "256KiB",
                "auto_loose_min_savings_ratio": 0.05,
                "auto_loose_max_raw_ratio": 0.90,
            }
            use_loose, message = streaming_pack._auto_loose_decision(
                source, "zeros.bin", rule, 16, cfg, 64 * 1024
            )
            self.assertFalse(use_loose)
            self.assertIsNone(message)

    def test_worker_policy_honors_rule_overrides(self):
        policy = streaming_pack._encoding_policy(
            {
                "compression_mode": "fast",
                "compression_level": 2,
                "acceleration": 3,
                "min_savings_bytes": 16,
                "min_savings_ratio": 0.0025,
                "io_neutral_min_savings_bytes": "2KiB",
            },
            {
                "compression_mode": "hc",
                "compression_level": 9,
                "acceleration": 1,
                "min_savings_bytes": 64,
                "min_savings_ratio": 0.01,
                "io_neutral_min_savings_bytes": "8KiB",
                "io_neutral_min_savings_ratio": 0.125,
            },
            64 * 1024,
        )
        self.assertEqual(policy["mode"], "fast")
        self.assertEqual(policy["level"], 2)
        self.assertEqual(policy["acceleration"], 3)
        self.assertEqual(policy["min_savings"], 16)
        self.assertAlmostEqual(policy["min_ratio"], 0.0025)
        self.assertEqual(policy["neutral_savings"], 2 * 1024)


if __name__ == "__main__":
    unittest.main()
