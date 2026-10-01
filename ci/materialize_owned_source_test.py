from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SOURCE_BRANCH = "packizard-source-v1"
EXPECTED_REPOSITORY = "z3r3lkio/packizard-builder"
EXPECTED_HEAD = "feature/packizard-native-engine"


def _run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None, capture: bool = False) -> str:
    result = subprocess.run(
        list(args), cwd=cwd, env=env, check=True,
        text=True, capture_output=capture,
    )
    return result.stdout.strip() if capture else ""


def _prune(stage: Path) -> None:
    for rel in (".git", "__pycache__", "pkg_bridge"):
        shutil.rmtree(stage / rel, ignore_errors=True)
    for path in list(stage.rglob("*")):
        if path.is_dir() and path.name in {"__pycache__", "bin", "obj", ".git"}:
            shutil.rmtree(path, ignore_errors=True)
    for path in list(stage.rglob("*")):
        if path.is_file() and path.suffix in {".pyc", ".pyo", ".log"}:
            path.unlink(missing_ok=True)
    (stage / "tools" / "appimagetool-x86_64.AppImage").unlink(missing_ok=True)
    (stage / "Lazy_AMPR.spec").unlink(missing_ok=True)
    (stage / "tests" / "test_zzzz_materialize_owned_source.py").unlink(missing_ok=True)


def materialize_source(source: Path, outer_repo: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="packizard-owned-source-") as temp:
        stage = Path(temp) / "source"
        shutil.copytree(source, stage, symlinks=True)
        _prune(stage)

        git_dir = outer_repo / ".git"
        if not git_dir.exists():
            raise RuntimeError(f"outer Packizard checkout is missing .git: {outer_repo}")

        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(Path(temp) / "source.index")
        env["GIT_AUTHOR_NAME"] = "github-actions[bot]"
        env["GIT_AUTHOR_EMAIL"] = "41898282+github-actions[bot]@users.noreply.github.com"
        env["GIT_COMMITTER_NAME"] = env["GIT_AUTHOR_NAME"]
        env["GIT_COMMITTER_EMAIL"] = env["GIT_AUTHOR_EMAIL"]

        base = ("git", f"--git-dir={git_dir}", f"--work-tree={stage}")
        _run(*base, "read-tree", "--empty", env=env)
        _run(*base, "add", "-f", "-A", env=env)
        tree = _run(*base, "write-tree", env=env, capture=True)
        parent = _run(
            "git", "-C", str(outer_repo), "ls-remote", "--heads", "origin", SOURCE_BRANCH,
            env=env, capture=True,
        )
        parent_sha = parent.split()[0] if parent else ""
        commit_args = ["git", f"--git-dir={git_dir}", "commit-tree", tree]
        if parent_sha:
            commit_args.extend(["-p", parent_sha])
        commit = subprocess.run(
            commit_args, env=env, input="Packizard-owned validated source snapshot\n",
            text=True, check=True, capture_output=True,
        ).stdout.strip()
        _run(
            "git", "-C", str(outer_repo), "push", "--force", "origin",
            f"{commit}:refs/heads/{SOURCE_BRANCH}", env=env,
        )
        return commit


class MaterializePackizardOwnedSource(unittest.TestCase):
    def test_zzzz_materialize_validated_source(self):
        if os.environ.get("GITHUB_ACTIONS") != "true":
            self.skipTest("source materialization only runs in GitHub Actions")
        if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
            self.skipTest("source materialization is restricted to PR verification")
        if os.environ.get("GITHUB_REPOSITORY") != EXPECTED_REPOSITORY:
            self.skipTest("not the Packizard repository")
        if os.environ.get("GITHUB_HEAD_REF") != EXPECTED_HEAD:
            self.skipTest("not the native-engine migration branch")

        source = Path.cwd().resolve()
        outer = source.parent
        commit = materialize_source(source, outer)
        self.assertRegex(commit, r"^[0-9a-f]{40}$")
        print(f"Materialized Packizard-owned source at {SOURCE_BRANCH} {commit}")


if __name__ == "__main__":
    unittest.main()
