"""Frozen Packizard packer entry point."""
import sys
from packizard_engine import packer
from packizard_engine.streaming_pack import install as install_streaming_pack
from packizard_engine.streaming_verify import install as install_streaming_verify

install_streaming_pack()
install_streaming_verify()

if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(packer.main())
