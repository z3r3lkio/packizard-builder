"""Frozen Packizard packer entry point."""
import sys
from packizard_engine.packer import main
if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
