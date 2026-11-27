"""Creador Personalizado 3.0: constructor de distribuciones Fedora a medida."""

import argparse
import getpass
import os
import re
import unicodedata
import sys
import threading
import time
import tempfile
from datetime import datetime

from PySide6.QtCore import QPoint, QSettings, QThread, Signal, Qt
from PySide6.QtWidgets import (
    QDialog,
    QPlainTextEdit,
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QInputDialog,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.builders import BuildEngineError, resolve_build_engine, resolve_builder_class
from core.config import BuildConfig, load_project_config
from core.kickstart.validator import validate_kickstart_file
from core.projects.manager import ProjectStore
from core.projects.catalog import (
    get_named_profile_template, get_project_template, list_named_profiles,
    list_project_types, merge_packages,
)
from core.desktops.environments import (
    UnknownDesktopEnvironmentError,
    get_desktop_environment,
)
from gui.components import EmptyState, FlowLayout, HelpPanel, SectionCard
from gui.ui_components import StatusMetricCard
from gui.layouts import add_page
from gui.icons import nav_icon
from gui.status import (
    HashWorker,
    HostStatusWorker,
    check_dependencies,
    disk_info,
    format_timestamp,
    recent_builds,
)
from gui.tab_aesthetic import AestheticTabMixin
from gui.tab_build import BuildTabMixin
from gui.tab_installer import InstallerTabMixin
from gui.tab_meta import MetaTabMixin
from gui.tab_security import SecurityTabMixin
from gui.tab_software import SoftwareTabMixin
from gui.tab_usb import UsbTabMixin
from gui.custom_distro import CustomDistroTabMixin
from gui.theme_manager import ThemeManager
from gui.validation import validate_all, validate_step, validate_until


SETTINGS_ORG = "CreadorKiosk"
SETTINGS_APP = "Creador-kiosk"

STEP_KEYS = ("step1", "step2", "step3", "step4", "step5", "step6")
STEP_LABELS = {
    "step1": "Identidad del sistema",
    "step2": "Apariencia",
    "step3": "Software",
    "step4": "Instalador",
    "step5": "Seguridad y servicios",
    "step6": "Compilación y validación",
}
NAV_ITEMS = (
    ("dashboard", "Panel principal"),
    ("step1", "1  Identidad del sistema"),
    ("step2", "2  Apariencia y personalización"),
    ("step3", "3  Selección de software"),
    ("step4", "4  Configuración del instalador"),
    ("step5", "5  Seguridad y servicios"),
    ("step6", "6  Compilación y validación"),
)
DASHBOARD_HELP = """
<p><b>Panel principal</b></p>
<p>Muestra informacion real del equipo: la ultima ISO generada, su ruta,
tamano y SHA-256, el espacio libre del volumen de salida, las dependencias
instaladas y el estado de <code>firewalld</code> y <code>sshd</code>.</p>
<p>La etiqueta <b>GENERADA</b> solo indica que el archivo existe. Una ISO
<b>validada</b> y una ISO <b>probada</b> son estados distintos que se agregan en
las etapas de laboratorio. Las tareas pendientes reflejan esa diferencia.</p>
<p>El hash se calcula en segundo plano para no bloquear la interfaz. Si la ISO
cambia de tamano o fecha, el hash guardado se invalida y se vuelve a calcular.</p>
"""


def _set_combo_by_data(combo, data):
    """Selecciona el item cuyo userData coincide con data (si existe)."""
    if data is None:
        return
    for index in range(combo.count()):
        if combo.itemData(index) == data:
            combo.setCurrentIndex(index)
            return


def _setting_bool(settings, key, default):
    """Lee un bool de QSettings (el backend INI lo devuelve como str)."""
    value = settings.value(key, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def _size_gib(size):
    return size / 1024 ** 3


class BuilderWorker(QThread):
    log_signal = Signal(str)
    progress_signal = Signal(int)
    iso_signal = Signal(str)
    finished_signal = Signal(bool)

    def __init__(self, config_data):
        super().__init__()
        self.config_model = BuildConfig.from_mapping(config_data)
        # Se conserva el contrato de diccionario exacto para constructores y
        # extensiones de terceros; el modelo tipado acompaña la ejecución.
        self.config = dict(config_data or {})
        # El GUI lo activa para pedirle al backend que aborte el build.
        self.cancel_event = threading.Event()

    def run(self):
        builder = None
        try:
            builder_class = resolve_builder_class(self.config)
            builder = builder_class(self.config)
            builder.cancel_event = self.cancel_event
            builder.log_signal.connect(self.log_signal.emit)
            builder.progress_signal.connect(self.progress_signal.emit)

            success = builder.build()
        except Exception as exc:  # noqa: BLE001 - nunca dejar el boton colgado
            self.log_signal.emit(f"💥 Error inesperado: {exc}")
            success = False

        if success and builder is not None:
            iso_path = getattr(builder, "last_iso_path", "")
            if iso_path:
                self.iso_signal.emit(iso_path)

        self.finished_signal.emit(success)


class QemuSmokeWorker(QThread):
    result_signal = Signal(str)

    def __init__(self, iso_path, firmwares):
        super().__init__()
        self.iso_path = iso_path
        self.firmwares = tuple(firmwares)

    def run(self):
        from core.iso.qemu_smoke import run_qemu_smoke
        for firmware in self.firmwares:
            result = run_qemu_smoke(self.iso_path, firmware=firmware)
            self.result_signal.emit(
                f"[QEMU {firmware.upper()}] {result.get('status')}: "
                f"{result.get('error') or ', '.join(result.get('markers', [])) or result.get('note', '')}"
            )


class KioskBuilderGUI(
    MetaTabMixin,
    AestheticTabMixin,
    SoftwareTabMixin,
    InstallerTabMixin,
    SecurityTabMixin,
    BuildTabMixin,
    UsbTabMixin,
    CustomDistroTabMixin,
    QMainWindow,
):
    """Ventana principal: panel, asistente de seis pasos y herramientas."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Creador Personalizado 3.0.0-alpha.8 | Fedora Image Studio")
        self.resize(1320, 900)
        self.setMinimumSize(900, 640)

        self.custom_app_path = ""
        self.worker = None
        self.qemu_worker = None
        self._last_iso_path = ""
        self.usb_worker = None
        self.hash_worker = None
        self._advanced_widgets = []
        self._pages = {}
        self._nav_buttons = {}
        self._current_key = "dashboard"
        self._last_build_error = ""
        self._custom_distro_mode = False
        self._project_type = "kiosk"
        # El flujo guiado para elegir escritorio llega en la etapa 4. Estos
        # valores mantienen el motor Kiosco como compatibilidad inicial.
        self._build_engine = ""
        self._desktop_environment = "gnome"
        self._display_server = "wayland"
        self._desktop_user = "fedora"
        self._custom_pkg_worker = None
        self._host_status_worker = None
        self._service_states_cache = {}
        self._last_host_query = 0.0
        self._dashboard_columns = 2
        self._sidebar_collapsed = False
        self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self._project_store = ProjectStore()
        self._active_project_path = ""
        self._active_project_id = ""
        self._active_project_name = ""
        self._active_profile_id = ""
        self.ui_mode = "advanced"
        self.theme_name = str(self._settings.value("theme", "light") or "light")
        self.theme_manager = ThemeManager(QApplication.instance(), self.theme_name)
        self.theme_manager.theme_changed.connect(self._on_theme_manager_changed)

        self._build_shell()
        self._init_pages()
        self._build_sidebar()
        self._load_settings()
        self._apply_theme(self.theme_name)
        self._apply_ui_mode(self.ui_mode, confirm=False)
        # La visibilidad de la página Kiosco debe derivarse del perfil ya
        # restaurado, no del estado provisional previo a cargar preferencias.
        self.refresh_project_mode_fields()
        self._navigate("dashboard", validate=False)
        self.refresh_dashboard()

    # -- Estructura visual ---------------------------------------------------
    def _build_shell(self):
        central = QWidget()
        central.setObjectName("centralRoot")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(260)
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(12, 16, 12, 12)
        self.sidebar_layout.setSpacing(4)
        self._nav_pill = QFrame(self.sidebar)
        self._nav_pill.setObjectName("navActivePill")
        self._nav_pill.setFixedSize(3, 16)
        self._nav_pill.hide()
        self._nav_pill.raise_()

        content = QWidget()
        content.setObjectName("contentRoot")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(22, 16, 22, 14)
        content_layout.setSpacing(12)

        topbar = QFrame()
        topbar.setObjectName("topBar")
        topbar_layout = QHBoxLayout(topbar)
        topbar_layout.setContentsMargins(0, 0, 0, 0)
        topbar_layout.setSpacing(8)

        self.btn_sidebar_toggle = QToolButton()
        self.btn_sidebar_toggle.setObjectName("sidebarToggle")
        self.btn_sidebar_toggle.setText("☰")
        self.btn_sidebar_toggle.setToolTip("Mostrar u ocultar la barra lateral.")
        self.btn_sidebar_toggle.clicked.connect(self._toggle_sidebar)
        topbar_layout.addWidget(self.btn_sidebar_toggle)

        self.lbl_breadcrumb = QLabel("Panel principal")
        self.lbl_breadcrumb.setObjectName("breadcrumb")
        self.lbl_breadcrumb.setWordWrap(False)
        topbar_layout.addWidget(self.lbl_breadcrumb)
        topbar_layout.addStretch(1)

        # Los selectores de Modo/Tema se ubican en el pie de la barra lateral
        # (WinUI 3). Se crean aquí para conservar los atributos existentes.
        self.combo_ui_mode = QComboBox()
        self.combo_ui_mode.addItem("Básico", "simple")
        self.combo_ui_mode.addItem("Avanzado", "advanced")
        self.combo_ui_mode.setToolTip(
            "Básico muestra solo las opciones esenciales. Avanzado habilita "
            "multiventana, privilegios, imágenes y parámetros técnicos."
        )
        self.combo_ui_mode.currentIndexChanged.connect(self._on_mode_changed)

        self.combo_theme = QComboBox()
        self.combo_theme.addItem("Claro", "light")
        self.combo_theme.addItem("Oscuro", "dark")
        self.combo_theme.currentIndexChanged.connect(self._on_theme_changed)

        self.lbl_global_status = QLabel("Configuracion sin validar")
        self.lbl_global_status.setObjectName("globalStatus")
        topbar_layout.addWidget(self.lbl_global_status)
        content_layout.addWidget(topbar)

        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1)

        self.help_panel = HelpPanel()
        self.help_panel.setVisible(False)
        content_layout.addWidget(self.help_panel)

        footer = QFrame()
        footer.setObjectName("wizardFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(14, 10, 14, 10)
        footer_layout.setSpacing(8)

        self.lbl_wizard_status = QLabel("")
        self.lbl_wizard_status.setObjectName("wizardStatus")
        self.lbl_wizard_status.setWordWrap(True)
        footer_layout.addWidget(self.lbl_wizard_status)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)

        self.btn_back = QPushButton("← Anterior")
        self.btn_back.clicked.connect(self._on_back)
        actions.addWidget(self.btn_back)

        self.btn_validate_step = QPushButton("Validar paso")
        self.btn_validate_step.setToolTip(
            "Valida los datos de la etapa actual y muestra los errores criticos."
        )
        self.btn_validate_step.clicked.connect(self._on_validate_step)
        actions.addWidget(self.btn_validate_step)

        self.btn_save = QPushButton("Guardar")
        self.btn_save.setToolTip("Guarda la configuracion actual en las preferencias.")
        self.btn_save.clicked.connect(self._on_save)
        actions.addWidget(self.btn_save)

        self.btn_help = QPushButton("Ayuda")
        self.btn_help.clicked.connect(self._on_help)
        actions.addWidget(self.btn_help)

        self.btn_next = QPushButton("Siguiente →")
        self.btn_next.setObjectName("primaryAction")
        self.btn_next.clicked.connect(self._on_next)
        actions.addWidget(self.btn_next)

        footer_layout.addLayout(actions)
        content_layout.addWidget(footer)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("mainSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(6)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(content)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([270, 1050])
        root.addWidget(self.splitter)
        self.setCentralWidget(central)

    def _toggle_sidebar(self):
        collapsed = self.sidebar.isVisible()
        self.sidebar.setVisible(not collapsed)
        self._sidebar_collapsed = collapsed
        self.btn_sidebar_toggle.setText("☰" if collapsed else "‹")
        self.btn_sidebar_toggle.setToolTip(
            "Mostrar la barra lateral." if collapsed else "Ocultar la barra lateral."
        )
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, self._reposition_nav_pill)

    def _build_sidebar(self):
        brand = QLabel("Creador Personalizado")
        brand.setObjectName("brandTitle")
        brand.setWordWrap(True)
        self.sidebar_layout.addWidget(brand)

        subtitle = QLabel("Constructor de distribuciones Fedora")
        subtitle.setObjectName("brandSubtitle")
        subtitle.setWordWrap(True)
        self.sidebar_layout.addWidget(subtitle)

        self.btn_sidebar_new = QPushButton("+ Nuevo proyecto")
        self.btn_sidebar_new.setObjectName("sidebarNewProjectButton")
        self.btn_sidebar_new.setToolTip(
            "Crea una configuración nueva y elige la modalidad en el paso 1."
        )
        self.btn_sidebar_new.clicked.connect(
            lambda: self._navigate("step1", validate=False)
        )
        self.sidebar_layout.addWidget(self.btn_sidebar_new)
        self.sidebar_layout.addSpacing(6)

        section = QLabel("ASISTENTE")
        section.setObjectName("sidebarSection")
        self.sidebar_layout.addWidget(section)

        for key, label in NAV_ITEMS:
            self._add_nav_button(key, label)
        self._add_nav_button("kiosk_config", "Configuración Kiosco")

        separator = QFrame()
        separator.setObjectName("navSeparator")
        self.sidebar_layout.addWidget(separator)

        tools = QLabel("HERRAMIENTAS")
        tools.setObjectName("sidebarSection")
        self.sidebar_layout.addWidget(tools)
        self._add_nav_button("custom_distro", "Gestor de software")
        self._add_nav_button("usb", "Unidad USB")

        self.sidebar_layout.addStretch(1)

        # Ajustes globales (WinUI 3)
        settings_div = QFrame()
        settings_div.setObjectName("sidebarDivider")
        settings_div.setFrameShape(QFrame.Shape.HLine)
        self.sidebar_layout.addWidget(settings_div)

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(8, 0, 8, 0)
        mode_row.setSpacing(8)
        mode_label = QLabel("Modo")
        mode_label.setObjectName("sidebarFooter")
        mode_row.addWidget(mode_label)
        self.combo_ui_mode.setMinimumHeight(30)
        mode_row.addWidget(self.combo_ui_mode, 1)
        self.sidebar_layout.addLayout(mode_row)

        theme_row = QHBoxLayout()
        theme_row.setContentsMargins(8, 0, 8, 0)
        theme_row.setSpacing(8)
        theme_label = QLabel("Tema")
        theme_label.setObjectName("sidebarFooter")
        theme_row.addWidget(theme_label)
        self.combo_theme.setMinimumHeight(30)
        theme_row.addWidget(self.combo_theme, 1)
        self.sidebar_layout.addLayout(theme_row)

        env_div = QFrame()
        env_div.setObjectName("sidebarDivider")
        env_div.setFrameShape(QFrame.Shape.HLine)
        self.sidebar_layout.addWidget(env_div)

        footer = QLabel("Fedora 44 · Python + PySide6")
        footer.setObjectName("sidebarFooter")
        footer.setWordWrap(True)
        self.sidebar_layout.addWidget(footer)

    _NAV_ICON_KEYS = {
        "dashboard": "home",
        "step1": "identity",
        "step2": "appearance",
        "step3": "software",
        "step4": "installer",
        "step5": "security",
        "step6": "build",
        "kiosk_config": "kiosk",
        "custom_distro": "manager",
        "usb": "usb",
    }

    def _add_nav_button(self, key, label):
        button = QPushButton(label)
        button.setObjectName("navButton")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumHeight(36)
        icon_name = self._NAV_ICON_KEYS.get(key)
        if icon_name:
            button.setIcon(nav_icon(icon_name, active=False, theme=getattr(self, "theme_name", "light")))
            button.setIconSize(button.iconSize().__class__(16, 16))
        button.clicked.connect(lambda checked=False, k=key: self._on_nav_clicked(k))
        self._nav_buttons[key] = button
        self.sidebar_layout.addWidget(button)

    def _refresh_nav_icons(self):
        theme = getattr(self, "theme_name", "light")
        current = getattr(self, "_current_key", "")
        for key, button in self._nav_buttons.items():
            icon_name = self._NAV_ICON_KEYS.get(key)
            if icon_name:
                button.setIcon(nav_icon(icon_name, active=(key == current), theme=theme))
                from PySide6.QtCore import QSize
                button.setIconSize(QSize(16, 16))

    def _reposition_nav_pill(self, key=None):
        key = self._current_key if key is None else key
        button = self._nav_buttons.get(key)
        if button is None or not button.isVisible():
            self._nav_pill.hide()
            return
        pos = button.mapTo(self.sidebar, QPoint(0, 0))
        y = pos.y() + (button.height() - 16) // 2
        self._nav_pill.move(4, max(0, y))
        self._nav_pill.show()
        self._nav_pill.raise_()

    def register_page(self, key, widget, title, subtitle, help_text, step=None):
        self._pages[key] = {
            "widget": widget,
            "title": title,
            "subtitle": subtitle,
            "help": help_text,
            "step": step,
        }
        self.stack.addWidget(widget)

    # -- Paginas -------------------------------------------------------------
    def _init_pages(self):
        self._init_dashboard_page()
        self.init_tab_meta()
        self.init_tab_aesthetic()
        self.init_tab_software()
        self.init_tab_installer()
        self.init_tab_security()
        self.init_tab_build()
        self.init_tab_usb()
        self.init_custom_distro()

    def _init_dashboard_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(14)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.card_last = StatusMetricCard(
            "Ultima compilacion",
            "Sin compilaciones",
            "Todavia no se genero una ISO en este equipo.",
        )
        self.card_iso = StatusMetricCard(
            "ISO generada",
            "—",
            "Ruta del archivo generado.",
        )
        self.card_hash = StatusMetricCard(
            "SHA-256",
            "—",
            "Se calcula en segundo plano cuando hay una ISO.",
        )
        self.card_disk = StatusMetricCard(
            "Espacio disponible",
            "—",
            "Volumen de salida de la ISO.",
        )
        self.card_deps = StatusMetricCard(
            "Dependencias",
            "—",
            "Herramientas y activos del host.",
        )
        self.card_services = StatusMetricCard(
            "Servicios del host",
            "—",
            "firewalld y sshd del equipo de compilacion.",
        )
        self.card_config = StatusMetricCard(
            "Configuracion activa",
            "—",
            "Resumen del asistente.",
        )
        self.card_pending = StatusMetricCard(
            "Tareas pendientes",
            "—",
            "Proximos pasos sugeridos.",
        )
        self._dashboard_cards = [
            self.card_last,
            self.card_iso,
            self.card_hash,
            self.card_disk,
            self.card_deps,
            self.card_services,
            self.card_config,
            self.card_pending,
        ]
        self.dashboard_grid = grid
        self._dashboard_columns = 2
        for index, card in enumerate(self._dashboard_cards):
            grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(grid)

        history = SectionCard(
            "Últimas compilaciones",
            "Actividad registrada por el historial local. No se inventan "
            "compilaciones: si el historial está vacío, la tabla queda vacía.",
        )
        self.table_history = QTableWidget(0, 3)
        self.table_history.setObjectName("historyTable")
        self.table_history.setHorizontalHeaderLabels(["Inicio", "Estado", "ISO"])
        self.table_history.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table_history.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table_history.setAlternatingRowColors(True)
        self.table_history.verticalHeader().setVisible(False)
        self.table_history.setMinimumHeight(132)
        self.table_history.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table_history.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table_history.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        history.add_widget(self.table_history)
        self.history_empty = EmptyState(
            "Todavía no hay compilaciones registradas",
            "El historial aparece aquí cuando una compilación termina y el "
            "motor guarda su resultado en la base local.",
        )
        history.add_widget(self.history_empty)
        layout.addWidget(history)

        self.card_errors = StatusMetricCard(
            "Ultimos errores",
            "Sin errores registrados",
            "Se muestra el ultimo fallo de compilacion.",
        )
        layout.addWidget(self.card_errors)

        actions = FlowLayout(h_spacing=10, v_spacing=10)
        self.btn_new_project = QPushButton("＋ Nuevo proyecto")
        self.btn_new_project.setObjectName("primaryAction")
        self.btn_new_project.setToolTip(
            "Abre el paso 1 para elegir explícitamente Fedora Desktop o Kiosco."
        )
        self.btn_new_project.clicked.connect(self.new_project)
        actions.addWidget(self.btn_new_project)

        self.btn_open_project = QPushButton("Abrir proyecto")
        self.btn_open_project.clicked.connect(self.open_project)
        actions.addWidget(self.btn_open_project)

        self.btn_save_project = QPushButton("Guardar proyecto")
        self.btn_save_project.clicked.connect(self.save_current_project)
        actions.addWidget(self.btn_save_project)

        self.btn_open_manager = QPushButton("Abrir gestor de software")
        self.btn_open_manager.clicked.connect(
            lambda: self._navigate("custom_distro", validate=False)
        )
        actions.addWidget(self.btn_open_manager)

        self.btn_refresh_dashboard = QPushButton("Actualizar estado")
        self.btn_refresh_dashboard.clicked.connect(self.refresh_dashboard)
        actions.addWidget(self.btn_refresh_dashboard)

        self.btn_go_wizard = QPushButton("Continuar asistente")
        self.btn_go_wizard.clicked.connect(
            lambda: self._navigate("step1", validate=False)
        )
        actions.addWidget(self.btn_go_wizard)

        self.btn_go_build = QPushButton("Ir a compilar")
        self.btn_go_build.clicked.connect(lambda: self._go_to_step(6))
        actions.addWidget(self.btn_go_build)
        layout.addLayout(actions)

        add_page(
            self,
            "dashboard",
            page,
            "Panel principal",
            "Estado real del entorno, la ultima ISO y la configuracion activa.",
            DASHBOARD_HELP,
            step=None,
        )

    def _update_dashboard_columns(self):
        """Distribuye las tarjetas segun el ancho real disponible."""
        if not hasattr(self, "dashboard_grid"):
            return
        width = self.stack.width() if hasattr(self, "stack") else self.width()
        if width <= 0:
            width = max(self.width() - 300, 320)
        columns = 3 if width >= 1000 else 2 if width >= 640 else 1
        if columns == self._dashboard_columns:
            return
        self._dashboard_columns = columns
        for card in self._dashboard_cards:
            self.dashboard_grid.removeWidget(card)
        for index, card in enumerate(self._dashboard_cards):
            self.dashboard_grid.addWidget(
                card, index // columns, index % columns
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_dashboard_columns()
        self._reposition_nav_pill()

    def showEvent(self, event):
        super().showEvent(event)
        self._reposition_nav_pill()

    # -- Navegacion del asistente -------------------------------------------
    def _step_number(self, key):
        page = self._pages.get(key)
        return page["step"] if page else None

    def _current_step(self):
        return self._step_number(self._current_key)

    def _navigate(self, key, validate=False):
        if key not in self._pages:
            return False
        if key == "kiosk_config" and self._selected_build_engine() != "kiosk":
            return False

        if validate:
            target = self._step_number(key)
            current = self._current_step()
            if target is not None:
                if current is None:
                    should_validate = target > 1
                else:
                    should_validate = target > current
                if should_validate:
                    issues = validate_until(target - 1, self.collect_config())
                    if issues:
                        self._show_issues(issues)
                        key = STEP_KEYS[issues[0].step - 1]

        self._current_key = key
        page = self._pages[key]
        self.stack.setCurrentWidget(page["widget"])

        for nav_key, button in self._nav_buttons.items():
            button.setChecked(nav_key == key)
        self._refresh_nav_icons()
        self._reposition_nav_pill(key)

        step = page["step"]
        if key == "dashboard":
            self.lbl_breadcrumb.setText("Panel principal")
            self.lbl_wizard_status.setText("Panel principal · Estado real del entorno")
        elif key == "custom_distro":
            self.lbl_breadcrumb.setText("Herramientas · Gestor de software")
            self.lbl_wizard_status.setText(
                "Herramienta independiente del asistente · consultas DNF de solo lectura"
            )
            ensure = getattr(self, "_ensure_catalog_loaded", None)
            if callable(ensure):
                ensure()
        elif key == "usb":
            self.lbl_breadcrumb.setText("Herramientas · Unidad USB")
            self.lbl_wizard_status.setText("Herramienta independiente del asistente")
        elif key == "kiosk_config":
            self.lbl_breadcrumb.setText("Kiosco · Configuración exclusiva")
            self.lbl_wizard_status.setText(
                "Opciones exclusivas del motor Kiosco · No afectan Fedora Desktop"
            )
        else:
            self.lbl_breadcrumb.setText(f"Asistente · Paso {step} de 6")
            self.lbl_wizard_status.setText(f"Paso {step} de 6 · {page['title']}")

        self.btn_back.setVisible(step is not None)
        self.btn_validate_step.setVisible(step is not None)
        self.btn_next.setVisible(step is not None and step < 6)
        self.btn_save.setVisible(True)
        self.btn_help.setVisible(True)
        if step is not None:
            self.btn_back.setText("← Anterior")
            self.btn_next.setText("Siguiente →")

        self._set_help_for(key)

        if key == "dashboard":
            self.refresh_dashboard()
            self._update_dashboard_columns()
        elif key == "step5":
            self.refresh_service_state()
        elif key == "step6":
            self.refresh_build_summary()
        elif key == "usb" and (
            self.usb_worker is None or not self.usb_worker.isRunning()
        ):
            self.refresh_usb_devices()
        return True

    def _on_nav_clicked(self, key):
        self._navigate(key, validate=True)

    def _go_to_step(self, step):
        self._navigate(STEP_KEYS[step - 1], validate=True)

    def _on_next(self):
        step = self._current_step()
        if step is None or step >= 6:
            return
        if not self._validate_step(step, report=True):
            return
        self._navigate(STEP_KEYS[step], validate=False)

    def _on_validate_step(self):
        step = self._current_step()
        if step is None:
            return
        issues = validate_step(step, self.collect_config())
        self._refresh_step_indicators()
        if step == 6:
            self.refresh_build_summary()
        if issues:
            self._show_issues(issues)
            self.lbl_wizard_status.setText(
                f"Paso {step} de 6 · {len(issues)} error(es) critico(s): "
                "corrija los datos antes de continuar"
            )
            return
        self.lbl_wizard_status.setText(
            f"Paso {step} de 6 · {self._pages[self._current_key]['title']} "
            "sin errores criticos ✓"
        )

    def _on_back(self):
        step = self._current_step()
        if step is None:
            return
        if step <= 1:
            self._navigate("dashboard", validate=False)
        else:
            self._navigate(STEP_KEYS[step - 2], validate=False)

    def _on_save(self):
        self._save_settings()
        self._refresh_step_indicators()
        self.lbl_wizard_status.setText(
            "Configuracion guardada · "
            + datetime.now().strftime("%H:%M")
            + " · la contrasena no se guarda"
        )
        if self._current_key == "dashboard":
            self.refresh_dashboard()

    def _on_help(self):
        visible = not self.help_panel.isVisible()
        self.help_panel.setVisible(visible)
        self.btn_help.setText("Ocultar ayuda" if visible else "Ayuda")
        if visible:
            self._set_help_for(self._current_key)

    def _set_help_for(self, key):
        page = self._pages.get(key)
        if page is None:
            return
        self.help_panel.set_content(
            f"Ayuda · {page['title']}",
            page["help"],
        )

    # -- Modo Simple / Avanzado ---------------------------------------------
    def _register_advanced(self, widget, form=None):
        self._advanced_widgets.append((widget, form))

    def _apply_ui_mode(self, mode, confirm=True):
        if mode not in ("simple", "advanced"):
            mode = "advanced"

        if mode == "simple" and confirm and self._advanced_features_active():
            reply = QMessageBox.question(
                self,
                "Cambiar a modo Simple",
                "Se desactivaran las opciones avanzadas activas "
                "(multiventana, privilegios, sandbox y paquetes "
                "extra).\n\n¿Continuar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                _set_combo_by_data(self.combo_ui_mode, self.ui_mode)
                return

        self.ui_mode = mode
        if mode == "simple":
            self._reset_advanced_features()

        advanced_visible = mode == "advanced"
        for widget, form in self._advanced_widgets:
            if form is not None:
                label = form.labelForField(widget)
                if label is not None:
                    label.setVisible(advanced_visible)
            widget.setVisible(advanced_visible)

        _set_combo_by_data(self.combo_ui_mode, mode)
        self._settings.setValue("ui_mode", mode)
        self.lbl_global_status.setText(
            "Modo Simple" if mode == "simple" else "Modo Avanzado"
        )

    def _advanced_features_active(self):
        return any(
            (
                self.check_multi_app.isChecked(),
                self.check_sudo_nopasswd.isChecked(),
                self.check_no_sandbox.isChecked(),
                self.check_ssh_password.isChecked(),
                self.check_allow_unsigned_rpms.isChecked(),
            )
        )

    def _reset_advanced_features(self):
        self.check_multi_app.setChecked(False)
        self.check_sudo_nopasswd.setChecked(False)
        self.check_no_sandbox.setChecked(False)
        self.check_ssh_password.setChecked(False)
        self.check_allow_unsigned_rpms.setChecked(False)
        self.check_vt.setChecked(True)
        self.txt_extra_packages.clear()
        self.txt_extra_groups.clear()
        # La identidad visual del instalador es parte del proyecto, no una
        # preferencia avanzada: no se elimina al cambiar a modo Simple.
        _set_combo_by_data(self.combo_res, "auto")

    def _on_mode_changed(self, *args):
        mode = self.combo_ui_mode.currentData()
        if mode == self.ui_mode:
            return
        self._apply_ui_mode(mode, confirm=True)

    # -- Tema ----------------------------------------------------------------
    def _apply_theme(self, theme):
        if theme not in ("light", "dark"):
            theme = "light"
        self.theme_name = theme
        manager = getattr(self, "theme_manager", None)
        if manager is not None:
            manager.set_theme(theme)
        else:
            # Compatibilidad durante la construcción inicial de la ventana.
            from gui.theme_manager import build_stylesheet
            QApplication.instance().setStyleSheet(build_stylesheet(theme))
        _set_combo_by_data(self.combo_theme, theme)
        self._settings.setValue("theme", theme)
        if hasattr(self, "_nav_buttons"):
            self._refresh_nav_icons()
        # Refrescar iconos SVG en tarjetas/expanders
        try:
            from gui.icons import resolve_icon
            for lbl in self.findChildren(QLabel):
                key = lbl.property("iconKey")
                if key:
                    size = max(lbl.width(), lbl.height(), 16)
                    qicon = resolve_icon(str(key), size=size)
                    if not qicon.isNull():
                        lbl.setPixmap(qicon.pixmap(size, size))
        except Exception:
            pass

    def _on_theme_manager_changed(self, theme):
        self.theme_name = theme
        if hasattr(self, "_nav_buttons"):
            self._refresh_nav_icons()

    def _on_theme_changed(self, *args):
        theme = self.combo_theme.currentData()
        if theme == self.theme_name:
            return
        self._apply_theme(theme)

    # -- Validacion ----------------------------------------------------------
    def _validate_step(self, step, report=False):
        issues = validate_step(step, self.collect_config())
        if issues and report:
            self._show_issues(issues)
        return not issues

    def _validate_all_and_report(self, navigate=False):
        issues = validate_all(self.collect_config())
        if issues:
            self._show_issues(issues)
            if hasattr(self, "lbl_validation"):
                self.lbl_validation.setText(
                    "❌ Validacion con errores: " + issues[0].message.splitlines()[0]
                )
            if navigate:
                self._navigate(STEP_KEYS[issues[0].step - 1], validate=False)
            return False
        if hasattr(self, "lbl_validation"):
            self.lbl_validation.setText(
                "✅ Configuracion valida. Las dependencias y el espacio "
                "disponible fueron verificados."
            )
        return True

    def validate_configuration(self):
        if self._validate_all_and_report(navigate=False):
            self.lbl_global_status.setText("Configuracion validada")
        else:
            self.lbl_global_status.setText("Revisar configuracion")

    def _show_issues(self, issues):
        title = issues[0].title
        if len(issues) > 1:
            title += f" (y {len(issues) - 1} mas)"
        lines = []
        for issue in issues:
            lines.append(
                f"• Paso {issue.step} — {issue.title}:\n{issue.message}"
            )
        QMessageBox.warning(self, title, "\n\n".join(lines))

    def _refresh_step_indicators(self):
        config = self.collect_config()
        for number, key in enumerate(STEP_KEYS, start=1):
            button = self._nav_buttons.get(key)
            if button is None:
                continue
            ok = not validate_step(number, config)
            label = STEP_LABELS[key]
            button.setText(("✓  " if ok else "") + f"{number}  {label}")
            button.setToolTip(
                "Sin errores criticos en este paso."
                if ok
                else "Hay datos incompletos o invalidos en este paso."
            )

    # -- Configuracion -------------------------------------------------------
    def _selected_build_engine(self):
        """Deriva el motor del perfil activo para evitar estados desincronizados.

        ``_build_engine`` es un valor auxiliar usado al cargar perfiles antiguos;
        el tipo de proyecto es la fuente de verdad de la selección en la GUI.
        La resolución genérica conserva su prioridad para configuraciones
        persistidas o llamadas externas al asistente.
        """
        project_type = str(getattr(self, "_project_type", "kiosk") or "kiosk")
        try:
            template = get_project_template(project_type)
            return resolve_build_engine({"engine": template.get("engine"),
                                         "project_type": project_type})
        except (BuildEngineError, ValueError):
            # Compatibilidad defensiva con proyectos antiguos/desconocidos.
            try:
                return resolve_build_engine({"engine": self._build_engine})
            except BuildEngineError:
                return "kiosk"

    def refresh_project_mode_fields(self):
        """Aísla visualmente los controles propios de cada motor."""
        is_kiosk = self._selected_build_engine() == "kiosk"
        advanced = getattr(self, "ui_mode", "advanced") == "advanced"
        if hasattr(self, "group_desktop_account"):
            self.group_desktop_account.setVisible(not is_kiosk)
        if hasattr(self, "group_kiosk_security"):
            self.group_kiosk_security.setVisible(is_kiosk and advanced)
        if hasattr(self, "group_kiosk_display"):
            self.group_kiosk_display.setVisible(is_kiosk)
        if hasattr(self, "_nav_buttons") and "kiosk_config" in self._nav_buttons:
            kiosk_button = self._nav_buttons["kiosk_config"]
            kiosk_button.setVisible(True)
            kiosk_button.setEnabled(is_kiosk)
            kiosk_button.setToolTip(
                "Configuración exclusiva del perfil Kiosco."
                if is_kiosk else
                "Disponible únicamente cuando el proyecto utiliza el motor Kiosco."
            )
        if not is_kiosk and self._current_key == "kiosk_config":
            self._navigate("step3", validate=False)

    def collect_config(self):
        mode = self.combo_default_app.currentData()
        multi_app = self.check_multi_app.isChecked()
        app2_mode = self.combo_app2.currentData() if multi_app else "chromium"
        values = {
            "iso_name": self.txt_name.text().strip(),
            "version": self.txt_version.text().strip(),
            "developer": self.txt_dev.text().strip(),
            "product_name": self.txt_product_name.text().strip(),
            "release": self.combo_base.currentData(),
            "boot_mode": self.combo_boot.currentData(),
            "password": self.txt_password.text(),
            "enable_firewall": self.check_firewall.isChecked(),
            "enable_ssh": self.check_enable_ssh.isChecked(),
            "ssh_password_auth": (
                self.check_enable_ssh.isChecked()
                and self.check_ssh_password.isChecked()
            ),
            "sudo_nopasswd": self.check_sudo_nopasswd.isChecked(),
            "chromium_no_sandbox": self.check_no_sandbox.isChecked(),
            "allow_unsigned_rpms": self.check_allow_unsigned_rpms.isChecked(),
            "resolution": self.combo_res.currentData(),
            "plymouth_image": self.plymouth_field.path,
            "installer_banner": self.banner_field.path,
            "installer_text": self.txt_installer_text.toPlainText().strip(),
            "enable_installer": self.check_enable_installer.isChecked(),
            "app_mode": mode,
            "app_url": self.txt_url.text().strip(),
            "app_path": self.custom_app_path,
            "multi_app": multi_app,
            "app2_mode": app2_mode,
            "app2_url": self.txt_url2.text().strip(),
            "app2_command": self.txt_cmd2.text().strip(),
            "app2_path": self.app2_local_path,
            "extra_packages": self.txt_extra_packages.text(),
            "extra_groups": self.txt_extra_groups.text(),
            "custom_distro_mode": bool(self._custom_distro_mode),
            "project_type": getattr(self, "_project_type", "kiosk"),
            "engine": self._selected_build_engine(),
            "desktop_environment": getattr(
                self, "_desktop_environment", "gnome"
            ),
            "display_server": getattr(self, "_display_server", "wayland"),
            "desktop_user": getattr(self, "_desktop_user", "fedora"),
            "restart_on_crash": self.check_restart.isChecked(),
            "block_vt": self.check_vt.isChecked(),
            "output_dir": self.txt_output.text().strip(),
            "selected_packages": sorted(getattr(self, "_custom_pkg_names", set())),
            "selected_groups": sorted(getattr(self, "_custom_groups", set())),
            "local_rpm_paths": list(getattr(self, "_custom_local_rpm_paths", [])),
            "project_name": self._active_project_name,
            "profile_id": self._active_profile_id,
            "profile_name": (get_named_profile_template(self._active_profile_id).get("name", "") if self._active_profile_id else ""),
            "cache_enabled": getattr(self, "check_cache_enabled", None).isChecked() if getattr(self, "check_cache_enabled", None) else True,
            "hardware_modules": list(getattr(self, "_hardware_modules", [])),
        }
        # La GUI conserva el contrato dict para los mixins heredados, pero el
        # modelo tipado central valida y normaliza la configuración.
        return BuildConfig.from_mapping(values).to_dict()

    def _load_settings(self):
        """Restaura la ultima configuracion usada (nunca la contrasena)."""
        settings = self._settings

        mode = str(settings.value("ui_mode", "advanced") or "advanced")
        self.ui_mode = mode if mode in ("simple", "advanced") else "advanced"
        _set_combo_by_data(self.combo_ui_mode, self.ui_mode)

        theme = str(settings.value("theme", "light") or "light")
        self.theme_name = theme if theme in ("light", "dark") else "light"
        _set_combo_by_data(self.combo_theme, self.theme_name)

        saved_project_type = str(settings.value("project_type", "kiosk") or "kiosk")
        self._project_type = saved_project_type
        _set_combo_by_data(self.combo_project_type, saved_project_type)

        desktop_environment = str(
            settings.value("desktop_environment", "gnome") or "gnome"
        )
        self._desktop_environment = desktop_environment
        _set_combo_by_data(self.combo_desktop_env, desktop_environment)
        self._display_server = str(settings.value("display_server", "") or "")
        self.refresh_desktop_environment_fields()
        self.txt_desktop_user.setText(
            str(settings.value("desktop_user", "fedora") or "fedora")
        )

        if not settings.contains("iso_name"):
            self._restore_last_project()
            return

        self.txt_name.setText(str(settings.value("iso_name", self.txt_name.text())))
        self.txt_product_name.setText(
            str(settings.value("product_name", self.txt_product_name.text()))
        )
        self.txt_version.setText(str(settings.value("version", self.txt_version.text())))
        self.txt_dev.setText(str(settings.value("developer", self.txt_dev.text())))
        _set_combo_by_data(self.combo_boot, settings.value("boot_mode", "dual"))

        self.check_firewall.setChecked(
            _setting_bool(settings, "enable_firewall", True)
        )
        ssh_enabled = _setting_bool(settings, "enable_ssh", False)
        self.check_enable_ssh.setChecked(ssh_enabled)
        self.check_ssh_password.setChecked(
            ssh_enabled and _setting_bool(settings, "ssh_password_auth", False)
        )
        self.check_sudo_nopasswd.setChecked(
            _setting_bool(settings, "sudo_nopasswd", False)
        )

        _set_combo_by_data(self.combo_res, settings.value("resolution", "auto"))

        _set_combo_by_data(
            self.combo_default_app, settings.value("app_mode", "chromium")
        )
        self.txt_url.setText(str(settings.value("app_url", self.txt_url.text())))
        app_path = str(settings.value("app_path", "") or "")
        if app_path and os.path.exists(app_path):
            self.custom_app_path = app_path
            self.lbl_custom_app.setText(app_path)
        self.txt_extra_packages.setText(
            str(settings.value("extra_packages", "") or "")
        )
        self.txt_extra_groups.setText(
            str(settings.value("extra_groups", "") or "")
        )

        self.check_restart.setChecked(
            _setting_bool(settings, "restart_on_crash", True)
        )
        self.check_no_sandbox.setChecked(
            _setting_bool(settings, "chromium_no_sandbox", False)
        )
        self.check_allow_unsigned_rpms.blockSignals(True)
        self.check_allow_unsigned_rpms.setChecked(
            _setting_bool(settings, "allow_unsigned_rpms", False)
        )
        self.check_allow_unsigned_rpms.blockSignals(False)
        self.check_vt.setChecked(_setting_bool(settings, "block_vt", True))

        self.check_multi_app.setChecked(_setting_bool(settings, "multi_app", True))
        _set_combo_by_data(
            self.combo_app2, settings.value("app2_mode", "firefox-es")
        )
        self.txt_url2.setText(str(settings.value("app2_url", self.txt_url2.text())))
        self.txt_cmd2.setText(str(settings.value("app2_command", "") or ""))
        app2_path = str(settings.value("app2_path", "") or "")
        if app2_path and os.path.isfile(app2_path):
            self.app2_local_path = app2_path
            self.lbl_app2_local.setText(app2_path)

        self.txt_output.setText(
            str(settings.value("output_dir", self.txt_output.text()))
        )
        if hasattr(self, "check_cache_enabled"):
            self.check_cache_enabled.setChecked(
                _setting_bool(settings, "cache_enabled", True)
            )
            self.check_qemu_bios.setChecked(
                _setting_bool(settings, "qemu_bios", False)
            )
            self.check_qemu_uefi.setChecked(
                _setting_bool(settings, "qemu_uefi", False)
            )

        self.check_enable_installer.setChecked(
            _setting_bool(settings, "enable_installer", True)
        )
        installer_text = str(settings.value("installer_text", "") or "")
        if installer_text:
            self.txt_installer_text.setPlainText(installer_text)

        # Imagenes: solo se restauran si el archivo sigue existiendo.
        for field, key in (
            (self.plymouth_field, "plymouth_image"),
            (self.banner_field, "installer_banner"),
        ):
            path = str(settings.value(key, "") or "")
            if path and os.path.isfile(path):
                field.path = path
                field.source_path = path
                field.update_display()
        self._restore_last_project()

    # -- Proyectos independientes -------------------------------------------
    def _restore_last_project(self):
        """Abre el último proyecto usado; las preferencias globales no lo sustituyen."""
        path = str(self._settings.value("last_project_path", "") or "")
        if not path or not os.path.isfile(os.path.join(path, "project.json")):
            return
        try:
            record = self._project_store.load(path)
            self._apply_project_record(record)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.warning(self, "Proyecto no disponible", f"No se pudo restaurar el último proyecto:\n{exc}")

    def new_project(self):
        """Crea un proyecto nuevo desde una precarga explícita de perfil."""
        name, accepted = QInputDialog.getText(self, "Nuevo proyecto", "Nombre del proyecto:")
        if not accepted or not name.strip():
            return
        named_profiles = list_named_profiles()
        named_choices = {f"{item['name']} — Perfil guardado [{item['id']}]": item['id'] for item in named_profiles}
        generic_choices = {f"Plantilla general — {label} [{key}]": key for key, label, _tagline in list_project_types()}
        choices = list(named_choices) + list(generic_choices)
        selected, accepted = QInputDialog.getItem(
            self, "Plantilla inicial", "Elegí una precarga para este proyecto:", choices, 0, False
        )
        if not accepted or not selected:
            return
        profile_id = named_choices.get(selected, "")
        project_type = (
            next(item["project_type"] for item in named_profiles if item["id"] == profile_id)
            if profile_id else generic_choices[selected]
        )
        try:
            if self._active_project_path:
                self._persist_active_project()
            self._apply_profile_defaults(name.strip(), project_type, profile_id=profile_id)
            record = self._project_store.create(name.strip(), project_type, self.collect_config())
            self._apply_project_record(record)
            self.txt_output.setText(os.path.join(self._active_project_path, "builds"))
            self._settings.setValue("last_project_path", self._active_project_path)
            self._save_settings()
            self.lbl_global_status.setText(f"Proyecto '{name.strip()}' creado con precarga {project_type}.")
            self._navigate("step1", validate=False)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "No se pudo crear el proyecto", str(exc))

    def open_project(self):
        projects = self._project_store.list_projects()
        if not projects:
            QMessageBox.information(self, "Abrir proyecto", "Todavía no hay proyectos guardados. Creá uno nuevo para comenzar.")
            return
        labels = [f"{item['name']} — {item.get('profile_name') or item['project_type']} · {item['id'][:8]}" for item in projects]
        selected, accepted = QInputDialog.getItem(self, "Abrir proyecto", "Proyecto guardado:", labels, 0, False)
        if not accepted or not selected:
            return
        index = labels.index(selected)
        try:
            if self._active_project_path:
                self._persist_active_project()
            self._apply_project_record(self._project_store.load(projects[index]["path"]))
            self._settings.setValue("last_project_path", self._active_project_path)
            self._save_settings()
            self.lbl_global_status.setText(f"Proyecto '{self._active_project_name}' abierto.")
            self._navigate("step1", validate=False)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "No se pudo abrir el proyecto", str(exc))

    def save_current_project(self):
        if not self._active_project_path:
            self.new_project()
            return
        try:
            self._persist_active_project()
            self.lbl_global_status.setText(f"Proyecto '{self._active_project_name}' guardado.")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "No se pudo guardar", str(exc))

    def _persist_active_project(self):
        if not self._active_project_path:
            return
        record = self._project_store.save(self._active_project_path, self.collect_config())
        self._active_project_id = record["id"]
        self._active_project_name = record["name"]
        self._settings.setValue("last_project_path", self._active_project_path)

    def _apply_profile_defaults(self, project_name, project_type, profile_id=""):
        template = get_named_profile_template(profile_id) if profile_id else get_project_template(project_type)
        defaults = dict(template.get("defaults", {}))
        self._active_profile_id = profile_id
        ascii_name = unicodedata.normalize("NFKD", project_name).encode("ascii", "ignore").decode("ascii")
        iso_name = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_name).strip(".-_")[:60] or "Fedora-Personalizada"
        self._active_project_path = ""
        self._active_project_id = ""
        self._active_project_name = project_name
        self.setWindowTitle(f"Creador Personalizado 3.0.0-alpha.8 | {project_name}")
        self.txt_name.setText(iso_name)
        self.txt_product_name.setText(project_name)
        self.txt_version.setText(str(defaults.get("version", "1.0.0")))
        self.txt_dev.setText(str(defaults.get("developer", "Creador Personalizado")))
        _set_combo_by_data(self.combo_project_type, project_type)
        _set_combo_by_data(self.combo_manager_project_type, project_type)
        _set_combo_by_data(self.combo_base, str(defaults.get("release", "44")))
        _set_combo_by_data(self.combo_boot, defaults.get("boot_mode", "dual"))
        self._project_type = project_type
        self._build_engine = template.get("engine", "desktop")
        self._desktop_environment = defaults.get("desktop_environment", "gnome")
        _set_combo_by_data(self.combo_desktop_env, self._desktop_environment)
        self._display_server = str(defaults.get("display_server") or "")
        self.txt_desktop_user.setText(defaults.get("desktop_user", "fedora"))
        _set_combo_by_data(self.combo_default_app, defaults.get("app_mode", "chromium"))
        self.txt_url.setText(defaults.get("app_url", "http://localhost"))
        self.check_multi_app.setChecked(bool(defaults.get("multi_app", False)))
        _set_combo_by_data(self.combo_app2, defaults.get("app2_mode", "firefox-es"))
        self.txt_url2.setText("http://localhost")
        self.txt_cmd2.clear()
        self.custom_app_path = ""
        self.app2_local_path = ""
        self.lbl_custom_app.setText("No seleccionado")
        self.lbl_app2_local.setText("No seleccionado")
        self.check_firewall.setChecked(bool(defaults.get("enable_firewall", True)))
        self.check_enable_ssh.setChecked(bool(defaults.get("enable_ssh", False)))
        self.check_ssh_password.setChecked(False)
        self.check_sudo_nopasswd.setChecked(bool(defaults.get("sudo_nopasswd", False)))
        self.check_vt.setChecked(bool(defaults.get("block_vt", project_type == "kiosk")))
        self.check_enable_installer.setChecked(bool(defaults.get("enable_installer", True)))
        self.check_restart.setChecked(True)
        self.check_no_sandbox.setChecked(False)
        self.check_allow_unsigned_rpms.setChecked(False)
        self._custom_distro_mode = True
        packages = merge_packages(template.get("packages", []))
        self._custom_pkg_names = set(packages)
        self._custom_groups = set()
        self._restore_local_rpm_selection([])
        self.txt_extra_packages.setText(" ".join(packages))
        self.txt_extra_groups.clear()
        self.list_fedora_selected.clear()
        self.list_fedora_selected.addItems(packages)
        self._refresh_pending_table()
        self.txt_installer_text.setPlainText(
            f"Bienvenido a {project_name}.\nEsta distribución está basada en Fedora 44 y fue preparada con Creador Personalizado."
        )
        self.plymouth_field.clear()
        self.banner_field.clear()
        self.txt_output.setText(os.path.expanduser("~/ISOs"))
        _set_combo_by_data(self.combo_res, "auto")
        self.txt_password.clear()
        self._update_project_description()
        self.refresh_desktop_environment_fields()

    def _apply_project_record(self, record):
        config = dict(record.get("config") or {})
        self._active_project_path = str(record.get("path") or "")
        self._active_project_id = str(record.get("id") or "")
        self._active_project_name = str(record.get("name") or config.get("project_name") or "Proyecto")
        self._active_profile_id = str(config.get("profile_id") or record.get("profile_id") or "")
        self.setWindowTitle(f"Creador Personalizado 3.0.0-alpha.8 | {self._active_project_name}")
        if "installer_text" not in config:
            self.txt_installer_text.setPlainText(
                f"Bienvenido a {self._active_project_name}.\n"
                "Esta distribución está basada en Fedora y fue preparada con Creador Personalizado."
            )
        self.txt_password.clear()
        # Aplicar primero el tipo/motor para que los controles dependientes se actualicen.
        project_type = str(config.get("project_type") or record.get("project_type") or "custom")
        _set_combo_by_data(self.combo_project_type, project_type)
        _set_combo_by_data(self.combo_manager_project_type, project_type)
        self._project_type = project_type
        self._build_engine = get_project_template(project_type)["engine"]
        for key, widget in (("iso_name", self.txt_name), ("product_name", self.txt_product_name), ("version", self.txt_version), ("developer", self.txt_dev), ("desktop_user", self.txt_desktop_user), ("app_url", self.txt_url), ("app2_url", self.txt_url2), ("app2_command", self.txt_cmd2), ("extra_packages", self.txt_extra_packages), ("extra_groups", self.txt_extra_groups), ("installer_text", self.txt_installer_text)):
            if key in config:
                if hasattr(widget, "setPlainText"):
                    widget.setPlainText(str(config[key] or ""))
                else:
                    widget.setText(str(config[key] or ""))
        for key, combo in (("release", self.combo_base), ("boot_mode", self.combo_boot), ("resolution", self.combo_res), ("app_mode", self.combo_default_app), ("app2_mode", self.combo_app2), ("desktop_environment", self.combo_desktop_env), ("display_server", self.combo_display_server)):
            if key in config:
                _set_combo_by_data(combo, config[key])
        self._desktop_environment = str(config.get("desktop_environment") or "gnome")
        self._display_server = str(config.get("display_server") or "")
        self._desktop_user = str(config.get("desktop_user") or "fedora")
        self.check_enable_installer.setChecked(bool(config.get("enable_installer", True)))
        for key, widget in (("enable_firewall", self.check_firewall), ("enable_ssh", self.check_enable_ssh), ("ssh_password_auth", self.check_ssh_password), ("sudo_nopasswd", self.check_sudo_nopasswd), ("chromium_no_sandbox", self.check_no_sandbox), ("allow_unsigned_rpms", self.check_allow_unsigned_rpms), ("restart_on_crash", self.check_restart), ("block_vt", self.check_vt), ("multi_app", self.check_multi_app)):
            if key in config:
                widget.setChecked(bool(config[key]))
        if "output_dir" in config:
            self.txt_output.setText(str(config["output_dir"] or ""))
        self.custom_app_path = str(config.get("app_path") or "")
        self.app2_local_path = str(config.get("app2_path") or "")
        self.lbl_custom_app.setText(self.custom_app_path or "No seleccionado")
        self.lbl_app2_local.setText(self.app2_local_path or "No seleccionado")
        for field, key in ((self.plymouth_field, "plymouth_image"), (self.banner_field, "installer_banner")):
            path = str(config.get(key) or "")
            if path and os.path.isfile(path):
                field.path = path
                field.source_path = path
                field.update_display()
            else:
                field.clear()
        self._custom_pkg_names = set(config.get("selected_packages") or [])
        self._custom_groups = set(config.get("selected_groups") or [])
        self._restore_local_rpm_selection(config.get("local_rpm_paths") or [])
        if not self._custom_pkg_names and config.get("extra_packages"):
            self._custom_pkg_names = set(str(config["extra_packages"]).replace(",", " ").split())
        self._custom_distro_mode = bool(config.get("custom_distro_mode", True))
        self._refresh_pending_table()
        self._settings.setValue("last_project_path", self._active_project_path)
        self.refresh_desktop_environment_fields()
        self.refresh_project_mode_fields()
        self._update_project_description()

    def _save_settings(self):
        """Guarda la configuracion actual (la contrasena nunca se guarda)."""
        settings = self._settings
        settings.setValue("ui_mode", self.ui_mode)
        settings.setValue("theme", self.theme_name)
        settings.setValue("last_project_path", self._active_project_path)
        if self._active_project_path:
            # La configuración de distribución pertenece al proyecto activo;
            # QSettings conserva solo preferencias de interfaz y la ruta reciente.
            self._persist_active_project()
            return
        # Compatibilidad con instalaciones antiguas que todavía no tienen proyecto.
        settings.setValue("iso_name", self.txt_name.text())
        settings.setValue("product_name", self.txt_product_name.text())
        settings.setValue("version", self.txt_version.text())
        settings.setValue("developer", self.txt_dev.text())
        settings.setValue("boot_mode", self.combo_boot.currentData())
        settings.setValue("enable_firewall", self.check_firewall.isChecked())
        settings.setValue("enable_ssh", self.check_enable_ssh.isChecked())
        settings.setValue("ssh_password_auth", self.check_ssh_password.isChecked())
        settings.setValue("sudo_nopasswd", self.check_sudo_nopasswd.isChecked())
        settings.setValue("resolution", self.combo_res.currentData())
        settings.setValue("app_mode", self.combo_default_app.currentData())
        settings.setValue("app_url", self.txt_url.text())
        settings.setValue("app_path", self.custom_app_path)
        settings.setValue("extra_packages", self.txt_extra_packages.text())
        settings.setValue("extra_groups", self.txt_extra_groups.text())
        settings.setValue("project_type", getattr(self, "_project_type", "kiosk"))
        settings.setValue(
            "desktop_environment", str(getattr(self, "_desktop_environment", "gnome") or "gnome")
        )
        settings.setValue(
            "display_server", str(getattr(self, "_display_server", "") or "")
        )
        settings.setValue(
            "desktop_user", str(getattr(self, "_desktop_user", "fedora") or "fedora")
        )
        settings.setValue("restart_on_crash", self.check_restart.isChecked())
        settings.setValue("chromium_no_sandbox", self.check_no_sandbox.isChecked())
        settings.setValue("allow_unsigned_rpms", self.check_allow_unsigned_rpms.isChecked())
        settings.setValue("block_vt", self.check_vt.isChecked())
        settings.setValue("multi_app", self.check_multi_app.isChecked())
        settings.setValue("app2_mode", self.combo_app2.currentData())
        settings.setValue("app2_url", self.txt_url2.text())
        settings.setValue("app2_command", self.txt_cmd2.text())
        settings.setValue("app2_path", self.app2_local_path)
        settings.setValue("output_dir", self.txt_output.text())
        settings.setValue("enable_installer", self.check_enable_installer.isChecked())
        settings.setValue("cache_enabled", self.check_cache_enabled.isChecked())
        settings.setValue("qemu_bios", self.check_qemu_bios.isChecked())
        settings.setValue("qemu_uefi", self.check_qemu_uefi.isChecked())
        settings.setValue("installer_text", self.txt_installer_text.toPlainText())
        settings.setValue("plymouth_image", self.plymouth_field.path)
        settings.setValue("installer_banner", self.banner_field.path)

    # -- Panel de estado -----------------------------------------------------
    def refresh_dashboard(self):
        settings = self._settings
        path = str(settings.value("last_iso_path", "") or "")

        if path and os.path.isfile(path):
            stat = os.stat(path)
            size = stat.st_size
            mtime = int(stat.st_mtime)
            status = str(settings.value("last_build_status", "ok") or "ok")
            last_time = settings.value("last_build_time", "") or mtime
            state = "ok" if status == "ok" else "warn"
            badge = "GENERADA" if status == "ok" else status.upper()
            if status == "ok":
                last_detail = f"{os.path.basename(path)}\n{_size_gib(size):.2f} GiB"
            else:
                last_detail = (
                    f"Ultimo intento: {status}\n"
                    f"ISO anterior: {os.path.basename(path)} "
                    f"({_size_gib(size):.2f} GiB)"
                )
            self.card_last.set_content(
                format_timestamp(last_time) or "Sin fecha",
                last_detail,
                badge=badge,
                state=state,
            )
            self.card_iso.set_content(
                os.path.basename(path),
                f"{path}\n{_size_gib(size):.2f} GiB · modificada "
                f"{format_timestamp(mtime)}\n"
                "Estado: GENERADA · pendiente de validar y probar",
                badge="GENERADA",
                state="ok",
                copyable=True,
            )
            self._update_hash_card(path, size, mtime)
            self.card_pending.set_content(
                "Validar y probar la ISO",
                "• Validar estructura y Kickstart (laboratorio)\n"
                "• Probar arranque BIOS/UEFI en QEMU\n"
                "• Escribir a USB si corresponde",
                badge="PENDIENTE",
                state="warn",
            )
        else:
            self.card_last.set_content(
                "Sin compilaciones",
                "Todavia no se genero una ISO en este equipo.",
                badge="SIN ISO",
                state="info",
            )
            self.card_iso.set_content(
                "—",
                "La ruta aparecera aqui al terminar una compilacion.",
                badge="",
                state="info",
            )
            self.card_hash.set_content(
                "—",
                "Se calcula cuando existe una ISO generada.",
                badge="",
                state="info",
            )
            self.card_pending.set_content(
                "Completar el asistente",
                "• Revisar los seis pasos\n• Validar la configuracion\n• Generar la ISO",
                badge="PENDIENTE",
                state="warn",
            )

        disk = disk_info(self.txt_output.text())
        if disk.get("ok") is False and "error" in disk:
            self.card_disk.set_content(
                "No disponible",
                disk["error"],
                badge="ERROR",
                state="error",
            )
        else:
            free = disk["free"]
            self.card_disk.set_content(
                f"{_size_gib(free):.1f} GiB libres",
                f"{disk['path']}\nTotal {_size_gib(disk['total']):.1f} GiB · "
                f"se requieren 12 GiB para compilar",
                badge="OK" if disk["enough"] else "BAJO",
                state="ok" if disk["enough"] else "error",
            )

        dependencies = check_dependencies()
        if dependencies["ok"]:
            detail = "livecd-tools, syslinux, xorriso y lorax disponibles."
            badge = "OK"
            state = "ok"
        else:
            names = ", ".join(
                f"{item['name']} ({item['package']})"
                for item in dependencies["missing"]
            )
            detail = "Faltan: " + names
            badge = "FALTAN"
            state = "error"
        self.card_deps.set_content(
            f"{dependencies['available']}/{dependencies['total']} disponibles",
            detail,
            badge=badge,
            state=state,
        )

        if self._service_states_cache:
            self._apply_service_states(self._service_states_cache)
        else:
            self.card_services.set_content(
                "Consultando…",
                "El estado se consulta en segundo plano para no congelar la interfaz.",
                badge="HOST",
                state="info",
            )
        self._start_host_status_query()

        config = self.collect_config()
        boot_labels = {"dual": "Dual (UEFI + BIOS)", "uefi": "Solo UEFI"}
        app_labels = {
            "chromium": "Chromium",
            "firefox": "Firefox",
            "firefox-es": "Firefox es-AR",
            "custom": "Aplicacion local",
        }
        installer = "Instalador ON" if config["enable_installer"] else "Instalador OFF"
        boot_session = "Inicio Live automatico"
        if config["engine"] == "desktop":
            try:
                environment = get_desktop_environment(
                    config.get("desktop_environment") or "gnome"
                )
                engine_label = (
                    f"Desktop · {environment['name']} "
                    f"({environment['session_manager']})"
                )
            except UnknownDesktopEnvironmentError:
                engine_label = "Desktop · entorno desconocido"
        else:
            engine_label = "Kiosco · Cage/Sway"
        self.card_config.set_content(
            config["iso_name"] or "Sin nombre",
            f"Producto: {config['product_name'] or 'Fedora Linux'}\n"
            f"Motor: {engine_label}\n"
            f"Arranque: {boot_labels.get(config['boot_mode'], config['boot_mode'])}\n"
            f"App: {app_labels.get(config['app_mode'], config['app_mode'])}\n"
            f"{installer} · {boot_session}",
            badge=self.ui_mode.upper(),
            state="info",
        )

        last_error = str(settings.value("last_build_error", "") or "")
        if last_error:
            self.card_errors.set_content(
                "Ultimo fallo registrado",
                last_error,
                badge="ERROR",
                state="error",
            )
        else:
            self.card_errors.set_content(
                "Sin errores registrados",
                "No hay fallos de compilacion guardados.",
                badge="OK",
                state="ok",
            )

        if dependencies["ok"]:
            self.lbl_global_status.setText(
                "Entorno listo" if path else "Entorno listo · sin ISO"
            )
        else:
            self.lbl_global_status.setText("Faltan dependencias")

        self._refresh_step_indicators()
        self._refresh_history_table()

    def _refresh_history_table(self):
        """Muestra solo compilaciones que existen en el historial local."""
        if not hasattr(self, "table_history"):
            return
        rows = recent_builds(5)
        labels = {
            "RUNNING": "En curso",
            "GENERATED": "Generada",
            "VALIDATED": "Validada",
            "TESTED": "Probada",
            "FAILED": "Fallida",
            "CANCELLED": "Cancelada",
        }
        self.table_history.setRowCount(len(rows))
        for index, row in enumerate(rows):
            iso_path = str(row.get("iso_path") or "")
            iso_label = os.path.basename(iso_path) if iso_path else "—"
            values = (
                format_timestamp(row.get("started_at")) or "Sin fecha",
                labels.get(str(row.get("status") or ""), str(row.get("status") or "")),
                iso_label,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 2 and iso_path:
                    item.setToolTip(iso_path)
                self.table_history.setItem(index, column, item)
            error = str(row.get("error") or "")
            if error:
                for column in range(3):
                    item = self.table_history.item(index, column)
                    if item is not None:
                        item.setToolTip(error)
        self.table_history.setVisible(bool(rows))
        self.history_empty.setVisible(not rows)

    def _apply_service_states(self, states):
        text = " · ".join(f"{name}: {value}" for name, value in states.items())
        self.card_services.set_content(
            text or "Sin datos",
            "Estado del host de compilacion, no de la ISO.",
            badge="HOST",
            state="info",
        )
        if hasattr(self, "lbl_service_state"):
            self.lbl_service_state.setText("Servicios del host: " + text)

    def _start_host_status_query(self, force=False):
        """Consulta servicios en un hilo; reutiliza el resultado reciente."""
        if self._host_status_worker is not None and self._host_status_worker.isRunning():
            return
        now = time.monotonic()
        if (
            not force
            and self._service_states_cache
            and now - self._last_host_query < 20
        ):
            return
        self._last_host_query = now
        worker = HostStatusWorker()
        worker.ready.connect(self._on_host_status_ready)
        worker.finished.connect(self._on_host_status_finished)
        self._host_status_worker = worker
        worker.start()

    def _on_host_status_ready(self, states):
        self._service_states_cache = dict(states)
        self._apply_service_states(self._service_states_cache)

    def _on_host_status_finished(self):
        self._last_host_query = time.monotonic()

    def _update_hash_card(self, path, size, mtime):
        cached_hash = str(self._settings.value("last_iso_sha256", "") or "")
        cached_size = self._settings.value("last_iso_size", 0)
        cached_mtime = self._settings.value("last_iso_mtime", 0)
        try:
            cache_matches = int(cached_size) == size and int(cached_mtime) == mtime
        except (TypeError, ValueError):
            cache_matches = False

        if cached_hash and cache_matches:
            self.card_hash.set_content(
                cached_hash[:20] + "…",
                cached_hash,
                badge="SHA-256",
                state="ok",
                copyable=True,
            )
            return

        self.card_hash.set_content(
            "Calculando…",
            "El hash se calcula en segundo plano; la interfaz sigue disponible.",
            badge="EN CURSO",
            state="info",
        )
        self._start_hash(path, size, mtime)

    def _start_hash(self, path, size, mtime):
        if self.hash_worker is not None and self.hash_worker.isRunning():
            if (
                self.hash_worker.path == path
                and self.hash_worker.size == size
                and self.hash_worker.mtime == mtime
            ):
                return
            self.hash_worker.cancel()
            self.hash_worker.wait()

        worker = HashWorker(path, size, mtime)
        worker.done.connect(self._on_hash_done)
        worker.failed.connect(self._on_hash_failed)
        self.hash_worker = worker
        worker.start()

    def _on_hash_done(self, path, digest, size, mtime):
        if path != str(self._settings.value("last_iso_path", "") or ""):
            return
        try:
            current = os.stat(path)
        except OSError:
            return
        if current.st_size != size or int(current.st_mtime) != mtime:
            # El archivo cambio mientras se calculaba: el hash ya no es valido.
            return
        self._settings.setValue("last_iso_sha256", digest)
        self._settings.setValue("last_iso_size", size)
        self._settings.setValue("last_iso_mtime", mtime)
        self.card_hash.set_content(
            digest[:20] + "…",
            digest,
            badge="SHA-256",
            state="ok",
            copyable=True,
        )

    def _on_hash_failed(self, path, message):
        self.card_hash.set_content(
            "No se pudo calcular",
            message,
            badge="ERROR",
            state="error",
        )

    # -- Compilacion ---------------------------------------------------------
    def preview_kickstart(self):
        """Genera una receta temporal, la valida y muestra exactamente su contenido."""
        try:
            config = BuildConfig.from_mapping(self.collect_config()).to_dict()
            builder_class = resolve_builder_class(config)
            builder = builder_class(config)
            with tempfile.TemporaryDirectory(prefix="creador-kickstart-preview-") as tmp:
                builder.work_dir = tmp
                builder.ks_path = os.path.join(tmp, "preview.ks")
                if getattr(builder, "engine", "kiosk") == "desktop":
                    builder.desktop_generator.write(builder.ks_path, "")
                else:
                    builder._generate_kickstart("")
                report = validate_kickstart_file(
                    builder.ks_path, release=str(config.get("release") or "44")
                )
                content = open(builder.ks_path, encoding="utf-8").read()
            dialog = QDialog(self)
            dialog.setWindowTitle("Vista previa del Kickstart generado")
            dialog.resize(900, 700)
            layout = QVBoxLayout(dialog)
            status = QLabel(
                ("Validación oficial ksvalidator" if report.get("official")
                 else "Validación estructural interna (ksvalidator no disponible)")
                + (" · CORRECTO" if report["ok"] else " · ERRORES")
            )
            layout.addWidget(status)
            issue_text = "\\n".join(
                f"{kind.upper()}: {message}" for kind, message in report.get("issues", [])
            ) or "Sin observaciones."
            issues_label = QLabel(issue_text)
            issues_label.setWordWrap(True)
            layout.addWidget(issues_label)
            details = QPlainTextEdit()
            details.setReadOnly(True)
            details.setPlainText(content)
            layout.addWidget(details, 1)
            close = QPushButton("Cerrar")
            close.clicked.connect(dialog.accept)
            layout.addWidget(close)
            dialog.exec()
        except Exception as exc:
            QMessageBox.warning(self, "Vista previa Kickstart", str(exc))

    def start_build_process(self):
        if self.worker is not None and self.worker.isRunning():
            return

        if not self._validate_all_and_report(navigate=True):
            return

        self.refresh_build_summary()

        config = self.collect_config()
        self._last_build_error = ""
        self.btn_build.setEnabled(False)
        self.btn_build.setText("COMPILANDO...")
        self.btn_validate.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_cancel.setText("Cancelar")
        self.progress_bar.setValue(0)
        self.txt_logs.clear()
        self.lbl_validation.setText(
            "✅ Configuracion valida. Compilacion iniciada en segundo plano."
        )
        self.lbl_global_status.setText("Compilando…")

        self._save_settings()
        self.worker = BuilderWorker(config)
        self.worker.log_signal.connect(self._append_build_log)
        self.worker.progress_signal.connect(self.progress_bar.setValue)
        self.worker.iso_signal.connect(self.on_iso_ready)
        self.worker.finished_signal.connect(self.build_finished)
        self.worker.start()

    def _append_build_log(self, text):
        self.txt_logs.append(text)
        upper = text.upper()
        if "❌" in text or "ERROR" in upper or "FALLO" in upper:
            self._last_build_error = text.strip()

    def on_iso_ready(self, path):
        self._last_iso_path = path
        self.txt_usb_iso.setText(path)
        self.txt_logs.append(f"\n💽 ISO lista para escribir en USB: {path}")
        try:
            stat = os.stat(path)
        except OSError:
            return
        self._settings.setValue("last_iso_path", path)
        self._settings.setValue("last_iso_size", stat.st_size)
        self._settings.setValue("last_iso_mtime", int(stat.st_mtime))
        self._settings.setValue("last_iso_sha256", "")
        self._settings.setValue(
            "last_build_time", datetime.now().isoformat(timespec="seconds")
        )
        self.card_iso.set_content(
            os.path.basename(path),
            f"{path}\n{_size_gib(stat.st_size):.2f} GiB",
            badge="GENERADA",
            state="ok",
            copyable=True,
        )
        self._start_hash(path, stat.st_size, int(stat.st_mtime))
        self.refresh_dashboard()

    def _record_build_finished(self, success, cancelled):
        state = "ok" if success else ("cancelled" if cancelled else "error")
        self._settings.setValue("last_build_status", state)
        self._settings.setValue(
            "last_build_time", datetime.now().isoformat(timespec="seconds")
        )
        if success:
            self._settings.setValue("last_build_error", "")
            self.lbl_global_status.setText("ISO generada · pendiente de validar")
        elif cancelled:
            self._settings.setValue(
                "last_build_error", "Compilacion cancelada por el usuario."
            )
            self.lbl_global_status.setText("Compilacion cancelada")
        else:
            self._settings.setValue(
                "last_build_error",
                self._last_build_error
                or "Fallo la creacion de la ISO. Revisa el registro.",
            )
            self.lbl_global_status.setText("Error de compilacion")
        self.refresh_dashboard()

    # -- Cierre --------------------------------------------------------------
    def closeEvent(self, event):
        if self.usb_worker is not None and self.usb_worker.isRunning():
            QMessageBox.warning(
                self,
                "Escritura en curso",
                "Espera a que termine dd antes de cerrar la aplicacion.",
            )
            event.ignore()
            return
        if self.qemu_worker is not None and self.qemu_worker.isRunning():
            QMessageBox.warning(
                self, "Prueba QEMU en curso",
                "Espera a que termine la prueba de arranque en QEMU."
            )
            event.ignore()
            return
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.warning(
                self,
                "Compilacion en curso",
                "Espera a que termine livecd-creator antes de cerrar. "
                "Tambien podes cancelarla con el boton Cancelar.",
            )
            event.ignore()
            return
        # P0: un QThread DNF destruido mientras corre provoca SIGABRT al
        # cerrar la ventana. Se espera su finalizacion; si excede el margen,
        # se ignora el cierre en lugar de destruir el hilo en ejecucion.
        if self._custom_pkg_worker is not None and self._custom_pkg_worker.isRunning():
            if not self._custom_pkg_worker.wait(5000):
                QMessageBox.warning(
                    self,
                    "Consulta DNF en curso",
                    "La consulta DNF todavia esta en curso. Espera a que "
                    "termine (el limite de DNF es de 180 segundos) antes de "
                    "cerrar la aplicacion.",
                )
                event.ignore()
                return
            self._custom_pkg_worker = None
        if self._host_status_worker is not None and self._host_status_worker.isRunning():
            if not self._host_status_worker.wait(9000):
                QMessageBox.warning(
                    self,
                    "Consulta de servicios en curso",
                    "El host todavia esta respondiendo la consulta de "
                    "servicios. Intenta cerrar de nuevo en unos segundos.",
                )
                event.ignore()
                return
            self._host_status_worker = None
        if self.hash_worker is not None and self.hash_worker.isRunning():
            self.hash_worker.cancel()
            self.hash_worker.wait()
            self.hash_worker = None
        self._save_settings()
        super().closeEvent(event)


def run_headless_build(project_path: str) -> int:
    """Ejecuta un proyecto guardado sin abrir la interfaz gráfica."""
    config = load_project_config(project_path)
    config = BuildConfig.from_mapping(config).to_dict()
    engine = resolve_build_engine(config)
    if engine == "desktop" and not config.get("password") and not config.get("password_hash"):
        config["password"] = getpass.getpass("Contraseña inicial del usuario de escritorio: ")
    builder_class = resolve_builder_class(config)
    builder = builder_class(config)
    builder.log_signal.connect(lambda message: print(message, flush=True))
    builder.progress_signal.connect(lambda value: print(f"[PROGRESO] {value}%", flush=True))
    return 0 if builder.build() else 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Creador-Personalizado: constructor Fedora Desktop/Kiosco."
    )
    parser.add_argument("--build", metavar="PROJECT_JSON",
                        help="compila un project.json sin abrir la GUI")
    parser.add_argument("--headless", action="store_true",
                        help="ejecuta el build en consola (requiere --build)")
    parser.add_argument("--qemu-smoke", metavar="ISO",
                        help="ejecuta una prueba de humo QEMU sobre una ISO")
    parser.add_argument("--firmware", choices=("bios", "uefi"), default="bios",
                        help="firmware para --qemu-smoke (predeterminado: bios)")
    parser.add_argument("--qemu-timeout", type=int, default=90,
                        help="segundos máximos de prueba QEMU")
    args = parser.parse_args(argv)

    if args.qemu_smoke:
        from core.iso.qemu_smoke import run_qemu_smoke
        result = run_qemu_smoke(args.qemu_smoke, args.firmware, args.qemu_timeout)
        print(result)
        return 0 if result.get("status") in {"BOOT_MARKER_FOUND", "DISPLAY_ACTIVITY_DETECTED"} else 1
    if args.build:
        if not args.headless:
            parser.error("--build requiere --headless.")
        return run_headless_build(args.build)
    if args.headless:
        parser.error("--headless requiere --build PROJECT_JSON.")

    app = QApplication(sys.argv[:1])
    window = KioskBuilderGUI()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
