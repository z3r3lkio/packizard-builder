#!/usr/bin/env python3
"""Compatibility entry point for Packizard's native NAPS engine.

The workflow historically invoked this filename for a sequence of LibProsperoPKG patches.  Keep the
entry point stable while delegating to the Packizard-owned canonical DATA/NAPS implementation.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from packizard_native_naps_profile import apply


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="build-src")
    args = parser.parse_args()
    apply(Path(args.root))


if __name__ == "__main__":
    main()
