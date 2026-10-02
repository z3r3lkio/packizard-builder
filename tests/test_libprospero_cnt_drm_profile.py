import tempfile
import unittest
from pathlib import Path

from scripts.libprospero_cnt_drm_profile import apply_cnt_drm_profile


SOURCE = """using System;
class P {
    private static uint Flags1For(uint id) => id switch
    {
        (uint)ProsperoCntEntryId.LICENSE_DAT => 0x80000000,
        (uint)ProsperoCntEntryId.LICENSE_INFO => 0x80000000,
        (uint)ProsperoCntEntryId.NPTITLE_DAT => 0x80000000,
        (uint)ProsperoCntEntryId.NPBIND_DAT => 0x80000000,
        0x2020 => 0x80000000,
        0x2021 => 0x80000000,
    };
    private static uint Flags2For(uint id) => id switch
    {
        (uint)ProsperoCntEntryId.LICENSE_DAT => 0x00003000,
        (uint)ProsperoCntEntryId.LICENSE_INFO => 0x00004000,
        (uint)ProsperoCntEntryId.NPTITLE_DAT => 0x00003000,
        (uint)ProsperoCntEntryId.NPBIND_DAT => 0x00003000,
        0x2020 => 0x00003000,
        0x2021 => 0x00003000,
    };

    object Build(ProsperoPkgBuildProperties props, string sourceFolder)
    {
        uint contentType = ContentTypeFor(props.VolumeType);
        var pkg = new ProsperoCnt
        {
            Header = new ProsperoCntHeader
            {
                drm_type = DrmTypeNone,
                content_type = contentType,
                content_flags = ContentFlagsFor(props.VolumeType),
            }
        };
        byte[] paramJson = [];
        LayOutEntries(pkg, paramJson);
        return pkg;
    }

    private static void LayOutEntries(ProsperoCnt pkg, byte[] paramJson)
    {
        var meta = new ProsperoCntMetaEntry
        {
                Flags1 = Flags1For((uint)entry.Id),
                Flags2 = Flags2For((uint)entry.Id),
        };
    }
}
"""


class CntDrmProfileTests(unittest.TestCase):
    def _vendor(self, root: Path, source: str = SOURCE) -> Path:
        vendor = root / "LibProsperoPKG"
        pkg = vendor / "src" / "LibProsperoPkg" / "PKG"
        pkg.mkdir(parents=True)
        (pkg / "ProsperoPkgBuilder.cs").write_text(source, encoding="utf-8")
        return vendor

    def test_standard_drm_matches_same_title_reference_profile(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td))
            self.assertTrue(apply_cnt_drm_profile(vendor))
            text = (vendor / "src/LibProsperoPkg/PKG/ProsperoPkgBuilder.cs").read_text(encoding="utf-8")
            self.assertIn('applicationDrmType, "standard"', text)
            self.assertIn("drm_type = standardDrm ? 0x10u : DrmTypeNone", text)
            self.assertIn("ProsperoCntContentFlags.Unk_x8000000", text)
            self.assertIn("LICENSE_DAT => standardDrm ? 0u : 0x80000000", text)
            self.assertIn("LICENSE_INFO => standardDrm ? 0u : 0x00004000", text)
            self.assertIn("Flags1For((uint)entry.Id, standardDrm)", text)

    def test_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td))
            self.assertTrue(apply_cnt_drm_profile(vendor))
            self.assertFalse(apply_cnt_drm_profile(vendor))

    def test_refuses_unknown_preimage(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td), "// changed upstream\n")
            with self.assertRaises(RuntimeError):
                apply_cnt_drm_profile(vendor)


if __name__ == "__main__":
    unittest.main()
