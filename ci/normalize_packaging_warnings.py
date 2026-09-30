#!/usr/bin/env python3
"""Normalize deterministic Linux packaging warnings in reconstructed sources."""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one {label}; found {count}")
    return text.replace(old, new, 1)


def patch_linux_script(root: Path) -> None:
    path = root / "build_linux.sh"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "Categories=Game;Utility;",
        "Categories=Utility;",
        "desktop Categories entry",
    )

    cleanup = 'rm -rf -- "$appdir/usr/share/metainfo"'
    metadata = '''rm -rf -- "$appdir/usr/share/metainfo"
mkdir -p -- "$appdir/usr/share/metainfo"
cat > "$appdir/usr/share/metainfo/io.github.z3r3lkio.packizard-builder.metainfo.xml" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>io.github.z3r3lkio.packizard-builder</id>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>GPL-3.0-or-later</project_license>
  <name>Packizard Builder</name>
  <summary>Integrated PS5 AMPR/LZ4 compression and package workflow</summary>
  <description>
    <p>Packizard Builder provides an integrated desktop workflow for AMPR/LZ4 compression and package creation.</p>
  </description>
  <launchable type="desktop-id">packizard-builder.desktop</launchable>
  <url type="homepage">https://github.com/z3r3lkio/packizard-builder</url>
  <releases>
    <release version="$version" date="$(date -u +%Y-%m-%d)"/>
  </releases>
  <content_rating type="oars-1.1"/>
</component>
EOF'''
    text = replace_once(text, cleanup, metadata, "AppStream cleanup marker")

    path.write_text(text, encoding="utf-8", newline="\n")
    print("Normalized Linux desktop/AppStream packaging metadata")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="build-src")
    args = parser.parse_args()
    patch_linux_script(Path(args.root).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
