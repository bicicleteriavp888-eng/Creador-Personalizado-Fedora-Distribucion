"""Paso 3: catálogo de software y selección del escritorio."""

from gui.components import prepare_combo
from gui.layouts import add_page
from gui.ui_components import SettingExpanderCard, SettingRowCard, ToggleSwitch
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QInputDialog,
    QVBoxLayout,
    QWidget,
)
from core.hardware.scanner import scan_hardware, export_hardware_profile, load_hardware_profile
from core.desktops.environments import (
    get_desktop_environment,
    list_desktop_environments,
    supported_display_servers,
)

HELP = """
<p><b>Software de la distribución</b></p>
<p>El paso 3 concentra el acceso al catálogo único de software Fedora. Desde
el gestor se consultan repositorios, paquetes, grupos Comps y dependencias;
la selección se comparte con el proyecto y con las herramientas.</p>
<p>En el motor Fedora Desktop se elige GNOME, KDE Plasma o Xfce. El selector
muestra Wayland o X11 y deshabilita las combinaciones que no están disponibles
en Fedora 44 para ese escritorio: GNOME y Plasma usan Wayland; Xfce utiliza X11.</p>
<p>Las opciones de aplicación, Cage/Sway y multiventana del motor Kiosco
se administran en la página independiente <b>Configuración Kiosco</b>.</p>
"""


class SoftwareTabMixin:
    """Paso 3: catálogo de software y selección del escritorio."""

    def init_tab_software(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # --- Entorno gráfico Kiosco (info) ---
        self.group_env = QFrame()
        self.group_env.setObjectName("settingRowCard")
        env_layout = QVBoxLayout(self.group_env)
        env_layout.setContentsMargins(16, 14, 16, 14)
        env_layout.setSpacing(6)
        env_title = QLabel("Entorno gráfico objetivo")
        env_title.setObjectName("settingTitle")
        env_layout.addWidget(env_title)
        env_layout.addWidget(QLabel("Servidor gráfico: Wayland"))
        self.lbl_compositor = QLabel("Compositor de kiosco: Cage (pantalla completa, sin barras)")
        self.lbl_compositor.setWordWrap(True)
        self.lbl_compositor.setObjectName("settingDescription")
        env_layout.addWidget(self.lbl_compositor)
        layout.addWidget(self.group_env)

        # --- Escritorio Desktop ---
        self.group_desktop_env = SettingExpanderCard(
            "Escritorio de la distribución",
            "Seleccioná el escritorio y el servidor gráfico para el motor Fedora Desktop.",
            "🖥",
        )
        self.lbl_desktop_env_description = QLabel()
        self.lbl_desktop_env_description.setWordWrap(True)
        self.lbl_desktop_env_description.setObjectName("settingDescription")

        self.combo_desktop_env = QComboBox()
        prepare_combo(self.combo_desktop_env, 18)
        self.combo_desktop_env.setToolTip("Gestor de sesión y tipo de sesión de la distribución de escritorio.")
        for key, name, manager in list_desktop_environments():
            self.combo_desktop_env.addItem(f"{name} · {manager}", key)
        self.combo_desktop_env.currentIndexChanged.connect(self._on_desktop_environment_changed)

        self.combo_display_server = QComboBox()
        prepare_combo(self.combo_display_server, 18)
        self.combo_display_server.setToolTip(
            "Servidor gráfico de la sesión. Las opciones dependen del escritorio y de los paquetes disponibles en Fedora 44."
        )
        self.combo_display_server.currentIndexChanged.connect(self._on_display_server_changed)

        desktop_inner = QFrame()
        desktop_inner.setObjectName("settingRowCard")
        di = QVBoxLayout(desktop_inner)
        di.setContentsMargins(16, 12, 16, 12)
        di.setSpacing(8)
        di.addWidget(self.lbl_desktop_env_description)
        di.addWidget(SettingRowCard("Entorno de escritorio", "GNOME, KDE Plasma o Xfce.", "🪟", self.combo_desktop_env))
        di.addWidget(SettingRowCard("Servidor gráfico", "Wayland o X11 según compatibilidad.", "📺", self.combo_display_server))
        self.group_desktop_env.add_widget(desktop_inner)
        layout.addWidget(self.group_desktop_env)
        self.refresh_desktop_environment_fields()

        # --- Controles Kiosco (atributos preservados) ---
        self.combo_default_app = QComboBox()
        prepare_combo(self.combo_default_app, 20)
        self.combo_default_app.addItem("Chromium (kiosk Wayland)", "chromium")
        self.combo_default_app.addItem("Firefox (kiosk)", "firefox")
        self.combo_default_app.addItem("Firefox (kiosk en español es-AR)", "firefox-es")
        self.combo_default_app.addItem("Aplicación local (binario, script o RPM)", "custom")
        self.combo_default_app.currentIndexChanged.connect(self.update_app_fields)

        self.txt_url = QLineEdit("http://localhost")
        self.txt_url.setPlaceholderText("URL que abrirá el navegador en kiosco")

        self.btn_custom_app = QPushButton("Archivo / RPM...")
        self.btn_custom_app.setToolTip(
            "Selecciona el ejecutable, el script o el paquete .rpm de la app. "
            "Si eliges un .rpm, se instala dentro de la imagen y el kiosco "
            "arranca con el ejecutable que trae el paquete."
        )
        self.btn_custom_app.clicked.connect(self.select_app_file)
        self.btn_custom_dir = QPushButton("Carpeta...")
        self.btn_custom_dir.clicked.connect(self.select_app_dir)

        custom_row = QWidget()
        custom_layout = QHBoxLayout(custom_row)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(8)
        custom_layout.addWidget(self.btn_custom_app)
        custom_layout.addWidget(self.btn_custom_dir)

        self.lbl_custom_app = QLabel("No seleccionado")
        self.lbl_custom_app.setWordWrap(True)

        self.txt_extra_packages = QLineEdit()
        self.txt_extra_packages.setPlaceholderText("Sin paquetes adicionales seleccionados")
        self.txt_extra_packages.setReadOnly(True)
        self.txt_extra_groups = QLineEdit()
        self.txt_extra_groups.setPlaceholderText("Sin grupos Comps seleccionados")
        self.txt_extra_groups.setReadOnly(True)
        self.btn_open_software_manager = QPushButton("Abrir gestor de software Fedora…")
        self.btn_open_software_manager.setToolTip(
            "Abrir el catálogo único de repositorios, paquetes, grupos Comps y resolución de dependencias."
        )
        self.btn_open_software_manager.clicked.connect(lambda: self._navigate("custom_distro", validate=False))

        self.check_allow_unsigned_rpms = QCheckBox(
            "Permitir instalar RPM sin firma digital (bajo mi responsabilidad)"
        )
        self.check_allow_unsigned_rpms.setChecked(False)
        self.check_allow_unsigned_rpms.toggled.connect(self.confirm_unsigned_rpm_policy)

        self.check_restart = ToggleSwitch(checked=True)
        self.check_no_sandbox = QCheckBox("Deshabilitar sandbox de Chromium (menos seguro)")
        self.check_no_sandbox.setChecked(False)

        # --- Página Kiosco ---
        self.group_kiosk_app = QFrame()
        self.group_kiosk_app.setObjectName("settingRowCard")
        kiosk_app_layout = QVBoxLayout(self.group_kiosk_app)
        kiosk_app_layout.setContentsMargins(16, 14, 16, 14)
        kiosk_app_layout.setSpacing(8)
        kt = QLabel("Aplicación en Kiosco")
        kt.setObjectName("settingTitle")
        kiosk_app_layout.addWidget(kt)
        kiosk_app_layout.addWidget(SettingRowCard("Aplicación principal", "Navegador o aplicación local para el modo kiosco.", "📱", self.combo_default_app))
        kiosk_app_layout.addWidget(SettingRowCard("URL de inicio", "Dirección que abrirá el navegador en kiosco.", "🌐", self.txt_url))
        kiosk_app_layout.addWidget(SettingRowCard("Ruta de app propia", "Archivo, script o RPM local.", "📦", custom_row))
        kiosk_app_layout.addWidget(self.lbl_custom_app)
        self.card_allow_unsigned = SettingRowCard(
            "Permitir RPM sin firma",
            "Solo bajo tu responsabilidad; se siguen rechazando firmas inválidas o digests corruptos.",
            "⚠",
            self.check_allow_unsigned_rpms,
        )
        kiosk_app_layout.addWidget(self.card_allow_unsigned)
        kiosk_app_layout.addWidget(SettingRowCard("Reiniciar ante fallos", "Reinicia la app automáticamente si se cierra (Restart=always).", "🔁", self.check_restart))
        self.card_no_sandbox = SettingRowCard(
            "Deshabilitar sandbox de Chromium",
            "Menos seguro. Usar solo si el navegador no arranca en el hardware destino.",
            "🧪",
            self.check_no_sandbox,
        )
        kiosk_app_layout.addWidget(self.card_no_sandbox)

        # --- Multiventana ---
        self.group_multi_app = QFrame()
        self.group_multi_app.setObjectName("settingRowCard")
        multi_layout = QVBoxLayout(self.group_multi_app)
        multi_layout.setContentsMargins(16, 14, 16, 14)
        multi_layout.setSpacing(8)
        mt = QLabel("Segunda aplicación / Multiventana (Sway)")
        mt.setObjectName("settingTitle")
        multi_layout.addWidget(mt)

        self.check_multi_app = QCheckBox("Habilitar segunda aplicación con cambio de ventana (Sway)")
        self.check_multi_app.setChecked(True)
        self.check_multi_app.toggled.connect(self.update_app_fields)

        self.combo_app2 = QComboBox()
        prepare_combo(self.combo_app2, 18)
        self.combo_app2.addItem("Chromium (kiosk Wayland)", "chromium")
        self.combo_app2.addItem("Firefox (kiosk)", "firefox")
        self.combo_app2.addItem("Firefox (kiosk en español es-AR)", "firefox-es")
        self.combo_app2.addItem("Comando personalizado", "custom")
        self.combo_app2.addItem("Archivo local (binario, script o RPM)", "local")
        self.combo_app2.setCurrentIndex(self.combo_app2.findData("firefox-es"))
        self.combo_app2.currentIndexChanged.connect(self.update_app2_fields)
        self.app2_local_path = ""

        self.txt_url2 = QLineEdit("http://localhost")
        self.txt_cmd2 = QLineEdit()
        self.txt_cmd2.setPlaceholderText("ej: /usr/bin/htop o chromium --kiosk http://localhost")
        self.btn_app2_file = QPushButton("Archivo / RPM...")
        self.btn_app2_file.clicked.connect(self.select_app2_local_file)
        self.lbl_app2_local = QLabel("No seleccionado")
        self.lbl_app2_local.setWordWrap(True)
        local2_row = QWidget()
        local2_layout = QHBoxLayout(local2_row)
        local2_layout.setContentsMargins(0, 0, 0, 0)
        local2_layout.setSpacing(8)
        local2_layout.addWidget(self.btn_app2_file)
        local2_layout.addWidget(self.lbl_app2_local, 1)

        self.lbl_app2_hint = QLabel(
            "<i>La app principal va al workspace 1 y la segunda al 2. "
            "Atajos: Super+1 / Super+2 / Super+Tab; Alt+9 abre el configurador de red WiFi.</i>"
        )
        self.lbl_app2_hint.setWordWrap(True)

        multi_layout.addWidget(self.check_multi_app)
        multi_layout.addWidget(SettingRowCard("Segunda aplicación", "Aplicación para el workspace 2.", "🪟", self.combo_app2))
        multi_layout.addWidget(SettingRowCard("URL de inicio", "URL para Chromium/Firefox.", "🌐", self.txt_url2))
        multi_layout.addWidget(SettingRowCard("Comando", "Comando personalizado dentro de la imagen.", "⌨", self.txt_cmd2))
        multi_layout.addWidget(SettingRowCard("Archivo local", "Binario, script o RPM para la segunda app.", "📦", local2_row))
        multi_layout.addWidget(self.lbl_app2_hint)

        kiosk_page = QWidget()
        kiosk_layout = QVBoxLayout(kiosk_page)
        kiosk_layout.addWidget(self.group_kiosk_app)
        kiosk_layout.addWidget(self.group_multi_app)
        kiosk_layout.addStretch(1)
        add_page(
            self, "kiosk_config", kiosk_page, "Configuración Kiosco",
            "Definí la aplicación de inicio y, si lo necesitás, el modo multiventana. Estas opciones solo pertenecen al motor Kiosco.",
            "<p><b>Configuración exclusiva de Kiosco</b></p><p>Elegí Chromium, Firefox o una aplicación propia. La segunda aplicación y el cambio de ventana se ejecutan mediante Sway.</p>",
            step=None,
        )

        # --- Software de la distribución ---
        software_card = QFrame()
        software_card.setObjectName("settingRowCard")
        software_layout = QVBoxLayout(software_card)
        software_layout.setContentsMargins(16, 14, 16, 14)
        software_layout.setSpacing(8)
        st = QLabel("Software de la distribución")
        st.setObjectName("settingTitle")
        software_layout.addWidget(st)
        sh = QLabel("Elegí paquetes, grupos y dependencias desde el gestor único de software Fedora. La selección se comparte con el proyecto y con las herramientas.")
        sh.setObjectName("settingDescription")
        sh.setWordWrap(True)
        software_layout.addWidget(sh)
        software_layout.addWidget(SettingRowCard("Paquetes seleccionados", "Resumen de paquetes agregados al proyecto.", "📦", self.txt_extra_packages))
        software_layout.addWidget(SettingRowCard("Grupos Comps seleccionados", "Grupos Comps agregados al proyecto.", "🧰", self.txt_extra_groups))
        software_layout.addWidget(self.btn_open_software_manager)
        layout.addWidget(software_card)
        self.group_software = software_card

        # --- Diagnóstico de hardware ---
        hardware_card = QFrame()
        hardware_card.setObjectName("settingRowCard")
        hardware_layout = QVBoxLayout(hardware_card)
        hardware_layout.setContentsMargins(16, 14, 16, 14)
        hardware_layout.setSpacing(8)
        ht = QLabel("Diagnóstico y perfiles de hardware")
        ht.setObjectName("settingTitle")
        hardware_layout.addWidget(ht)
        hh = QLabel("Analiza PCI/USB del equipo de compilación (lspci -nnk y lsusb), sugiere paquetes Fedora y permite guardar/cargar recetas de hardware.")
        hh.setObjectName("settingDescription")
        hh.setWordWrap(True)
        hardware_layout.addWidget(hh)
        hardware_actions = QHBoxLayout()
        self.btn_scan_hardware = QPushButton("Analizar hardware del equipo")
        self.btn_scan_hardware.clicked.connect(self.scan_host_hardware)
        self.btn_export_hardware = QPushButton("Exportar perfil…")
        self.btn_export_hardware.clicked.connect(self.export_host_hardware_profile)
        self.btn_import_hardware = QPushButton("Cargar perfil…")
        self.btn_import_hardware.clicked.connect(self.import_host_hardware_profile)
        hardware_actions.addWidget(self.btn_scan_hardware)
        hardware_actions.addWidget(self.btn_export_hardware)
        hardware_actions.addWidget(self.btn_import_hardware)
        hardware_actions.addStretch(1)
        hardware_layout.addLayout(hardware_actions)
        self.lbl_hardware_scan = QLabel("Todavía no se analizó el hardware.")
        self.lbl_hardware_scan.setWordWrap(True)
        self.lbl_hardware_scan.setObjectName("settingDescription")
        hardware_layout.addWidget(self.lbl_hardware_scan)
        layout.addWidget(hardware_card)
        self._last_hardware_scan = None

        layout.addStretch(1)
        self._register_advanced(self.group_env)
        self._register_advanced(self.group_multi_app)
        self._register_advanced(self.card_allow_unsigned)
        self._register_advanced(self.card_no_sandbox)
        self.refresh_desktop_environment_fields()

        add_page(
            self, "step3", tab, "Selección de software",
            "Selección de escritorio y servidor gráfico, más el catálogo único de software Fedora.",
            HELP, step=3,
        )
        self.update_app_fields()

    def confirm_unsigned_rpm_policy(self, checked):
        """Exige una confirmación adicional al habilitar RPM sin firma."""
        if not checked:
            return
        answer = QMessageBox.warning(
            self, "Aceptar RPM sin firma",
            "Los paquetes RPM sin firma pueden haber sido modificados o contener "
            "software malicioso. Solo continúa si confías en el archivo y en su "
            "origen.\n\nSe seguirán rechazando firmas inválidas, claves desconocidas "
            "y paquetes con digests incorrectos.\n\n¿Asumes la responsabilidad?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self.check_allow_unsigned_rpms.blockSignals(True)
            self.check_allow_unsigned_rpms.setChecked(False)
            self.check_allow_unsigned_rpms.blockSignals(False)

    def update_app_fields(self, *args):
        is_custom = self.combo_default_app.currentData() == "custom"
        self.btn_custom_app.setEnabled(is_custom)
        self.btn_custom_dir.setEnabled(is_custom)
        self.lbl_custom_app.setEnabled(is_custom)
        self.txt_url.setEnabled(not is_custom)
        if self.check_multi_app.isChecked():
            self.lbl_compositor.setText(
                "Compositor de kiosco: Sway (dos apps en workspaces 1 y 2; cambio con Super+1 / Super+2 / Super+Tab; Alt+9 red WiFi)"
            )
        else:
            self.lbl_compositor.setText("Compositor de kiosco: Cage (pantalla completa, sin barras)")
        self.update_app2_fields()

    def update_app2_fields(self, *args):
        enabled = self.check_multi_app.isChecked()
        mode = self.combo_app2.currentData()
        self.combo_app2.setEnabled(enabled)
        self.txt_url2.setEnabled(enabled and mode in ("chromium", "firefox", "firefox-es"))
        self.txt_cmd2.setEnabled(enabled and mode == "custom")
        self.btn_app2_file.setEnabled(enabled and mode == "local")
        self.lbl_app2_local.setEnabled(enabled and mode == "local")
        self.lbl_app2_hint.setEnabled(enabled)

    def refresh_desktop_environment_fields(self):
        """Muestra u oculta el selector de escritorio según el motor."""
        engine = self._selected_build_engine()
        visible = engine == "desktop"
        if not hasattr(self, "group_desktop_env"):
            return
        self.group_desktop_env.setVisible(visible)
        advanced = getattr(self, "ui_mode", "advanced") == "advanced"
        if hasattr(self, "group_env"):
            self.group_env.setVisible((not visible) and advanced)
        if hasattr(self, "group_multi_app"):
            self.group_multi_app.setVisible((not visible) and advanced)
        if hasattr(self, "group_kiosk_app"):
            self.group_kiosk_app.setVisible(not visible)
        if hasattr(self, "_nav_buttons") and "kiosk_config" in self._nav_buttons:
            self._nav_buttons["kiosk_config"].setVisible(not visible)
        if not visible:
            if getattr(self, "_current_key", "") == "kiosk_config":
                self._navigate("step3", validate=False)
            return
        key = str(getattr(self, "_desktop_environment", "gnome") or "gnome")
        index = self.combo_desktop_env.findData(key)
        if index < 0:
            index = 0
            key = str(self.combo_desktop_env.itemData(0) or "gnome")
        self.combo_desktop_env.blockSignals(True)
        self.combo_desktop_env.setCurrentIndex(index)
        self.combo_desktop_env.blockSignals(False)
        environment = get_desktop_environment(key)
        current_server = str(
            getattr(self, "_display_server", environment["session_type"]) or environment["session_type"]
        ).lower()
        options = supported_display_servers(key)
        self.combo_display_server.blockSignals(True)
        self.combo_display_server.clear()
        for server, label in (("wayland", "Wayland"), ("x11", "X11")):
            self.combo_display_server.addItem(label, server)
            item = self.combo_display_server.model().item(self.combo_display_server.count() - 1)
            if server not in options:
                item.setEnabled(False)
                item.setToolTip(f"{label} no está disponible para {environment['name']} en los repositorios Fedora 44 configurados.")
        if current_server not in options:
            current_server = environment["session_type"]
        self.combo_display_server.setCurrentIndex(max(0, self.combo_display_server.findData(current_server)))
        self.combo_display_server.blockSignals(False)
        self._display_server = current_server
        self.lbl_desktop_env_description.setText(
            f"{environment['name']} · {environment['session_manager']} · sesión {current_server.upper()}"
        )

    def _on_desktop_environment_changed(self, *_args):
        key = str(self.combo_desktop_env.currentData() or "gnome")
        self._desktop_environment = key
        self.refresh_desktop_environment_fields()

    def _on_display_server_changed(self, *_args):
        server = str(self.combo_display_server.currentData() or "").lower()
        if server:
            self._display_server = server
            self.refresh_desktop_environment_description()

    def refresh_desktop_environment_description(self):
        key = str(getattr(self, "_desktop_environment", "gnome") or "gnome")
        environment = get_desktop_environment(key)
        server = str(getattr(self, "_display_server", environment["session_type"]))
        self.lbl_desktop_env_description.setText(
            f"{environment['name']} · {environment['session_manager']} · sesión {server.upper()}"
        )

    def select_app2_local_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar binario, script o RPM de la segunda aplicación", "",
            "Ejecutables y paquetes (*.rpm);;Todos los archivos (*)",
        )
        if path:
            self.app2_local_path = path
            self.lbl_app2_local.setText(path)

    def select_app_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar ejecutable, script o paquete RPM", "",
            "Ejecutables y paquetes (*.rpm);;Todos los archivos (*)",
        )
        if path:
            self.custom_app_path = path
            self.lbl_custom_app.setText(path)

    def select_app_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de la aplicación")
        if path:
            self.custom_app_path = path
            self.lbl_custom_app.setText(path)

    def scan_host_hardware(self):
        """Analiza PCI/USB y ofrece agregar solo paquetes base de Fedora."""
        try:
            report = scan_hardware()
            self._last_hardware_scan = report
            recommendations = report.get("recommendations", [])
            base = [item["package"] for item in recommendations if not item.get("requires_external_repo")]
            manual = [item["package"] for item in recommendations if item.get("requires_external_repo")]
            self.lbl_hardware_scan.setText(
                f"PCI: {len(report.get('pci_devices', []))} · USB: {len(report.get('usb_devices', []))} · "
                f"Paquetes base sugeridos: {', '.join(base) or 'ninguno'} · Controladores manuales: {', '.join(manual) or 'ninguno'}"
            )
            if base:
                reply = QMessageBox.question(
                    self, "Recomendaciones de hardware",
                    "Se detectaron estos paquetes base de Fedora:\n\n" + ", ".join(base)
                    + "\n\n¿Querés agregarlos a la selección de software? Los controladores externos no se agregarán automáticamente.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    current = [x for x in self.txt_extra_packages.text().split() if x]
                    merged = list(dict.fromkeys(current + base))
                    self.txt_extra_packages.setText(" ".join(merged))
            QMessageBox.information(
                self, "Diagnóstico de hardware",
                report.get("notice", "Análisis terminado.")
                + ("\n\nControladores de terceros: " + ", ".join(manual) + ". Requieren revisión manual y repositorio externo." if manual else "")
            )
        except Exception as exc:
            QMessageBox.warning(self, "Diagnóstico de hardware", str(exc))

    def export_host_hardware_profile(self):
        """Guarda selección y diagnóstico en un perfil JSON portable."""
        try:
            name, accepted = QInputDialog.getText(self, "Exportar perfil de hardware", "Nombre del perfil:")
            if not accepted or not name.strip():
                return
            path, _ = QFileDialog.getSaveFileName(
                self, "Guardar perfil de hardware", name.strip().replace(" ", "-") + ".json", "Perfiles JSON (*.json)"
            )
            if not path:
                return
            report = self._last_hardware_scan or scan_hardware()
            selected = [x for x in self.txt_extra_packages.text().split() if x]
            resolution = self.combo_res.currentData() or "auto"
            export_hardware_profile(path, report, name, str(resolution), selected)
            QMessageBox.information(self, "Perfil exportado", f"Perfil guardado en:\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "Exportar perfil", str(exc))

    def import_host_hardware_profile(self):
        """Carga un perfil y fusiona paquetes validados con la selección actual."""
        path, _ = QFileDialog.getOpenFileName(self, "Cargar perfil de hardware", "", "Perfiles JSON (*.json)")
        if not path:
            return
        try:
            profile = load_hardware_profile(path)
            current = [x for x in self.txt_extra_packages.text().split() if x]
            merged = list(dict.fromkeys(current + profile.get("selected_packages", [])))
            self.txt_extra_packages.setText(" ".join(merged))
            resolution = str(profile.get("resolution") or "auto")
            for index in range(self.combo_res.count()):
                if self.combo_res.itemData(index) == resolution:
                    self.combo_res.setCurrentIndex(index)
                    break
            self.lbl_hardware_scan.setText(
                f"Perfil cargado: {profile.get('name', 'sin nombre')} · {len(profile.get('selected_packages', []))} paquetes."
            )
        except Exception as exc:
            QMessageBox.warning(self, "Cargar perfil", str(exc))