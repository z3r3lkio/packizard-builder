#!/usr/bin/env python3
"""Install the Packizard PS5 runtime source into a reconstructed source tree."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

RUNTIME_DIRNAME = "packizard_ps5_runtime"

BUILD_WRAPPER = '''#!/usr/bin/env bash
set -euo pipefail
: "${PS5_PAYLOAD_SDK:?Set PS5_PAYLOAD_SDK to your ps5-payload-sdk path}"
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"
make PS5_PAYLOAD_SDK="$PS5_PAYLOAD_SDK" all
mkdir -p out/packizard
sprx="$(find out -type f -name 'libSceAmpr.sprx' -print -quit || true)"
prx="$(find out -type f -name 'libSceAmpr.prx' -print -quit || true)"
[[ -n "$sprx" ]] || { echo "PS5 runtime build did not produce libSceAmpr.sprx" >&2; exit 1; }
cp -f "$sprx" out/packizard/libSceAmpr.sprx
if [[ -n "$prx" ]]; then cp -f "$prx" out/packizard/libSceAmpr.prx; fi
echo "Packizard PS5 Runtime: out/packizard/libSceAmpr.sprx"
'''


def install(output: Path) -> Path:
    output = Path(output)
    legacy = output / "external" / "ampr_emu"
    if not legacy.is_dir():
        raise RuntimeError(f"PS5 compatibility source is missing from reconstructed tree: {legacy}")

    runtime_root = output / "packizard_runtime" / "ps5" / RUNTIME_DIRNAME
    shutil.rmtree(runtime_root, ignore_errors=True)
    runtime_root.mkdir(parents=True, exist_ok=True)

    for dirname in ("src", "include", "ps5"):
        source = legacy / dirname
        if not source.is_dir():
            raise RuntimeError(f"PS5 runtime source directory missing: {source}")
        shutil.copytree(source, runtime_root / dirname)

    lz4_source = legacy / "third_party" / "lz4"
    if not lz4_source.is_dir():
        raise RuntimeError(f"PS5 runtime LZ4 source missing: {lz4_source}")
    shutil.copytree(lz4_source, runtime_root / "third_party" / "lz4")

    for filename in ("Makefile", "LICENSE"):
        source = legacy / filename
        if not source.is_file():
            raise RuntimeError(f"PS5 runtime source file missing: {source}")
        shutil.copy2(source, runtime_root / filename)

    wrapper = runtime_root / "build_packizard_runtime.sh"
    wrapper.write_text(BUILD_WRAPPER, encoding="utf-8", newline="\n")
    wrapper.chmod(0o755)
    (runtime_root / "PACKIZARD_RUNTIME.md").write_text(
        "# Packizard PS5 Runtime\n\n"
        "Packizard owns the integration, packaging and build contract for this PS5-side runtime. "
        "The sceAmpr ABI and libSceAmpr.sprx filename are retained for game compatibility.\n\n"
        "The current compatibility implementation retains source derived from ampr_emu and therefore "
        "its GPL attribution remains until that implementation is independently replaced.\n",
        encoding="utf-8", newline="\n",
    )

    identity = output / "core" / "packizard_ps5_runtime.py"
    identity.parent.mkdir(parents=True, exist_ok=True)
    identity.write_text(
        '"""Packizard PS5 runtime identity and compatibility ABI."""\n'
        'RUNTIME_NAME = "Packizard PS5 Runtime"\n'
        'RUNTIME_GENERATION = 1\n'
        'COMPATIBILITY_LIBRARY = "libSceAmpr.sprx"\n'
        'COMPATIBILITY_FORMAT = "AMPRPAK4"\n'
        'SOURCE_ROOT = "packizard_runtime/ps5/packizard_ps5_runtime"\n',
        encoding="utf-8", newline="\n",
    )

    marker = output / "resources" / "fakelib" / "PACKIZARD_RUNTIME_SOURCE.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        "Packizard PS5 Runtime source: packizard_runtime/ps5/packizard_ps5_runtime\n"
        "ABI compatibility filename: libSceAmpr.sprx\n"
        "Build with build_packizard_runtime.sh and PS5_PAYLOAD_SDK.\n",
        encoding="utf-8", newline="\n",
    )
    return runtime_root


def assert_installed(output: Path) -> None:
    root = Path(output) / "packizard_runtime" / "ps5" / RUNTIME_DIRNAME
    required = (
        root / "src" / "sceampr_exports.cpp",
        root / "src" / "ampr_emu_pack.cpp",
        root / "include" / "ampr_emu_pack_format.h",
        root / "Makefile",
        root / "LICENSE",
        root / "build_packizard_runtime.sh",
    )
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise RuntimeError("Packizard PS5 runtime source is incomplete: " + ", ".join(missing))
    if "PS5_PAYLOAD_SDK" not in (root / "Makefile").read_text(encoding="utf-8", errors="replace"):
        raise RuntimeError("Packizard PS5 runtime does not expose a PS5 payload SDK build")
    if "out/packizard/libSceAmpr.sprx" not in (root / "build_packizard_runtime.sh").read_text(encoding="utf-8"):
        raise RuntimeError("Packizard PS5 runtime does not produce the compatibility SPRX")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="build-src")
    args = parser.parse_args()
    output = Path(args.root).resolve()
    if not output.is_dir():
        raise SystemExit(f"source tree does not exist: {output}")
    installed = install(output)
    assert_installed(output)
    print(f"Installed Packizard PS5 Runtime source at {installed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
