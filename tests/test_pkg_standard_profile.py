import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StandardPkgProfileTests(unittest.TestCase):
    def _bridge(self) -> Path | None:
        names = ("Packizard.PkgBridge.exe", "Packizard.PkgBridge") if os.name == "nt" else ("Packizard.PkgBridge", "Packizard.PkgBridge.exe")
        for directory in (
            ROOT / "pkg_bridge" / "linux-x64",
            ROOT / "pkg_bridge" / "win-x64",
            ROOT / "pkg_bridge",
        ):
            for name in names:
                path = directory / name
                if path.is_file() and (os.name == "nt" or os.access(path, os.X_OK)):
                    return path
        return None

    def test_standard_profile_builds_and_verifies_with_real_bridge(self):
        bridge = self._bridge()
        if bridge is None:
            self.skipTest("integrated PKG bridge is not prepared in this test environment")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            output = root / "output"
            (source / "sce_sys").mkdir(parents=True)
            output.mkdir()
            # The package engine can structurally package an arbitrary payload; no executable launch
            # semantics are needed for this format/integrity smoke test.
            (source / "payload.bin").write_bytes((b"PACKIZARD-STANDARD-PFS\n" * 4096))

            request = {
                "source_folder": str(source),
                "output_folder": str(output),
                "content_id": "UP9000-PPSA99098_00-PACKIZARDSTD0001",
                "title_id": "PPSA99098",
                "title": "Packizard Standard Profile Test",
                "version": "01.00",
                "passcode": "0" * 32,
                "mode": "Application",
                "output_format": "DebugImage",
                "image_profile": "Standard",
                "application_type": "NotSpecified",
                "application_drm_type": "free",
                "generate_param_json_if_missing": True,
                "fake_sign_self_modules": False,
                "license_free": True,
                "verify_after_build": True,
            }
            request_path = root / "request.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")

            built = subprocess.run(
                [str(bridge), "build", "--request", str(request_path)],
                cwd=bridge.parent,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                check=False,
            )
            self.assertEqual(built.returncode, 0, built.stdout + "\n" + built.stderr)
            events = [json.loads(line) for line in built.stdout.splitlines() if line.lstrip().startswith("{")]
            results = [event for event in events if event.get("type") == "result"]
            self.assertTrue(results, built.stdout)
            package = Path(results[-1]["outputPath"])
            self.assertTrue(package.is_file())

            verified = subprocess.run(
                [str(bridge), "verify", "--package", str(package), "--content-id", request["content_id"]],
                cwd=bridge.parent,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + "\n" + verified.stderr)
            self.assertIn('"accepted":true', verified.stdout.replace(" ", "").lower())

    def test_sdk_oracle_defaults_to_standard_not_nwonly(self):
        # Regression statement for the console EICV class: our normal profile must stay Standard.
        # The explicit Nwonly value remains available only for controlled A/B diagnostics.
        program = (ROOT / "bridge" / "Packizard.PkgBridge" / "Program.cs").read_text(encoding="utf-8")
        self.assertIn("nameof(ProsperoPackageImageProfile.Standard)", program)
        self.assertIn('JsonPropertyName("image_profile")', program)


if __name__ == "__main__":
    unittest.main()
