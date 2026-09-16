from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ENV_TOOL_PATH = "PACKIZARD_PPR_PKG"
KNOWN_EXECUTABLE_NAMES = (
    "LibProsperoPkg.Gui.exe",
    "PPR-PKG Builder.exe",
    "PPR-PKG-Builder.exe",
    "PPR-PKG-builder.exe",
    "fpkg-gui.exe",
    "LibProsperoPkg.Gui.dll",
)


class PprPkgBuilderError(RuntimeError):
    pass


@dataclass(frozen=True)
class PprPkgBuilderInfo:
    path: Path
    command: tuple[str, ...]

    @property
    def display_name(self) -> str:
        return self.path.name


def _runtime_root() -> Path:
    """Return the application root both from source and from a PyInstaller build."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _iter_candidate_directories(root: Path | None = None) -> Iterable[Path]:
    root = Path(root) if root else _runtime_root()
    yield root / "tools" / "ppr_pkg_builder"
    yield root / "tools" / "ppr-pkg-builder"
    yield root / "resources" / "ppr_pkg_builder"
    yield root / "resources" / "ppr-pkg-builder"
    yield root


def candidate_tool_paths(
    configured: str | os.PathLike[str] | None = None,
    *,
    root: Path | None = None,
) -> list[Path]:
    """Return ordered paths that may point to the official PPR-PKG Builder.

    The exact builder is intentionally not redistributed by Packizard. A configured
    path always wins, followed by PACKIZARD_PPR_PKG, then well-known local folders.
    """
    candidates: list[Path] = []

    def add(value: str | os.PathLike[str] | None):
        if not value:
            return
        path = Path(value).expanduser()
        if path not in candidates:
            candidates.append(path)

    add(configured)
    add(os.environ.get(ENV_TOOL_PATH))

    for directory in _iter_candidate_directories(root):
        for name in KNOWN_EXECUTABLE_NAMES:
            add(directory / name)
    return candidates


def find_ppr_pkg_builder(
    configured: str | os.PathLike[str] | None = None,
    *,
    root: Path | None = None,
) -> Path | None:
    for candidate in candidate_tool_paths(configured, root=root):
        if candidate.is_file():
            return candidate.resolve()
    return None


def build_launch_command(path: str | os.PathLike[str]) -> list[str]:
    tool = Path(path).expanduser().resolve()
    if not tool.is_file():
        raise PprPkgBuilderError(f"PPR-PKG Builder no existe: {tool}")

    if tool.suffix.lower() == ".dll":
        dotnet = shutil.which("dotnet")
        if not dotnet:
            raise PprPkgBuilderError(
                "La herramienta seleccionada es una DLL .NET y no se encontró 'dotnet' en PATH."
            )
        return [dotnet, str(tool)]

    if sys.platform != "win32" and tool.suffix.lower() == ".exe":
        raise PprPkgBuilderError(
            "La versión de PPR-PKG Builder mostrada en la referencia es una aplicación Windows. "
            "Ejecuta Packizard en Windows o selecciona una variante oficial compatible con este sistema."
        )
    return [str(tool)]


def inspect_ppr_pkg_builder(
    configured: str | os.PathLike[str] | None = None,
    *,
    root: Path | None = None,
) -> PprPkgBuilderInfo | None:
    path = find_ppr_pkg_builder(configured, root=root)
    if not path:
        return None
    return PprPkgBuilderInfo(path=path, command=tuple(build_launch_command(path)))


def launch_ppr_pkg_builder(path: str | os.PathLike[str]) -> subprocess.Popen:
    """Launch the selected official builder without inventing unsupported CLI flags."""
    tool = Path(path).expanduser().resolve()
    command = build_launch_command(tool)
    kwargs: dict = {
        "cwd": str(tool.parent),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(command, **kwargs)
