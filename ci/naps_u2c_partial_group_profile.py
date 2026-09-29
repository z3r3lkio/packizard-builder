#!/usr/bin/env python3
"""Compatibility entry point for Packizard's native NAPS engine.

The workflow historically invokes this filename. Keep that stable, but do not layer legacy u2c
patches on top of the native planner: the native profile owns DATA geometry, interval mapping,
validation, serialization and deterministic read-back validation as one coherent implementation.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import packizard_native_naps_profile as native


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="build-src")
    args = parser.parse_args()
    root = Path(args.root)
    native.apply(root)

    # Keep the stable native.apply profile focused on package routing while this compatibility entry
    # point installs the Packizard-owned reader used by regression/diagnostic round trips. The reader is
    # also shipped in the bridge assembly, so future runtime validation can use the exact same section map.
    source = Path(__file__).resolve().parent / "native_naps" / "PackizardNativeNapsReader.cs"
    destination = root / "vendor" / "LibProsperoPKG" / "src" / "LibProsperoPkg" / "PKG" / "PackizardNativeNapsReader.cs"
    if not source.is_file():
        raise RuntimeError(f"Missing Packizard native reader: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    print("Installed Packizard-native NAPS reader")


if __name__ == "__main__":
    main()
