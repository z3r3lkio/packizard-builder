import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.pkg_engine import (
    ENGINE_REF,
    ENGINE_VERSION,
    ENV_BRIDGE_PATH,
    PPR_GUI_REFERENCE_VERSION,
    PkgBuildOptions,
    PkgEngineError,
    candidate_bridge_paths,
    find_pkg_bridge,
    probe_pkg_engine,
    run_pkg_build,
)


class PkgEngineTests(unittest.TestCase):
    def test_candidates_are_internal_bridge_only(self):
        with tempfile.TemporaryDirectory() as td:
            paths = candidate_bridge_paths(root=Path(td))
        joined = "\n".join(str(path).lower() for path in paths)
        self.assertIn("packizard.pkgbridge", joined)
        self.assertNotIn("libprosperopkg.gui", joined)
        self.assertNotIn("ppr-pkg", joined)

    def test_env_bridge_wins(self):
        with tempfile.TemporaryDirectory() as td:
            bridge = Path(td) / ("Packizard.PkgBridge.exe" if os.name == "nt" else "Packizard.PkgBridge")
            bridge.write_bytes(b"bridge")
            with mock.patch.dict(os.environ, {ENV_BRIDGE_PATH: str(bridge)}):
                self.assertEqual(find_pkg_bridge(root=Path(td) / "empty"), bridge.resolve())

    def test_defaults_follow_current_ppr_reference(self):
        options = PkgBuildOptions("source", "output")
        self.assertEqual(options.application_drm_type, "standard")
        self.assertFalse(options.license_free)
        self.assertTrue(options.verify_after_build)
        self.assertEqual(PPR_GUI_REFERENCE_VERSION, "0.6.8")

    def test_options_validate_passcode_and_ids(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "src"
            source.mkdir()
            good = PkgBuildOptions(
                source_folder=str(source),
                output_folder=str(Path(td) / "out"),
                content_id="UP9000-PPSA00000_00-PROSPERO00000000",
                title_id="PPSA00000",
            )
            good.validate()
            with self.assertRaises(PkgEngineError):
                PkgBuildOptions(str(source), str(Path(td) / "out"), passcode="bad").validate()
            future = PkgBuildOptions(str(Path(td) / "future-compressed"), str(Path(td) / "out"))
            future.validate(require_source=False)
            with self.assertRaises(PkgEngineError):
                future.validate()

    @unittest.skipIf(os.name == "nt", "fake POSIX bridge test")
    def test_probe_reports_integrated_engine(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bridge_dir = root / "pkg_bridge"
            bridge_dir.mkdir()
            bridge = bridge_dir / "Packizard.PkgBridge"
            payload = json.dumps({
                "engine": "LibProsperoPKG",
                "engineVersion": ENGINE_VERSION,
                "engineRef": ENGINE_REF,
                "keysAvailable": True,
                "pprGuiReferenceVersion": PPR_GUI_REFERENCE_VERSION,
            })
            bridge.write_text(f"#!/bin/sh\nprintf '%s\\n' '{payload}'\n", encoding="utf-8")
            bridge.chmod(bridge.stat().st_mode | stat.S_IXUSR)
            info = probe_pkg_engine(root=root)
            self.assertIsNotNone(info)
            self.assertEqual(info.engine_version, ENGINE_VERSION)
            self.assertTrue(info.keys_available)
            self.assertEqual(info.ppr_gui_reference_version, PPR_GUI_REFERENCE_VERSION)

    @unittest.skipIf(os.name == "nt", "fake POSIX bridge test")
    def test_build_consumes_json_events(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "src"
            output = root / "out"
            source.mkdir()
            bridge_dir = root / "pkg_bridge"
            bridge_dir.mkdir()
            bridge = bridge_dir / "Packizard.PkgBridge"
            script = r'''#!/usr/bin/env python3
import json, pathlib, sys
req = pathlib.Path(sys.argv[sys.argv.index('--request') + 1])
data = json.loads(req.read_text())
out = pathlib.Path(data['output_folder']) / 'result.pkg'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(b'PKG')
print(json.dumps({'type':'log','message':'building'}), flush=True)
print(json.dumps({'type':'warning','message':'test warning'}), flush=True)
print(json.dumps({'type':'result','outputPath':str(out),'warnings':['test warning']}), flush=True)
'''
            bridge.write_text(script, encoding="utf-8")
            bridge.chmod(bridge.stat().st_mode | stat.S_IXUSR)
            logs = []
            result, warnings = run_pkg_build(
                PkgBuildOptions(str(source), str(output)),
                root=root,
                log_callback=logs.append,
            )
            self.assertTrue(result.is_file())
            self.assertIn("building", logs)
            self.assertEqual(warnings, ["test warning"])


if __name__ == "__main__":
    unittest.main()
