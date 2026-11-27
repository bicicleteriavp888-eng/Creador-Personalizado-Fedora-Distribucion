"""Generador de Kickstart independiente para Fedora Desktop.

El motor Desktop no reutiliza ``KioskISOBuilder``: produce su propia receta con
un entorno de escritorio explícito (GNOME/GDM, KDE Plasma/SDDM o Xfce/LightDM),
usuario convencional, objetivo gráfico y servicios de escritorio. No incluye
``cage``, ``sway``, ``seatd``, ``kioskuser`` ni ``kiosk.service``.

La generación es pura: valida la configuración, arma el texto y, si se pide,
lo escribe con permisos ``0600`` porque contiene el hash SHA-512 de la
contraseña. La ejecución de ``livecd-creator`` queda para la etapa de
integración del constructor.
"""
from __future__ import annotations

import base64
import os
import re
import tempfile
import time

from core.constants import DEFAULT_MIRRORLIST, FEDORA_ARCH, FEDORA_RELEASE
from core.desktops.environments import get_desktop_environment
from core.desktops.packages import (
    SUPPORTED_BOOT_MODES,
    DesktopPackageError,
    resolve_desktop_packages,
)
from core.repositories.manager import RepositoryManager
from core.repositories.package_checker import validate_product_name
from core.security.credentials import password_hash as generate_password_hash

USERNAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
PASSWORD_HASH_PATTERN = re.compile(r"^\$6\$[./0-9A-Za-z]+\$[./0-9A-Za-z]+$")
LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:_[A-Za-z]{2})?(?:\.[A-Za-z0-9-]+)?$")
KEYBOARD_PATTERN = re.compile(r"^[A-Za-z0-9._+-]+$")
TIMEZONE_PATTERN = re.compile(r"^[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)*$")
RELEASE_PATTERN = re.compile(r"^\d{1,3}$")
ARCH_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


class DesktopKickstartError(RuntimeError):
    """Configuración inválida para generar un Kickstart de escritorio."""


class DesktopKickstartGenerator:
    """Genera el Kickstart de una imagen Fedora Desktop."""

    def __init__(self, config):
        self.config = dict(config or {})
        self.environment = get_desktop_environment(
            self.config.get("desktop_environment") or "gnome"
        )
        self.display_server = str(
            self.config.get("display_server") or self.environment["session_type"]
        ).strip().lower()

        self.release = str(self.config.get("release") or FEDORA_RELEASE).strip()
        self.arch = str(self.config.get("arch") or FEDORA_ARCH).strip()
        self.boot_mode = str(self.config.get("boot_mode") or "dual").strip().lower()

        self.iso_name = (self.config.get("iso_name") or "Fedora-Desktop").strip()
        self.version = (self.config.get("version") or "1.0").strip()
        self.developer = re.sub(
            r"[\x00-\x1f\x7f]+",
            " ",
            (self.config.get("developer") or "Creador-kiosk").strip(),
        )[:80]
        self.product_name = (self.config.get("product_name") or "").strip()

        self.username = (
            self.config.get("desktop_user")
            or self.config.get("username")
            or "fedora"
        )
        self.username = str(self.username).strip()
        self.force_password_change = bool(
            self.config.get("force_password_change", True)
        )

        self.language = str(self.config.get("language") or "es_AR.UTF-8").strip()
        self.keyboard = str(self.config.get("keyboard") or "la-latin1").strip()
        self.timezone = str(
            self.config.get("timezone") or "America/Buenos_Aires"
        ).strip()

        self.enable_firewall = bool(self.config.get("enable_firewall", True))
        self.enable_ssh = bool(self.config.get("enable_ssh", False))
        self.ssh_password_auth = bool(
            self.config.get("ssh_password_auth", False)
        )
        self.sudo_nopasswd = bool(self.config.get("sudo_nopasswd", False))
        self.enable_installer = bool(self.config.get("enable_installer", True))

        self.mirror = (
            os.environ.get("CREADOR_MIRROR")
            or os.environ.get("KIOSK_MIRROR")
            or ""
        ).rstrip("/")
        self.mirrorlist = (
            os.environ.get("CREADOR_MIRRORLIST")
            or os.environ.get("KIOSK_MIRRORLIST")
            or DEFAULT_MIRRORLIST
        ).rstrip("/")

    # -- API pública ---------------------------------------------------------

    def validate(self):
        """Valida la configuración sin generar el hash ni escribir el archivo.

        Es el punto de entrada para la comprobación previa del constructor:
        entorno conocido, usuario y metadatos válidos, contraseña o hash
        presentes y paquetes/grupos adicionales aceptados por la política.
        """
        self._validate()
        self._validate_password_source()
        self.resolve_packages()

    def resolve_packages(self):
        """Resuelve y valida los paquetes del entorno sin generar el Kickstart."""
        return resolve_desktop_packages(
            self.config.get("desktop_environment") or "gnome",
            extra_packages=" ".join([
                str(self.config.get("extra_packages", "") or ""),
                *[str(name) for name in self.config.get("local_rpm_packages", [])],
            ]).strip(),
            extra_groups=self.config.get("extra_groups", ()),
            enable_firewall=self.enable_firewall,
            enable_ssh=self.enable_ssh,
            enable_installer=self.enable_installer,
            boot_mode=self.boot_mode,
            hardware_modules=self.config.get("hardware_modules"),
            wifi_live_assistant=bool(self.config.get("wifi_live_assistant", False)),
            display_server=self.display_server,
        )

    def render(self, password_hash_value=None):
        """Devuelve el Kickstart completo como texto."""
        self._validate()
        password_hash = self._resolve_password_hash(password_hash_value)
        packages = self.resolve_packages()

        repo_lines = RepositoryManager(
            mirror=self.mirror,
            mirrorlist=self.mirrorlist,
            release=self.release,
            arch=self.arch,
        ).lines()
        local_repo = self.config.get("local_rpm_repo")
        if local_repo:
            # Ruta generada por el constructor y validada antes de livecd-creator.
            local_repo = os.path.abspath(os.path.expanduser(str(local_repo)))
            repo_lines += f'\nrepo --name=creador-local-rpms --baseurl="file://{local_repo}"'

        post_sections = [
            self._user_section(password_hash),
            self._graphical_section(),
            self._sudo_section(),
            self._branding_section(),
            self._installer_branding_section(),
            self._ssh_section(),
            self._firewall_section(),
            self._final_check_section(),
        ]
        post_body = "\n".join(
            section.strip() for section in post_sections if section.strip()
        )

        return f"""# Kickstart generado por Creador-kiosk · Motor Fedora Desktop
# Imagen: {self.iso_name} {self.version}
# Autor: {self.developer}
# Entorno: {self.environment['name']} · {self.environment['session_manager']}
# Servidor gráfico: {self.display_server.upper()}
# Base: Fedora {self.release} / {self.arch} / {self.boot_mode}
# Generado: {time.strftime('%Y-%m-%d %H:%M:%S')}
text
lang {self.language}
keyboard {self.keyboard}
timezone {self.timezone}
authselect select local --force
rootpw --lock
selinux --enforcing
{self._firewall_line()}
services --enabled={','.join(self._enabled_services())}
bootloader --location=mbr --timeout=5 --append="loglevel=7"

# --- PARTICIONAMIENTO -------------------------------------------------------
zerombr
clearpart --all
part / --size 20480 --fstype ext4

# --- REPOSITORIOS -----------------------------------------------------------
# Mirrorlist oficial con failover o mirror fijo mediante CREADOR_MIRROR.
{repo_lines}

{self._packages_section(packages)}

%post --erroronfail
{post_body}
%end
"""

    def write(self, path, password_hash_value=None):
        """Escribe el Kickstart de forma atómica con permisos ``0600``."""
        content = self.render(password_hash_value)
        target = os.path.abspath(os.path.expanduser(str(path)))
        directory = os.path.dirname(target) or "."
        os.makedirs(directory, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=".desktop-kickstart-", dir=directory, text=True
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        os.chmod(target, 0o600)
        return target

    # -- Validación ----------------------------------------------------------

    def _validate(self):
        if self.config.get("auto_install_enabled"):
            raise DesktopKickstartError(
                "Anaconda no admite Kickstart automatizado desde Live ISO. "
                "Usa una ISO Netinstall, estándar o boot.iso."
            )
        if not RELEASE_PATTERN.fullmatch(self.release):
            raise DesktopKickstartError(
                f"Versión de Fedora inválida: {self.release or '(vacía)'}"
            )
        if not ARCH_PATTERN.fullmatch(self.arch):
            raise DesktopKickstartError(
                f"Arquitectura inválida: {self.arch or '(vacía)'}"
            )
        if self.boot_mode not in SUPPORTED_BOOT_MODES:
            raise DesktopKickstartError(
                f"Modo de arranque desconocido: {self.boot_mode or '(vacío)'}. "
                f"Valores admitidos: {', '.join(SUPPORTED_BOOT_MODES)}."
            )
        if not USERNAME_PATTERN.fullmatch(self.username):
            raise DesktopKickstartError(
                "Nombre de usuario inválido: usa minúsculas, números, guion "
                "o guion bajo, con hasta 32 caracteres y sin empezar por número."
            )
        if not LANGUAGE_PATTERN.fullmatch(self.language):
            raise DesktopKickstartError(f"Idioma inválido: {self.language}")
        if not KEYBOARD_PATTERN.fullmatch(self.keyboard):
            raise DesktopKickstartError(f"Teclado inválido: {self.keyboard}")
        if not TIMEZONE_PATTERN.fullmatch(self.timezone):
            raise DesktopKickstartError(f"Zona horaria inválida: {self.timezone}")
        if self.product_name:
            error = validate_product_name(self.product_name)
            if error is not None:
                raise DesktopKickstartError(error)
        if len(self.iso_name) > 80 or any(
            ord(ch) < 32 or ord(ch) == 127 for ch in self.iso_name
        ):
            raise DesktopKickstartError(
                "El nombre de la imagen no puede superar 80 caracteres ni "
                "contener caracteres de control."
            )

    def _validate_password_source(self):
        """Comprueba que exista una contraseña o un hash válido sin generarlo."""
        password_hash_value = self.config.get("password_hash")
        if password_hash_value is not None:
            value = str(password_hash_value).strip()
            if not PASSWORD_HASH_PATTERN.fullmatch(value):
                raise DesktopKickstartError(
                    "El hash de contraseña no es un SHA-512 crypt válido ($6$...)."
                )
            return
        password = self.config.get("password")
        if password is None or str(password) == "":
            raise DesktopKickstartError(
                "Falta la contraseña inicial del usuario de escritorio."
            )

    def _resolve_password_hash(self, password_hash_value):
        if password_hash_value is None:
            password_hash_value = self.config.get("password_hash") or None
        if password_hash_value is None:
            password = self.config.get("password")
            if password is None or str(password) == "":
                raise DesktopKickstartError(
                    "Falta la contraseña inicial del usuario de escritorio."
                )
            password_hash_value = generate_password_hash(password)
        value = str(password_hash_value).strip()
        if not PASSWORD_HASH_PATTERN.fullmatch(value):
            raise DesktopKickstartError(
                "El hash de contraseña no es un SHA-512 crypt válido ($6$...)."
            )
        return value

    # -- Secciones -----------------------------------------------------------

    def _firewall_line(self):
        if not self.enable_firewall:
            return "firewall --disabled"
        suffix = " --service=ssh" if self.enable_ssh else ""
        return "firewall --enabled" + suffix

    def _enabled_services(self):
        services = ["NetworkManager", self.environment["display_manager_unit"]]
        if self.enable_firewall:
            services.append("firewalld")
        if self.enable_ssh:
            services.append("sshd")
        return services

    def _packages_section(self, packages):
        lines = ["%packages"]
        for title, entries in packages:
            lines.append(f"# --- {title} ---")
            lines.extend(entries)
        lines.append("%end")
        return "\n".join(lines)

    def _user_section(self, password_hash):
        username = self.username
        change = (
            f"chage --lastday 0 '{username}'\n"
            if self.force_password_change
            else ""
        )
        return f"""
# --- Cuenta de escritorio ---------------------------------------------------
if ! id -u '{username}' >/dev/null 2>&1; then
    useradd --create-home --groups wheel --shell /bin/bash '{username}'
fi
printf '%s\\n' '{username}:{password_hash}' | chpasswd -e
{change}"""

    def _graphical_section(self):
        service = self.environment["display_manager_service"]
        return f"""
# --- Sesión gráfica ---------------------------------------------------------
# Sesión seleccionada por el proyecto: {self.display_server.upper()}
systemctl set-default graphical.target
systemctl enable {service}
"""

    def _sudo_section(self):
        policy = "%wheel ALL=(ALL) NOPASSWD: ALL" if self.sudo_nopasswd else (
            "%wheel ALL=(ALL) ALL"
        )
        return f"""
# --- sudo para el grupo wheel ----------------------------------------------
cat > /etc/sudoers.d/90-creador-desktop <<'CREADOR_DESKTOP_EOF'
{policy}
CREADOR_DESKTOP_EOF
chmod 0440 /etc/sudoers.d/90-creador-desktop
visudo -cf /etc/sudoers.d/90-creador-desktop >/dev/null
"""

    def _branding_section(self):
        if not self.product_name:
            return ""
        pretty = f"{self.product_name} {self.version}".strip()
        system_release = f"{self.product_name} release {self.release}"
        name_b64 = base64.b64encode(self.product_name.encode("utf-8")).decode("ascii")
        pretty_b64 = base64.b64encode(pretty.encode("utf-8")).decode("ascii")
        release_b64 = base64.b64encode(
            system_release.encode("utf-8")
        ).decode("ascii")
        return f"""
# --- Identidad del producto (base64 evita interpolación shell) -------------
rm -f /etc/os-release
if [ -f /usr/lib/os-release ]; then
    sed -e '/^NAME=/d' -e '/^PRETTY_NAME=/d' /usr/lib/os-release > /etc/os-release
else
    printf 'ID=fedora\\nVERSION_ID=%s\\n' '{self.release}' > /etc/os-release
fi
printf '%s' '{name_b64}' | base64 -d > /tmp/creador-desktop-name
printf '%s' '{pretty_b64}' | base64 -d > /tmp/creador-desktop-pretty
printf 'NAME="%s"\\n' "$(cat /tmp/creador-desktop-name)" >> /etc/os-release
printf 'PRETTY_NAME="%s"\\n' "$(cat /tmp/creador-desktop-pretty)" >> /etc/os-release
chmod 0644 /etc/os-release
printf '%s' '{release_b64}' | base64 -d > /etc/system-release
rm -f /tmp/creador-desktop-name /tmp/creador-desktop-pretty
"""

    def _installer_branding_section(self):
        """Instala el banner y el texto propios del instalador de este proyecto.

        Los recursos se codifican en Base64 para evitar problemas de quoting
        en Kickstart y solo se incorporan cuando Anaconda está habilitado.
        """
        if not self.enable_installer:
            return ""

        lines = ["# --- Personalización del instalador Anaconda ----------------------------"]
        banner = str(self.config.get("installer_banner") or "").strip()
        welcome = str(self.config.get("installer_text") or "").strip()

        if banner:
            if not os.path.isfile(banner):
                raise DesktopKickstartError(
                    f"No existe la imagen banner del instalador: {banner}"
                )
            with open(banner, "rb") as stream:
                image_data = stream.read()
            if len(image_data) > 4 * 1024 * 1024:
                raise DesktopKickstartError(
                    "La imagen banner del instalador supera los 4 MiB. Usa una imagen más liviana."
                )
            encoded_image = base64.b64encode(image_data).decode("ascii")
            lines.append(f"""
mkdir -p /usr/share/anaconda/pixmaps /usr/share/pixmaps
printf '%s' '{encoded_image}' | base64 -d > /usr/share/anaconda/pixmaps/top-banner.png
cp -f /usr/share/anaconda/pixmaps/top-banner.png /usr/share/anaconda/pixmaps/banner.png
cp -f /usr/share/anaconda/pixmaps/top-banner.png /usr/share/pixmaps/installer-banner.png
""")

        if welcome:
            encoded_text = base64.b64encode(welcome.encode("utf-8")).decode("ascii")
            lines.append(f"""
mkdir -p /usr/share/anaconda/help /etc/creador-personalizado
printf '%s' '{encoded_text}' | base64 -d > /usr/share/anaconda/help/welcome.txt
printf '%s' '{encoded_text}' | base64 -d > /etc/creador-personalizado/installer-message.txt
""")

        if len(lines) == 1:
            return ""
        return "\n".join(lines)

    def _ssh_section(self):
        if not self.enable_ssh:
            return ""
        password = "yes" if self.ssh_password_auth else "no"
        return f"""
# --- SSH habilitado de forma explícita -------------------------------------
mkdir -p /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/00-creador-desktop.conf <<'CREADOR_SSH_EOF'
PasswordAuthentication {password}
KbdInteractiveAuthentication {password}
PermitRootLogin no
CREADOR_SSH_EOF
systemctl enable sshd.service
"""

    def _firewall_section(self):
        if not self.enable_firewall:
            return ""
        ssh_rule = (
            "firewall-offline-cmd --zone=public --add-service=ssh "
            ">/dev/null 2>&1 || true"
            if self.enable_ssh
            else ": # SSH deshabilitado por defecto"
        )
        return f"""
# --- Firewall: solo servicios habilitados explícitamente -------------------
systemctl enable firewalld.service
if command -v firewall-offline-cmd >/dev/null 2>&1; then
    {ssh_rule}
fi
"""

    def _final_check_section(self):
        return f"""
# --- Verificación mínima del motor Desktop ---------------------------------
test -f /usr/bin/{self.environment['display_manager']} || \\
    test -x /usr/sbin/{self.environment['display_manager']} || {{
    echo "Falta el gestor de sesión {self.environment['display_manager']}" >&2
    exit 1
}}
systemctl is-enabled {self.environment['display_manager_service']} >/dev/null
"""
