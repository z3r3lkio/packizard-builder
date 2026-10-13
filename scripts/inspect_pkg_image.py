#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.pkg_image_validation import compare_pkg_images, inspect_pkg_image, write_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect Packizard/PS5 FIH, embedded CNT and authentication metadata."
    )
    parser.add_argument("package", help="Packizard/debug FIH package to inspect")
    parser.add_argument("--reference", help="Known-good package to compare field-by-field")
    parser.add_argument("--output", help="Write the JSON report to this path")
    args = parser.parse_args()

    if args.reference:
        report = compare_pkg_images(args.reference, args.package)
    else:
        report = inspect_pkg_image(args.package).to_dict()

    if args.output:
        write_report(report, args.output)
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
