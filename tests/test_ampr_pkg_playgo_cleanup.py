import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / "ci"


def load_profile():
    spec = importlib.util.spec_from_file_location("ampr_pkg_profile_playgo", CI / "ampr_pkg_profile.py")
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AmprPkgPlayGoCleanupTests(unittest.TestCase):
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

    def test_ampr_profile_drops_stale_playgo_from_inner_image(self):
        module = load_profile()
        with tempfile.TemporaryDirectory() as td:
            root = self._prepared_root(td)
            module.apply(root)

            assembler = (root / module.ASSEMBLER_REL).read_text(encoding="utf-8")
            self.assertIn("IsPackizardStalePlayGoPath", assembler)
            self.assertIn(
                "preserveCntMetadataInInner && IsPackizardStalePlayGoPath(fullPath)",
                assembler,
            )
            self.assertIn('const string prefix = "/sce_sys/playgo";', assembler)

    def test_ampr_profile_sanitizes_packaged_param_without_touching_source(self):
        module = load_profile()
        with tempfile.TemporaryDirectory() as td:
            root = self._prepared_root(td)
            module.apply(root)

            builder = (root / module.PKG_BUILDER_REL).read_text(encoding="utf-8")
            self.assertIn(
                "NormalizeParamJson(File.ReadAllBytes(path), IsPackizardAmprTree(sourceFolder))",
                builder,
            )
            self.assertIn('ClearJsonString(updated, "versionFileUri")', builder)
            self.assertIn('ClearJsonInteger(updated, "attribute3")', builder)
            self.assertIn("This rewrite is in-memory; the source param.json is never modified.", builder)

    def test_non_ampr_normalization_keeps_launch_metadata_path_opt_in(self):
        module = load_profile()
        with tempfile.TemporaryDirectory() as td:
            root = self._prepared_root(td)
            module.apply(root)

            builder = (root / module.PKG_BUILDER_REL).read_text(encoding="utf-8")
            self.assertIn("if (packizardAmprProfile)", builder)
            self.assertIn("NormalizeParamJson(byte[] paramJson, bool packizardAmprProfile = false)", builder)


if __name__ == "__main__":
    unittest.main()
