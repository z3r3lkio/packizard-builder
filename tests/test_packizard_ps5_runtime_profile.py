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


def make_fixture(root: Path) -> None:
    source = root / "external" / "ampr_emu"
    (source / "src").mkdir(parents=True)
    (source / "include").mkdir(parents=True)
    (source / "ps5").mkdir(parents=True)
    (source / "third_party" / "lz4").mkdir(parents=True)
    (source / "src" / "sceampr_exports.cpp").write_text("// exports\n", encoding="utf-8")
    (source / "src" / "ampr_emu_pack.cpp").write_text("// reader\n", encoding="utf-8")
    (source / "include" / "ampr_emu_pack_format.h").write_text("// format\n", encoding="utf-8")
    (source / "ps5" / "README").write_text("sdk\n", encoding="utf-8")
    (source / "third_party" / "lz4" / "lz4.c").write_text("/* lz4 */\n", encoding="utf-8")
    (source / "Makefile").write_text("PS5_PAYLOAD_SDK ?= /opt/ps5-payload-sdk\nall:\n\t@true\n", encoding="utf-8")
    (source / "LICENSE").write_text("GPL compatibility fixture\n", encoding="utf-8")
    (root / "core").mkdir()
    (root / "resources" / "fakelib").mkdir(parents=True)


class PackizardPs5RuntimeProfileTests(unittest.TestCase):
    def test_installs_runtime_source_and_identity(self):
        module = load_module(ROOT / "ci" / "packizard_ps5_runtime.py", "packizard_ps5_runtime_test")
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            make_fixture(output)
            installed = module.install(output)
            module.assert_installed(output)
            self.assertTrue((installed / "src" / "sceampr_exports.cpp").is_file())
            identity = (output / "core" / "packizard_ps5_runtime.py").read_text(encoding="utf-8")
            self.assertIn('RUNTIME_NAME = "Packizard PS5 Runtime"', identity)
            self.assertIn('COMPATIBILITY_LIBRARY = "libSceAmpr.sprx"', identity)

    def test_runtime_build_contract_requires_payload_sdk(self):
        module = load_module(ROOT / "ci" / "packizard_ps5_runtime.py", "packizard_ps5_runtime_contract_test")
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            make_fixture(output)
            installed = module.install(output)
            wrapper = (installed / "build_packizard_runtime.sh").read_text(encoding="utf-8")
            self.assertIn("PS5_PAYLOAD_SDK", wrapper)
            self.assertIn("out/packizard/libSceAmpr.sprx", wrapper)


if __name__ == "__main__":
    unittest.main()
