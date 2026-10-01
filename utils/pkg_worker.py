import traceback

from PySide6.QtCore import QThread, Signal

from core.pkg_engine import PkgBuildOptions, run_pkg_build


class PkgBuildWorker(QThread):
    log_updated = Signal(str)
    status_updated = Signal(str)
    progress_updated = Signal(int)
    build_finished = Signal(bool, str, str)  # ok, output_path, message

    def __init__(self, options: PkgBuildOptions, parent=None):
        super().__init__(parent)
        self.options = options
        self._cancelled = False
        self._active_process = None

    def cancel(self):
        self._cancelled = True
        process = self._active_process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def _set_process(self, process):
        self._active_process = process
        if process is not None and self._cancelled and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def run(self):
        try:
            self.status_updated.emit("Building PKG with integrated LibProsperoPKG engine…")
            self.progress_updated.emit(5)
            output, warnings = run_pkg_build(
                self.options,
                log_callback=self.log_updated.emit,
                cancel_check=lambda: self._cancelled,
                process_callback=self._set_process,
            )
            if self._cancelled:
                self.build_finished.emit(False, "", "Cancelled by user.")
                return
            self.progress_updated.emit(100)
            message = f"PKG created: {output}"
            if warnings:
                message += f" ({len(warnings)} warning(s))"
            self.build_finished.emit(True, str(output), message)
        except Exception:  # noqa: BLE001 - worker boundary must surface the complete failure
            self.build_finished.emit(False, "", traceback.format_exc())
