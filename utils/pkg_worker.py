import traceback

from PySide6.QtCore import QThread, Signal

from core.pkg_engine import (
    PkgBuildOptions,
    run_pkg_build,
    run_pkg_extract,
    run_pkg_verify,
)


class _CancellablePkgWorker(QThread):
    log_updated = Signal(str)
    status_updated = Signal(str)
    progress_updated = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
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


class PkgBuildWorker(_CancellablePkgWorker):
    build_finished = Signal(bool, str, str)  # ok, output_path, message

    def __init__(self, options: PkgBuildOptions, parent=None):
        super().__init__(parent)
        self.options = options

    def run(self):
        try:
            self.status_updated.emit("Building PKG with Packizard PKG Engine…")
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


class PkgVerifyWorker(_CancellablePkgWorker):
    operation_finished = Signal(bool, str, str)

    def __init__(self, package_path: str, expected_content_id: str = "", parent=None):
        super().__init__(parent)
        self.package_path = package_path
        self.expected_content_id = expected_content_id

    def run(self):
        try:
            self.status_updated.emit("Verifying PKG…")
            self.progress_updated.emit(10)
            output = run_pkg_verify(
                self.package_path,
                expected_content_id=self.expected_content_id,
                log_callback=self.log_updated.emit,
                cancel_check=lambda: self._cancelled,
                process_callback=self._set_process,
            )
            if self._cancelled:
                self.operation_finished.emit(False, "", "Cancelled by user.")
                return
            self.progress_updated.emit(100)
            self.operation_finished.emit(True, str(output), "PKG verification passed.")
        except Exception:  # noqa: BLE001
            self.operation_finished.emit(False, "", traceback.format_exc())


class PkgExtractWorker(_CancellablePkgWorker):
    operation_finished = Signal(bool, str, str)

    def __init__(self, package_path: str, output_directory: str, passcode: str, parent=None):
        super().__init__(parent)
        self.package_path = package_path
        self.output_directory = output_directory
        self.passcode = passcode

    def run(self):
        try:
            self.status_updated.emit("Extracting PKG…")
            self.progress_updated.emit(10)
            output = run_pkg_extract(
                self.package_path,
                self.output_directory,
                self.passcode,
                log_callback=self.log_updated.emit,
                cancel_check=lambda: self._cancelled,
                process_callback=self._set_process,
            )
            if self._cancelled:
                self.operation_finished.emit(False, "", "Cancelled by user.")
                return
            self.progress_updated.emit(100)
            self.operation_finished.emit(True, str(output), f"PKG extracted to: {output}")
        except Exception:  # noqa: BLE001
            self.operation_finished.emit(False, "", traceback.format_exc())
