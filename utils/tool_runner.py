"""Resolve Packizard engine helpers in source and frozen builds."""

import sys
from pathlib import Path

_WORKERS = {
    "packer": "Packizard-Packer-Worker",
    "profile": "Packizard-Profile-Worker",
}

def command_for(script: Path) -> list[str]:
    script = Path(script)
    worker_name = _WORKERS.get(script.stem)
    if getattr(sys, "frozen", False):
        if worker_name is None:
            raise FileNotFoundError(f"Unknown Packizard helper: {script.stem}")
        suffix = ".exe" if sys.platform == "win32" else ""
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        worker = root / "workers" / worker_name / f"{worker_name}{suffix}"
        if not worker.is_file():
            raise FileNotFoundError(f"Bundled Packizard helper not found: {worker}")
        return [str(worker)]
    return [sys.executable, str(script)]
