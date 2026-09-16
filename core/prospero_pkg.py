from __future__ import annotations

import ctypes
import os
import platform
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

LIBPROSPERO_ABI = 7
LIBPROSPERO_VERSION = "2.5"

_TITLE_ID_RE = re.compile(r"^PPSA\d{5}$", re.IGNORECASE)
_CONTENT_ID_RE = re.compile(r"^[A-Z0-9]{6}-[A-Z0-9]{9}_00-[A-Z0-9]{16}$", re.IGNORECASE)
_VERSION_RE = re.compile(r"^\d{2}\.\d{2}$")


class ProsperoError(RuntimeError):
    pass


@dataclass(slots=True)
class PkgBuildOptions:
    source_folder: Path
    output_folder: Path
    content_id: str
    title_id: str
    title: str
    version: str = "01.00"
    passcode: str = ""
    mode: int = 0
    output_format: int = 1
    application_type: int = 1
    generate_param_json: bool = True
    fake_sign_self: bool = False
    license_free: bool = False
    application_drm_type: str = ""
    backup_mode: bool = False


class _LppBuildOptions(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_int32),
        ("mode", ctypes.c_int32),
        ("output_format", ctypes.c_int32),
        ("inner_compression", ctypes.c_int32),
        ("application_type", ctypes.c_int32),
        ("content_badge_type", ctypes.c_int32),
        ("generate_param_json", ctypes.c_int32),
        ("compress_inner_image", ctypes.c_int32),
        ("fake_sign_self", ctypes.c_int32),
        ("has_authority_id", ctypes.c_int32),
        ("app_version", ctypes.c_uint64),
        ("firmware_version", ctypes.c_uint64),
        ("authority_id", ctypes.c_uint64),
        ("source_folder", ctypes.c_char_p),
        ("output_folder", ctypes.c_char_p),
        ("content_id", ctypes.c_char_p),
        ("passcode", ctypes.c_char_p),
        ("title", ctypes.c_char_p),
        ("title_id", ctypes.c_char_p),
        ("version", ctypes.c_char_p),
        ("application_drm_type", ctypes.c_char_p),
        ("license_free", ctypes.c_int32),
    ]


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def platform_key() -> str:
    machine = platform.machine().lower()
    is_arm = machine in {"arm64", "aarch64"}
    if sys.platform.startswith("win"):
        return "win-arm64" if is_arm else "win-x64"
    if sys.platform == "darwin":
        return "osx-arm64" if is_arm else "osx-x64"
    return "linux-arm64" if is_arm else "linux-x64"


def _library_names() -> tuple[str, ...]:
    if sys.platform.startswith("win"):
        return ("LibProsperoPkg.dll", "libprosperopkg.dll")
    if sys.platform == "darwin":
        return ("libLibProsperoPkg.dylib", "LibProsperoPkg.dylib", "libprosperopkg.dylib")
    return ("LibProsperoPkg.so", "libLibProsperoPkg.so", "libprosperopkg.so")


def candidate_library_paths() -> list[Path]:
    override = os.environ.get("PACKIZARD_LIBPROSPERO", "").strip()
    roots: list[Path] = []
    if override:
        p = Path(override).expanduser()
        if p.is_file():
            return [p]
        roots.append(p)

    root = _runtime_root()
    key = platform_key()
    roots.extend(
        [
            root / "pkg_engine" / key,
            root / "resources" / "pkg_engine" / key,
            root / "resources" / "pkg_engine",
            root,
        ]
    )
    paths: list[Path] = []
    for folder in roots:
        for name in _library_names():
            paths.append(folder / name)
    return paths


def find_library() -> Optional[Path]:
    for path in candidate_library_paths():
        if path.is_file():
            return path
    return None


class ProsperoPkgEngine:
    def __init__(self, library_path: Path | None = None):
        self.library_path = Path(library_path) if library_path else find_library()
        if not self.library_path:
            raise ProsperoError(
                "LibProsperoPkg no está instalado. Ejecuta scripts/fetch_pkg_engine.py "
                "o usa una compilación de Packizard que incluya el motor PKG."
            )
        try:
            self.lib = ctypes.CDLL(str(self.library_path))
        except OSError as exc:
            raise ProsperoError(f"No se pudo cargar LibProsperoPkg: {exc}") from exc
        self._bind()
        abi = int(self.lib.lpp_abi_version())
        if abi != LIBPROSPERO_ABI:
            raise ProsperoError(
                f"ABI de LibProsperoPkg incompatible: {abi}; Packizard requiere {LIBPROSPERO_ABI}."
            )

    def _bind(self) -> None:
        self.lib.lpp_version.argtypes = []
        self.lib.lpp_version.restype = ctypes.c_char_p
        self.lib.lpp_abi_version.argtypes = []
        self.lib.lpp_abi_version.restype = ctypes.c_int
        self.lib.lpp_keys_available.argtypes = []
        self.lib.lpp_keys_available.restype = ctypes.c_int
        self.lib.lpp_last_error.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.lib.lpp_last_error.restype = ctypes.c_int
        self.lib.lpp_is_valid_content_id.argtypes = [ctypes.c_char_p]
        self.lib.lpp_is_valid_content_id.restype = ctypes.c_int
        self.lib.lpp_is_valid_title_id.argtypes = [ctypes.c_char_p]
        self.lib.lpp_is_valid_title_id.restype = ctypes.c_int
        self.lib.lpp_build_package_ex.argtypes = [
            ctypes.POINTER(_LppBuildOptions),
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self.lib.lpp_build_package_ex.restype = ctypes.c_int
        self.lib.lpp_convert_backup.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self.lib.lpp_convert_backup.restype = ctypes.c_int

    @property
    def version(self) -> str:
        raw = self.lib.lpp_version()
        return raw.decode("utf-8", "replace") if raw else "LibProsperoPkg"

    @property
    def keys_available(self) -> bool:
        return bool(self.lib.lpp_keys_available())

    def _last_error(self) -> str:
        buf = ctypes.create_string_buffer(8192)
        self.lib.lpp_last_error(buf, len(buf))
        return buf.value.decode("utf-8", "replace") or "Error desconocido de LibProsperoPkg"

    def valid_title_id(self, value: str) -> bool:
        return bool(self.lib.lpp_is_valid_title_id(value.encode("utf-8")))

    def valid_content_id(self, value: str) -> bool:
        return bool(self.lib.lpp_is_valid_content_id(value.encode("utf-8")))

    def build(self, options: PkgBuildOptions) -> Path:
        validate_build_options(options, engine=self)
        Path(options.output_folder).mkdir(parents=True, exist_ok=True)
        if options.backup_mode:
            return self.convert_backup(options)
        source_b = str(Path(options.source_folder).resolve()).encode("utf-8")
        output_b = str(Path(options.output_folder).resolve()).encode("utf-8")
        content_b = options.content_id.strip().upper().encode("utf-8")
        passcode_b = options.passcode.encode("utf-8") if options.passcode else b""
        title_b = options.title.strip().encode("utf-8")
        title_id_b = options.title_id.strip().upper().encode("utf-8")
        version_b = options.version.strip().encode("utf-8")
        drm_b = options.application_drm_type.strip().encode("utf-8") if options.application_drm_type else None

        native = _LppBuildOptions()
        native.struct_size = ctypes.sizeof(_LppBuildOptions)
        native.mode = int(options.mode)
        native.output_format = int(options.output_format)
        native.inner_compression = 3
        native.application_type = int(options.application_type)
        native.content_badge_type = -1
        native.generate_param_json = int(bool(options.generate_param_json))
        native.compress_inner_image = 0
        native.fake_sign_self = int(bool(options.fake_sign_self or options.license_free))
        native.has_authority_id = 0
        native.app_version = 0
        native.firmware_version = 0
        native.authority_id = 0
        native.source_folder = source_b
        native.output_folder = output_b
        native.content_id = content_b
        native.passcode = passcode_b
        native.title = title_b
        native.title_id = title_id_b
        native.version = version_b
        native.application_drm_type = drm_b
        native.license_free = int(bool(options.license_free))

        out_buf = ctypes.create_string_buffer(16384)
        rc = int(self.lib.lpp_build_package_ex(ctypes.byref(native), out_buf, len(out_buf)))
        if rc != 0:
            raise ProsperoError(self._last_error())
        raw_path = out_buf.value.decode("utf-8", "replace").strip()
        if not raw_path:
            raise ProsperoError("LibProsperoPkg terminó sin devolver la ruta del PKG.")
        return Path(raw_path)

    def convert_backup(self, options: PkgBuildOptions) -> Path:
        source_b = str(Path(options.source_folder).resolve()).encode("utf-8")
        output_b = str(Path(options.output_folder).resolve()).encode("utf-8")
        content_b = options.content_id.strip().upper().encode("utf-8") if options.content_id.strip() else None
        passcode_b = options.passcode.encode("utf-8") if options.passcode else None
        version_b = options.version.strip().encode("utf-8") if options.version.strip() else None
        substituted = ctypes.c_int(0)
        out_buf = ctypes.create_string_buffer(16384)
        rc = int(self.lib.lpp_convert_backup(source_b, output_b, content_b, passcode_b, version_b, ctypes.byref(substituted), out_buf, len(out_buf)))
        if rc != 0:
            raise ProsperoError(self._last_error())
        raw_path = out_buf.value.decode("utf-8", "replace").strip()
        if not raw_path:
            raise ProsperoError("LibProsperoPkg terminó sin devolver la ruta del PKG convertido.")
        return Path(raw_path)


def validate_build_options(options: PkgBuildOptions, engine: ProsperoPkgEngine | None = None) -> None:
    source = Path(options.source_folder)
    output_text = str(options.output_folder).strip()
    if not source.is_dir():
        raise ProsperoError("La carpeta de origen no existe.")
    if not output_text:
        raise ProsperoError("Selecciona una carpeta de salida.")
    title_id = options.title_id.strip().upper()
    content_id = options.content_id.strip().upper()
    if options.passcode and len(options.passcode) != 32:
        raise ProsperoError("El passcode debe tener 32 caracteres o quedar vacío para usar ceros.")

    if options.backup_mode:
        if content_id:
            content_ok = engine.valid_content_id(content_id) if engine else bool(_CONTENT_ID_RE.fullmatch(content_id))
            if not content_ok:
                raise ProsperoError("Content ID inválido para la conversión de backup.")
        if options.version.strip() and not _VERSION_RE.fullmatch(options.version.strip()):
            raise ProsperoError("La versión debe tener el formato NN.NN, por ejemplo 01.00.")
        return

    if engine:
        title_ok = engine.valid_title_id(title_id)
        content_ok = engine.valid_content_id(content_id)
    else:
        title_ok = bool(_TITLE_ID_RE.fullmatch(title_id))
        content_ok = bool(_CONTENT_ID_RE.fullmatch(content_id))
    if not title_ok:
        raise ProsperoError("Title ID inválido. Debe tener el formato PPSA12345.")
    if not content_ok:
        raise ProsperoError("Content ID inválido. Debe tener 36 caracteres, por ejemplo UP9000-PPSA00000_00-PROSPERO00000000.")
    if not _VERSION_RE.fullmatch(options.version.strip()):
        raise ProsperoError("La versión debe tener el formato NN.NN, por ejemplo 01.00.")
    if not options.title.strip():
        raise ProsperoError("El título no puede quedar vacío.")
    if not (source / "sce_sys").is_dir() and not options.generate_param_json:
        raise ProsperoError("La carpeta no contiene sce_sys y la generación de param.json está desactivada.")
