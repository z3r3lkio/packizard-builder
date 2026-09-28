#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import naps_data_block_map_profile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="build-src")
    args = parser.parse_args()
    naps_data_block_map_profile.apply(Path(args.root))


if __name__ == "__main__":
    main()
