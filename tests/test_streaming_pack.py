import inspect
import unittest

from packizard_engine import packer
from packizard_engine import streaming_pack


class StreamingPackTests(unittest.TestCase):
    def test_install_replaces_legacy_build(self):
        legacy = packer.build
        try:
            streaming_pack.install()
            self.assertIsNot(packer.build, legacy)
            source = inspect.getsource(packer.build)
            self.assertIn("build_streaming", source)
        finally:
            packer.build = legacy

    def test_streaming_builder_does_not_retain_game_payload_collection(self):
        source = inspect.getsource(streaming_pack.build_streaming)
        self.assertNotIn("source.read_bytes", source)
        self.assertNotIn("payloads.append", source)
        self.assertIn('source.open("rb")', source)
        self.assertIn('pack_path.open("w+b")', source)
        self.assertIn("handle.write(stored)", source)


if __name__ == "__main__":
    unittest.main()
