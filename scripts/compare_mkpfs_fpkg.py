#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.pkg_image_validation import compare_pkg_images

CRITICAL_FIELDS = {
    "format_version",
    "pfs_offset",
    "pfs_size",
    "embedded_cnt_offset",
    "data_region_block_count",
    "block_size_field",
    "inner_image_block_count",
    "field_0x94",
    "field_0x98",
    "content_version_hi",
    "inner_image_size",
    "inner_image_logical_size",
    "outer_file_count",
    "flat_path_table_count",
    "cnt_flags",
    "cnt_entry_count",
    "cnt_sc_entry_count",
    "cnt_entry_table_offset",
    "cnt_body_offset",
    "cnt_body_size",
    "content_id",
    "drm_type",
    "content_type",
    "content_flags",
    "cnt_pfs_flags",
    "cnt_pfs_image_offset",
    "cnt_pfs_image_size",
    # EICV-sensitive finalized-image digest slots. 0x30/0x70/0xD0 are the
    # outer-superblock digest triplet; 0xB0 authenticates the nested image map.
    "digest_0x30",
    "digest_0x70",
    "digest_0xb0",
    "digest_0xd0",
    "pfs_sha256",
}

# Entry existence, flags and size are structural. SHA-256 differences can be
# expected when randomized RSA ciphertext or compressed stream bytes differ.
CRITICAL_ENTRY_SUFFIXES = (".flags1", ".flags2", ".data_size")


def classify(report: dict) -> dict:
    critical = []
    tolerated = []
    for diff in report["differences"]:
        field = str(diff["field"])
        is_critical = (
            field in CRITICAL_FIELDS
            or field.startswith("entry_") and "." not in field
            or field.startswith("entry_") and field.endswith(CRITICAL_ENTRY_SUFFIXES)
        )
        (critical if is_critical else tolerated).append(diff)
    return {
        "reference": report["reference"],
        "candidate": report["candidate"],
        "critical_differences": critical,
        "tolerated_differences": tolerated,
        "parity": not critical,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare a Packizard FPKG with an MkPFS.CSharp/PS5PkgTool-parity reference."
    )
    parser.add_argument("reference", help="MkPFS.CSharp reference .pkg")
    parser.add_argument("candidate", help="Packizard-generated .pkg")
    parser.add_argument("--output", help="Write JSON report")
    args = parser.parse_args()

    result = classify(compare_pkg_images(args.reference, args.candidate))
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if result["parity"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
