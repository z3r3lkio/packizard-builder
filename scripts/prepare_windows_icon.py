#!/usr/bin/env python3
"""Generate the Windows ICO used by the Packizard Builder executable."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        default="resources/branding/packizard_icon.png",
        help="Square Packizard PNG source",
    )
    parser.add_argument(
        "--output",
        default="resources/branding/packizard_icon.ico",
        help="ICO output path",
    )
    args = parser.parse_args()

    source = Path(args.source)
    output = Path(args.output)
    if not source.is_file():
        raise SystemExit(f"Missing Packizard icon source: {source}")

    with Image.open(source) as image:
        image.load()
        if image.width != image.height or image.width < 256:
            raise SystemExit(
                f"Packizard icon source must be square and at least 256x256; got {image.width}x{image.height}"
            )
        rgba = image.convert("RGBA")
        output.parent.mkdir(parents=True, exist_ok=True)
        rgba.save(output, format="ICO", sizes=SIZES, bitmap_format="png")

    with Image.open(output) as icon:
        icon.load()
        if icon.format != "ICO":
            raise SystemExit(f"Generated file is not an ICO: {output}")

    print(f"Generated Packizard Windows icon: {output} ({', '.join(f'{w}x{h}' for w, h in SIZES)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
