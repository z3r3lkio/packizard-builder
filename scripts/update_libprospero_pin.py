#!/usr/bin/env python3
"""Update Packizard's validated LibProsperoPKG public-source snapshot pin.

The PPR-PKG Builder GUI reference version is tracked separately in
bridge/PPR_GUI_REFERENCE_VERSION because it uses a different release scheme.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_exact(path: Path, pattern: str, replacement: str, *, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    updated, replacements = re.subn(pattern, replacement, text, count=count, flags=re.MULTILINE)
    if replacements != count:
        raise SystemExit(f"Expected {count} replacement(s) in {path}, got {replacements}")
    path.write_text(updated, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True, help="Upstream assembly version, e.g. 2.6.0")
    parser.add_argument("--ref", required=True, help="Full upstream main commit SHA")
    args = parser.parse_args()
    version = args.version.strip().lstrip("v")
    ref = args.ref.strip().lower()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9._-]+)?", version):
        raise SystemExit(f"Unexpected upstream version: {version}")
    if not re.fullmatch(r"[0-9a-f]{40}", ref):
        raise SystemExit("--ref must be a full 40-character commit SHA")

    (ROOT / "bridge" / "LIBPROSPERO_VERSION").write_text(f"v{version}\n", encoding="utf-8")
    (ROOT / "bridge" / "LIBPROSPERO_REF").write_text(ref + "\n", encoding="utf-8")

    replace_exact(ROOT / "core" / "pkg_engine.py", r'^ENGINE_VERSION = "[^"]+"$', f'ENGINE_VERSION = "{version}"')
    replace_exact(ROOT / "core" / "pkg_engine.py", r'^ENGINE_REF = "[0-9a-fA-F]{40}"$', f'ENGINE_REF = "{ref}"')
    replace_exact(
        ROOT / "bridge" / "Packizard.PkgBridge" / "Program.cs",
        r'private const string EngineVersion = "[^"]+";',
        f'private const string EngineVersion = "{version}";',
    )
    replace_exact(
        ROOT / "bridge" / "Packizard.PkgBridge" / "Program.cs",
        r'private const string EngineRef = "[0-9a-fA-F]{40}";',
        f'private const string EngineRef = "{ref}";',
    )

    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    text, n1 = re.subn(r'validated upstream snapshot: \*\*v[^*]+\*\*', f'validated upstream snapshot: **v{version}**', text, count=1)
    text, n2 = re.subn(r'pinned commit: `[0-9a-fA-F]{40}`', f'pinned commit: `{ref}`', text, count=1)
    if n1 != 1 or n2 != 1:
        raise SystemExit("README pin markers were not found")
    readme.write_text(text, encoding="utf-8", newline="\n")

    notices = ROOT / "THIRD_PARTY_NOTICES.md"
    text = notices.read_text(encoding="utf-8")
    text, n1 = re.subn(r'integrates \*\*LibProsperoPKG v[^*]+\*\*', f'integrates **LibProsperoPKG v{version}**', text, count=1)
    text, n2 = re.subn(r'pinned main snapshot: `v[^`]+`', f'pinned main snapshot: `v{version}`', text, count=1)
    text, n3 = re.subn(r'pinned commit: `[0-9a-fA-F]{40}`', f'pinned commit: `{ref}`', text, count=1)
    if (n1, n2, n3) != (1, 1, 1):
        raise SystemExit("THIRD_PARTY_NOTICES pin markers were not found")
    notices.write_text(text, encoding="utf-8", newline="\n")

    print(f"Updated LibProsperoPKG snapshot pin to v{version} ({ref})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
