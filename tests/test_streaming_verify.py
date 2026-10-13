import inspect
import unittest

from packizard_engine.streaming_verify import verify_streaming


class StreamingVerifyTests(unittest.TestCase):
    def test_verifier_does_not_materialize_whole_files(self):
        source = inspect.getsource(verify_streaming)
        self.assertNotIn("read_bytes()", source)
        self.assertNotIn("bytearray()", source)
        self.assertNotIn("bytes(data)", source)
        self.assertIn('source_handle.read(len(raw))', source)
        self.assertIn('source_handle.read(1)', source)


if __name__ == "__main__":
    unittest.main()
