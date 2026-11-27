"""Paso 4: instalador (Anaconda) y personalización de bienvenida."""

from core.builder import MAX_PLYMOUTH_BYTES
from gui.components import configure_image_preview
from gui.images import ImageField
from gui.layouts import add_page
from gui.ui_components import SettingRowCard, ToggleSwitch
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

HELP = """
<p><b>Configuración del instalador</b></p>
<p>Si habilitás Anaconda, la ISO agrega una entrada <i>Instalar en disco</i>
en el menú de arranque. Al elegirla se abre el instalador en lugar del entorno Live.</p>
<p>El banner y el mensaje de bienvenida son opciones de personalización. La
imagen se optimiza y se limita a 4 MiB. Mantene una tecla presionada al iniciar
para ver el menú de arranque.</p>
"""


class InstallerTabMixin:
    """Paso 4: instalador Anaconda y branding (mixin de KioskBuilderGUI)."""

    def init_tab_installer(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # --- Instalador ---
        self.check_enable_installer = ToggleSwitch(checked=True)
        self.check_enable_installer.setToolTip(
            "Incluye Anaconda y agrega una entrada de instalación en el menú de arranque."
        )
        self.card_enable_installer = SettingRowCard(
            "Incluir instalador en disco duro (Anaconda)",
            "Agrega una entrada de instalación en el menú de arranque.",
            "💾",
            self.check_enable_installer,
        )
        layout.addWidget(self.card_enable_installer)

        # --- Banner ---
        banner_card = QFrame()
        banner_card.setObjectName("settingRowCard")
        banner_layout = QVBoxLayout(banner_card)
        banner_layout.setContentsMargins(16, 14, 16, 14)
        banner_layout.setSpacing(10)
        banner_title = QLabel("Identidad visual del instalador")
        banner_title.setObjectName("settingTitle")
        banner_layout.addWidget(banner_title)
        banner_desc = QLabel(
            "Personalizá el banner del instalador Anaconda. Si no elegís una imagen, se usa el tema predeterminado."
        )
        banner_desc.setObjectName("settingDescription")
        banner_desc.setWordWrap(True)
        banner_layout.addWidget(banner_desc)

        self.installer_preview = QLabel("Sin banner · tema predeterminado")
        self.installer_preview.setObjectName("imagePreview")
        configure_image_preview(self.installer_preview, minimum=(220, 110), maximum=(480, 220))
        banner_layout.addWidget(self.installer_preview, 0)

        self.btn_installer_banner = QPushButton("Seleccionar banner…")
        self.btn_installer_banner.setToolTip("Selecciona la imagen que mostrará el instalador (Anaconda).")
        self.lbl_installer_banner = QLabel("Por defecto · tema del sistema")
        self.lbl_installer_banner.setWordWrap(True)
        self.lbl_installer_banner.setObjectName("inlineHint")
        self.btn_installer_banner_clear = QPushButton("Quitar imagen")
        self.banner_field = ImageField(
            self, self.installer_preview, self.lbl_installer_banner,
            "Seleccionar imagen banner del instalador", "installer-banner.png",
            MAX_PLYMOUTH_BYTES, "4 MiB", "Sin banner · tema predeterminado",
            "Por defecto · tema del sistema",
        )
        self.btn_installer_banner.clicked.connect(self.banner_field.select)
        self.btn_installer_banner_clear.clicked.connect(self.banner_field.clear)
        banner_actions = QHBoxLayout()
        banner_actions.setSpacing(8)
        banner_actions.addWidget(self.btn_installer_banner)
        banner_actions.addWidget(self.btn_installer_banner_clear)
        banner_actions.addStretch(1)
        banner_layout.addLayout(banner_actions)
        banner_layout.addWidget(self.lbl_installer_banner)
        banner_hint = QLabel(
            "PNG, JPG, WebP o BMP. La imagen se convierte y optimiza para el encabezado del instalador."
        )
        banner_hint.setObjectName("settingDescription")
        banner_hint.setWordWrap(True)
        banner_layout.addWidget(banner_hint)
        layout.addWidget(banner_card)

        # --- Mensaje de bienvenida ---
        text_card = QFrame()
        text_card.setObjectName("settingRowCard")
        text_layout = QVBoxLayout(text_card)
        text_layout.setContentsMargins(16, 14, 16, 14)
        text_layout.setSpacing(10)
        text_title = QLabel("Mensaje de bienvenida")
        text_title.setObjectName("settingTitle")
        text_layout.addWidget(text_title)
        text_desc = QLabel(
            "Este mensaje se incluye en el contenido del instalador y del sistema instalado."
        )
        text_desc.setObjectName("settingDescription")
        text_desc.setWordWrap(True)
        text_layout.addWidget(text_desc)

        self.txt_installer_text = QTextEdit(
            "Bienvenido al instalador de la distribución Kiosco.\n"
            "Este asistente instalará el sistema operativo en su equipo de forma rápida y segura."
        )
        self.txt_installer_text.setPlaceholderText(
            "Escribí el texto de bienvenida o descripción del sistema…"
        )
        self.txt_installer_text.setMinimumHeight(110)
        text_layout.addWidget(self.txt_installer_text)
        layout.addWidget(text_card)

        layout.addStretch(1)
        self.group_installer_banner = banner_card
        self.group_installer_text = text_card
        add_page(
            self, "step4", tab, "Configuración del instalador",
            "Definí si la ISO incluye Anaconda y personalizá su bienvenida.",
            HELP, step=4,
        )