from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackizardPs5RuntimeProfileTests(unittest.TestCase):
    def test_installs_runtime_source_and_identity(self):
        module = load_module(ROOT / "ci" / "packizard_ps5_runtime.py", "packizard_ps5_runtime_test")
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            (output / "core").mkdir()
            (output / "resources" / "fakelib").mkdir(parents=True)
            installed = module.install(ROOT, output)
            module.assert_installed(output)
            self.assertTrue((installed / "src" / "sceampr_exports.cpp").is_file())
            identity = (output / "core" / "packizard_ps5_runtime.py").read_text(encoding="utf-8")
            self.assertIn('RUNTIME_NAME = "Packizard PS5 Runtime"', identity)
            self.assertIn('COMPATIBILITY_LIBRARY = "libSceAmpr.sprx"', identity)

    def test_runtime_archive_is_pinned(self):
        module = load_module(ROOT / "ci" / "packizard_ps5_runtime.py", "packizard_ps5_runtime_hash_test")
        archive = ROOT / "runtime" / "ps5" / module.ARCHIVE_NAME
        import hashlib
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), module.ARCHIVE_SHA256)


if __name__ == "__main__":
    unittest.main()
