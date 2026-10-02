from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

FIH_MAGIC = b"\x7fFIH"
CNT_MAGIC = b"\x7fCNT"
FIH_HEADER_SIZE = 0x10000
CNT_HEADER_SIZE = 0x5A0
ENTRY_META_SIZE = 0x20

ENTRY_NAMES = 0x0200
IMAGE_KEY = 0x0020
GENERAL_DIGESTS = 0x0080
DIGESTS = 0x0001


class PkgImageValidationError(ValueError):
    """Raised when a package cannot be parsed as a finalized PS5 image."""


@dataclass(frozen=True)
class EntryReport:
    id: int
    name_offset: int
    flags1: int
    flags2: int
    data_offset: int
    data_size: int
    name: str = ""
    sha256: str = ""


@dataclass(frozen=True)
class ImageReport:
    path: str
    file_size: int
    package_type: str
    signed_byte: int
    format_version: int
    pfs_offset: int
    pfs_size: int
    embedded_cnt_offset: int
    data_region_block_count: int
    block_size_field: int
    field_0x68: int
    inner_image_block_count: int
    field_0x94: int
    field_0x98: int
    content_version_hi: int
    inner_image_size: int
    inner_image_logical_size: int
    outer_file_count: int
    flat_path_table_count: int
    digest_0x30: str
    digest_0x70: str
    digest_0xb0: str
    digest_0xd0: str
    cnt_flags: int
    cnt_entry_count: int
    cnt_sc_entry_count: int
    cnt_entry_table_offset: int
    cnt_body_offset: int
    cnt_body_size: int
    content_id: str
    drm_type: int
    content_type: int
    content_flags: int
    cnt_pfs_flags: int
    cnt_pfs_image_offset: int
    cnt_pfs_image_size: int
    entries: tuple[EntryReport, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["entries"] = [asdict(e) for e in self.entries]
        data["warnings"] = list(self.warnings)
        return data


def _u16le(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def _u32le(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def _u64le(data: bytes, off: int) -> int:
    return struct.unpack_from("<Q", data, off)[0]


def _u16be(data: bytes, off: int) -> int:
    return struct.unpack_from(">H", data, off)[0]


def _u32be(data: bytes, off: int) -> int:
    return struct.unpack_from(">I", data, off)[0]


def _u64be(data: bytes, off: int) -> int:
    return struct.unpack_from(">Q", data, off)[0]


def _ascii_nul(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("ascii", errors="replace")


def _read_at(fh, offset: int, size: int, file_size: int) -> bytes:
    if offset < 0 or size < 0 or offset + size > file_size:
        raise PkgImageValidationError(
            f"range outside package: offset=0x{offset:x} size=0x{size:x} file=0x{file_size:x}"
        )
    fh.seek(offset)
    data = fh.read(size)
    if len(data) != size:
        raise PkgImageValidationError("unexpected end of package")
    return data


def inspect_pkg_image(path: str | Path) -> ImageReport:
    pkg = Path(path)
    file_size = pkg.stat().st_size
    if file_size < FIH_HEADER_SIZE:
        raise PkgImageValidationError("package is too small to contain an FIH header")

    warnings: list[str] = []
    with pkg.open("rb") as fh:
        fih = _read_at(fh, 0, FIH_HEADER_SIZE, file_size)
        if fih[:4] != FIH_MAGIC:
            raise PkgImageValidationError("package is not a finalized PS5 FIH image")

        signed_byte = fih[0x05]
        package_type = "FullDebug" if signed_byte == 0 else ("FullRetail" if signed_byte == 0x80 else "UnknownFIH")
        format_version = _u16le(fih, 0x06)
        pfs_offset = _u64le(fih, 0x10)
        pfs_size = _u64le(fih, 0x18)
        embedded_cnt_offset = _u64le(fih, 0x58)
        data_region_block_count = _u64le(fih, 0x50)
        block_size_field = _u64le(fih, 0x60)
        field_0x68 = _u64le(fih, 0x68)
        inner_image_block_count = _u32le(fih, 0x90)
        field_0x94 = _u32le(fih, 0x94)
        field_0x98 = _u32le(fih, 0x98)
        content_version_hi = _u32le(fih, 0x9C)
        inner_image_size = _u64le(fih, 0xA0)
        inner_image_logical_size = _u64le(fih, 0xA8)
        outer_file_count = _u32le(fih, 0xF0)
        flat_path_table_count = _u32le(fih, 0xF8)

        if format_version != 3:
            warnings.append(f"FIH format version is {format_version}, expected 3")
        if pfs_offset != FIH_HEADER_SIZE:
            warnings.append(f"FIH PFS offset is 0x{pfs_offset:x}, expected 0x{FIH_HEADER_SIZE:x}")
        if not pfs_size or pfs_offset + pfs_size > file_size:
            warnings.append("FIH PFS range is empty or outside the package")
        expected_cnt = pfs_offset + pfs_size
        if embedded_cnt_offset != expected_cnt:
            warnings.append(
                f"embedded CNT is not contiguous with PFS: got 0x{embedded_cnt_offset:x}, expected 0x{expected_cnt:x}"
            )
        if data_region_block_count == 0:
            warnings.append("FIH 0x50 data-region block count is zero")
        if block_size_field not in (0, FIH_HEADER_SIZE):
            warnings.append(f"FIH 0x60 block-size field is 0x{block_size_field:x}, expected 0x10000")
        if inner_image_block_count and inner_image_size != inner_image_block_count * FIH_HEADER_SIZE:
            warnings.append("FIH 0xA0 does not equal 0x90 block count * 0x10000")
        if field_0x94 != field_0x98:
            warnings.append("FIH 0x94 and 0x98 mirrored values differ")

        cnt = _read_at(fh, embedded_cnt_offset, CNT_HEADER_SIZE, file_size)
        if cnt[:4] != CNT_MAGIC:
            raise PkgImageValidationError(f"embedded CNT magic missing at 0x{embedded_cnt_offset:x}")

        cnt_flags = _u32be(cnt, 0x04)
        cnt_entry_count = _u32be(cnt, 0x10)
        cnt_sc_entry_count = _u16be(cnt, 0x14)
        cnt_entry_table_offset = _u32be(cnt, 0x18)
        cnt_body_offset = _u64be(cnt, 0x20)
        cnt_body_size = _u64be(cnt, 0x28)
        content_id = _ascii_nul(cnt[0x40:0x70])
        drm_type = _u32be(cnt, 0x70)
        content_type = _u32be(cnt, 0x74)
        content_flags = _u32be(cnt, 0x78)
        cnt_pfs_flags = _u64be(cnt, 0x408)
        cnt_pfs_image_offset = _u64be(cnt, 0x410)
        cnt_pfs_image_size = _u64be(cnt, 0x418)

        if cnt_pfs_image_offset != pfs_offset:
            warnings.append(
                f"CNT pfs_image_offset 0x{cnt_pfs_image_offset:x} != FIH PFS offset 0x{pfs_offset:x}"
            )
        if cnt_pfs_image_size != pfs_size:
            warnings.append(
                f"CNT pfs_image_size 0x{cnt_pfs_image_size:x} != FIH PFS size 0x{pfs_size:x}"
            )

        table_start = embedded_cnt_offset + cnt_entry_table_offset
        max_entries = max(0, (file_size - table_start) // ENTRY_META_SIZE)
        if cnt_entry_count > min(max_entries, 0x10000):
            raise PkgImageValidationError("CNT entry table count is outside the package")

        raw_entries: list[EntryReport] = []
        names_entry: EntryReport | None = None
        for index in range(cnt_entry_count):
            rec = _read_at(fh, table_start + index * ENTRY_META_SIZE, ENTRY_META_SIZE, file_size)
            entry_id = _u32be(rec, 0)
            name_off = _u32be(rec, 0x04)
            flags1 = _u32be(rec, 0x08)
            flags2 = _u32be(rec, 0x0C)
            data_off = _u32be(rec, 0x10)
            data_size = _u32be(rec, 0x14)
            sha256 = ""
            absolute_data = embedded_cnt_offset + data_off
            if data_size and absolute_data + data_size <= file_size:
                blob = _read_at(fh, absolute_data, data_size, file_size)
                sha256 = hashlib.sha256(blob).hexdigest()
            item = EntryReport(entry_id, name_off, flags1, flags2, data_off, data_size, "", sha256)
            raw_entries.append(item)
            if entry_id == ENTRY_NAMES:
                names_entry = item

        names_blob = b""
        if names_entry and names_entry.data_size:
            names_blob = _read_at(
                fh,
                embedded_cnt_offset + names_entry.data_offset,
                names_entry.data_size,
                file_size,
            )

        entries: list[EntryReport] = []
        for item in raw_entries:
            name = ""
            if names_blob and 0 < item.name_offset < len(names_blob):
                name = _ascii_nul(names_blob[item.name_offset:])
            entries.append(
                EntryReport(
                    item.id,
                    item.name_offset,
                    item.flags1,
                    item.flags2,
                    item.data_offset,
                    item.data_size,
                    name,
                    item.sha256,
                )
            )

        ids = {entry.id for entry in entries}
        for required, label in (
            (IMAGE_KEY, "IMAGE_KEY (0x20)"),
            (GENERAL_DIGESTS, "GENERAL_DIGESTS (0x80)"),
            (DIGESTS, "DIGESTS (0x01)"),
        ):
            if required not in ids:
                warnings.append(f"embedded CNT is missing {label}")

        if inner_image_logical_size:
            warnings.append(
                "FIH 0xA8/0xB0 semantic check requires a known-good reference: "
                "the pinned engine documents these fields inconsistently "
                "(inner-PFS logical image vs NAPS preimage)"
            )

        return ImageReport(
            path=str(pkg.resolve()),
            file_size=file_size,
            package_type=package_type,
            signed_byte=signed_byte,
            format_version=format_version,
            pfs_offset=pfs_offset,
            pfs_size=pfs_size,
            embedded_cnt_offset=embedded_cnt_offset,
            data_region_block_count=data_region_block_count,
            block_size_field=block_size_field,
            field_0x68=field_0x68,
            inner_image_block_count=inner_image_block_count,
            field_0x94=field_0x94,
            field_0x98=field_0x98,
            content_version_hi=content_version_hi,
            inner_image_size=inner_image_size,
            inner_image_logical_size=inner_image_logical_size,
            outer_file_count=outer_file_count,
            flat_path_table_count=flat_path_table_count,
            digest_0x30=fih[0x30:0x50].hex(),
            digest_0x70=fih[0x70:0x90].hex(),
            digest_0xb0=fih[0xB0:0xD0].hex(),
            digest_0xd0=fih[0xD0:0xF0].hex(),
            cnt_flags=cnt_flags,
            cnt_entry_count=cnt_entry_count,
            cnt_sc_entry_count=cnt_sc_entry_count,
            cnt_entry_table_offset=cnt_entry_table_offset,
            cnt_body_offset=cnt_body_offset,
            cnt_body_size=cnt_body_size,
            content_id=content_id,
            drm_type=drm_type,
            content_type=content_type,
            content_flags=content_flags,
            cnt_pfs_flags=cnt_pfs_flags,
            cnt_pfs_image_offset=cnt_pfs_image_offset,
            cnt_pfs_image_size=cnt_pfs_image_size,
            entries=tuple(entries),
            warnings=tuple(warnings),
        )


def compare_pkg_images(reference: str | Path, candidate: str | Path) -> dict[str, Any]:
    ref = inspect_pkg_image(reference)
    cand = inspect_pkg_image(candidate)
    ignore = {"path", "warnings", "entries", "file_size"}
    ref_dict = ref.to_dict()
    cand_dict = cand.to_dict()
    differences: list[dict[str, Any]] = []

    for key in sorted(k for k in ref_dict if k not in ignore):
        if ref_dict[key] != cand_dict[key]:
            differences.append({"field": key, "reference": ref_dict[key], "candidate": cand_dict[key]})

    ref_entries = {entry.id: entry for entry in ref.entries}
    cand_entries = {entry.id: entry for entry in cand.entries}
    for entry_id in sorted(set(ref_entries) | set(cand_entries)):
        ref_entry = ref_entries.get(entry_id)
        cand_entry = cand_entries.get(entry_id)
        if ref_entry is None or cand_entry is None:
            differences.append(
                {
                    "field": f"entry_0x{entry_id:04x}",
                    "reference": bool(ref_entry),
                    "candidate": bool(cand_entry),
                }
            )
            continue
        for attr in ("flags1", "flags2", "data_size", "sha256"):
            ref_value = getattr(ref_entry, attr)
            cand_value = getattr(cand_entry, attr)
            if ref_value != cand_value:
                differences.append(
                    {
                        "field": f"entry_0x{entry_id:04x}.{attr}",
                        "reference": ref_value,
                        "candidate": cand_value,
                    }
                )

    return {
        "reference": ref.to_dict(),
        "candidate": cand.to_dict(),
        "differences": differences,
    }


def write_report(report: ImageReport | dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    payload = report.to_dict() if isinstance(report, ImageReport) else report
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target
