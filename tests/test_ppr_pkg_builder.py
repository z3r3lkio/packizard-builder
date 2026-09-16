import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.ppr_pkg_builder import (
    ENV_TOOL_PATH,
    PprPkgBuilderError,
    build_launch_command,
    candidate_tool_paths,
    find_ppr_pkg_builder,
)


class PprPkgBuilderTests(unittest.TestCase):
    def test_configured_path_has_priority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            configured = root / "custom.exe"
            configured.write_bytes(b"test")
            bundled_dir = root / "tools" / "ppr_pkg_builder"
            bundled_dir.mkdir(parents=True)
            (bundled_dir / "LibProsperoPkg.Gui.exe").write_bytes(b"other")
            self.assertEqual(find_ppr_pkg_builder(configured, root=root), configured.resolve())

    def test_environment_path_is_considered(self):
        with tempfile.TemporaryDirectory() as td:
            tool = Path(td) / "PPR-PKG Builder.exe"
            tool.write_bytes(b"test")
            with mock.patch.dict(os.environ, {ENV_TOOL_PATH: str(tool)}, clear=False):
                self.assertEqual(find_ppr_pkg_builder(root=Path(td) / "empty"), tool.resolve())

    def test_known_local_names_are_scanned(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "tools" / "ppr_pkg_builder" / "LibProsperoPkg.Gui.exe"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"test")
            self.assertEqual(find_ppr_pkg_builder(root=root), target.resolve())

    def test_candidate_list_does_not_include_native_libprospero_engine(self):
        names = [p.name.lower() for p in candidate_tool_paths(root=Path("/tmp/example"))]
        self.assertNotIn("libprosperopkg.dll", names)
        self.assertNotIn("libprosperopkg.so", names)

    def test_missing_path_is_rejected(self):
        with self.assertRaises(PprPkgBuilderError):
            build_launch_command("/definitely/missing/PPR-PKG-Builder.exe")

    def test_dll_uses_dotnet(self):
        with tempfile.TemporaryDirectory() as td:
            tool = Path(td) / "LibProsperoPkg.Gui.dll"
            tool.write_bytes(b"test")
            with mock.patch("core.ppr_pkg_builder.shutil.which", return_value="/usr/bin/dotnet"):
                command = build_launch_command(tool)
            self.assertEqual(command[0], "/usr/bin/dotnet")
            self.assertEqual(Path(command[1]), tool.resolve())


if __name__ == "__main__":
    unittest.main()
