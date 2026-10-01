from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
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
from utils.pkg_worker import PkgBuildWorker


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
    """Packizard's integrated PKG builder UI."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.source_path: Path | None = None
        self.output_dir: Path | None = None
        self.worker: PkgBuildWorker | None = None
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
            "Construye el PKG directamente dentro de Packizard. "
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
            "Source",
            "Selecciona la carpeta preparada que contiene sce_sys/. Para comprimir y empaquetar en un solo paso usa el tick de la página Compress.",
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
            "Opciones del motor PKG integrado de Packizard.",
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
        self.verify_cb.setToolTip("Valida estructuralmente el paquete al terminar y detiene la construcción si detecta errores.")
        options.add_row("Verification", self.verify_cb)
        layout.addWidget(options)

        run_card = SectionCard(
            "Build",
            "El trabajo se ejecuta mediante el motor PKG integrado de Packizard; el log aparece aquí y puede cancelarse.",
        )
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(150)
        self.log_output.setPlaceholderText("PKG build log")
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
        self._responsive_cards = [source, metadata, options, run_card]

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 760
        for card in self._responsive_cards:
            card.set_compact(compact)

    def refresh_engine_status(self):
        try:
            info = probe_pkg_engine()
        except PkgEngineError as exc:
            info = None
            self.status_label.setText(str(exc))
        if info:
            keys = "keys available" if info.keys_available else "key material unavailable"
            self.engine_badge.setText(f"Packizard PKG Engine v{info.engine_version} · integrated")
            self.engine_badge.setToolTip(f"Motor PKG integrado de Packizard\n{keys}")
            self.engine_badge.setProperty("warning", not bool(info.keys_available))
            self.build_btn.setEnabled(bool(info.keys_available))
        else:
            self.engine_badge.setText(f"Packizard PKG Engine v{ENGINE_VERSION} · bridge missing")
            self.engine_badge.setProperty("warning", True)
            self.build_btn.setEnabled(False)
            if self.worker is None:
                self.status_label.setText(
                    "Integrated PKG bridge is not present in this development/source run. Packaged releases include it."
                )
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

    def _source_from_text(self):
        text = self.source_edit.text().strip()
        if text:
            self.set_source(Path(text), warn=False)

    def _output_from_text(self):
        text = self.output_edit.text().strip()
        if text:
            self.output_dir = Path(text).expanduser()

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

    def _build(self):
        if self.worker is not None and self.worker.isRunning():
            return
        try:
            options = self.build_options()
            options.validate()
        except PkgEngineError as exc:
            QMessageBox.warning(self, "Cannot build PKG", str(exc))
            return

        self.log_output.clear()
        self.progress.setValue(0)
        self.status_label.setText("Queued…")
        worker = PkgBuildWorker(options, self)
        worker.log_updated.connect(self.log_output.appendPlainText)
        worker.status_updated.connect(self.status_label.setText)
        worker.progress_updated.connect(self.progress.setValue)
        worker.build_finished.connect(self._finished)
        worker.finished.connect(worker.deleteLater)
        self.worker = worker
        self.build_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        worker.start()

    def _cancel(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.status_label.setText("Cancelling…")

    def _finished(self, ok: bool, output_path: str, message: str):
        self.cancel_btn.setVisible(False)
        self.worker = None
        self.refresh_engine_status()
        if ok:
            self.progress.setValue(100)
            self.status_label.setText(message)
            self.log_output.appendPlainText(f"Output: {output_path}")
        elif "cancel" in message.casefold():
            self.progress.setValue(0)
            self.status_label.setText("Cancelled")
        else:
            self.status_label.setText("PKG build failed. See log for details.")
            self.log_output.appendPlainText(message)
            QMessageBox.critical(self, "PKG build failed", message.splitlines()[-1] if message else "Unknown error")
