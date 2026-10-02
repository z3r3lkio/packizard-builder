import tempfile
import unittest
from pathlib import Path

from scripts.libprospero_fih_profile import apply_fih_reference_profile


FIH_ORIGINAL_SNIPPET = """class F {
    void A() {
                bool nwonly = nwonlyInnerContentInodes > 0;
                uint innerBlocks = (uint)(sbBlockIndex - 1);
                uint metaOrInodes = nwonly ? (uint)nwonlyInnerContentInodes : (uint)(totalBlocks - innerBlocks);
                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihInnerImageBlockCountField), innerBlocks);
                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountField), metaOrInodes);
                BinaryPrimitives.WriteUInt32LittleEndian(h.AsSpan(ProsperoPkgLayout.FihMetaBlockCountMirrorField), metaOrInodes);
    }
    void B(
        uint nwonlyContentVersionHi = 0, int nwonlyInnerContentInodes = 0, int nwonlyAppFileCount = 0,
        Func<string, byte[]>? siArchivePathFactory = null)
    {
                nwonlyContentVersionHi, nwonlyInnerContentInodes, nwonlyAppFileCount,
                siArchivePathFactory);
            nwonlyContentVersionHi: nwonlyContentVersionHi,
            nwonlyInnerContentInodes: nwonlyInnerContentInodes,
            nwonlyAppFileCount: nwonlyAppFileCount);
    }
    void C(
        long nestedImageSize, long nestedMetaBaseBlocks, uint nwonlyContentVersionHi,
        int nwonlyInnerContentInodes, int nwonlyAppFileCount,
        Func<string, byte[]>? siArchivePathFactory)
    {
            nwonlyContentVersionHi: nwonlyContentVersionHi,
            nwonlyInnerContentInodes: nwonlyInnerContentInodes,
            nwonlyAppFileCount: nwonlyAppFileCount,
            sblockOffsetOverride: sbOffset,
    }
}
"""

PKG_ORIGINAL_SNIPPET = """class P {
    // The PS5 Flags1 word for each entry id.
    private static uint Flags1For(uint id) => id switch
    {
        (uint)ProsperoCntEntryId.DIGESTS => 0x40000000,
        (uint)ProsperoCntEntryId.ENTRY_KEYS => 0x60000000,
        (uint)ProsperoCntEntryId.IMAGE_KEY => 0x60000000,        // image key is not entry-encrypted.
        (uint)ProsperoCntEntryId.GENERAL_DIGESTS => 0x60000000,
        (uint)ProsperoCntEntryId.METAS => 0x60000000,
        (uint)ProsperoCntEntryId.ENTRY_NAMES => 0x40000000,
        0x2000 => 0x00000000,                          // param.json
        _ => 0x08000000,                               // media / data entries
    };

    // No CNT entries in this package class are entry-encrypted, so Flags2 is always zero.
    private static uint Flags2For(uint id) => 0u;
}
"""

PACKAGE_ORIGINAL_SNIPPET = """class H {
    void F() {
            nwonlyContentVersionHi: nwonlyFih?.ContentVersionHi ?? 0,
            nwonlyInnerContentInodes: nwonlyFih?.InnerContentInodes ?? 0,
            nwonlyAppFileCount: nwonlyFih?.AppFileCount ?? 0,
            siArchivePathFactory: siPathFactory);
    }
}
"""

OUTER_ORIGINAL_SNIPPET = """class O {
    void BuildForPackage() {
        var (tweak, data) = ProsperoPfsKeys.DeriveImageEncryptionKeys(ekpfs, seed);
        Encrypt(build, tweak, data);

        return new ProsperoOuterPackageImage
        {
            Ciphertext = build.Plaintext,
        };
    }
    void BuildForPackageToFile() {
                xts.CryptSector(block, sector, encrypt: true);
                fs.Position = checked((long)i * BlockSize);
                fs.Write(block, 0, block.Length);
    }
}
"""

INNER_ASSEMBLER_ORIGINAL_SNIPPET = """class A {
    void B() {
        var afidOrder = new List<FileNode>();
        Dir? sceSys = uroot.SubDirs.FirstOrDefault(d => d.Name == SceSysDir);
        if (sceSys != null) CollectFilesPreOrder(sceSys, afidOrder);
        foreach (var d in dirsPreOrder)
    }
}
"""

INNER_READER_ORIGINAL_SNIPPET = """class R {
    void B() {
        long metaBase = boundaries.LastOrDefault(v => v < mountSize);

        var mount = new byte[mountSize];

            long fileEnd = NextBoundary(boundaries, uncompOff, mountSize);
            long uncompLen = Math.Min(Ublock256K, fileEnd - uncompOff);
            if (uncompLen <= 0 || i + 1 >= cb.Count)
                break;

            int evenComp = (int)(e.ClenEvenMinus1 / 2 + 1);

            DecodeBlockInto(innerArr, onDisk, totalComp, evenComp, (int)uncompLen, kraken,
                            mount, (int)uncompOff);

            uncompOff += uncompLen;
            onDisk += kraken ? totalComp : uncompLen;
    }
}
"""


class LibProsperoFihProfileTests(unittest.TestCase):
    def _vendor(
        self,
        root: Path,
        fih: str = FIH_ORIGINAL_SNIPPET,
        pkg: str = PKG_ORIGINAL_SNIPPET,
        outer: str = OUTER_ORIGINAL_SNIPPET,
    ) -> Path:
        vendor = root / "LibProsperoPKG"
        pkg_base = vendor / "src" / "LibProsperoPkg" / "PKG"
        pfs_base = vendor / "src" / "LibProsperoPkg" / "PFS"
        pkg_base.mkdir(parents=True)
        pfs_base.mkdir(parents=True)
        (pkg_base / "ProsperoFihBuilder.cs").write_text(fih, encoding="utf-8")
        (pkg_base / "ProsperoPkgBuilder.cs").write_text(pkg, encoding="utf-8")
        (vendor / "src" / "LibProsperoPkg" / "ProsperoPackageBuilder.cs").write_text(
            PACKAGE_ORIGINAL_SNIPPET, encoding="utf-8"
        )
        (pfs_base / "ProsperoOuterPfsBuilder.cs").write_text(outer, encoding="utf-8")
        (pfs_base / "ProsperoPs5InnerImageAssembler.cs").write_text(
            INNER_ASSEMBLER_ORIGINAL_SNIPPET, encoding="utf-8"
        )
        (pfs_base / "ProsperoPs5InnerImageReader.cs").write_text(
            INNER_READER_ORIGINAL_SNIPPET, encoding="utf-8"
        )
        return vendor

    def test_applies_reference_profile_to_small_large_and_decode_paths(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td))
            self.assertTrue(apply_fih_reference_profile(vendor))

            pkg_base = vendor / "src" / "LibProsperoPkg" / "PKG"
            pfs_base = vendor / "src" / "LibProsperoPkg" / "PFS"
            fih = (pkg_base / "ProsperoFihBuilder.cs").read_text(encoding="utf-8")
            pkg = (pkg_base / "ProsperoPkgBuilder.cs").read_text(encoding="utf-8")
            package = (vendor / "src/LibProsperoPkg/ProsperoPackageBuilder.cs").read_text(encoding="utf-8")
            outer = (pfs_base / "ProsperoOuterPfsBuilder.cs").read_text(encoding="utf-8")
            assembler = (pfs_base / "ProsperoPs5InnerImageAssembler.cs").read_text(encoding="utf-8")
            reader = (pfs_base / "ProsperoPs5InnerImageReader.cs").read_text(encoding="utf-8")

            self.assertIn("rootInclusiveInodes", fih)
            self.assertIn("nestedImageSize + blockSize - 1", fih)
            self.assertIn("sbBlockIndex - napsBlocks", fih)
            self.assertIn("nwonlyNdblock: nwonlyNdblock", fih)
            self.assertIn("nwonlyNdblock: nwonlyFih?.Ndblock ?? 0", package)

            self.assertIn("ProsperoCntEntryId.LICENSE_DAT => 0x80000000", pkg)
            self.assertIn("ProsperoCntEntryId.LICENSE_INFO => 0x00004000", pkg)

            self.assertNotIn("Encrypt(build, tweak, data);", outer)
            self.assertNotIn("xts.CryptSector(block, sector, encrypt: true);", outer)
            self.assertIn("FullDebug references store", outer)

            self.assertIn("FileNode? keystone", assembler)
            self.assertIn("afidOrder.Add(keystone)", assembler)
            self.assertIn("long dataEnd = boundaries.LastOrDefault", reader)
            self.assertIn("bool logicalHole", reader)
            self.assertIn("if (!logicalHole)", reader)

    def test_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td))
            self.assertTrue(apply_fih_reference_profile(vendor))
            self.assertFalse(apply_fih_reference_profile(vendor))

    def test_refuses_unknown_fih_preimage(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td), fih="// changed upstream\n")
            with self.assertRaises(RuntimeError):
                apply_fih_reference_profile(vendor)

    def test_refuses_unknown_pkg_preimage(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td), pkg="// changed upstream\n")
            with self.assertRaises(RuntimeError):
                apply_fih_reference_profile(vendor)

    def test_refuses_unknown_outer_pfs_preimage(self):
        with tempfile.TemporaryDirectory() as td:
            vendor = self._vendor(Path(td), outer="// changed upstream\n")
            with self.assertRaises(RuntimeError):
                apply_fih_reference_profile(vendor)


if __name__ == "__main__":
    unittest.main()
