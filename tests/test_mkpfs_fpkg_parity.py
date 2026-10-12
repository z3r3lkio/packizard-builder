import unittest

from scripts.compare_mkpfs_fpkg import classify


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


if __name__ == "__main__":
    unittest.main()
