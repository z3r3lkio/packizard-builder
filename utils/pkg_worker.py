from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core.prospero_pkg import PkgBuildOptions, ProsperoPkgEngine


class PkgBuildWorker(QThread):
    progress_updated = Signal(int)
    status_updated = Signal(str)
    log_updated = Signal(str)
    build_finished = Signal(bool, str, str)

    def __init__(self, options: PkgBuildOptions, parent=None):
        super().__init__(parent)
        self.options = options

    def run(self):
        try:
            self.status_updated.emit("Cargando motor PKG…")
            self.progress_updated.emit(5)
            engine = ProsperoPkgEngine()
            self.log_updated.emit(
                f"[PKG] Motor: {engine.version} | ABI 7 | claves: "
                + ("disponibles" if engine.keys_available else "no disponibles")
            )
            self.status_updated.emit("Construyendo PKG…")
            self.progress_updated.emit(15)
            output = engine.build(self.options)
            self.progress_updated.emit(100)
            self.status_updated.emit("PKG completado")
            self.log_updated.emit(f"[PKG] Creado: {output}")
            self.build_finished.emit(True, "PKG creado correctamente.", str(output))
        except Exception as exc:
            self.progress_updated.emit(0)
            self.status_updated.emit("Error")
            self.log_updated.emit(f"[PKG][ERROR] {type(exc).__name__}: {exc}")
            self.build_finished.emit(False, str(exc), "")
