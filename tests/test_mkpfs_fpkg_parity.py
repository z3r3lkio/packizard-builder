import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from core.pkg_image_validation import inspect_pkg_image
from scripts.compare_mkpfs_fpkg import classify

ROOT = Path(__file__).resolve().parents[1]


class MkPfsParityComparatorTests(unittest.TestCase):
    def test_structural_field_difference_is_critical(self):
        result = classify(
            {
                "reference": {},
                "candidate": {},
                "differences": [
                    {"field": "pfs_size", "reference": 1, "candidate": 2},
                    {"field": "digest_0x30", "reference": "aa", "candidate": "bb"},
                ],
            }
        )
        self.assertFalse(result["parity"])
        self.assertEqual(
            [item["field"] for item in result["critical_differences"]],
            ["pfs_size", "digest_0x30"],
        )
        self.assertEqual(result["tolerated_differences"], [])

    def test_cnt_entry_flags_and_size_are_critical_but_hash_is_tolerated(self):
        result = classify(
            {
                "reference": {},
                "candidate": {},
                "differences": [
                    {"field": "entry_0x0020.flags1", "reference": 1, "candidate": 2},
                    {"field": "entry_0x0080.data_size", "reference": 32, "candidate": 64},
                    {"field": "entry_0x0001.sha256", "reference": "aa", "candidate": "bb"},
                ],
            }
        )
        self.assertFalse(result["parity"])
        self.assertEqual(
            [item["field"] for item in result["critical_differences"]],
            ["entry_0x0020.flags1", "entry_0x0080.data_size"],
        )
        self.assertEqual(
            [item["field"] for item in result["tolerated_differences"]],
            ["entry_0x0001.sha256"],
        )

    def test_only_entry_hash_differences_can_still_have_structural_parity(self):
        result = classify(
            {
                "reference": {},
                "candidate": {},
                "differences": [
                    {"field": "entry_0x0020.sha256", "reference": "aa", "candidate": "bb"},
                ],
            }
        )
        self.assertTrue(result["parity"])
        self.assertFalse(result["critical_differences"])
        self.assertEqual(
            [item["field"] for item in result["tolerated_differences"]],
            ["entry_0x0020.sha256"],
        )


    def test_deterministic_stored_fixture_naps_size_is_672(self):
        # Fixture topology after applying the public MkPFS stored-mode rules:
        # 6 file chunks with 3 physical RUN anchors, 15 whole gap chunks plus one
        # partial gap, 3 metadata chunks, and the terminator.
        data_std, data_runs = 6, 3
        gap_whole, gap_partial = 15, 1
        metadata_std, metadata_runs = 3, 1
        terminator_std, terminator_runs = 1, 1
        cblocks = (
            data_std + data_runs
            + (2 * gap_whole) + gap_partial
            + metadata_std + metadata_runs
            + terminator_std + terminator_runs
        )
        self.assertEqual(cblocks, 46)

        inner_blocks = 18
        file_offsets = 10
        u2c_groups = 3
        raw_size = (
            16
            + inner_blocks * 8
            + file_offsets * 6
            + u2c_groups * 10
            + cblocks * 9
        )
        self.assertEqual(raw_size, 664)
        self.assertEqual((raw_size + 15) // 16 * 16, 672)

    def test_stored_inner_override_tracks_mkpfs_geometry(self):
        source = (ROOT / "bridge" / "overrides" / "ProsperoPs5InnerImageAssembler.cs").read_text(encoding="utf-8")
        self.assertIn("const int Half = 0x20000;", source)
        self.assertIn("BuildStoredParityDataStream", source)
        self.assertIn("StoredParityMode = !_compress", source)
        self.assertIn("ProsperoCompressedPfsFileWriter.WriteStored", source)
        self.assertIn("storedFile.DataOffset", source)
        self.assertIn("dataEndLogical + UBlock - 1", source)
        self.assertIn("+ 15) * (UBlock / BlockSize)", source)

    def test_stored_naps_gap_uses_mkpfs_ublock_topology(self):
        source = (
            ROOT / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg" / "PKG"
            / "PackizardNativeNapsEngine.cs"
        ).read_text(encoding="utf-8")
        self.assertIn("if (result.StoredParityMode)", source)
        self.assertIn("long whole = gapLength / UBlock;", source)
        self.assertIn("StartRun = true", source)
        self.assertIn("padding/rest", source)

    def test_fih_profile_uses_files_plus_two_and_physical_inner_blocks(self):
        source = (ROOT / "scripts" / "libprospero_fih_profile.py").read_text(encoding="utf-8")
        self.assertIn("asmResult.Placements.Count + 2", source)
        self.assertIn("asmResult.ImageLength + BlockSize - 1", source)
        self.assertIn("nwonly && nwonlyNdblock > 0", source)


    def test_playgo_entries_match_mkpfs_fixture_sizes(self):
        # Deterministic parity fixture: six actual inner files.
        inner_files = 6
        hash_table_size = 0x38 + inner_files * 8
        ficm_size = 0x10 + (2 * inner_files)
        self.assertEqual(hash_table_size, 104)
        self.assertEqual(ficm_size, 28)

    def test_playgo_builder_uses_paths_not_derived_chunk_count(self):
        playgo = (
            ROOT / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg"
            / "PlayGo" / "ProsperoPlayGo.cs"
        ).read_text(encoding="utf-8")
        pkg = (
            ROOT / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg"
            / "PKG" / "ProsperoPkgBuilder.cs"
        ).read_text(encoding="utf-8")

        self.assertIn("BuildHashTable(IReadOnlyList<string> innerPaths)", playgo)
        self.assertIn("ProsperoPs5FlatPathTable.HashPath", playgo)
        self.assertIn("ProsperoPs5FlatPathTable.HeaderSeed.CopyTo", playgo)
        self.assertNotIn("BuildHashTable(uint chunkCount)", playgo)

        self.assertIn("playgoInnerPaths", pkg)
        self.assertIn("2 * playgoInnerPaths.Length", pkg)
        self.assertIn("BuildHashTable(playgoInnerPaths)", pkg)
        self.assertNotIn("BuildHashTable(playgoFileCount / 2)", pkg)

        assembler = (
            ROOT / "bridge" / "overrides" / "ProsperoPs5InnerImageAssembler.cs"
        ).read_text(encoding="utf-8")
        self.assertIn("FullPath = file.FullPath", assembler)


    def test_fih_authentication_digests_are_critical(self):
        report = {
            "reference": {},
            "candidate": {},
            "differences": [
                {"field": "digest_0x30", "reference": "aa", "candidate": "bb"},
                {"field": "digest_0x70", "reference": "aa", "candidate": "bb"},
                {"field": "digest_0xb0", "reference": "aa", "candidate": "bb"},
                {"field": "digest_0xd0", "reference": "aa", "candidate": "bb"},
            ],
        }
        classified = classify(report)
        self.assertFalse(classified["parity"])
        self.assertEqual(
            {d["field"] for d in classified["critical_differences"]},
            {"digest_0x30", "digest_0x70", "digest_0xb0", "digest_0xd0"},
        )
        self.assertEqual(classified["tolerated_differences"], [])


    def test_outer_pfs_ciphertext_is_parity_critical(self):
        report = {
            "reference": {},
            "candidate": {},
            "differences": [
                {"field": "pfs_sha256", "reference": "aa", "candidate": "bb"},
            ],
        }
        classified = classify(report)
        self.assertFalse(classified["parity"])
        self.assertEqual(
            [d["field"] for d in classified["critical_differences"]],
            ["pfs_sha256"],
        )


    def test_stored_auth_path_uses_byte_exact_naps_contract(self):
        source = (
            ROOT / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg"
            / "PKG" / "PackizardNativeNapsEngine.cs"
        ).read_text(encoding="utf-8")
        self.assertIn("return GenerateStoredParity(result)", source)
        self.assertIn("extra: 0x08", source)
        self.assertIn("terminatorUoff", source)
        self.assertIn("while ((output.Length & 7) != 0)", source)
        self.assertIn("stored mode: compression selector is zero", source)
        self.assertNotIn("GenerateStoredParity(result);\n        long mountSize", source)

    def test_stored_metadata_handles_large_inode_and_afid_layouts(self):
        source = (
            ROOT / "bridge" / "overrides" / "ProsperoPs5InnerImageAssembler.cs"
        ).read_text(encoding="utf-8")
        self.assertIn("const int MaxRecordsPerUBlock = 30;", source)
        self.assertIn("f.MovedForNaps = true;", source)
        self.assertIn("afids.Add(-1);", source)
        self.assertIn("(inodeCount + InodesPerBlock - 1) / InodesPerBlock", source)
        self.assertIn("nextBlock++;", source)
        self.assertIn("ClearStoredPfscSignatureSection(metadataHeader)", source)
        self.assertIn("FullPath = file.FullPath", source)
        self.assertIn("BuildStoredGapBytes(dataStream.LogicalLength, storedMetaBase)", source)

    def test_deterministic_fixture_matches_pinned_auth_digests(self):
        names = ("Packizard.PkgBridge.exe", "Packizard.PkgBridge") if os.name == "nt" else (
            "Packizard.PkgBridge", "Packizard.PkgBridge.exe"
        )
        bridge = None
        for directory in (
            ROOT / "pkg_bridge" / "linux-x64",
            ROOT / "pkg_bridge" / "win-x64",
            ROOT / "pkg_bridge",
        ):
            for name in names:
                candidate = directory / name
                if candidate.is_file() and (os.name == "nt" or os.access(candidate, os.X_OK)):
                    bridge = candidate
                    break
            if bridge is not None:
                break
        if bridge is None:
            self.skipTest("integrated PKG bridge is not prepared in this test environment")

        content_id = "UP9000-PPSA99097_00-PACKIZARDPARITY1"
        title_id = "PPSA99097"
        passcode = "0" * 32
        with tempfile.TemporaryDirectory(prefix="packizard-auth-fixture-") as td:
            root = Path(td)
            source = root / "source"
            output = root / "output"
            (source / "sce_sys" / "about").mkdir(parents=True)
            (source / "data").mkdir()
            output.mkdir()

            param = {
                "applicationCategoryType": 0,
                "applicationDrmType": "free",
                "contentId": content_id,
                "contentVersion": "01.00",
                "masterVersion": "01.00",
                "requiredSystemSoftwareVersion": "0x0000000000000000",
                "sdkVersion": "0x0000000000000000",
                "titleId": title_id,
                "defaultLanguage": "en-US",
                "localizedParameters": {"en-US": {"titleName": "Packizard MkPFS Parity"}},
            }
            (source / "sce_sys" / "param.json").write_text(
                json.dumps(param, separators=(",", ":"), ensure_ascii=True),
                encoding="utf-8",
            )
            (source / "sce_sys" / "keystone").write_bytes(b"K" * 0x60)
            (source / "sce_sys" / "pfs-version.dat").write_bytes(b"01.000.000")
            (source / "sce_sys" / "about" / "right.sprx").write_bytes(
                (b"PACKIZARD-RIGHT-SPRX\n" * 128)[:4096]
            )
            (source / "eboot.bin").write_bytes((b"PACKIZARD-PARITY-EBOOT\n" * 257)[:8192])
            (source / "data" / "alpha.dat").write_bytes(bytes(range(256)) * 300)
            (source / "data" / "zeros.bin").write_bytes(b"\0" * 131072)

            request = {
                "source_folder": str(source),
                "output_folder": str(output),
                "content_id": content_id,
                "title_id": title_id,
                "title": "Packizard MkPFS Parity",
                "version": "01.00",
                "passcode": passcode,
                "mode": "Application",
                "output_format": "DebugImage",
                "image_profile": "Standard",
                "application_type": "NotSpecified",
                "application_drm_type": "free",
                "generate_param_json_if_missing": False,
                "fake_sign_self_modules": False,
                "license_free": True,
                "verify_after_build": True,
                "outer_seed_hex": "00112233445566778899aabbccddeeff",
                "inner_compression": "stored",
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
            events = [
                json.loads(line)
                for line in built.stdout.splitlines()
                if line.lstrip().startswith("{")
            ]
            outputs = [
                event.get("outputPath")
                for event in events
                if event.get("type") == "result" and event.get("outputPath")
            ]
            self.assertTrue(outputs, built.stdout)
            report = inspect_pkg_image(outputs[-1])

            expected_sblock = "eb5cc9b42d9d1666b31c2b02b90767b24e3f0f75f002ca192bf62eefbb21dcac"
            self.assertEqual(report.digest_0x30, expected_sblock)
            self.assertEqual(report.digest_0x70, expected_sblock)
            self.assertEqual(report.digest_0xd0, expected_sblock)
            self.assertEqual(
                report.digest_0xb0,
                "96db59d376d82bebc33ae4e1d333ed87eca111d3da868344eccf40bab78fc23d",
            )
            self.assertEqual(
                report.pfs_sha256,
                "ce547514e2cd615db47379d298630f97933cee3a2b58a3ac90c09f0c5e1d3fde",
            )


if __name__ == "__main__":
    unittest.main()
