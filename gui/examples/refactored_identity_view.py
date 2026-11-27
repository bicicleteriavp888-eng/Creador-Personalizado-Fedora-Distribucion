"""Ejemplo de refactor: vista "Identidad del sistema" con Design System WinUI 3.

Objetivo del ejemplo:
- Separar presentación (widgets/composición) de lógica (estado, validación,
  mapeo de datos).
- Reutilizar ThemeManager + ui_components.
- Mantener compatibilidad con la estructura actual del proyecto (mixin/página).

Este archivo es un ejemplo de integración; no reemplaza automáticamente al
tab actual. Puede adaptarse a `gui/tab_meta.py` progresivamente.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.projects.catalog import list_project_types
from gui.ui_components import ActionFooter, SettingExpanderCard, SettingRowCard, ToggleSwitch


# ---------------------------------------------------------------------------
# Modelo / estado de la vista
# ---------------------------------------------------------------------------


@dataclass
class IdentityFormData:
    project_type: str = "kiosk"
    iso_name: str = "TallerArgOS-kiosk"
    product_name: str = "TallerArgOS Fedora Kiosk"
    version: str = "1.0.0"
    developer: str = "Sergio"
    base_distribution: str = "44"
    boot_mode: str = "dual"
    desktop_user: str = "fedora"
    password: str = ""
    enable_installer_branding: bool = True


# ---------------------------------------------------------------------------
# Presentación (View): solo construye UI y expone widgets/señales
# ---------------------------------------------------------------------------


class IdentityView(QWidget):
    """Vista pura: composición visual, sin reglas de negocio."""

    # Señales que la lógica puede observar.
    project_type_changed = Signal(str)
    validate_requested = Signal()
    next_requested = Signal()
    back_requested = Signal()
    save_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("contentArea")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Scroll de contenido ---
        self.scroll = QScrollArea()
        self.scroll.setObjectName("contentScrollArea")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self.scroll, 1)

        scroll_content = QWidget()
        scroll_content.setObjectName("contentContainer")
        self.scroll.setWidget(scroll_content)

        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(32, 24, 32, 24)
        scroll_layout.setSpacing(16)
        scroll_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        # Contenedor centrado con ancho máximo de formulario.
        self.content_column = QWidget()
        self.content_column.setObjectName("contentColumn")
        self.content_column.setMaximumWidth(960)
        self.content_column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        column_layout = QVBoxLayout(self.content_column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(4)

        # --- Encabezado de página (sin caja contenedora) ---
        self.breadcrumb = QLabel("Asistente > Identidad del sistema")
        self.breadcrumb.setObjectName("breadcrumbPath")
        column_layout.addWidget(self.breadcrumb)

        self.page_title = QLabel("Identidad del sistema")
        self.page_title.setObjectName("pageTitle")
        column_layout.addWidget(self.page_title)

        self.page_description = QLabel(
            "Definí el producto, el perfil de distribución y la cuenta inicial "
            "del sistema. Estos datos se usan en la imagen y el instalador."
        )
        self.page_description.setObjectName("pageDescription")
        self.page_description.setWordWrap(True)
        column_layout.addWidget(self.page_description)
        column_layout.addSpacing(16)

        # --- Controles ---
        self.project_type_combo = QComboBox()
        self._populate_project_types()
        self.project_type_combo.currentIndexChanged.connect(self._emit_project_type)

        self.iso_name_edit = QLineEdit()
        self.iso_name_edit.setPlaceholderText("Nombre identificador de la ISO")

        self.product_name_edit = QLineEdit()
        self.product_name_edit.setPlaceholderText("Nombre visible del producto")

        self.version_edit = QLineEdit()
        self.version_edit.setPlaceholderText("1.0.0")

        self.developer_edit = QLineEdit()
        self.developer_edit.setPlaceholderText("Creador o taller")

        self.base_combo = QComboBox()
        self.base_combo.addItem("Fedora 44 (repos estáticos)", "44")

        self.boot_combo = QComboBox()
        self.boot_combo.addItem("Dual (UEFI + BIOS)", "dual")
        self.boot_combo.addItem("Solo UEFI", "uefi")

        self.desktop_user_edit = QLineEdit()
        self.desktop_user_edit.setPlaceholderText("fedora")

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Contraseña inicial")

        self.installer_branding_toggle = ToggleSwitch(checked=True)

        # --- Tarjetas ---
        self.card_project_type = SettingRowCard(
            title="Tipo de distribución",
            description="Define el objetivo del proyecto y el motor de construcción.",
            icon="🧩",
            control=self.project_type_combo,
        )
        self.card_iso_name = SettingRowCard(
            title="Nombre de la ISO",
            description="Identificador del archivo generado.",
            icon="💿",
            control=self.iso_name_edit,
        )
        self.card_product = SettingRowCard(
            title="Nombre del producto",
            description="Nombre que verá el usuario en el instalador y el sistema.",
            icon="🏷",
            control=self.product_name_edit,
        )
        self.card_version = SettingRowCard(
            title="Versión",
            description="Versión visible de la distribución.",
            icon="🔢",
            control=self.version_edit,
        )
        self.card_developer = SettingRowCard(
            title="Creador / Taller",
            description="Nombre del responsable o equipo que publica la imagen.",
            icon="👤",
            control=self.developer_edit,
        )

        for card in [
            self.card_project_type,
            self.card_iso_name,
            self.card_product,
            self.card_version,
            self.card_developer,
        ]:
            column_layout.addWidget(card)

        # Opciones avanzadas agrupadas en expander.
        self.advanced_expander = SettingExpanderCard(
            title="Plataforma y arranque",
            description="Opciones técnicas de base Fedora y modo de arranque.",
            icon="⚙",
        )
        self.advanced_expander.add_widget(
            SettingRowCard(
                title="Distribución base",
                description="Versión de Fedora usada como base del proyecto.",
                icon="🐧",
                control=self.base_combo,
            )
        )
        self.advanced_expander.add_widget(
            SettingRowCard(
                title="Modo de arranque",
                description="Compatibilidad de arranque para la imagen generada.",
                icon="🚀",
                control=self.boot_combo,
            )
        )
        self.advanced_expander.add_widget(
            SettingRowCard(
                title="Identidad visual del instalador",
                description="Mantener branding personalizado en el instalador.",
                icon="🎨",
                control=self.installer_branding_toggle,
            )
        )
        column_layout.addSpacing(8)
        column_layout.addWidget(self.advanced_expander)

        # Cuenta de escritorio (visible según perfil; la lógica controla visibilidad).
        self.account_section_label = QLabel("Cuenta de escritorio")
        self.account_section_label.setObjectName("settingTitle")
        self.account_section_label.setStyleSheet("margin-top: 16px; margin-bottom: 4px;")
        column_layout.addWidget(self.account_section_label)

        self.card_desktop_user = SettingRowCard(
            title="Usuario",
            description="Cuenta inicial para el motor Fedora Desktop.",
            icon="👥",
            control=self.desktop_user_edit,
        )
        self.card_password = SettingRowCard(
            title="Contraseña inicial",
            description="Solo se aplica al motor Fedora Desktop.",
            icon="🔒",
            control=self.password_edit,
        )
        column_layout.addWidget(self.card_desktop_user)
        column_layout.addWidget(self.card_password)

        column_layout.addStretch(1)
        scroll_layout.addWidget(self.content_column)

        # --- Footer de acciones ---
        self.footer = ActionFooter()
        self.footer.set_progress(1, 6)
        self.btn_back = self.footer.add_button("Anterior")
        self.btn_validate = self.footer.add_button("Validar paso")
        self.btn_save = self.footer.add_button("Guardar")
        self.btn_help = self.footer.add_button("Ayuda")
        self.btn_next = self.footer.add_button("Siguiente →", primary=True)

        self.btn_back.clicked.connect(self.back_requested.emit)
        self.btn_validate.clicked.connect(self.validate_requested.emit)
        self.btn_save.clicked.connect(self.save_requested.emit)
        self.btn_next.clicked.connect(self.next_requested.emit)
        root.addWidget(self.footer)

    def _populate_project_types(self) -> None:
        self.project_type_combo.clear()
        for key, name, tagline in list_project_types():
            self.project_type_combo.addItem(f"{name} — {tagline}", key)

    def _emit_project_type(self) -> None:
        value = str(self.project_type_combo.currentData() or "kiosk")
        self.project_type_changed.emit(value)

    # --- API de lectura/escritura para la lógica ---

    def get_data(self) -> IdentityFormData:
        return IdentityFormData(
            project_type=str(self.project_type_combo.currentData() or "kiosk"),
            iso_name=self.iso_name_edit.text().strip(),
            product_name=self.product_name_edit.text().strip(),
            version=self.version_edit.text().strip(),
            developer=self.developer_edit.text().strip(),
            base_distribution=str(self.base_combo.currentData() or "44"),
            boot_mode=str(self.boot_combo.currentData() or "dual"),
            desktop_user=self.desktop_user_edit.text().strip(),
            password=self.password_edit.text(),
            enable_installer_branding=self.installer_branding_toggle.isChecked(),
        )

    def set_data(self, data: IdentityFormData) -> None:
        self._set_combo_by_data(self.project_type_combo, data.project_type)
        self.iso_name_edit.setText(data.iso_name)
        self.product_name_edit.setText(data.product_name)
        self.version_edit.setText(data.version)
        self.developer_edit.setText(data.developer)
        self._set_combo_by_data(self.base_combo, data.base_distribution)
        self._set_combo_by_data(self.boot_combo, data.boot_mode)
        self.desktop_user_edit.setText(data.desktop_user)
        self.password_edit.setText(data.password)
        self.installer_branding_toggle.setChecked(data.enable_installer_branding)

    def set_account_visible(self, visible: bool) -> None:
        self.account_section_label.setVisible(visible)
        self.card_desktop_user.setVisible(visible)
        self.card_password.setVisible(visible)

    def show_validation_error(self, message: str) -> None:
        # En producción: usar un InfoBar/banner no intrusivo.
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(self, "Validación", message)

    @staticmethod
    def _set_combo_by_data(combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)


# ---------------------------------------------------------------------------
# Lógica / Controller: reglas, validación, orquestación
# ---------------------------------------------------------------------------


class IdentityController(QObject):
    """Coordina la vista con el modelo y los servicios de la aplicación."""

    def __init__(self, view: IdentityView, project_service=None, parent: QObject | None = None):
        super().__init__(parent)
        self.view = view
        self.project_service = project_service  # p.ej. ProjectStore / facade
        self._wire_events()
        self._sync_visibility(self.view.get_data().project_type)

    def _wire_events(self) -> None:
        self.view.project_type_changed.connect(self._sync_visibility)
        self.view.validate_requested.connect(self.validate)
        self.view.save_requested.connect(self.save)
        self.view.next_requested.connect(self.go_next)
        self.view.back_requested.connect(self.go_back)

    def _sync_visibility(self, project_type: str) -> None:
        # Regla de negocio: Kiosco no usa cuenta/contraseña de escritorio.
        is_kiosk = project_type == "kiosk"
        self.view.set_account_visible(not is_kiosk)

    def validate(self) -> tuple[bool, list[str]]:
        data = self.view.get_data()
        errors: list[str] = []

        if not data.iso_name:
            errors.append("El nombre de la ISO es obligatorio.")
        if not data.product_name:
            errors.append("El nombre del producto es obligatorio.")
        if not data.version:
            errors.append("La versión es obligatoria.")
        if data.project_type != "kiosk" and not data.password:
            errors.append("La contraseña inicial es obligatoria para Fedora Desktop.")

        if errors:
            self.view.show_validation_error("\n".join(f"• {e}" for e in errors))
            return False, errors
        return True, []

    def save(self) -> bool:
        ok, _ = self.validate()
        if not ok:
            return False
        data = self.view.get_data()
        # Persistencia desacoplada: la vista no conoce QSettings/ProjectStore.
        if self.project_service is not None:
            self.project_service.save_identity(data)
        return True

    def go_next(self) -> None:
        if self.save():
            # La navegación real la delega el shell principal.
            # Aquí solo se muestra el patrón: emitir/llamar callback.
            print("[navigation] next -> apariencia")

    def go_back(self) -> None:
        print("[navigation] back -> dashboard")


# ---------------------------------------------------------------------------
# Integración de ejemplo en una ventana/shell
# ---------------------------------------------------------------------------


def build_identity_page(project_service=None) -> tuple[IdentityView, IdentityController]:
    """Factory conveniente para registrar la página en el stack principal."""
    view = IdentityView()
    controller = IdentityController(view=view, project_service=project_service)
    return view, controller


# Ejemplo de uso aislado (ejecutar este archivo directamente).
if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication, QMainWindow

    from gui.theme_manager import ThemeManager

    app = QApplication(sys.argv)
    theme = ThemeManager(app, "light")

    window = QMainWindow()
    window.setWindowTitle("Ejemplo Design System - Identidad")
    window.resize(1200, 800)

    view, _controller = build_identity_page()
    window.setCentralWidget(view)

    # Demo rápida: alternar tema con Alt+T
    toggle_action = window.menuBar().addAction("Alternar tema")
    toggle_action.setShortcut("Alt+T")
    toggle_action.triggered.connect(theme.toggle_theme)

    window.show()
    sys.exit(app.exec())
