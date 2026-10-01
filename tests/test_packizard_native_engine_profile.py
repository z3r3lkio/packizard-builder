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
            self.assertIn("Packizard Compression", (root / "gui" / "page.py").read_text(encoding="utf-8"))

    def test_product_reference_guard_rejects_legacy_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "core").mkdir()
            (root / "main.py").write_text('TITLE = "Lazy_AMPR"\n', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                native_profile.assert_product_references_are_clean(root)

    def test_desktop_engine_installs_outside_external_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for folder in ("core", "gui", "utils", "tests"):
                (root / folder).mkdir(parents=True, exist_ok=True)
            (root / "core" / "lz4_packer.py").write_text(
                'from pathlib import Path\nTOOLS_DIR = Path(__file__).resolve().parent.parent / "external" / "ampr_emu" / "tools"\nX = TOOLS_DIR / "ampr_pack.py"\n',
                encoding="utf-8",
            )
            native_profile.install_engine(ROOT, root)
            native_profile.assert_desktop_engine_is_native(root)
            engine = root / "packizard_engine"
            for name in ("__init__.py", "lz4.py", "container.py", "packer.py", "profile.py"):
                self.assertTrue((engine / name).is_file())
            core_text = (root / "core" / "lz4_packer.py").read_text(encoding="utf-8")
            self.assertIn('"packizard_engine"', core_text)
            self.assertIn('TOOLS_DIR / "packer.py"', core_text)
            self.assertNotIn("external/ampr_emu", core_text)
            completed = subprocess.run(
                [sys.executable, "-c", "import packizard_engine.packer as p; print(p.VERSION)"],
                cwd=root,
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
            (root / "tests" / "test_build_diagnostics.py").write_text(
                "entry = root / 'worker_ampr_pack.py'\nprofile = root / 'worker_ampr_pack_profile.py'\n",
                encoding="utf-8",
            )
            for name in ("build_windows.ps1", "build_linux.sh", "build_macos.sh"):
                (root / name).write_text('ampr_pack.spec ampr_pack_profile.spec ampr_pack ampr_pack_profile\n', encoding="utf-8")
            worker_profile.apply(root)
            single_profile.apply(root)
            main_spec = (root / "Packizard_Builder_OneFile.spec").read_text(encoding="utf-8")
            windows_build = (root / "build_windows.ps1").read_text(encoding="utf-8")
            packer_spec = (root / "Packizard_Packer_Worker.spec").read_text(encoding="utf-8")
            runner = (root / "utils" / "tool_runner.py").read_text(encoding="utf-8")
            diagnostics_test = (root / "tests" / "test_build_diagnostics.py").read_text(encoding="utf-8")
            self.assertIn('name="Packizard-Builder"', main_spec)
            self.assertIn("workers/Packizard-Packer-Worker", main_spec)
            self.assertIn("workers/Packizard-Profile-Worker", main_spec)
            self.assertNotIn("workers/ampr_pack", main_spec)
            self.assertIn("Packizard-Builder.exe", windows_build)
            self.assertIn("Packizard_Packer_Worker.spec", windows_build)
            self.assertIn("Packizard_Profile_Worker.spec", windows_build)
            self.assertNotIn("coll = COLLECT", packer_spec)
            self.assertNotIn("external/ampr_emu/tools", packer_spec)
            self.assertIn("_MEIPASS", runner)
            self.assertIn("worker_packizard_packer.py", diagnostics_test)
            self.assertIn("worker_packizard_profile.py", diagnostics_test)
            self.assertFalse((root / "ampr_pack.spec").exists())
            self.assertFalse((root / "ampr_pack_profile.spec").exists())


if __name__ == "__main__":
    unittest.main()
