import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "ci" / "naps_u2c_partial_group_profile.py"
TARGET = Path("vendor/LibProsperoPKG/src/LibProsperoPkg/PKG/ProsperoNapsLayoutBuilder.cs")


def load_profile():
    spec = importlib.util.spec_from_file_location("naps_u2c_partial_group_profile", PROFILE)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class NapsU2cPartialGroupProfileTests(unittest.TestCase):
    def test_unused_terminal_slots_are_zero_filled(self):
        profile = load_profile()
        legacy = '''class Fixture\n{\n        int Delta(int ublock, int baseIndex)\n        {\n            if (ublock < numUBlocks) return first[ublock] - baseIndex;\n            return (numCblockInfo - 1) - baseIndex;             // beyond last ublock -> terminator\n        }\n}\n'''
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / TARGET
            target.parent.mkdir(parents=True)
            target.write_text(legacy, encoding="utf-8")
            profile.apply(root)
            patched = target.read_text(encoding="utf-8")

        self.assertIn("if (ublock >= numUBlocks) return 0;", patched)
        self.assertIn("for real U-block", patched)
        self.assertNotIn("beyond last ublock -> terminator", patched)

    def test_profile_is_idempotent(self):
        profile = load_profile()
        legacy = '''class Fixture\n{\n        int Delta(int ublock, int baseIndex)\n        {\n            if (ublock < numUBlocks) return first[ublock] - baseIndex;\n            return (numCblockInfo - 1) - baseIndex;             // beyond last ublock -> terminator\n        }\n}\n'''
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / TARGET
            target.parent.mkdir(parents=True)
            target.write_text(legacy, encoding="utf-8")
            profile.apply(root)
            once = target.read_text(encoding="utf-8")
            profile.apply(root)
            twice = target.read_text(encoding="utf-8")
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
