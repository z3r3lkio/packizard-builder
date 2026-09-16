#!/usr/bin/env python3
"""CI bootstrap wrapper with base-version diagnostics."""
from pathlib import Path
import hashlib


def main() -> int:
    ci_dir = Path(__file__).resolve().parent
    packed = ci_dir / "integrated_pkg.patch.xz.b64"
    if packed.is_file():
        packed.unlink()
    import bootstrap_source_impl as impl
    original_run = impl.run

    def diagnostic_run(*args: str, cwd=None) -> None:
        if len(args) >= 4 and args[0] == "git" and args[1] == "apply" and "packizard-integrated-" in str(args[-1]):
            root = Path(cwd)
            version = root / "version.py"
            data = version.read_bytes()
            print("PACKIZARD_BASE_VERSION_SHA256=" + hashlib.sha256(data).hexdigest())
            print("PACKIZARD_BASE_VERSION_CONTENT=" + data.decode("utf-8").strip().replace("\n", " | "))
        return original_run(*args, cwd=cwd)

    impl.run = diagnostic_run
    return impl.main()


if __name__ == "__main__":
    raise SystemExit(main())
