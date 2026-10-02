import struct
import tempfile
import unittest
from pathlib import Path

from core.pkg_image_validation import (
    CNT_HEADER_SIZE,
    FIH_HEADER_SIZE,
    PkgImageValidationError,
    compare_pkg_images,
    inspect_pkg_image,
)


def _build_fixture(path: Path, *, logical_size: int = 0x2345, digest_byte: int = 0xB0) -> None:
    pfs_size = 0x20000
    cnt_offset = FIH_HEADER_SIZE + pfs_size
    total_size = cnt_offset + 0x4000
    blob = bytearray(total_size)

    blob[0:4] = b"\x7fFIH"
    blob[5] = 0
    struct.pack_into("<H", blob, 0x06, 3)
    struct.pack_into("<Q", blob, 0x10, FIH_HEADER_SIZE)
    struct.pack_into("<Q", blob, 0x18, pfs_size)
    struct.pack_into("<Q", blob, 0x50, 1)
    struct.pack_into("<Q", blob, 0x58, cnt_offset)
    struct.pack_into("<Q", blob, 0x60, FIH_HEADER_SIZE)
    struct.pack_into("<Q", blob, 0x68, 0x800000000000)
    struct.pack_into("<I", blob, 0x90, 1)
    struct.pack_into("<I", blob, 0x94, 2)
    struct.pack_into("<I", blob, 0x98, 2)
    struct.pack_into("<Q", blob, 0xA0, FIH_HEADER_SIZE)
    struct.pack_into("<Q", blob, 0xA8, logical_size)
    blob[0xB0:0xD0] = bytes([digest_byte]) * 32

    base = cnt_offset
    blob[base:base + 4] = b"\x7fCNT"
    struct.pack_into(">I", blob, base + 0x04, 0x00020001)
    struct.pack_into(">I", blob, base + 0x10, 4)
    struct.pack_into(">H", blob, base + 0x14, 0)
    struct.pack_into(">I", blob, base + 0x18, CNT_HEADER_SIZE)
    struct.pack_into(">Q", blob, base + 0x20, 0x1000)
    struct.pack_into(">Q", blob, base + 0x28, 0x2000)
    cid = b"UP9000-PPSA00000_00-PROSPERO00000000"
    blob[base + 0x40:base + 0x40 + len(cid)] = cid
    struct.pack_into(">I", blob, base + 0x70, 0)
    struct.pack_into(">I", blob, base + 0x74, 0x20)
    struct.pack_into(">I", blob, base + 0x78, 1)
    struct.pack_into(">Q", blob, base + 0x408, 0xA00000000000030C)
    struct.pack_into(">Q", blob, base + 0x410, FIH_HEADER_SIZE)
    struct.pack_into(">Q", blob, base + 0x418, pfs_size)

    entry_table = base + CNT_HEADER_SIZE
    entry_data = base + 0x1000
    entries = [0x0001, 0x0020, 0x0080, 0x0200]
    for i, entry_id in enumerate(entries):
        off = entry_table + i * 0x20
        struct.pack_into(">I", blob, off + 0x00, entry_id)
        struct.pack_into(">I", blob, off + 0x04, 0)
        struct.pack_into(">I", blob, off + 0x08, 0)
        struct.pack_into(">I", blob, off + 0x0C, 0)
        struct.pack_into(">I", blob, off + 0x10, 0x1000 + i * 0x40)
        struct.pack_into(">I", blob, off + 0x14, 0x20)
        data = bytes([entry_id & 0xFF]) * 0x20
        start = entry_data + i * 0x40
        blob[start:start + len(data)] = data

    path.write_bytes(blob)


class PkgImageValidationTests(unittest.TestCase):
    def test_inspects_fih_and_embedded_cnt(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "fixture.pkg"
            _build_fixture(path)
            report = inspect_pkg_image(path)
            self.assertEqual(report.package_type, "FullDebug")
            self.assertEqual(report.format_version, 3)
            self.assertEqual(report.pfs_offset, FIH_HEADER_SIZE)
            self.assertEqual(report.cnt_pfs_image_offset, FIH_HEADER_SIZE)
            self.assertEqual(report.content_type, 0x20)
            self.assertEqual({entry.id for entry in report.entries}, {0x1, 0x20, 0x80, 0x200})
            self.assertTrue(any("0xA8/0xB0" in warning for warning in report.warnings))

    def test_compare_is_field_and_entry_aware(self):
        with tempfile.TemporaryDirectory() as td:
            reference = Path(td) / "reference.pkg"
            candidate = Path(td) / "candidate.pkg"
            _build_fixture(reference, logical_size=0x2345, digest_byte=0xAA)
            _build_fixture(candidate, logical_size=0x3456, digest_byte=0xBB)
            diff = compare_pkg_images(reference, candidate)
            fields = {item["field"] for item in diff["differences"]}
            self.assertIn("inner_image_logical_size", fields)
            self.assertIn("digest_0xb0", fields)

    def test_rejects_non_fih_input(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.pkg"
            path.write_bytes(b"X" * FIH_HEADER_SIZE)
            with self.assertRaises(PkgImageValidationError):
                inspect_pkg_image(path)


if __name__ == "__main__":
    unittest.main()
