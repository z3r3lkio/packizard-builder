#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from compare_mkpfs_fpkg import classify
from core.pkg_image_validation import compare_pkg_images

CONTENT_ID = "UP9000-PPSA99097_00-PACKIZARDPARITY1"
TITLE_ID = "PPSA99097"
PASSCODE = "0" * 32
SEED_HEX = "00112233445566778899aabbccddeeff"
TIMESTAMP = "0"


def run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "command failed:\n"
            + " ".join(cmd)
            + "\n--- stdout ---\n"
            + result.stdout
            + "\n--- stderr ---\n"
            + result.stderr
        )
    return result


def write_fixture(root: Path) -> None:
    (root / "sce_sys").mkdir(parents=True)
    param = {
        "applicationCategoryType": 0,
        "applicationDrmType": "free",
        "contentId": CONTENT_ID,
        "contentVersion": "01.00",
        "masterVersion": "01.00",
        "requiredSystemSoftwareVersion": "0x0000000000000000",
        "sdkVersion": "0x0000000000000000",
        "titleId": TITLE_ID,
        "defaultLanguage": "en-US",
        "localizedParameters": {"en-US": {"titleName": "Packizard MkPFS Parity"}},
    }
    (root / "sce_sys" / "param.json").write_text(
        json.dumps(param, separators=(",", ":"), ensure_ascii=True),
        encoding="utf-8",
    )
    # A deterministic non-SELF payload named eboot.bin keeps the fixture accepted
    # by both builders while --no-fake-sign / fake_sign_self_modules=false makes
    # executable conversion irrelevant to this filesystem/container parity test.
    # Supply system-inner inputs explicitly so both builders consume identical
    # bytes instead of their independent embedded/generated defaults.
    (root / "sce_sys" / "keystone").write_bytes(b"K" * 0x60)
    (root / "sce_sys" / "pfs-version.dat").write_bytes(b"01.000.000")
    (root / "sce_sys" / "about").mkdir()
    (root / "sce_sys" / "about" / "right.sprx").write_bytes((b"PACKIZARD-RIGHT-SPRX\n" * 128)[:4096])

    (root / "eboot.bin").write_bytes((b"PACKIZARD-PARITY-EBOOT\n" * 257)[:8192])
    (root / "data").mkdir()
    (root / "data" / "alpha.dat").write_bytes(bytes(range(256)) * 300)
    (root / "data" / "zeros.bin").write_bytes(b"\0" * 131072)


def packizard_build(bridge: Path, source: Path, output: Path) -> Path:
    request = {
        "source_folder": str(source),
        "output_folder": str(output),
        "content_id": CONTENT_ID,
        "title_id": TITLE_ID,
        "title": "Packizard MkPFS Parity",
        "version": "01.00",
        "passcode": PASSCODE,
        "mode": "Application",
        "output_format": "DebugImage",
        "image_profile": "Standard",
        "application_type": "NotSpecified",
        "application_drm_type": "free",
        "generate_param_json_if_missing": False,
        "fake_sign_self_modules": False,
        "license_free": True,
        "verify_after_build": True,
        "outer_seed_hex": SEED_HEX,
        "inner_compression": "stored",
    }
    request_path = output.parent / "packizard-request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    result = run([str(bridge), "build", "--request", str(request_path)], cwd=bridge.parent)
    events = [
        json.loads(line)
        for line in result.stdout.splitlines()
        if line.lstrip().startswith("{")
    ]
    outputs = [event.get("outputPath") for event in events if event.get("type") == "result"]
    if not outputs:
        raise RuntimeError("Packizard bridge produced no result event\n" + result.stdout)
    return Path(outputs[-1]).resolve()


def mkpfs_build(mkpfs_repo: Path, source: Path, output: Path) -> Path:
    project = mkpfs_repo / "src" / "MkPFS.Cli"
    run(
        [
            "dotnet",
            "run",
            "--project",
            str(project),
            "-c",
            "Release",
            "--no-build",
            "--",
            "pack",
            "fpkg",
            str(source),
            str(output),
            "--content-id",
            CONTENT_ID,
            "--passcode",
            PASSCODE,
            "--compression",
            "stored",
            "--seed",
            SEED_HEX,
            "--timestamp",
            TIMESTAMP,
            "--no-fake-sign",
            "--json",
        ],
        cwd=mkpfs_repo,
    )
    if not output.is_file():
        raise RuntimeError(f"MkPFS did not produce {output}")
    return output.resolve()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--mkpfs-repo", required=True)
    parser.add_argument("--report")
    args = parser.parse_args()

    bridge = Path(args.bridge).resolve()
    mkpfs_repo = Path(args.mkpfs_repo).resolve()

    with tempfile.TemporaryDirectory(prefix="packizard-mkpfs-parity-") as td:
        work = Path(td)
        source = work / "source"
        source.mkdir()
        write_fixture(source)
        packizard_dir = work / "packizard"
        packizard_dir.mkdir()
        mkpfs_pkg = work / "mkpfs.pkg"

        candidate = packizard_build(bridge, source, packizard_dir)
        reference = mkpfs_build(mkpfs_repo, source, mkpfs_pkg)
        result = classify(compare_pkg_images(reference, candidate))

        if args.report:
            Path(args.report).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({
            "parity": result["parity"],
            "critical_differences": result["critical_differences"],
            "tolerated_difference_count": len(result["tolerated_differences"]),
            "reference": str(reference),
            "candidate": str(candidate),
        }, indent=2, sort_keys=True))
        return 0 if result["parity"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
