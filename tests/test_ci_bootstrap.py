import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'ci' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BootstrapRegressionTests(unittest.TestCase):
    def test_pinned_checkout_is_prepared_before_overrides(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'scripts').mkdir()
            (root / 'scripts' / 'prepare_pkg_bridge.py').write_text(
                "def ensure_upstream():\n    raise RuntimeError('checkout requested')\n",
                encoding='utf-8',
            )
            with self.assertRaisesRegex(RuntimeError, '^checkout requested$'):
                load('bootstrap_source')._apply_large_pkg_overrides(root)

    def test_branding_patches_active_spec_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spec = 'import sys\na = Analysis(["main.py"])\nexe = EXE(\n    console=False,\n)\n'
            for name in ('Lazy_AMPR.spec', 'Packizard_Builder.spec'):
                (root / name).write_text(spec, encoding='utf-8')
            (root / 'main.py').write_text(
                'from PySide6.QtCore import Qt\n'
                'def main():\n'
                '    app.setApplicationVersion(VERSION)\n'
                '    window = MainWindow()\n', encoding='utf-8',
            )
            (root / 'build_windows.ps1').write_text(
                '    & $python -m PyInstaller --noconfirm --clean --workpath $work --distpath $dist Packizard_Builder.spec\n',
                encoding='utf-8',
            )
            module = load('bootstrap_source_impl')
            module._patch_application_branding(ROOT, root)
            names = ('Packizard_Builder.spec', 'main.py', 'build_windows.ps1')
            before = {name: (root / name).read_bytes() for name in names}
            module._patch_application_branding(ROOT, root)
            self.assertEqual(before, {name: (root / name).read_bytes() for name in names})
            self.assertEqual((root / 'Lazy_AMPR.spec').read_text(), spec)
            self.assertIn('sys.platform == "win32" else None', (root / 'Packizard_Builder.spec').read_text())
            script = (root / 'build_windows.ps1').read_text()
            self.assertLess(script.index('prepare_windows_icon.py'), script.index('-m PyInstaller'))


if __name__ == '__main__':
    unittest.main()
