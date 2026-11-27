"""Paso 5: seguridad y servicios del sistema."""

from gui.layouts import add_page
from gui.status import service_states
from gui.ui_components import SettingRowCard, ToggleSwitch
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

HELP = """
<p><b>Seguridad y servicios</b></p>
<p>El firewall queda habilitado por defecto y solo permite SSH. SSH permanece
deshabilitado salvo que lo actives expresamente. Si habilitás SSH sin
autenticación por contraseña, necesitás una clave pública instalada de antemano.</p>
<p>La administración local usa el grupo <code>wheel</code>. La opción
<code>NOPASSWD</code> es avanzada y reduce la seguridad. El bloqueo de consolas
virtuales es una protección exclusiva del motor Kiosco.</p>
<p>Los estados de <code>firewalld</code> y <code>sshd</code> corresponden al equipo
donde corre Creador Personalizado, no a la ISO que se está construyendo.</p>
"""


class SecurityTabMixin:
    """Paso 5: seguridad y servicios (mixin de KioskBuilderGUI)."""

    def init_tab_security(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # --- Red y acceso remoto ---
        self.check_firewall = ToggleSwitch(checked=True)
        self.check_firewall.setToolTip(
            "Activa firewalld y permite solo SSH. Recomendado para equipos conectados a la red."
        )
        self.card_firewall = SettingRowCard(
            "Firewall del sistema",
            "Activa firewalld y permite solo el tráfico necesario.",
            "🛡",
            self.check_firewall,
        )
        layout.addWidget(self.card_firewall)

        self.check_enable_ssh = ToggleSwitch(checked=False)
        self.check_enable_ssh.setToolTip(
            "SSH permanece deshabilitado por defecto. Activá esta opción solo si necesitás acceso remoto."
        )
        self.card_ssh = SettingRowCard(
            "Administración remota por SSH",
            "Habilita acceso remoto seguro solo si lo necesitás.",
            "🔐",
            self.check_enable_ssh,
        )
        layout.addWidget(self.card_ssh)

        self.check_ssh_password = ToggleSwitch(checked=False)
        self.check_ssh_password.setEnabled(False)
        self.check_ssh_password.setToolTip(
            "Si se desactiva, necesitás una clave pública instalada previamente para acceder por SSH."
        )
        self.check_enable_ssh.toggled.connect(self._on_ssh_toggled)
        self.card_ssh_password = SettingRowCard(
            "Autenticación SSH con contraseña",
            "Menos seguro. Si está desactivado, se requiere clave pública.",
            "🔑",
            self.check_ssh_password,
        )
        layout.addWidget(self.card_ssh_password)

        self.lbl_service_state = QLabel("Consultando servicios del host…")
        self.lbl_service_state.setObjectName("managerStatus")
        self.lbl_service_state.setWordWrap(True)
        layout.addWidget(self.lbl_service_state)

        # --- Privilegios compartidos ---
        self.check_sudo_nopasswd = ToggleSwitch(checked=False)
        self.check_sudo_nopasswd.setToolTip(
            "Por defecto sudo pide contraseña. Activá esta opción solo si automatizás tareas administrativas."
        )
        self.card_sudo = SettingRowCard(
            "Sudo sin contraseña para wheel",
            "Opción avanzada y menos segura para administración local.",
            "⚡",
            self.check_sudo_nopasswd,
        )
        layout.addWidget(self.card_sudo)
        self.group_common_privileges = self.card_sudo

        # --- Kiosco ---
        self.check_vt = ToggleSwitch(checked=True)
        self.check_vt.setToolTip(
            "Opción exclusiva de Kiosco: desactiva getty y el auto-spawn de VTs. "
            "No elimina el cambio de VT a nivel kernel."
        )
        self.card_vt = SettingRowCard(
            "Bloquear consolas virtuales",
            "Exclusivo Kiosco: deshabilita getty en tty2…tty6.",
            "🖥",
            self.check_vt,
        )
        layout.addWidget(self.card_vt)
        self.group_kiosk_security = self.card_vt

        note = QLabel(
            "Los estados consultados corresponden al equipo donde corre Creador Personalizado. "
            "Las opciones de terminal Kiosco no se aplican a Fedora Desktop."
        )
        note.setObjectName("inlineHint")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

        self._register_advanced(self.card_ssh_password)
        self._register_advanced(self.group_common_privileges)
        self._register_advanced(self.group_kiosk_security)
        self.refresh_project_mode_fields()
        add_page(
            self, "step5", tab, "Seguridad y servicios",
            "Configurá la superficie de acceso, los privilegios y los servicios del sistema.",
            HELP, step=5,
        )
        self.refresh_service_state()

    def _on_ssh_toggled(self, enabled):
        self.check_ssh_password.setEnabled(enabled)
        if not enabled:
            self.check_ssh_password.setChecked(False)

    def refresh_service_state(self):
        """Actualiza el estado del host sin bloquear el hilo de la interfaz."""
        start = getattr(self, "_start_host_status_query", None)
        if callable(start):
            start(force=True)
            return
        states = service_states()
        self.lbl_service_state.setText(
            "Servicios del host: " + " · ".join(
                f"{name}: {state}" for name, state in states.items()
            )
        )