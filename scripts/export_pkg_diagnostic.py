#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.pkg_image_validation import CNT_HEADER_SIZE, ENTRY_META_SIZE, FIH_HEADER_SIZE, inspect_pkg_image

AUTH_ENTRY_NAMES = {
    0x0001: "digests",
    0x0020: "image-key",
    0x0080: "general-digests",
}
PFS_PREFIX_SIZE = 0x40000
MAX_AUTH_ENTRY_SIZE = 0x100000
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _read_range(path: Path, offset: int, size: int) -> bytes:
    file_size = path.stat().st_size
    if offset < 0 or size < 0 or offset + size > file_size:
        raise ValueError(
            f"range outside package: offset=0x{offset:x} size=0x{size:x} file=0x{file_size:x}"
        )
    with path.open("rb") as fh:
        fh.seek(offset)
        data = fh.read(size)
    if len(data) != size:
        raise ValueError("unexpected end of package while exporting diagnostics")
    return data


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_member(archive: zipfile.ZipFile, name: str, data: bytes) -> dict[str, object]:
    info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)
    return {"name": name, "size": len(data), "sha256": _sha256(data)}


def export_bundle(package: str | Path, output: str | Path) -> Path:
    pkg = Path(package).expanduser().resolve()
    target = Path(output).expanduser().resolve()
    report = inspect_pkg_image(pkg)
    report_data = report.to_dict()
    # Avoid leaking the user's absolute local path in a bundle intended for sharing.
    report_data["path"] = pkg.name

    members: list[tuple[str, bytes]] = []
    members.append(("report.json", (json.dumps(report_data, indent=2, sort_keys=True) + "\n").encode("utf-8")))
    members.append(("fih.bin", _read_range(pkg, 0, FIH_HEADER_SIZE)))

    pfs_prefix = min(report.pfs_size, PFS_PREFIX_SIZE)
    if pfs_prefix:
        members.append(("pfs-head.bin", _read_range(pkg, report.pfs_offset, pfs_prefix)))

    members.append(("cnt-header.bin", _read_range(pkg, report.embedded_cnt_offset, CNT_HEADER_SIZE)))

    table_size = report.cnt_entry_count * ENTRY_META_SIZE
    if table_size:
        table_offset = report.embedded_cnt_offset + report.cnt_entry_table_offset
        members.append(("cnt-entry-table.bin", _read_range(pkg, table_offset, table_size)))

    # The CNT prefix is useful for header-adjacent metadata while remaining bounded.
    cnt_prefix_size = min(max(report.cnt_body_offset, CNT_HEADER_SIZE), 0x10000)
    members.append(("cnt-prefix.bin", _read_range(pkg, report.embedded_cnt_offset, cnt_prefix_size)))

    omitted: list[dict[str, object]] = []
    for entry in report.entries:
        label = AUTH_ENTRY_NAMES.get(entry.id)
        if label is None or entry.data_size <= 0:
            continue
        if entry.data_size > MAX_AUTH_ENTRY_SIZE:
            omitted.append(
                {
                    "entry_id": f"0x{entry.id:04x}",
                    "reason": "entry exceeds diagnostic bundle size limit",
                    "size": entry.data_size,
                }
            )
            continue
        absolute = report.embedded_cnt_offset + entry.data_offset
        members.append((f"auth-{label}-0x{entry.id:04x}.bin", _read_range(pkg, absolute, entry.data_size)))

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    manifest_files: list[dict[str, object]] = []
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in members:
            manifest_files.append(_write_member(archive, name, data))
        manifest = {
            "format": "Packizard PKG diagnostic bundle v1",
            "source_name": pkg.name,
            "source_size": pkg.stat().st_size,
            "files": manifest_files,
            "omitted": omitted,
            "privacy": "Contains package/container metadata and selected authentication entries; game payload files are not exported.",
        }
        _write_member(
            archive,
            "manifest.json",
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )

    return target


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a small Packizard FIH/PFS/CNT diagnostic ZIP from a large PS5 PKG."
    )
    parser.add_argument("package", help="Known-good or Packizard-generated FIH PKG")
    parser.add_argument(
        "--output",
        help="Output ZIP path (default: <package>.packizard-diagnostic.zip)",
    )
    args = parser.parse_args()

    pkg = Path(args.package)
    output = Path(args.output) if args.output else pkg.with_name(pkg.stem + ".packizard-diagnostic.zip")
    result = export_bundle(pkg, output)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
