from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from core.param_parser import parse_game_info
from core.prospero_pkg import (
    PkgBuildOptions, ProsperoPkgEngine, find_library, platform_key,
    validate_build_options,
)
from gui.widgets import AnimatedButton, CenteredComboBox, SectionCard, StatusBadge


class PkgPage(QWidget):
    build_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ContentBG")
        self.source_dir: Path | None = None
        self.output_dir: Path | None = None
        self._running = False
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

        header_row = QHBoxLayout()
        header_text = QVBoxLayout()
        title = QLabel("Build PKG")
        title.setObjectName("Header")
        subtitle = QLabel("Convierte una aplicación preparada o un backup descifrado en un PKG de depuración usando LibProsperoPkg.")
        subtitle.setObjectName("SubHeader")
        subtitle.setWordWrap(True)
        header_text.addWidget(title)
        header_text.addWidget(subtitle)
        header_row.addLayout(header_text, 1)
        self.engine_badge = StatusBadge("Comprobando motor…", icon="package")
        header_row.addWidget(self.engine_badge, 0, Qt.AlignTop)
        layout.addLayout(header_row)

        source = SectionCard(
            "Origen y destino",
            "Acepta una aplicación preparada o un backup descifrado. En modo backup, LibProsperoPkg sustituye ejecutables por sus ELF descifrados antes de crear el fPKG.",
            label_width=130,
        )
        self.source_kind = CenteredComboBox()
        self.source_kind.addItems(["Prepared application", "Decrypted backup"])
        self.source_kind.currentTextChanged.connect(self._source_kind_changed)
        source.add_row("Modo", self.source_kind)
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Carpeta de juego / app")
        self.source_edit.editingFinished.connect(self._source_from_text)
        source_btn = AnimatedButton("Examinar", "secondary", icon="folder")
        source_btn.clicked.connect(self._browse_source)
        source.add_row("Origen", self.source_edit, source_btn)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Carpeta donde se guardará el .pkg")
        self.output_edit.editingFinished.connect(self._output_from_text)
        output_btn = AnimatedButton("Examinar", "secondary", icon="folder")
        output_btn.clicked.connect(self._browse_output)
        source.add_row("Salida", self.output_edit, output_btn)
        layout.addWidget(source)

        metadata = SectionCard("Metadatos del paquete", "Se rellenan automáticamente desde sce_sys/param.json cuando es posible.", label_width=130)
        self.title_edit = QLineEdit(); self.title_edit.setPlaceholderText("Título visible"); metadata.add_row("Título", self.title_edit)
        self.title_id_edit = QLineEdit(); self.title_id_edit.setPlaceholderText("PPSA12345"); self.title_id_edit.setMaxLength(9); metadata.add_row("Title ID", self.title_id_edit)
        self.content_id_edit = QLineEdit(); self.content_id_edit.setPlaceholderText("UP9000-PPSA12345_00-PACKIZARD0000000"); self.content_id_edit.setMaxLength(36); metadata.add_row("Content ID", self.content_id_edit)
        self.version_edit = QLineEdit("01.00"); self.version_edit.setMaxLength(5); metadata.add_row("Versión", self.version_edit)
        self.passcode_edit = QLineEdit(); self.passcode_edit.setPlaceholderText("Vacío = 32 ceros"); self.passcode_edit.setMaxLength(32); self.passcode_edit.setEchoMode(QLineEdit.Password); metadata.add_row("Passcode", self.passcode_edit)
        layout.addWidget(metadata)

        options = SectionCard("Opciones", "License-free activa fake-sign para módulos y el modo DRM libre del paquete de depuración.", label_width=130)
        self.app_type = CenteredComboBox(); self.app_type.addItems(["Paid standalone", "Upgradable", "Demo", "Freemium", "Not specified"]); options.add_row("Tipo de app", self.app_type)
        self.generate_param = QCheckBox("Generar param.json si falta"); self.generate_param.setChecked(True); options.add_row("Metadata", self.generate_param)
        self.fake_sign = QCheckBox("Fake-sign de ELF/PRX sin firmar"); options.add_row("Módulos", self.fake_sign)
        self.license_free = QCheckBox("Crear paquete debug/license-free"); self.license_free.toggled.connect(self._license_free_changed); options.add_row("Licencia", self.license_free)
        layout.addWidget(options)

        run = SectionCard("Construcción", "La operación puede tardar varios minutos con juegos grandes.")
        self.status_label = QLabel("Listo"); self.status_label.setObjectName("SubHeader")
        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        run.add_widget(self.status_label); run.add_widget(self.progress)
        buttons = QWidget(); buttons_l = QHBoxLayout(buttons); buttons_l.setContentsMargins(0, 0, 0, 0); buttons_l.addStretch(1)
        self.build_btn = AnimatedButton("Build PKG", "big", icon="package"); self.build_btn.clicked.connect(self._request_build); buttons_l.addWidget(self.build_btn)
        run.add_widget(buttons); layout.addWidget(run); layout.addStretch(1)
        self.scroll.setWidget(host); outer.addWidget(self.scroll)
        self._responsive_cards = [source, metadata, options, run]

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for card in self._responsive_cards:
            card.set_compact(self.width() < 760)

    def refresh_engine_status(self):
        lib = find_library()
        if not lib:
            self.engine_badge.setText(f"Motor PKG no instalado · {platform_key()}")
            self.engine_badge.setProperty("warning", True)
        else:
            try:
                engine = ProsperoPkgEngine(lib)
                keys = "keys OK" if engine.keys_available else "sin publishing keys"
                self.engine_badge.setText(f"{engine.version} · {keys}")
                self.engine_badge.setProperty("warning", False)
            except Exception as exc:
                self.engine_badge.setText(f"Motor PKG incompatible · {exc}")
                self.engine_badge.setProperty("warning", True)
        self.engine_badge.style().unpolish(self.engine_badge); self.engine_badge.style().polish(self.engine_badge)

    def _browse_source(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de origen")
        if folder: self.set_source(Path(folder))

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de salida")
        if folder: self.set_output(Path(folder))

    def _source_from_text(self):
        text = self.source_edit.text().strip()
        if text: self.set_source(Path(text))

    def _output_from_text(self):
        text = self.output_edit.text().strip()
        if text: self.output_dir = Path(text).expanduser()

    def set_source(self, path: Path):
        path = Path(path).expanduser()
        if not path.is_dir():
            QMessageBox.warning(self, "Origen inválido", "La carpeta seleccionada no existe."); return
        self.source_dir = path; self.source_edit.setText(str(path))
        if not self.output_dir: self.set_output(path.parent / "Packizard_PKG")
        info = parse_game_info(path)
        if info.get("title"): self.title_edit.setText(str(info["title"]))
        title_id = str(info.get("title_id") or "")
        if title_id and title_id != "Unknown": self.title_id_edit.setText(title_id.upper())
        content_id = str(info.get("content_id") or "")
        if content_id and content_id != "Unknown": self.content_id_edit.setText(content_id.upper())
        version = str(info.get("version") or "")
        if version and len(version.split(".")) == 2:
            a, b = version.split(".", 1)
            self.version_edit.setText(f"{int(a):02d}.{int(b):02d}" if a.isdigit() and b.isdigit() else version)

    def set_output(self, path: Path):
        self.output_dir = Path(path).expanduser(); self.output_edit.setText(str(self.output_dir))

    def _source_kind_changed(self, text: str):
        backup = text == "Decrypted backup"
        self.title_edit.setEnabled((not backup) and (not self._running)); self.title_id_edit.setEnabled((not backup) and (not self._running))
        self.app_type.setEnabled((not backup) and (not self._running)); self.generate_param.setEnabled((not backup) and (not self._running))
        self.fake_sign.setEnabled((not backup) and (not self._running) and (not self.license_free.isChecked())); self.license_free.setEnabled((not backup) and (not self._running))
        self.status_label.setText("Backup: Content ID y versión pueden heredarse de param.json" if backup else "Listo")

    def _license_free_changed(self, checked):
        if checked:
            self.fake_sign.setChecked(True); self.fake_sign.setEnabled(False)
        else:
            self.fake_sign.setEnabled(True)

    def _application_type_value(self) -> int:
        return {"Paid standalone": 1, "Upgradable": 2, "Demo": 3, "Freemium": 4, "Not specified": 0}.get(self.app_type.currentText(), 1)

    def build_options(self) -> PkgBuildOptions:
        source_text = self.source_edit.text().strip(); output_text = self.output_edit.text().strip()
        if not source_text: raise ValueError("Selecciona una carpeta de origen.")
        if not output_text: raise ValueError("Selecciona una carpeta de salida.")
        return PkgBuildOptions(
            source_folder=self.source_dir or Path(source_text).expanduser(), output_folder=self.output_dir or Path(output_text).expanduser(),
            content_id=self.content_id_edit.text().strip(), title_id=self.title_id_edit.text().strip(), title=self.title_edit.text().strip(),
            version=self.version_edit.text().strip() or "01.00", passcode=self.passcode_edit.text(), application_type=self._application_type_value(),
            generate_param_json=self.generate_param.isChecked(), fake_sign_self=self.fake_sign.isChecked(), license_free=self.license_free.isChecked(),
            backup_mode=self.source_kind.currentText() == "Decrypted backup",
        )

    def _request_build(self):
        if self._running: return
        try:
            options = self.build_options(); validate_build_options(options)
        except Exception as exc:
            QMessageBox.warning(self, "Datos incompletos", str(exc)); return
        self.build_requested.emit(options)

    def set_running_state(self, running: bool):
        self._running = bool(running); self.build_btn.setEnabled(not running)
        for widget in (self.source_kind, self.source_edit, self.output_edit, self.content_id_edit, self.version_edit, self.passcode_edit): widget.setEnabled(not running)
        backup = self.source_kind.currentText() == "Decrypted backup"
        for widget in (self.title_edit, self.title_id_edit, self.app_type, self.generate_param, self.license_free): widget.setEnabled((not running) and (not backup))
        self.fake_sign.setEnabled((not running) and (not backup) and (not self.license_free.isChecked()))

    def set_progress(self, value: int): self.progress.setValue(max(0, min(100, int(value))))
    def set_status(self, text: str): self.status_label.setText(text)
    def set_error(self, text: str): self.status_label.setText(text); self.status_label.setProperty("error", True); self.status_label.style().unpolish(self.status_label); self.status_label.style().polish(self.status_label)
    def set_success(self, output_path: str): self.status_label.setProperty("error", False); self.status_label.setText(f"Completado: {output_path}"); self.status_label.style().unpolish(self.status_label); self.status_label.style().polish(self.status_label)
