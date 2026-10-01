from __future__ import annotations

import os
import random
import unittest

from native.packizard_lz4 import PackizardLz4Error, PackizardLz4Codec, compress_block, decompress_block


class PackizardLz4Tests(unittest.TestCase):
    def round_trip(self, payload: bytes) -> None:
        encoded = compress_block(payload)
        decoded = decompress_block(encoded, len(payload))
        self.assertEqual(decoded, payload)

    def test_empty(self):
        self.round_trip(b"")

    def test_small_literals(self):
        for size in range(1, 32):
            self.round_trip(bytes(range(size)))

    def test_repetitive_payloads(self):
        for payload in (
            b"A" * 65536,
            (b"PackizardEngine" * 8192),
            bytes(range(256)) * 2048,
            (b"abcd" * 262144),
        ):
            self.round_trip(payload)

    def test_random_payloads(self):
        rng = random.Random(0x5041434B495A4152)
        for size in (64, 1024, 16384, 65536):
            payload = bytes(rng.randrange(256) for _ in range(size))
            self.round_trip(payload)

    def test_codec_contract(self):
        codec = PackizardLz4Codec()
        payload = (b"packizard-native-lz4/" * 4096) + os.urandom(97)
        for mode in ("fast", "hc"):
            encoded = codec.compress(payload, mode=mode, level=12, acceleration=1)
            self.assertEqual(codec.decompress(encoded, len(payload)), payload)

    def test_rejects_zero_offset(self):
        with self.assertRaises(PackizardLz4Error):
            decompress_block(b"\x00\x00\x00", 4)

    def test_rejects_output_overflow(self):
        encoded = compress_block(b"A" * 1024)
        with self.assertRaises(PackizardLz4Error):
            decompress_block(encoded, 1023)


if __name__ == "__main__":
    unittest.main()
