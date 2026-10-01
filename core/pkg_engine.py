from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

ENGINE_NAME = "LibProsperoPKG"
ENGINE_VERSION = "2.6.0"
ENGINE_REF = "748eabf1b7d17819528cabf367d8e27109d8fce3"
PPR_GUI_REFERENCE_VERSION = "0.6.8"
ENV_BRIDGE_PATH = "PACKIZARD_PKG_BRIDGE"


class PkgEngineError(RuntimeError):
    """Raised when Packizard's integrated package engine cannot complete a build."""


@dataclass
class PkgBuildOptions:
    source_folder: str
    output_folder: str
    content_id: str = ""
    title_id: str = ""
    title: str = ""
    version: str = "01.00"
    passcode: str = "0" * 32
    mode: str = "Application"
    output_format: str = "DebugImage"
    application_type: str = "NotSpecified"
    application_drm_type: str = "standard"
    generate_param_json_if_missing: bool = True
    fake_sign_self_modules: bool = True
    license_free: bool = False
    verify_after_build: bool = True

    def normalized(self) -> "PkgBuildOptions":
        source = Path(self.source_folder).expanduser()
        output = Path(self.output_folder).expanduser()
        version = (self.version or "01.00").strip()
        passcode = (self.passcode or "").strip() or ("0" * 32)
        return PkgBuildOptions(
            source_folder=str(source),
            output_folder=str(output),
            content_id=(self.content_id or "").strip().upper(),
            title_id=(self.title_id or "").strip().upper(),
            title=(self.title or "").strip(),
            version=version,
            passcode=passcode,
            mode=(self.mode or "Application").strip(),
            output_format=(self.output_format or "DebugImage").strip(),
            application_type=(self.application_type or "NotSpecified").strip(),
            application_drm_type=(self.application_drm_type or "").strip().lower(),
            generate_param_json_if_missing=bool(self.generate_param_json_if_missing),
            fake_sign_self_modules=bool(self.fake_sign_self_modules),
            license_free=bool(self.license_free),
            verify_after_build=bool(self.verify_after_build),
        )

    def validate(self, *, require_source: bool = True) -> None:
        options = self.normalized()
        source = Path(options.source_folder)
        if require_source and not source.is_dir():
            raise PkgEngineError(f"PKG source folder not found: {source}")
        if not options.output_folder:
            raise PkgEngineError("PKG output folder is required.")
        if options.passcode and len(options.passcode) != 32:
            raise PkgEngineError("PKG passcode must contain exactly 32 characters.")
        if options.content_id and len(options.content_id) != 36:
            raise PkgEngineError("Content ID must contain exactly 36 characters.")
        if options.title_id and len(options.title_id) != 9:
            raise PkgEngineError("Title ID must contain exactly 9 characters.")

    def to_request(self) -> dict:
        options = self.normalized()
        options.validate()
        return asdict(options)


@dataclass(frozen=True)
class PkgEngineInfo:
    path: Path
    engine_name: str
    engine_version: str
    engine_ref: str
    keys_available: bool | None = None
    ppr_gui_reference_version: str = PPR_GUI_REFERENCE_VERSION


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _bridge_names() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("Packizard.PkgBridge.exe", "Packizard.PkgBridge")
    return ("Packizard.PkgBridge", "Packizard.PkgBridge.exe")


def candidate_bridge_paths(*, root: Path | None = None) -> list[Path]:
    root = Path(root) if root else _runtime_root()
    candidates: list[Path] = []
    configured = os.environ.get(ENV_BRIDGE_PATH)
    if configured:
        candidates.append(Path(configured).expanduser())
    for directory in (
        root / "pkg_bridge",
        root / "workers" / "pkg_bridge",
        root / "bridge" / "publish",
    ):
        for name in _bridge_names():
            candidates.append(directory / name)
    return candidates


def find_pkg_bridge(*, root: Path | None = None) -> Path | None:
    for candidate in candidate_bridge_paths(root=root):
        if candidate.is_file():
            return candidate.resolve()
    return None


def _command_for_bridge(path: Path, *args: str) -> list[str]:
    if not path.is_file():
        raise PkgEngineError(f"Integrated PKG bridge not found: {path}")
    if sys.platform != "win32" and not os.access(path, os.X_OK):
        raise PkgEngineError(f"Integrated PKG bridge is not executable: {path}")
    return [str(path), *args]


def probe_pkg_engine(*, root: Path | None = None, timeout: float = 8.0) -> PkgEngineInfo | None:
    bridge = find_pkg_bridge(root=root)
    if not bridge:
        return None
    try:
        result = subprocess.run(
            _command_for_bridge(bridge, "probe"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except OSError as exc:
        raise PkgEngineError(f"Could not start integrated PKG engine: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise PkgEngineError(detail or f"PKG engine probe failed with code {result.returncode}.")
    try:
        payload = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise PkgEngineError("Integrated PKG engine returned an invalid probe response.") from exc
    return PkgEngineInfo(
        path=bridge,
        engine_name=str(payload.get("engine") or ENGINE_NAME),
        engine_version=str(payload.get("engineVersion") or ENGINE_VERSION),
        engine_ref=str(payload.get("engineRef") or ENGINE_REF),
        keys_available=payload.get("keysAvailable"),
        ppr_gui_reference_version=str(payload.get("pprGuiReferenceVersion") or PPR_GUI_REFERENCE_VERSION),
    )


def run_pkg_build(
    options: PkgBuildOptions,
    *,
    log_callback: Callable[[str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    process_callback: Callable[[subprocess.Popen | None], None] | None = None,
    root: Path | None = None,
) -> tuple[Path, list[str]]:
    """Build a PKG through Packizard's bundled LibProsperoPKG bridge.

    The bridge is a first-party Packizard helper linked to the pinned upstream
    LibProsperoPKG release. No external GUI is launched.
    """
    bridge = find_pkg_bridge(root=root)
    if not bridge:
        raise PkgEngineError(
            "The integrated PKG engine is missing from this Packizard build. "
            "Reinstall a complete release or rebuild Packizard with the PKG bridge enabled."
        )

    request = options.to_request()
    output_dir = Path(request["output_folder"])
    output_dir.mkdir(parents=True, exist_ok=True)

    request_path: Path | None = None
    process: subprocess.Popen | None = None
    try:
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix="packizard-pkg-",
            delete=False,
        )
        request_path = Path(handle.name)
        json.dump(request, handle, ensure_ascii=False, indent=2)
        handle.close()

        kwargs: dict = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "cwd": str(bridge.parent),
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        process = subprocess.Popen(
            _command_for_bridge(bridge, "build", "--request", str(request_path)),
            **kwargs,
        )
        if process_callback:
            process_callback(process)

        output_path: Path | None = None
        warnings: list[str] = []
        error_message = ""
        if process.stdout is None:
            raise PkgEngineError("PKG bridge did not expose a progress stream.")

        for raw in process.stdout:
            if cancel_check and cancel_check():
                try:
                    process.terminate()
                except OSError:
                    pass
                raise PkgEngineError("PKG build cancelled by user.")

            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                if log_callback:
                    log_callback(line)
                continue

            event_type = str(event.get("type") or "").casefold()
            if event_type == "log":
                message = str(event.get("message") or "")
                if message and log_callback:
                    log_callback(message)
            elif event_type == "warning":
                message = str(event.get("message") or "")
                if message:
                    warnings.append(message)
                    if log_callback:
                        log_callback(f"PKG warning: {message}")
            elif event_type == "result":
                candidate = str(event.get("outputPath") or "").strip()
                if candidate:
                    output_path = Path(candidate)
                for warning in event.get("warnings") or []:
                    text = str(warning).strip()
                    if text and text not in warnings:
                        warnings.append(text)
            elif event_type == "error":
                error_message = str(event.get("message") or "PKG build failed.")
                details = str(event.get("details") or "").strip()
                if details:
                    error_message += f"\n{details}"

        returncode = process.wait()
        if process.stdout is not None:
            process.stdout.close()
        if returncode != 0:
            raise PkgEngineError(error_message or f"Integrated PKG engine exited with code {returncode}.")
        if not output_path:
            raise PkgEngineError("Integrated PKG engine completed without reporting an output package.")
        if not output_path.is_file():
            raise PkgEngineError(f"PKG engine reported a package that does not exist: {output_path}")
        return output_path.resolve(), warnings
    finally:
        if process_callback:
            process_callback(None)
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
        if request_path is not None:
            request_path.unlink(missing_ok=True)
