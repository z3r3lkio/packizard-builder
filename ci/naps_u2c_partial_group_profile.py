#!/usr/bin/env python3
"""Compatibility entry point for Packizard's native NAPS engine.

The workflow historically invokes this filename.  Keep that stable, but do not layer legacy u2c
patches on top of the native planner: the native profile now owns DATA geometry, interval mapping,
validation and serialization as one coherent implementation.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import packizard_native_naps_profile as native


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="build-src")
    args = parser.parse_args()
    native.apply(Path(args.root))


if __name__ == "__main__":
    main()
