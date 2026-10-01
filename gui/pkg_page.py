from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.param_parser import parse_game_info
from core.pkg_engine import (
    ENGINE_VERSION,
    PkgBuildOptions,
    PkgEngineError,
    probe_pkg_engine,
)
from gui.widgets import AnimatedButton, CenteredComboBox, SectionCard, StatusBadge
from utils.pkg_worker import PkgBuildWorker, PkgExtractWorker, PkgVerifyWorker


PACKAGE_MODES = ("Application", "Homebrew", "AdditionalContentData", "AdditionalContentNoData")
OUTPUT_FORMATS = ("DebugImage", "MetadataContainer")
APPLICATION_TYPES = (
    "NotSpecified",
    "PaidStandaloneFullApp",
    "UpgradableApp",
    "DemoApp",
    "FreemiumApp",
)
DRM_TYPES = ("standard", "free", "freemium", "Auto")


def _pkg_version(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "01.00"
    parts = text.split(".")
    if len(parts) >= 2 and all(part.isdigit() for part in parts[:2]):
        return f"{int(parts[0]):02d}.{int(parts[1]):02d}"
    return text


class PkgPage(QWidget):
    """Packizard's integrated PKG build, verify and extraction UI."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.source_path: Path | None = None
        self.output_dir: Path | None = None
        self.existing_pkg_path: Path | None = None
        self.extract_dir: Path | None = None
        self.last_result_dir: Path | None = None
        self.worker: PkgBuildWorker | None = None
        self.tool_worker: PkgVerifyWorker | PkgExtractWorker | None = None
        self.engine_available = False
        self.keys_available = False
        self._init_ui()
        self.refresh_engine_status()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("ContentBG")
        host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 4, 10)
        layout.setSpacing(14)

        header = QHBoxLayout()
        text = QVBoxLayout()
        title = QLabel("Build PKG")
        title.setObjectName("Header")
        subtitle = QLabel(
            "Construye, verifica y extrae paquetes directamente dentro de Packizard. "
            "No se abre ninguna aplicación externa."
        )
        subtitle.setObjectName("SubHeader")
        subtitle.setWordWrap(True)
        text.addWidget(title)
        text.addWidget(subtitle)
        header.addLayout(text, 1)
        self.engine_badge = StatusBadge(f"Packizard PKG Engine v{ENGINE_VERSION}", icon="package")
        header.addWidget(self.engine_badge, 0, Qt.AlignTop)
        layout.addLayout(header)

        source = SectionCard(
            "Build paths",
            "Selecciona la carpeta preparada que contiene sce_sys/ y la carpeta de salida del paquete.",
            label_width=150,
        )
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Carpeta preparada para el paquete")
        self.source_edit.editingFinished.connect(self._source_from_text)
        source_btn = AnimatedButton("Examinar", "secondary", icon="folder")
        source_btn.clicked.connect(self._browse_source)
        source.add_row("Source folder", self.source_edit, source_btn)

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Carpeta para el .pkg")
        self.output_edit.editingFinished.connect(self._output_from_text)
        output_btn = AnimatedButton("Examinar", "secondary", icon="folder")
        output_btn.clicked.connect(self._browse_output)
        source.add_row("Output folder", self.output_edit, output_btn)
        layout.addWidget(source)

        existing = SectionCard(
            "Existing PKG tools",
            "Selecciona un PKG existente para validarlo o extraerlo. La extracción usa el Passcode indicado en Package metadata.",
            label_width=150,
        )
        self.existing_pkg_edit = QLineEdit()
        self.existing_pkg_edit.setPlaceholderText("Archivo .pkg existente")
        self.existing_pkg_edit.editingFinished.connect(self._existing_pkg_from_text)
        existing_btn = AnimatedButton("Examinar", "secondary", icon="folder")
        existing_btn.clicked.connect(self._browse_existing_pkg)
        existing.add_row("PKG file", self.existing_pkg_edit, existing_btn)

        self.extract_edit = QLineEdit()
        self.extract_edit.setPlaceholderText("Carpeta de extracción")
        self.extract_edit.editingFinished.connect(self._extract_from_text)
        extract_dir_btn = AnimatedButton("Examinar", "secondary", icon="folder")
        extract_dir_btn.clicked.connect(self._browse_extract_dir)
        existing.add_row("Extraction folder", self.extract_edit, extract_dir_btn)

        tool_buttons = QWidget()
        tool_buttons_l = QHBoxLayout(tool_buttons)
        tool_buttons_l.setContentsMargins(0, 0, 0, 0)
        tool_buttons_l.setSpacing(8)
        tool_buttons_l.addStretch(1)
        self.verify_existing_btn = AnimatedButton("Verify PKG", "secondary")
        self.verify_existing_btn.clicked.connect(self._verify_existing)
        tool_buttons_l.addWidget(self.verify_existing_btn)
        self.extract_existing_btn = AnimatedButton("Extract PKG", "secondary")
        self.extract_existing_btn.clicked.connect(self._extract_existing)
        tool_buttons_l.addWidget(self.extract_existing_btn)
        self.open_result_btn = AnimatedButton("Open result folder", "secondary", icon="folder")
        self.open_result_btn.clicked.connect(self._open_result_folder)
        tool_buttons_l.addWidget(self.open_result_btn)
        existing.add_widget(tool_buttons)
        layout.addWidget(existing)

        metadata = SectionCard(
            "Package metadata",
            "Los valores se rellenan desde sce_sys/param.json cuando es posible y se pueden editar antes de construir.",
            label_width=150,
        )
        self.title_edit = QLineEdit()
        metadata.add_row("Title", self.title_edit)
        self.title_id_edit = QLineEdit()
        self.title_id_edit.setPlaceholderText("PPSA00000")
        metadata.add_row("Title ID", self.title_id_edit)
        self.content_id_edit = QLineEdit()
        self.content_id_edit.setPlaceholderText("UP9000-PPSA00000_00-PROSPERO00000000")
        metadata.add_row("Content ID", self.content_id_edit)
        self.version_edit = QLineEdit("01.00")
        metadata.add_row("Version", self.version_edit)
        self.passcode_edit = QLineEdit("0" * 32)
        self.passcode_edit.setMaxLength(32)
        metadata.add_row("Passcode", self.passcode_edit)
        layout.addWidget(metadata)

        options = SectionCard(
            "Build options",
            "Opciones reales expuestas por el motor PKG integrado de Packizard.",
            label_width=180,
        )
        self.mode_combo = CenteredComboBox()
        self.mode_combo.addItems(PACKAGE_MODES)
        options.add_row("Package mode", self.mode_combo)

        self.format_combo = CenteredComboBox()
        self.format_combo.addItems(OUTPUT_FORMATS)
        options.add_row("Output format", self.format_combo)

        self.app_type_combo = CenteredComboBox()
        self.app_type_combo.addItems(APPLICATION_TYPES)
        options.add_row("Application type", self.app_type_combo)

        self.drm_combo = CenteredComboBox()
        self.drm_combo.addItems(DRM_TYPES)
        options.add_row("DRM metadata", self.drm_combo)

        self.generate_param_cb = QCheckBox("Generate param.json when missing")
        self.generate_param_cb.setChecked(True)
        options.add_row("Metadata", self.generate_param_cb)

        self.fake_sign_cb = QCheckBox("Fake-sign raw ELF/PRX/SPRX modules")
        self.fake_sign_cb.setChecked(True)
        options.add_row("Executable modules", self.fake_sign_cb)

        self.license_free_cb = QCheckBox("License-free debug package")
        self.license_free_cb.setChecked(False)
        options.add_row("License", self.license_free_cb)

        self.verify_cb = QCheckBox("Verify package after build")
        self.verify_cb.setChecked(True)
        self.verify_cb.setToolTip("Valida formato e integridad estructural al terminar y detiene la construcción si detecta errores.")
        options.add_row("Verification", self.verify_cb)
        layout.addWidget(options)

        run_card = SectionCard(
            "Build and log",
            "Las operaciones se ejecutan mediante el motor PKG integrado de Packizard y pueden cancelarse.",
        )
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(170)
        self.log_output.setPlaceholderText("PKG operation log")
        run_card.add_widget(self.log_output)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        run_card.add_widget(self.progress)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("SubHeader")
        self.status_label.setWordWrap(True)
        run_card.add_widget(self.status_label)

        buttons = QWidget()
        buttons_l = QHBoxLayout(buttons)
        buttons_l.setContentsMargins(0, 0, 0, 0)
        buttons_l.setSpacing(8)
        self.clear_log_btn = AnimatedButton("Clear log", "secondary")
        self.clear_log_btn.clicked.connect(self.log_output.clear)
        buttons_l.addWidget(self.clear_log_btn)
        buttons_l.addStretch(1)
        self.cancel_btn = AnimatedButton("Cancel", "secondary", icon="stop")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel)
        buttons_l.addWidget(self.cancel_btn)
        self.build_btn = AnimatedButton("Build PKG", "big", icon="package")
        self.build_btn.clicked.connect(self._build)
        buttons_l.addWidget(self.build_btn)
        run_card.add_widget(buttons)
        layout.addWidget(run_card)
        layout.addStretch(1)

        self.scroll.setWidget(host)
        outer.addWidget(self.scroll)
        self._responsive_cards = [source, existing, metadata, options, run_card]
        self._refresh_action_state()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 760
        for card in self._responsive_cards:
            card.set_compact(compact)

    def _busy(self) -> bool:
        return self.worker is not None or self.tool_worker is not None

    def _refresh_action_state(self):
        busy = self._busy()
        self.build_btn.setEnabled(self.engine_available and self.keys_available and not busy)
        self.verify_existing_btn.setEnabled(self.engine_available and not busy)
        self.extract_existing_btn.setEnabled(self.engine_available and not busy)
        self.open_result_btn.setEnabled(self.last_result_dir is not None and not busy)
        self.clear_log_btn.setEnabled(not busy)
        self.cancel_btn.setVisible(busy)

    def refresh_engine_status(self):
        try:
            info = probe_pkg_engine()
        except PkgEngineError as exc:
            info = None
            self.status_label.setText(str(exc))
        self.engine_available = bool(info)
        self.keys_available = bool(info and info.keys_available)
        if info:
            keys = "keys available" if info.keys_available else "key material unavailable"
            self.engine_badge.setText(f"Packizard PKG Engine v{info.engine_version} · integrated")
            self.engine_badge.setToolTip(f"Motor PKG integrado de Packizard\n{keys}")
            self.engine_badge.setProperty("warning", not bool(info.keys_available))
        else:
            self.engine_badge.setText(f"Packizard PKG Engine v{ENGINE_VERSION} · bridge missing")
            self.engine_badge.setProperty("warning", True)
            if not self._busy():
                self.status_label.setText(
                    "Integrated PKG bridge is not present in this development/source run. Packaged releases include it."
                )
        self._refresh_action_state()
        self.engine_badge.style().unpolish(self.engine_badge)
        self.engine_badge.style().polish(self.engine_badge)

    def _browse_source(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta preparada")
        if folder:
            self.set_source(Path(folder))

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de salida")
        if folder:
            self.set_output(Path(folder))

    def _browse_existing_pkg(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Seleccionar PKG", "", "PKG files (*.pkg);;All files (*)")
        if filename:
            self.set_existing_pkg(Path(filename))

    def _browse_extract_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de extracción")
        if folder:
            self.set_extract_dir(Path(folder))

    def _source_from_text(self):
        text = self.source_edit.text().strip()
        if text:
            self.set_source(Path(text), warn=False)

    def _output_from_text(self):
        text = self.output_edit.text().strip()
        if text:
            self.output_dir = Path(text).expanduser()

    def _existing_pkg_from_text(self):
        text = self.existing_pkg_edit.text().strip()
        self.existing_pkg_path = Path(text).expanduser() if text else None

    def _extract_from_text(self):
        text = self.extract_edit.text().strip()
        self.extract_dir = Path(text).expanduser() if text else None

    def set_source(self, path: Path, *, warn: bool = True):
        path = Path(path).expanduser()
        if not path.is_dir():
            if warn:
                QMessageBox.warning(self, "Invalid source", "Select an existing package source folder.")
            return
        self.source_path = path.resolve()
        self.source_edit.setText(str(self.source_path))
        if not self.output_dir:
            self.set_output(self.source_path.parent / "Packizard_PKG")
        self._refresh_metadata()

    def set_output(self, path: Path):
        self.output_dir = Path(path).expanduser()
        self.output_edit.setText(str(self.output_dir))

    def set_existing_pkg(self, path: Path):
        self.existing_pkg_path = Path(path).expanduser()
        self.existing_pkg_edit.setText(str(self.existing_pkg_path))
        if not self.extract_dir:
            self.set_extract_dir(self.existing_pkg_path.with_name(self.existing_pkg_path.stem + "-extracted"))

    def set_extract_dir(self, path: Path):
        self.extract_dir = Path(path).expanduser()
        self.extract_edit.setText(str(self.extract_dir))

    def _refresh_metadata(self):
        if not self.source_path:
            return
        info = parse_game_info(self.source_path)
        self.title_edit.setText(str(info.get("title") or ""))
        self.title_id_edit.setText(self._clean(info.get("title_id")))
        self.content_id_edit.setText(self._clean(info.get("content_id")))
        self.version_edit.setText(_pkg_version(info.get("version") or "01.00"))

    @staticmethod
    def _clean(value) -> str:
        text = str(value or "").strip()
        return "" if text.lower() == "unknown" else text

    def build_options(self, *, source_override: Path | None = None) -> PkgBuildOptions:
        source = source_override or self.source_path
        if source is None:
            raise PkgEngineError("Select a package source folder first.")
        output = self.output_dir or (source.parent / "Packizard_PKG")
        drm = self.drm_combo.currentText()
        return PkgBuildOptions(
            source_folder=str(source),
            output_folder=str(output),
            content_id=self.content_id_edit.text(),
            title_id=self.title_id_edit.text(),
            title=self.title_edit.text(),
            version=self.version_edit.text(),
            passcode=self.passcode_edit.text(),
            mode=self.mode_combo.currentText(),
            output_format=self.format_combo.currentText(),
            application_type=self.app_type_combo.currentText(),
            application_drm_type="" if drm == "Auto" else drm,
            generate_param_json_if_missing=self.generate_param_cb.isChecked(),
            fake_sign_self_modules=self.fake_sign_cb.isChecked(),
            license_free=self.license_free_cb.isChecked(),
            verify_after_build=self.verify_cb.isChecked(),
        )

    def _wire_worker(self, worker):
        worker.log_updated.connect(self.log_output.appendPlainText)
        worker.status_updated.connect(self.status_label.setText)
        worker.progress_updated.connect(self.progress.setValue)
        worker.finished.connect(worker.deleteLater)

    def _build(self):
        if self._busy():
            return
        try:
            options = self.build_options()
            options.validate()
        except PkgEngineError as exc:
            QMessageBox.warning(self, "Cannot build PKG", str(exc))
            return

        self.log_output.clear()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText("Queued…")
        worker = PkgBuildWorker(options, self)
        self._wire_worker(worker)
        worker.build_finished.connect(self._finished)
        self.worker = worker
        self._refresh_action_state()
        worker.start()

    def _selected_existing_pkg(self) -> Path | None:
        text = self.existing_pkg_edit.text().strip()
        if text:
            self.existing_pkg_path = Path(text).expanduser()
        if self.existing_pkg_path and self.existing_pkg_path.is_file():
            return self.existing_pkg_path
        QMessageBox.warning(self, "PKG required", "Select an existing .pkg file first.")
        return None

    def _verify_existing(self):
        if self._busy():
            return
        package = self._selected_existing_pkg()
        if package is None:
            return
        self.log_output.clear()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        worker = PkgVerifyWorker(str(package), parent=self)
        self._wire_worker(worker)
        worker.operation_finished.connect(self._tool_finished)
        self.tool_worker = worker
        self._refresh_action_state()
        worker.start()

    def _extract_existing(self):
        if self._busy():
            return
        package = self._selected_existing_pkg()
        if package is None:
            return
        output_text = self.extract_edit.text().strip()
        if not output_text:
            QMessageBox.warning(self, "Extraction folder required", "Select an extraction folder first.")
            return
        passcode = self.passcode_edit.text().strip() or ("0" * 32)
        if len(passcode) != 32:
            QMessageBox.warning(self, "Invalid passcode", "PKG passcode must contain exactly 32 characters.")
            return
        self.extract_dir = Path(output_text).expanduser()
        self.log_output.clear()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        worker = PkgExtractWorker(str(package), str(self.extract_dir), passcode, self)
        self._wire_worker(worker)
        worker.operation_finished.connect(self._tool_finished)
        self.tool_worker = worker
        self._refresh_action_state()
        worker.start()

    def _open_result_folder(self):
        if self.last_result_dir is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_result_dir)))

    def _cancel(self):
        worker = self.worker or self.tool_worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            self.status_label.setText("Cancelling…")

    def _finished(self, ok: bool, output_path: str, message: str):
        self.worker = None
        if ok:
            self.progress.setValue(100)
            self.status_label.setText(message)
            self.log_output.appendPlainText(f"Output: {output_path}")
            if output_path:
                built = Path(output_path)
                self.set_existing_pkg(built)
                self.last_result_dir = built.parent
        elif "cancel" in message.casefold():
            self.progress.setValue(0)
            self.status_label.setText("Cancelled")
        else:
            self.status_label.setText("PKG build failed. See log for details.")
            self.log_output.appendPlainText(message)
            QMessageBox.critical(self, "PKG build failed", message.splitlines()[-1] if message else "Unknown error")
        self.refresh_engine_status()

    def _tool_finished(self, ok: bool, output_path: str, message: str):
        worker = self.tool_worker
        self.tool_worker = None
        if ok:
            self.progress.setValue(100)
            self.status_label.setText(message)
            if output_path:
                result = Path(output_path)
                self.last_result_dir = result if result.is_dir() else result.parent
                self.log_output.appendPlainText(f"Result: {output_path}")
        elif "cancel" in message.casefold():
            self.progress.setValue(0)
            self.status_label.setText("Cancelled")
        else:
            self.progress.setValue(0)
            self.status_label.setText("PKG operation failed. See log for details.")
            self.log_output.appendPlainText(message)
            QMessageBox.critical(self, "PKG operation failed", message.splitlines()[-1] if message else "Unknown error")
        self.refresh_engine_status()
        if worker is not None and worker.isRunning():
            pass
