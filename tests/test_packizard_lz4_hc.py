from __future__ import annotations

import unittest

from packizard_engine.packizard_lz4 import PackizardLz4Codec, decompress_block


class PackizardLz4HcTests(unittest.TestCase):
    def setUp(self):
        self.codec = PackizardLz4Codec()
        self.sample = (
            (b"ABCD" * 8192)
            + (b"0123456789abcdef" * 4096)
            + (b"ABCD" * 8192)
            + bytes(range(256)) * 128
        )

    def test_all_levels_round_trip(self):
        for level in range(1, 13):
            mode = "fast" if level <= 4 else "hc"
            encoded = self.codec.compress(self.sample, mode=mode, level=level)
            decoded = decompress_block(encoded, len(self.sample))
            self.assertEqual(decoded, self.sample, f"round-trip failed at level {level}")

    def test_hc_levels_are_deterministic(self):
        for level in range(5, 13):
            first = self.codec.compress(self.sample, mode="hc", level=level)
            second = self.codec.compress(self.sample, mode="hc", level=level)
            self.assertEqual(first, second)

    def test_higher_hc_depth_does_not_regress_reference_sample(self):
        sizes = [
            len(self.codec.compress(self.sample, mode="hc", level=level))
            for level in range(5, 13)
        ]
        for previous, current in zip(sizes, sizes[1:]):
            self.assertLessEqual(current, previous)

    def test_fast_levels_change_search_density(self):
        outputs = [
            self.codec.compress(self.sample, mode="fast", level=level)
            for level in range(1, 5)
        ]
        self.assertGreaterEqual(len(set(outputs)), 2)


if __name__ == "__main__":
    unittest.main()
