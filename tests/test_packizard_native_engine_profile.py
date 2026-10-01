from __future__ import annotations

import importlib.util
import subprocess
import sys
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


native_profile = load_module(ROOT / "ci" / "packizard_native_engine.py", "packizard_native_engine_test")
worker_profile = load_module(ROOT / "ci" / "internal_worker_profile.py", "internal_worker_profile_test")
single_profile = load_module(ROOT / "ci" / "single_executable_profile.py", "single_executable_profile_test")


class NativeEngineProfileTests(unittest.TestCase):
    def test_ui_rebranding_removes_legacy_product_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "gui").mkdir()
            (root / "core").mkdir()
            (root / "main.py").write_text('TITLE = "Lazy_AMPR - AMPR/LZ4 compression"\n', encoding="utf-8")
            (root / "gui" / "page.py").write_text('LABEL = "LZ4 Compression"\n', encoding="utf-8")
            changed = native_profile.patch_product_ui(root)
            self.assertEqual(len(changed), 2)
            native_profile.assert_product_references_are_clean(root)
            main_text = (root / "main.py").read_text(encoding="utf-8")
            self.assertIn("Packizard Builder", main_text)
            self.assertIn("Packizard compression", main_text)
            self.assertNotIn("Lazy", main_text)
            self.assertNotIn("AMPR/LZ4", main_text)
            self.assertIn("Packizard Compression", (root / "gui" / "page.py").read_text(encoding="utf-8"))

    def test_product_reference_guard_rejects_legacy_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "core").mkdir()
            (root / "main.py").write_text('TITLE = "Lazy_AMPR"\n', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                native_profile.assert_product_references_are_clean(root)

    def test_native_packer_replaces_inherited_format_module(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tools = root / "external" / "ampr_emu" / "tools"
            tools.mkdir(parents=True)
            (tools / "ampr_pack.py").write_text("# inherited implementation\n", encoding="utf-8")
            (tools / "ampr_pack_format.py").write_text("# inherited format\n", encoding="utf-8")
            native_profile.install_engine(ROOT, root)
            native_profile.assert_packizard_packer_is_native(root)
            self.assertTrue((tools / "packizard_lz4.py").is_file())
            self.assertTrue((tools / "packizard_container.py").is_file())
            self.assertTrue((tools / "packizard_packer.py").is_file())
            self.assertFalse((tools / "ampr_pack_format.py").exists())
            wrapper = (tools / "ampr_pack.py").read_text(encoding="utf-8")
            self.assertIn("from packizard_packer import", wrapper)
            completed = subprocess.run(
                [sys.executable, "-c", "import packizard_packer; print(packizard_packer.VERSION)"],
                cwd=tools,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("Packizard Engine", completed.stdout)

    def test_single_executable_profile_uses_packizard_helper_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for folder in ("core", "utils", "gui", "tests"):
                (root / folder).mkdir()
            (root / "utils" / "tool_runner.py").write_text('ROOT = Path(sys.executable).resolve().parent\n', encoding="utf-8")
            (root / "tests" / "test_cross_platform.py").write_text('', encoding="utf-8")
            for name in ("build_windows.ps1", "build_linux.sh", "build_macos.sh"):
                (root / name).write_text('ampr_pack.spec ampr_pack_profile.spec ampr_pack ampr_pack_profile\n', encoding="utf-8")
            worker_profile.apply(root)
            single_profile.apply(root)
            main_spec = (root / "Packizard_Builder_OneFile.spec").read_text(encoding="utf-8")
            windows_build = (root / "build_windows.ps1").read_text(encoding="utf-8")
            packer_spec = (root / "Packizard_Packer_Worker.spec").read_text(encoding="utf-8")
            runner = (root / "utils" / "tool_runner.py").read_text(encoding="utf-8")
            self.assertIn('name="Packizard-Builder"', main_spec)
            self.assertIn("workers/Packizard-Packer-Worker", main_spec)
            self.assertIn("workers/Packizard-Profile-Worker", main_spec)
            self.assertNotIn("workers/ampr_pack", main_spec)
            self.assertIn("Packizard-Builder.exe", windows_build)
            self.assertIn("Packizard_Packer_Worker.spec", windows_build)
            self.assertIn("Packizard_Profile_Worker.spec", windows_build)
            self.assertNotIn("coll = COLLECT", packer_spec)
            self.assertIn("_MEIPASS", runner)
            self.assertFalse((root / "ampr_pack.spec").exists())
            self.assertFalse((root / "ampr_pack_profile.spec").exists())


if __name__ == "__main__":
    unittest.main()
