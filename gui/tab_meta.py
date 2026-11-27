"""Paso 1: identidad y metadatos de la ISO."""

from core.projects.catalog import get_project_template, list_project_types
from gui.components import prepare_combo
from gui.layouts import add_page
from gui.ui_components import SettingExpanderCard, SettingRowCard
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QVBoxLayout, QWidget

HELP = """
<p><b>Identidad del sistema</b></p>
<p>Define el nombre de la imagen, el producto que identificará al sistema
instalado y los datos de publicación. La identidad se conserva en los
metadatos y en los componentes del sistema que correspondan.</p>
<p>La distribución elegida define el motor de la imagen: <code>kiosk</code>
para un equipo dedicado, o uno de los perfiles Desktop (<code>oficina</code>,
<code>web</code>, <code>gaming</code>, <code>security_lab</code> o
<code>custom</code>) que usan el motor Fedora Desktop.</p>
<p>El motor Kiosco arranca directamente como Live, sin LightDM ni contraseña.
Los perfiles Fedora Desktop conservan una contraseña inicial para el usuario
de escritorio.</p>
"""


class MetaTabMixin:
    """Paso 1: identidad y metadatos de la ISO (mixin de KioskBuilderGUI)."""

    def init_tab_meta(self):
        tab = QWidget()
        page_layout = QVBoxLayout(tab)

        # --- Controles (atributos preservados para compatibilidad) ---
        self.txt_name = QLineEdit("TallerArgOS-kiosk")
        self.txt_name.setPlaceholderText("Nombre identificador de la ISO")

        self.txt_product_name = QLineEdit("TallerArgOS Fedora Kiosk")
        self.txt_product_name.setToolTip(
            "Nombre del producto que muestra el instalador (Anaconda) y el "
            "sistema instalado. Dejalo vacío para mantener la identidad Fedora Linux."
        )

        self.txt_version = QLineEdit("1.0.0")
        self.txt_dev = QLineEdit("Sergio")

        self.combo_project_type = QComboBox()
        prepare_combo(self.combo_project_type, 22)
        self.combo_project_type.setToolTip(
            "Define el objetivo de la distribución y el motor de construcción."
        )
        for key, name, tagline in list_project_types():
            self.combo_project_type.addItem(f"{name} — {tagline}", key)
        self.combo_project_type.currentIndexChanged.connect(self._on_project_type_changed)

        self.combo_base = QComboBox()
        prepare_combo(self.combo_base, 18)
        self.combo_base.addItem("Fedora 44 (repos estáticos)", "44")

        self.combo_boot = QComboBox()
        prepare_combo(self.combo_boot, 18)
        self.combo_boot.addItem("Dual (UEFI + BIOS)", "dual")
        self.combo_boot.addItem("Solo UEFI", "uefi")
        self.combo_boot.setToolTip(
            "La imagen híbrida mantiene compatibilidad BIOS; esta opción controla "
            "la inclusión del stack EFI."
        )

        self.txt_desktop_user = QLineEdit(
            str(getattr(self, "_desktop_user", "fedora") or "fedora")
        )
        self.txt_desktop_user.setToolTip(
            "Usuario de la cuenta de escritorio. Solo aplica al motor Fedora Desktop; "
            "el motor Kiosco utiliza kioskuser."
        )
        self.txt_desktop_user.textChanged.connect(self._on_desktop_user_changed)

        self.txt_password = QLineEdit()
        self.txt_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_password.setPlaceholderText("Contraseña inicial")
        self.txt_password.setToolTip(
            "Solo se aplica al usuario de escritorio en el motor Fedora Desktop."
        )

        # --- Tarjetas de configuración ---
        self.card_project_type = SettingRowCard(
            "Tipo de distribución",
            "Define el objetivo del proyecto y el motor de construcción.",
            "🧩",
            self.combo_project_type,
        )
        self.card_iso_name = SettingRowCard(
            "Nombre de la ISO",
            "Identificador del archivo generado.",
            "💿",
            self.txt_name,
        )
        self.card_product_name = SettingRowCard(
            "Nombre del producto",
            "Nombre visible en el instalador y el sistema instalado.",
            "🏷",
            self.txt_product_name,
        )
        self.card_version = SettingRowCard(
            "Versión",
            "Versión visible de la distribución.",
            "🔢",
            self.txt_version,
        )
        self.card_developer = SettingRowCard(
            "Creador / Taller",
            "Responsable o equipo que publica la imagen.",
            "👤",
            self.txt_dev,
        )

        for card in (
            self.card_project_type,
            self.card_iso_name,
            self.card_product_name,
            self.card_version,
            self.card_developer,
        ):
            page_layout.addWidget(card)

        # Opciones técnicas avanzadas
        self.expander_platform = SettingExpanderCard(
            "Plataforma y arranque",
            "Opciones técnicas de base Fedora y modo de arranque.",
            "⚙",
        )
        self.card_base = SettingRowCard(
            "Distribución base",
            "Versión de Fedora usada como base del proyecto.",
            "🐧",
            self.combo_base,
        )
        self.card_boot = SettingRowCard(
            "Modo de arranque",
            "Compatibilidad de arranque para la imagen generada.",
            "🚀",
            self.combo_boot,
        )
        self.expander_platform.add_widget(self.card_base)
        self.expander_platform.add_widget(self.card_boot)
        page_layout.addWidget(self.expander_platform)

        # Cuenta de escritorio
        self.meta_hint = QLabel(
            "Motor Kiosco: inicio automático tipo Live, sin contraseña. "
            "Motor Fedora Desktop: usuario de escritorio con contraseña inicial."
        )
        self.meta_hint.setObjectName("inlineHint")
        self.meta_hint.setWordWrap(True)
        page_layout.addWidget(self.meta_hint)

        self.card_desktop_user = SettingRowCard(
            "Usuario de escritorio",
            "Cuenta inicial para el motor Fedora Desktop.",
            "👥",
            self.txt_desktop_user,
        )
        self.card_password = SettingRowCard(
            "Contraseña inicial",
            "Solo se aplica al motor Fedora Desktop.",
            "🔒",
            self.txt_password,
        )
        page_layout.addWidget(self.card_desktop_user)
        page_layout.addWidget(self.card_password)

        # Compatibilidad con código existente
        self.group_desktop_account = self.card_desktop_user  # usado por refresh_project_mode_fields
        self._password_label = self.card_password.title_label
        self._password_card = self.card_password
        self._desktop_user_card = self.card_desktop_user

        page_layout.addStretch(1)

        # Registrar avanzados (se oculta la tarjeta completa)
        self._register_advanced(self.card_base)
        self._register_advanced(self.card_boot)
        self._register_advanced(self.expander_platform)

        self._on_project_type_changed()
        add_page(
            self, "step1", tab, "Identidad del sistema",
            "Definí el producto, el perfil de distribución y la cuenta de usuario.",
            HELP, step=1,
        )

    def _on_project_type_changed(self, *_args):
        key = str(self.combo_project_type.currentData() or "custom")
        self._project_type = key
        self._build_engine = get_project_template(key)["engine"]
        refresh = getattr(self, "refresh_desktop_environment_fields", None)
        if callable(refresh):
            refresh()
        mode_refresh = getattr(self, "refresh_project_mode_fields", None)
        if callable(mode_refresh):
            mode_refresh()
        is_kiosk = key == "kiosk"
        # Mostrar/ocultar cuenta escritorio según perfil
        if hasattr(self, "_password_card"):
            self._password_card.setVisible(not is_kiosk)
        if hasattr(self, "_desktop_user_card"):
            self._desktop_user_card.setVisible(not is_kiosk)
        if hasattr(self, "meta_hint"):
            self.meta_hint.setText(
                "Motor Kiosco: inicio automático tipo Live, sin contraseña. "
                "Motor Fedora Desktop: usuario de escritorio con contraseña inicial."
                if is_kiosk
                else "Motor Fedora Desktop: configurá la cuenta inicial del usuario de escritorio."
            )

    def _on_desktop_user_changed(self, *_args):
        value = self.txt_desktop_user.text().strip()
        self._desktop_user = value or "fedora"