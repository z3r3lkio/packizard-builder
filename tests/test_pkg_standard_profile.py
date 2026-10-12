import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.libprospero_standard_package_profile import apply_standard_package_profile



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

    def test_standard_profile_preserves_data_first_naps_outer_pfs_pipeline(self):
        patcher = (ROOT / "scripts" / "libprospero_standard_package_profile.py").read_text(encoding="utf-8")
        # Regression guard from the MkPFS.CSharp/PS5PkgTool parity investigation:
        # Standard must not rewrite the nested image into conventional PFS+PFSC.
        self.assertNotIn("ProsperoPfsc.PackFile", patcher)
        self.assertNotIn("inner.pfs", patcher)
        self.assertIn("data-first inner image + naps_pkg_layout.dat", patcher)
        self.assertIn("SHA3 signed / AES-XTS encrypted outer PFS", patcher)

    def test_inner_assembler_is_owned_override_not_text_patched(self):
        patcher = (ROOT / "scripts" / "libprospero_standard_package_profile.py").read_text(encoding="utf-8")
        prepare = (ROOT / "scripts" / "prepare_pkg_bridge.py").read_text(encoding="utf-8")
        override = (ROOT / "bridge" / "overrides" / "ProsperoPs5InnerImageAssembler.cs").read_text(encoding="utf-8")

        self.assertNotIn("INNER_ASSEMBLER", patcher)
        self.assertNotIn("stored file payload selection", patcher)
        self.assertIn("ASSEMBLER_OVERRIDE", prepare)
        self.assertIn("shutil.copy2(ASSEMBLER_OVERRIDE, assembler_target)", prepare)
        self.assertLess(
            prepare.index("shutil.copy2(ASSEMBLER_OVERRIDE, assembler_target)"),
            prepare.index("apply_fih_reference_profile(VENDOR_DIR)"),
        )

        self.assertIn("bool compress = true", override)
        self.assertIn("private readonly bool _compress;", override)
        self.assertIn("if (!_compress", override)
        self.assertIn("storeRaw: !_compress", override)

        # Compatibility surface consumed by Packizard's native streaming/NAPS/SI path.
        self.assertIn("public string? ImageFilePath { get; init; }", override)
        self.assertIn("public long ImageLength { get; init; }", override)
        self.assertIn("IReadOnlyList<PackizardInnerDataBlock> DataBlocks", override)
        self.assertIn("bool preserveCntMetadataInInner = false", override)
        self.assertIn("PackizardNativeDataStream.Build", override)

        # Stored metadata must keep an explicit raw chunk map; an empty map would make
        # the NAPS generator attempt a fresh Kraken pack and break stored-mode parity.
        self.assertIn("RawMetadataBlocks(metaPlain)", override)
        self.assertIn("RawMetadataBlocks(byte[] metadata)", override)

    def test_standard_profile_is_complete_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            vendor = Path(temporary)
            low = vendor / "src" / "LibProsperoPkg" / "PKG" / "ProsperoPkgBuilder.cs"
            high = vendor / "src" / "LibProsperoPkg" / "ProsperoPackageBuilder.cs"
            low.parent.mkdir(parents=True)
            high.parent.mkdir(parents=True, exist_ok=True)

            low.write_text(
                """public sealed class ProsperoPkgBuildProperties
{
    public DateTime TimeStamp { get; init; } = DateTime.UnixEpoch;
}
byte[] outerSeed = System.Security.Cryptography.RandomNumberGenerator.GetBytes(16);
var asm = new LibProsperoPkg.PFS.ProsperoPs5InnerImageAssembler(fileTime, 0);
""",
                encoding="utf-8",
            )
            high.write_text(
                """public enum ProsperoOutputFormat
{
    DebugImage,
}

/// <summary>Options describing the PS5 package to build.</summary>
public sealed class ProsperoBuildOptions
{
    public ProsperoOutputFormat OutputFormat { get; set; } = ProsperoOutputFormat.DebugImage;
}
var props = new LibProsperoPkg.PKG.ProsperoPkgBuildProperties
{
            VolumeType = ProsperoVolumeTypeForMode(options.Mode),
        };
""",
                encoding="utf-8",
            )

            self.assertTrue(apply_standard_package_profile(vendor))
            self.assertFalse(apply_standard_package_profile(vendor))

            low_text = low.read_text(encoding="utf-8")
            high_text = high.read_text(encoding="utf-8")
            self.assertIn("public bool StoreInnerImage { get; init; }", low_text)
            self.assertIn("props.OuterSeed is { Length: 16 }", low_text)
            self.assertIn("compress: !props.StoreInnerImage", low_text)
            self.assertIn("public enum ProsperoPackageImageProfile", high_text)
            self.assertIn("public bool StoreInnerImage { get; set; }", high_text)
            self.assertIn("StoreInnerImage = options.StoreInnerImage", high_text)

    def test_sdk_oracle_defaults_to_standard_not_nwonly(self):
        # Regression statement for the console EICV class: our normal profile must stay Standard.
        # The explicit Nwonly value remains available only for controlled A/B diagnostics.
        program = (ROOT / "bridge" / "Packizard.PkgBridge" / "Program.cs").read_text(encoding="utf-8")
        self.assertIn("nameof(ProsperoPackageImageProfile.Standard)", program)
        self.assertIn('JsonPropertyName("image_profile")', program)


if __name__ == "__main__":
    unittest.main()
