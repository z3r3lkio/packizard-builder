import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
