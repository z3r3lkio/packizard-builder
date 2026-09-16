from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.param_parser import parse_game_info
from core.ppr_pkg_builder import (
    PprPkgBuilderError,
    find_ppr_pkg_builder,
    launch_ppr_pkg_builder,
)
from gui.widgets import AnimatedButton, CenteredComboBox, SectionCard, StatusBadge


class PkgPage(QWidget):
    """Launcher/integration page for the official PPR-PKG Builder application.

    Packizard deliberately does not call LibProsperoPkg's native ABI as a fallback:
    the PKG is created by the external PPR-PKG Builder selected by the user.
    """

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.setObjectName("ContentBG")
        self.source_path: Path | None = None
        self.output_dir: Path | None = None
        self._init_ui()
        configured = self.state.settings.get("ppr_pkg_builder_path", "")
        if configured:
            self.tool_edit.setText(configured)
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
        title = QLabel("Convert to PKG")
        title.setObjectName("Header")
        subtitle = QLabel(
            "La creación del PKG se realiza exclusivamente con PPR-PKG Builder, "
            "la aplicación de Drakmor & SvenGDK mostrada en la referencia."
        )
        subtitle.setObjectName("SubHeader")
        subtitle.setWordWrap(True)
        header_text.addWidget(title)
        header_text.addWidget(subtitle)
        header_row.addLayout(header_text, 1)
        self.engine_badge = StatusBadge("Buscando PPR-PKG Builder…", icon="package")
        header_row.addWidget(self.engine_badge, 0, Qt.AlignTop)
        layout.addLayout(header_row)

        tool = SectionCard(
            "PPR-PKG Builder",
            "Selecciona la aplicación exacta que quieres usar. Packizard no sustituye este motor, "
            "no usa LibProsperoPkg directamente y no cambia a otro builder si falta.",
            label_width=145,
        )
        self.tool_edit = QLineEdit()
        self.tool_edit.setPlaceholderText("LibProsperoPkg.Gui.exe / PPR-PKG Builder.exe")
        self.tool_edit.editingFinished.connect(self._tool_from_text)
        choose_tool = AnimatedButton("Seleccionar", "secondary", icon="folder")
        choose_tool.clicked.connect(self._browse_tool)
        tool.add_row("Aplicación", self.tool_edit, choose_tool)
        tool_note = QLabel(
            "La captura corresponde a “LibProsperoPKG v0.6.7 — package tool”. "
            "El ejecutable no se redistribuye dentro de Packizard: debes seleccionar tu copia de esa herramienta."
        )
        tool_note.setObjectName("SubHeader")
        tool_note.setWordWrap(True)
        tool.add_widget(tool_note)
        layout.addWidget(tool)

        source = SectionCard(
            "Origen y salida",
            "PPR-PKG Builder admite una carpeta o proyecto GP5. Packizard conserva estas rutas y puede "
            "copiarlas al portapapeles para pegarlas en la aplicación externa.",
            label_width=145,
        )
        self.source_kind = CenteredComboBox()
        self.source_kind.addItems(["Folder", "GP5 project"])
        self.source_kind.currentTextChanged.connect(self._source_kind_changed)
        source.add_row("Source", self.source_kind)
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Carpeta del juego / proyecto .gp5")
        self.source_edit.editingFinished.connect(self._source_from_text)
        source_btn = AnimatedButton("Examinar", "secondary", icon="folder")
        source_btn.clicked.connect(self._browse_source)
        copy_source = AnimatedButton("Copiar", "ghost", icon="doc")
        copy_source.clicked.connect(lambda: self._copy_path(self.source_edit.text(), "Origen copiado"))
        source.add_row("Origen", self.source_edit, source_btn, copy_source)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Carpeta donde PPR-PKG Builder guardará el .pkg")
        self.output_edit.editingFinished.connect(self._output_from_text)
        output_btn = AnimatedButton("Examinar", "secondary", icon="folder")
        output_btn.clicked.connect(self._browse_output)
        copy_output = AnimatedButton("Copiar", "ghost", icon="doc")
        copy_output.clicked.connect(lambda: self._copy_path(self.output_edit.text(), "Salida copiada"))
        source.add_row("Output folder", self.output_edit, output_btn, copy_output)
        layout.addWidget(source)

        metadata = SectionCard(
            "Metadatos detectados",
            "Vista previa leída desde param.json. PPR-PKG Builder seguirá siendo quien lea/valide "
            "los datos y construya el paquete.",
            label_width=145,
        )
        self.title_edit = self._readonly_line("—")
        metadata.add_row("Title", self.title_edit)
        self.title_id_edit = self._readonly_line("—")
        metadata.add_row("Title ID", self.title_id_edit)
        self.content_id_edit = self._readonly_line("—")
        metadata.add_row("Content ID", self.content_id_edit)
        self.version_edit = self._readonly_line("—")
        metadata.add_row("Version", self.version_edit)
        self.sdk_edit = self._readonly_line("—")
        metadata.add_row("SDK", self.sdk_edit)
        layout.addWidget(metadata)

        workflow = SectionCard(
            "Abrir herramienta",
            "Packizard abre PPR-PKG Builder en su propia carpeta de trabajo, sin flags no documentados. "
            "Si hay un origen seleccionado, su ruta se copia al portapapeles. Completa dentro de PPR-PKG Builder "
            "las opciones de la captura (DRM, SDK, image mode, PFS, Kraken, PlayGo, libScePubTools.dll, etc.) "
            "y pulsa Build PKG allí.",
        )
        self.status_label = QLabel("Listo")
        self.status_label.setObjectName("SubHeader")
        self.status_label.setWordWrap(True)
        workflow.add_widget(self.status_label)
        buttons = QWidget()
        buttons_l = QHBoxLayout(buttons)
        buttons_l.setContentsMargins(0, 0, 0, 0)
        buttons_l.addStretch(1)
        self.open_btn = AnimatedButton("Abrir PPR-PKG Builder", "big", icon="package")
        self.open_btn.clicked.connect(self._launch_builder)
        buttons_l.addWidget(self.open_btn)
        workflow.add_widget(buttons)
        layout.addWidget(workflow)
        layout.addStretch(1)
        self.scroll.setWidget(host)
        outer.addWidget(self.scroll)
        self._responsive_cards = [tool, source, metadata, workflow]

    @staticmethod
    def _readonly_line(text: str) -> QLineEdit:
        edit = QLineEdit(text)
        edit.setReadOnly(True)
        return edit

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 760
        for card in self._responsive_cards:
            card.set_compact(compact)

    def _configured_tool(self) -> str:
        return self.tool_edit.text().strip() or self.state.settings.get("ppr_pkg_builder_path", "")

    def refresh_engine_status(self):
        tool = find_ppr_pkg_builder(self._configured_tool())
        if tool:
            self.engine_badge.setText(f"PPR-PKG Builder · {tool.name}")
            self.engine_badge.setProperty("warning", False)
            if not self.tool_edit.text().strip():
                self.tool_edit.setText(str(tool))
            self.open_btn.setEnabled(True)
        else:
            self.engine_badge.setText("PPR-PKG Builder no seleccionado")
            self.engine_badge.setProperty("warning", True)
            self.open_btn.setEnabled(False)
        self.engine_badge.style().unpolish(self.engine_badge)
        self.engine_badge.style().polish(self.engine_badge)

    def _browse_tool(self):
        selected, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar PPR-PKG Builder", self.tool_edit.text().strip() or "",
            "PPR-PKG Builder (*.exe *.dll);;Todos los archivos (*)",
        )
        if selected:
            self._set_tool(Path(selected))

    def _tool_from_text(self):
        text = self.tool_edit.text().strip()
        if not text:
            self.state.settings["ppr_pkg_builder_path"] = ""
            self.state.save()
            self.refresh_engine_status()
            return
        self._set_tool(Path(text), warn=False)

    def _set_tool(self, path: Path, *, warn: bool = True):
        path = Path(path).expanduser()
        if not path.is_file():
            if warn:
                QMessageBox.warning(self, "Herramienta no encontrada", "El archivo seleccionado no existe.")
            self.refresh_engine_status()
            return
        self.tool_edit.setText(str(path.resolve()))
        self.state.settings["ppr_pkg_builder_path"] = str(path.resolve())
        self.state.save()
        self.refresh_engine_status()

    def _browse_source(self):
        if self.source_kind.currentText() == "GP5 project":
            selected, _ = QFileDialog.getOpenFileName(
                self, "Seleccionar proyecto GP5", "", "GP5 project (*.gp5);;Todos los archivos (*)"
            )
            if selected:
                self.set_source(Path(selected))
            return
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de origen")
        if folder:
            self.set_source(Path(folder))

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de salida")
        if folder:
            self.set_output(Path(folder))

    def _source_kind_changed(self, _text: str):
        current = self.source_edit.text().strip()
        if current:
            self.set_source(Path(current), warn=False)

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
        expects_gp5 = self.source_kind.currentText() == "GP5 project"
        valid = path.is_file() and path.suffix.lower() == ".gp5" if expects_gp5 else path.is_dir()
        if not valid:
            if warn:
                QMessageBox.warning(
                    self, "Origen inválido",
                    "Selecciona un archivo .gp5." if expects_gp5 else "La carpeta seleccionada no existe.",
                )
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
        if not self.source_path or not self.source_path.is_dir():
            self._set_metadata_empty()
            return
        info = parse_game_info(self.source_path)
        self.title_edit.setText(str(info.get("title") or "—"))
        self.title_id_edit.setText(self._clean_meta(info.get("title_id")))
        self.content_id_edit.setText(self._clean_meta(info.get("content_id")))
        self.version_edit.setText(self._clean_meta(info.get("version")))
        self.sdk_edit.setText(self._clean_meta(info.get("sdk_version")))

    @staticmethod
    def _clean_meta(value) -> str:
        text = str(value or "").strip()
        return "—" if not text or text.lower() == "unknown" else text

    def _set_metadata_empty(self):
        for edit in (self.title_edit, self.title_id_edit, self.content_id_edit, self.version_edit, self.sdk_edit):
            edit.setText("—")

    def _copy_path(self, value: str, status: str):
        value = value.strip()
        if not value:
            return
        QApplication.clipboard().setText(value)
        self.status_label.setText(status)

    def _launch_builder(self):
        tool = find_ppr_pkg_builder(self._configured_tool())
        if not tool:
            QMessageBox.warning(
                self, "PPR-PKG Builder no disponible",
                "Selecciona primero el ejecutable de PPR-PKG Builder que aparece en la referencia.",
            )
            self.refresh_engine_status()
            return
        try:
            if self.source_path:
                QApplication.clipboard().setText(str(self.source_path))
            launch_ppr_pkg_builder(tool)
        except (OSError, PprPkgBuilderError) as exc:
            self.status_label.setText(f"No se pudo abrir PPR-PKG Builder: {exc}")
            QMessageBox.critical(self, "Error al abrir PPR-PKG Builder", str(exc))
            return
        self.status_label.setText(
            "PPR-PKG Builder abierto. La ruta de origen está copiada al portapapeles; "
            "configura y construye el PKG en esa aplicación."
            if self.source_path
            else "PPR-PKG Builder abierto. La creación del PKG continúa en esa aplicación."
        )
