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
        self.assertEqual(result["critical_differences"][0]["field"], "pfs_size")
        self.assertEqual(result["tolerated_differences"][0]["field"], "digest_0x30")

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

    def test_only_digest_differences_can_still_have_structural_parity(self):
        result = classify(
            {
                "reference": {},
                "candidate": {},
                "differences": [
                    {"field": "digest_0x70", "reference": "aa", "candidate": "bb"},
                    {"field": "entry_0x0020.sha256", "reference": "aa", "candidate": "bb"},
                ],
            }
        )
        self.assertTrue(result["parity"])
        self.assertFalse(result["critical_differences"])


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


if __name__ == "__main__":
    unittest.main()
