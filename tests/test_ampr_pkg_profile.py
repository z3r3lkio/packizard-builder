import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / "ci"


def load_profile():
    spec = importlib.util.spec_from_file_location("ampr_pkg_profile", CI / "ampr_pkg_profile.py")
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AmprPkgProfileTests(unittest.TestCase):
    def _prepared_root(self, temp: str) -> Path:
        root = Path(temp)
        pfs = root / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg" / "PFS"
        pkg = root / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg" / "PKG"
        pfs.mkdir(parents=True)
        pkg.mkdir(parents=True)
        shutil.copy2(
            CI / "large_pkg_overrides" / "ProsperoPs5InnerImageAssembler.cs",
            pfs / "ProsperoPs5InnerImageAssembler.cs",
        )
        shutil.copy2(
            CI / "large_pkg_overrides" / "ProsperoPkgBuilder.cs",
            pkg / "ProsperoPkgBuilder.cs",
        )
        return root

    def test_profile_preserves_sce_sys_and_stores_ampr_root_raw(self):
        module = load_profile()
        with tempfile.TemporaryDirectory() as td:
            root = self._prepared_root(td)
            module.apply(root)

            assembler = (root / module.ASSEMBLER_REL).read_text(encoding="utf-8")
            builder = (root / module.PKG_BUILDER_REL).read_text(encoding="utf-8")

            self.assertIn("bool preserveCntMetadataInInner = false", assembler)
            self.assertIn("bool storeAmprCompatibilityPathsRaw = false", assembler)
            self.assertIn("!preserveCntMetadataInInner && IsExcludedFromInner(fullPath)", assembler)
            self.assertIn("IsAmprCompatibilityStoredPath(fullPath)", assembler)
            self.assertIn("ProsperoInnerFilePolicy.StoreVerbatim", assembler)
            self.assertIn('fullPath.StartsWith("/sce_sys/", StringComparison.Ordinal)', assembler)
            self.assertIn('fullPath.StartsWith("/sce_module/", StringComparison.Ordinal)', assembler)
            self.assertIn('name.StartsWith("ampr_assets-", StringComparison.Ordinal)', assembler)
            self.assertIn('name.EndsWith(".pak", StringComparison.Ordinal)', assembler)

            self.assertIn("bool packizardAmprProfile = IsPackizardAmprTree(sourceFolder);", builder)
            self.assertIn("Packizard AMPR/LZ4 compatibility profile enabled", builder)
            self.assertIn("preserveCntMetadataInInner: packizardAmprProfile", builder)
            self.assertIn("storeAmprCompatibilityPathsRaw: packizardAmprProfile", builder)
            self.assertIn('Directory.EnumerateFiles(sourceFolder, "ampr_assets-*.pak", SearchOption.TopDirectoryOnly)', builder)

    def test_profile_is_idempotent(self):
        module = load_profile()
        with tempfile.TemporaryDirectory() as td:
            root = self._prepared_root(td)
            module.apply(root)
            assembler_path = root / module.ASSEMBLER_REL
            builder_path = root / module.PKG_BUILDER_REL
            first = (assembler_path.read_bytes(), builder_path.read_bytes())
            module.apply(root)
            second = (assembler_path.read_bytes(), builder_path.read_bytes())
            self.assertEqual(first, second)

    def test_bootstrap_applies_profile_after_large_package_overrides(self):
        source = (CI / "bootstrap_source.py").read_text(encoding="utf-8")
        copy_pos = source.index('print(f"Applied {len(targets)} LibProsperoPKG large-package streaming overrides")')
        profile_pos = source.index("ampr_profile.apply(root)")
        self.assertGreater(profile_pos, copy_pos)


if __name__ == "__main__":
    unittest.main()
