#!/usr/bin/env python3
"""Remove known deterministic compiler warnings from reconstructed sources.

The compact Packizard repository reconstructs pinned upstream sources in CI.  Some
warnings are caused by intentionally-default feature switches or XML comments in
that pinned snapshot/our large-package overrides.  Fix them in the reconstructed
tree without changing runtime behaviour.  Every replacement is strict so an
upstream drift fails CI instead of silently patching the wrong code.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one occurrence in {path}: {old!r}; found {count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def normalize_oodle(root: Path) -> None:
    path = (
        root
        / "vendor"
        / "LibProsperoPKG"
        / "src"
        / "LibProsperoPkg"
        / "PFS"
        / "Compression"
        / "Oodle"
        / "OodleKrakenEncoder.cs"
    )
    replacements = {
        "    internal static bool UseOptimalParse;":
            "    internal static bool UseOptimalParse = false;",
        "    [ThreadStatic] internal static bool UseSeedDecay;":
            "    [ThreadStatic] internal static bool UseSeedDecay = false;",
        "    [ThreadStatic] internal static bool UseSublenGate;":
            "    [ThreadStatic] internal static bool UseSublenGate = false;",
        "    internal static bool UseReanchorTie;":
            "    internal static bool UseReanchorTie = false;",
        "    internal static bool UseRepFrontierGate;":
            "    internal static bool UseRepFrontierGate = false;",
        "    [ThreadStatic] internal static bool UseTieBreakLast;":
            "    [ThreadStatic] internal static bool UseTieBreakLast = false;",
        "    [ThreadStatic] internal static int SeedDecayBaseOverride;":
            "    [ThreadStatic] internal static int SeedDecayBaseOverride = 0;",
    }
    for old, new in replacements.items():
        replace_once(path, old, new)


def normalize_assembler(root: Path) -> None:
    path = (
        root
        / "vendor"
        / "LibProsperoPKG"
        / "src"
        / "LibProsperoPkg"
        / "PFS"
        / "ProsperoPs5InnerImageAssembler.cs"
    )
    replace_once(path, "        public string? OnDiskPath;", "        public string? OnDiskPath = null;")
    replace_once(path, "        public byte[]? OnDiskData;", "        public byte[]? OnDiskData = null;")


def normalize_fih_docs(root: Path) -> None:
    path = (
        root
        / "vendor"
        / "LibProsperoPKG"
        / "src"
        / "LibProsperoPkg"
        / "PKG"
        / "ProsperoFihBuilder.cs"
    )
    marker = (
        "    /// <param name=\"nwonlyAppFileCount\">Application-payload file count for the FIH file-count field.</param>\n"
        "    public static System.Collections.Generic.IReadOnlyList<string> BuildFromCnt("
    )
    replacement = (
        "    /// <param name=\"nwonlyAppFileCount\">Application-payload file count for the FIH file-count field.</param>\n"
        "    /// <param name=\"siArchivePathFactory\">Optional file-backed SI factory for large finalized mount images.</param>\n"
        "    public static System.Collections.Generic.IReadOnlyList<string> BuildFromCnt("
    )
    replace_once(path, marker, replacement)


def normalize_naps_meta_docs(root: Path) -> None:
    path = (
        root
        / "vendor"
        / "LibProsperoPKG"
        / "src"
        / "LibProsperoPkg"
        / "PKG"
        / "ProsperoNapsMeta.cs"
    )
    replace_once(path, '<see cref="BuildMeta18"/>', '<c>BuildMeta18</c>')


def normalize_si_archive_docs(root: Path) -> None:
    path = (
        root
        / "vendor"
        / "LibProsperoPKG"
        / "src"
        / "LibProsperoPkg"
        / "PKG"
        / "ProsperoSiArchive.cs"
    )
    replace_once(
        path,
        '<see cref="ProsperoPlayGo.BuildChunkCrc"/>',
        '<c>ProsperoPlayGo.BuildChunkCrc</c>',
    )
    replace_once(
        path,
        '<see cref="ProsperoNapsMeta.BuildMeta18"/>',
        '<c>ProsperoNapsMeta.BuildMeta18</c>',
    )
    replace_once(
        path,
        '    /// finalized <paramref name="mountImage"/> (FIH + PFS + CNT) it derives every reproducible member and',
        '    /// finalized mount image at <paramref name="mountImagePath"/> (FIH + PFS + CNT) it derives every reproducible member and',
    )
    replace_once(
        path,
        '    /// <param name="mountImage">The finalized FIH+PFS+CNT mount image.</param>',
        '    /// <param name="mountImagePath">Path to the finalized FIH+PFS+CNT mount image.</param>',
    )
    replace_once(
        path,
        '    /// caller with only the finalized image) it falls back to reading FIH[0xA0] out of <paramref name="mountImage"/>,',
        '    /// caller with only the finalized image) it falls back to reading FIH[0xA0] from <paramref name="mountImagePath"/>,',
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="build-src")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    normalize_oodle(root)
    normalize_assembler(root)
    normalize_fih_docs(root)
    normalize_naps_meta_docs(root)
    normalize_si_archive_docs(root)
    print("Normalized deterministic LibProsperoPKG compiler warnings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
