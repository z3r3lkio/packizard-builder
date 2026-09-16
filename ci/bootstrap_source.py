#!/usr/bin/env python3
"""CI entrypoint that prefers the verified split integrated overlay."""
from pathlib import Path


def main() -> int:
    ci_dir = Path(__file__).resolve().parent
    packed = ci_dir / "integrated_pkg.patch.xz.b64"
    if packed.is_file():
        packed.unlink()
    from bootstrap_source_impl import main as bootstrap_main
    return bootstrap_main()


if __name__ == "__main__":
    raise SystemExit(main())
