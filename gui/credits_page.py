from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from gui import styles as S
from gui.icons import icon_pixmap


class PackizardBadge(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(76, 76)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(S.CURRENT["nav_selected"]))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(self.rect())
        pixmap = icon_pixmap("package", 38, S.CURRENT["accent"])
        painter.drawPixmap((self.width() - 38) // 2, (self.height() - 38) // 2, pixmap)


class CreditsPage(QWidget):
    """Packizard ownership and third-party acknowledgements."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ContentBG")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        host = QWidget(); host.setObjectName("ContentBG"); host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        host_layout = QHBoxLayout(host); host_layout.setContentsMargins(0, 0, 0, 0)
        content = QWidget(); content.setObjectName("ContentBG"); content.setMaximumWidth(980); content.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout = QVBoxLayout(content); layout.setContentsMargins(0, 0, 0, 16); layout.setSpacing(18)

        title = QLabel("Packizard Builder"); title.setObjectName("Header")
        subtitle = QLabel("Packizard Engine compression and integrated PKG workflow in one application.")
        subtitle.setObjectName("SubHeader"); subtitle.setWordWrap(True)
        layout.addWidget(title); layout.addWidget(subtitle)

        owner = QFrame(); owner.setObjectName("CreditsThanks")
        owner_layout = QHBoxLayout(owner); owner_layout.setContentsMargins(26, 24, 26, 24); owner_layout.setSpacing(20)
        self.badge = PackizardBadge(); owner_layout.addWidget(self.badge, 0, Qt.AlignVCenter)
        owner_text = QWidget(); owner_text_layout = QVBoxLayout(owner_text); owner_text_layout.setContentsMargins(0, 0, 0, 0); owner_text_layout.setSpacing(5)
        integrator = QLabel("Packizard"); integrator.setObjectName("CreditName")
        role = QLabel("Integrator · Packizard Builder"); role.setObjectName("SectionTitle")
        detail = QLabel("Packizard maintains the application UX, Packizard Engine, PS5 runtime integration, PKG bridge and cross-platform release pipeline.")
        detail.setObjectName("SubHeader"); detail.setWordWrap(True)
        owner_text_layout.addWidget(integrator); owner_text_layout.addWidget(role); owner_text_layout.addWidget(detail)
        owner_layout.addWidget(owner_text, 1); layout.addWidget(owner)

        architecture = QFrame(); architecture.setObjectName("ContributorCard")
        arch_layout = QVBoxLayout(architecture); arch_layout.setContentsMargins(24, 20, 24, 20); arch_layout.setSpacing(6)
        arch_title = QLabel("Integrated engines"); arch_title.setObjectName("SectionTitle")
        arch_text = QLabel("Packizard Engine handles compression and asset containers. LibProsperoPKG is integrated through Packizard.PkgBridge for PKG creation without a separate GUI.")
        arch_text.setObjectName("SubHeader"); arch_text.setWordWrap(True)
        arch_layout.addWidget(arch_title); arch_layout.addWidget(arch_text); layout.addWidget(architecture)
        layout.addStretch(1)

        thanks = QLabel("Thanks to Nazky, Deckerr97, Pippo, drakmor, SvenGDK and other public tooling contributors whose research informed these workflows. Current component licenses and attribution details are preserved in THIRD_PARTY_NOTICES.md.")
        thanks.setObjectName("Subtitle"); thanks.setWordWrap(True); thanks.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        font = QFont(thanks.font()); font.setPointSize(max(8, font.pointSize() - 1)); thanks.setFont(font)
        layout.addWidget(thanks)

        host_layout.addStretch(1); host_layout.addWidget(content, 100); host_layout.addStretch(1)
        self.scroll.setWidget(host); outer.addWidget(self.scroll)

    def refresh_theme(self):
        self.badge.update()
