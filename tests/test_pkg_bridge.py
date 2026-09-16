import ctypes
import tempfile
import unittest
from pathlib import Path

from core.prospero_pkg import (
    LIBPROSPERO_ABI,
    PkgBuildOptions,
    ProsperoError,
    _LppBuildOptions,
    platform_key,
    validate_build_options,
)


class PkgBridgeTests(unittest.TestCase):
    def _valid(self, root: Path) -> PkgBuildOptions:
        source = root / "game"
        (source / "sce_sys").mkdir(parents=True)
        return PkgBuildOptions(
            source_folder=source,
            output_folder=root / "out",
            content_id="UP9000-PPSA12345_00-PACKIZARD0000000",
            title_id="PPSA12345",
            title="Packizard test",
            version="01.00",
        )

    def test_abi_struct_shape_matches_native_header(self):
        self.assertEqual(LIBPROSPERO_ABI, 7)
        names = [name for name, _ in _LppBuildOptions._fields_]
        self.assertEqual(names[-1], "license_free")
        self.assertGreater(ctypes.sizeof(_LppBuildOptions), 0)

    def test_valid_metadata_is_accepted_without_native_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            validate_build_options(self._valid(Path(tmp)))

    def test_invalid_title_and_content_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            opts = self._valid(Path(tmp))
            opts.title_id = "CUSA00001"
            with self.assertRaisesRegex(ProsperoError, "Title ID"):
                validate_build_options(opts)
            opts.title_id = "PPSA12345"
            opts.content_id = "bad"
            with self.assertRaisesRegex(ProsperoError, "Content ID"):
                validate_build_options(opts)

    def test_backup_conversion_allows_metadata_from_param_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "backup"
            source.mkdir()
            opts = PkgBuildOptions(source, root / "out", "", "", "", version="", backup_mode=True)
            validate_build_options(opts)

    def test_platform_key_is_supported(self):
        self.assertIn(platform_key(), {
            "win-x64", "win-arm64", "linux-x64", "linux-arm64", "osx-x64", "osx-arm64",
        })


if __name__ == "__main__":
    unittest.main()
