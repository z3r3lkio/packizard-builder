"""Frozen Packizard packer entry point."""
import sys

# Respect an explicitly injected packer module (used by diagnostics/tests) while
# resolving the real Packizard engine normally in frozen/source builds.
packer = sys.modules.get("packizard_engine.packer")
if packer is None:
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
