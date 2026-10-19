from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

APP_NAME = "Packizard Builder"
BASE_VERSION = (0, 2, 0)
BASE_MAIN_SHA = "0bbf4c124fbd9fc6dec2d883c587e40757d6a279"
BASE_UAT_SHA = "d8a66b6600831c0ae9c9609bca358a347850e4b0"
# Existing feature history used 0.2.0 for every artifact. Start the feature
# counter at the last such validated build so the first stamped build is 0.2.1.
BASE_FEATURE_SHA = "dbac176f7de91d169e24ba9d8a0267d6f8c69432"


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _count(spec: str, *, first_parent: bool = False) -> int:
    args = ["rev-list", "--count"]
    if first_parent:
        args.append("--first-parent")
    args.append(spec)
    return int(_git(*args) or "0")


def compute_version(
    channel: str,
    *,
    main_promotions: int,
    uat_promotions: int,
    feature_commits: int = 0,
) -> str:
    """Compute Packizard's major.UAT.feature version for one build channel."""
    if channel not in {"main", "uat", "feature"}:
        raise ValueError(f"Unknown build channel: {channel}")
    if min(main_promotions, uat_promotions, feature_commits) < 0:
        raise ValueError("Version counters cannot be negative")

    major = BASE_VERSION[0] + main_promotions
    minor = BASE_VERSION[1] + uat_promotions if main_promotions == 0 else uat_promotions

    if channel == "main":
        if main_promotions == 0:
            return ".".join(str(part) for part in BASE_VERSION)
        return f"{major}.0.0"
    if channel == "uat":
        return f"{major}.{minor}.0"
    return f"{major}.{minor}.{feature_commits}"


def _fetch_refs(branch: str, *, include_branch: bool) -> None:
    refs = {"main", "UAT"}
    if include_branch and branch and branch not in refs:
        refs.add(branch)
    for ref in sorted(refs):
        subprocess.run(
            ["git", "fetch", "--quiet", "origin", f"refs/heads/{ref}:refs/remotes/origin/{ref}"],
            check=True,
        )


def derive_version(branch: str, *, ref_type: str = "branch") -> tuple[str, str]:
    channel = "main" if ref_type == "tag" or branch == "main" else ("uat" if branch == "UAT" else "feature")
    _fetch_refs(branch, include_branch=channel == "feature")

    main_promotions = _count(f"{BASE_MAIN_SHA}..origin/main", first_parent=True)
    if main_promotions == 0:
        uat_promotions = _count(f"{BASE_UAT_SHA}..origin/UAT", first_parent=True)
    else:
        uat_promotions = _count("origin/main..origin/UAT", first_parent=True)

    feature_commits = 0
    if channel == "feature":
        target = f"origin/{branch}"
        current_uat = _git("rev-parse", "origin/UAT")
        if current_uat == BASE_UAT_SHA:
            feature_commits = _count(f"{BASE_FEATURE_SHA}..{target}")
        else:
            feature_commits = _count(f"origin/UAT..{target}")

    return channel, compute_version(
        channel,
        main_promotions=main_promotions,
        uat_promotions=uat_promotions,
        feature_commits=feature_commits,
    )


def write_version(path: str | Path, version: str, channel: str) -> Path:
    target = Path(path)
    target.write_text(
        f'APP_NAME = "{APP_NAME}"\nVERSION = "{version}"\nBUILD_CHANNEL = "{channel}"\n',
        encoding="utf-8",
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Stamp Packizard's channel-aware build version into version.py.")
    parser.add_argument("--branch", default=os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME") or "")
    parser.add_argument("--ref-type", default=os.environ.get("GITHUB_REF_TYPE") or "branch")
    parser.add_argument("--output", default="version.py")
    args = parser.parse_args()
    if not args.branch:
        raise SystemExit("Cannot determine the build branch; pass --branch explicitly.")

    channel, version = derive_version(args.branch, ref_type=args.ref_type)
    write_version(args.output, version, channel)
    print(f"Packizard build version: {version} ({channel})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
