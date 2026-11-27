"""Backend de generacion de ISOs kiosco (Fedora + Wayland/Cage o Sway).

Este modulo genera un Kickstart dinamico y lo entrega a livecd-creator.
Todas las decisiones de la GUI llegan por el diccionario ``config``.
"""

import base64
import glob
import os
import pwd
import re
import select
import shlex
import shutil
import subprocess
import time
import traceback
import urllib.request

from PySide6.QtCore import QObject, Signal

from core.privileges import detect_privilege_prefix
from core.processes import runner as process_runner
from core.history import BuildHistory
from core.security.allowlist import validate_packages_list
from core.software.local_rpm import inspect_local_rpm, inspect_local_rpms
from core.kickstart.validator import validate_kickstart_file

# --- Constantes de la receta -------------------------------------------------

FEDORA_RELEASE = "44"
FEDORA_ARCH = "x86_64"

# Por defecto se usa el mirrorlist oficial: dnf elige mirrors cercanos y hace
# failover automatico si uno falla. KIOSK_MIRROR fuerza un mirror fijo con
# layout Fedora (releases/ + updates/), por ejemplo para un mirror local.
DEFAULT_MIRRORLIST = "https://mirrors.fedoraproject.org/mirrorlist"

# livecd-creator necesita varios GiB para el arbol de instalacion y la ISO.
# /var/tmp esta respaldado por disco (a diferencia de /tmp, que en Fedora es
# tmpfs y consume RAM).
BUILD_ROOT = "/var/tmp/creador-kiosk"
CACHE_ROOT = "/var/cache/creador-personalizado"
DEFAULT_OUTPUT_DIR = "~/ISOs"

MIN_FREE_BYTES = 12 * 1024 ** 3
MAX_PLYMOUTH_BYTES = 4 * 1024 * 1024

def _sanitize(text, maxlen, fallback):
    """Deja solo caracteres seguros para labels/nombres de archivo."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (text or "").strip())
    cleaned = cleaned.strip("-._")
    return cleaned[:maxlen] or fallback


def _dedupe(items):
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def invalid_package_names(raw):
    """Devuelve los nombres de paquete no validos de una lista separada.

    'Paquetes adicionales' termina dentro del Kickstart: un nombre con
    caracteres de shell o saltos de linea romperia el %packages.
    """
    return [
        pkg
        for pkg in re.split(r"[\s,]+", raw or "")
        if pkg and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", pkg)
    ]


def validate_product_name(value):
    """Valida el nombre de producto usado en /etc/os-release y branding.

    Devuelve ``None`` si el valor es valido (vacio incluido: desactiva el
    branding) o un mensaje de error listo para mostrar en la GUI. La GUI y el
    backend comparten esta funcion para que no existan dos criterios distintos.
    """
    value = (value or "").strip()
    if len(value) > 80:
        return "El nombre del producto admite hasta 80 caracteres."
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return (
            "El nombre del producto no puede contener caracteres de control "
            "ni saltos de linea."
        )
    if '"' in value or "\\" in value or "$" in value:
        return (
            "El nombre del producto no puede contener comillas dobles, "
            "barras invertidas ni el caracter $."
        )
    return None


class KioskISOBuilder(QObject):
    log_signal = Signal(str)
    progress_signal = Signal(int)

    def __init__(self, config):
        super().__init__()
        self.config = dict(config or {})

        self.iso_name = (self.config.get("iso_name") or "TallerArgOS-kiosk").strip()
        self.version = _sanitize(self.config.get("version") or "1.0.0", 20, "1.0.0")
        self.developer = re.sub(
            r"[\x00-\x1f\x7f]+", " ",
            (self.config.get("developer") or "Creador-kiosk").strip(),
        )[:80]
        # Nombre del producto que muestran Anaconda y el sistema instalado
        # (hostnamectl). Vacio = no tocar la identidad de Fedora.
        self.product_name = (self.config.get("product_name") or "").strip()

        self.boot_mode = (self.config.get("boot_mode") or "dual").lower()
        self.resolution = (self.config.get("resolution") or "auto").strip()
        self.block_vt = bool(self.config.get("block_vt", True))
        self.restart_on_crash = bool(self.config.get("restart_on_crash", True))

        # Modo multiventana: Sway reemplaza a Cage y permite alternar entre dos
        # aplicaciones con workspaces (Super+1 / Super+2).
        self.multi_app = bool(self.config.get("multi_app", False))
        self.app2_mode = (self.config.get("app2_mode") or "chromium").lower()
        self.app2_url = (self.config.get("app2_url") or "http://localhost").strip()
        self.app2_command = (self.config.get("app2_command") or "").strip()
        self.app2_path = (self.config.get("app2_path") or "").strip()
        self.installer_banner = (self.config.get("installer_banner") or "").strip()
        self.installer_text = (self.config.get("installer_text") or "").strip()
        self.enable_installer = bool(self.config.get("enable_installer", True))


        # Opciones de seguridad. Los valores por defecto son los mas seguros:
        # firewall activo, sudo con contrasena y sandbox de Chromium activo.
        self.enable_firewall = bool(self.config.get("enable_firewall", True))
        self.enable_ssh = bool(self.config.get("enable_ssh", False))
        self.ssh_password_auth = bool(
            self.config.get("ssh_password_auth", False)
        )
        self.sudo_nopasswd = bool(self.config.get("sudo_nopasswd", False))
        self.chromium_no_sandbox = bool(
            self.config.get("chromium_no_sandbox", False)
        )
        # El usuario kioskuser no tiene contrasena utilizable. La sesion la
        # inicia kiosk.service directamente, sin autenticacion interactiva.

        self.mirror = (os.environ.get("KIOSK_MIRROR") or "").rstrip("/")
        self.mirrorlist = (
            os.environ.get("KIOSK_MIRRORLIST") or DEFAULT_MIRRORLIST
        ).rstrip("/")
        self.release = str(self.config.get("release") or FEDORA_RELEASE)

        # UID/GID reales, incluso si la GUI se lanzo con sudo.
        try:
            self.owner_uid = int(os.environ.get("SUDO_UID") or os.getuid())
        except ValueError:
            self.owner_uid = os.getuid()
        try:
            self.owner_gid = int(os.environ.get("SUDO_GID") or os.getgid())
        except ValueError:
            self.owner_gid = os.getgid()

        self.work_dir = os.path.join(
            (os.environ.get("KIOSK_BUILD_ROOT") or BUILD_ROOT).rstrip("/"), "build"
        )
        self.tmp_dir = os.path.join(
            (os.environ.get("KIOSK_BUILD_ROOT") or BUILD_ROOT).rstrip("/"), "tmp"
        )
        self.build_root = os.path.dirname(self.work_dir)
        self.cache_dir = (
            self.config.get("cache_dir")
            or os.environ.get("CREADOR_CACHE_DIR")
            or os.environ.get("KIOSK_CACHE_DIR")
            or CACHE_ROOT
        ).rstrip("/")
        self.cache_enabled = bool(self.config.get("cache_enabled", True))
        self.ks_path = os.path.join(self.work_dir, "kiosk.ks")
        self.log_path = os.path.join(self.work_dir, "kiosk-build.log")

        self.fslabel = _sanitize(f"{self.iso_name}-{self.version}", 32, "kiosk")
        self.iso_filename = "{}-{}.iso".format(
            _sanitize(self.iso_name, 60, "kiosk"),
            _sanitize(self.version, 20, "1.0"),
        )

        self.output_dir = self.config.get("output_dir") or DEFAULT_OUTPUT_DIR

        self._priv = None
        self._app = None
        self.last_iso_path = ""
        # threading.Event opcional: el GUI lo activa para abortar el build.
        self.cancel_event = None
        self.build_id = None

    # -- API publica ---------------------------------------------------------

    def build(self):
        """Ejecuta una compilación y registra siempre su resultado en historial."""
        history = None
        status = "FAILED"
        error_text = ""
        result = False
        try:
            try:
                history = BuildHistory()
                self.build_id = history.start(
                    self.config, log_path=self.log_path
                )
                self.log_signal.emit(
                    f"🧾 Compilación registrada en historial: {self.build_id}"
                )
            except Exception as exc:  # el historial no debe impedir compilar
                self.log_signal.emit(f"⚠ No pude iniciar el historial: {exc}")

            self._raise_if_cancelled()
            self.log_signal.emit("🔎 Verificando el entorno de compilacion...")
            self._preflight()
            self.progress_signal.emit(5)

            self._prepare_dirs()
            self._cleanup_stale_builds()
            self._check_disk()

            self.log_signal.emit(
                "🔓 Modo Live: inicio automatico, sin LightDM ni contrasena."
            )
            password_hash = ""

            self.log_signal.emit("📝 Generando Kickstart dinamico...")
            self._generate_kickstart(password_hash)
            self.progress_signal.emit(15)

            result = bool(self._run_livecd())
            status = "GENERATED" if result else (
                "CANCELLED" if self.cancel_event is not None and self.cancel_event.is_set()
                else "FAILED"
            )
            return result

        except RuntimeError as exc:
            error_text = str(exc)
            if self.cancel_event is not None and self.cancel_event.is_set():
                status = "CANCELLED"
                self.log_signal.emit("🛑 Compilacion cancelada por el usuario.")
            else:
                self.log_signal.emit(f"❌ {exc}")
            return False
        except Exception as exc:  # noqa: BLE001 - se reporta en la consola GUI
            error_text = str(exc)
            self.log_signal.emit(f"💥 Fallo critico en el backend: {exc}")
            for line in traceback.format_exc().strip().splitlines():
                self.log_signal.emit("   " + line)
            return False
        finally:
            if history is not None and self.build_id:
                try:
                    history.finish(
                        self.build_id, status,
                        iso_path=self.last_iso_path if result else None,
                        error=error_text or ("La compilación no produjo una ISO." if not result else ""),
                    )
                except Exception as exc:
                    self.log_signal.emit(f"⚠ No pude cerrar el registro de historial: {exc}")

    def _raise_if_cancelled(self):
        """Aborta con RuntimeError si el GUI pidio cancelar la compilacion."""
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise RuntimeError("Compilacion cancelada por el usuario.")

    # -- Preflight -----------------------------------------------------------

    def _uses_local_rpm(self):
        """True si alguna aplicacion local seleccionada es un paquete RPM."""
        app_mode = (self.config.get("app_mode") or "").lower()
        app_path = (self.config.get("app_path") or "").lower()
        if app_mode == "custom" and app_path.endswith(".rpm"):
            return True
        return bool(
            self.multi_app
            and self.app2_mode == "local"
            and self.app2_path.lower().endswith(".rpm")
        ) or bool(self.config.get("local_rpm_paths"))

    def _preflight(self):
        missing = [
            binary
            for binary in ("livecd-creator", "openssl", "mkefiboot", "xorrisofs")
            if shutil.which(binary) is None
        ]

        # livecd-creator copia estos archivos de syslinux (del chroot o del
        # host) para que la ISO arranque por BIOS. No son dependencias RPM de
        # livecd-tools, por eso se comprueban explicitamente.
        syslinux_assets = [
            "/usr/share/syslinux/isolinux.bin",
            "/usr/share/syslinux/isohdpfx.bin",
            "/usr/share/syslinux/vesamenu.c32",
        ]
        missing_assets = [
            path for path in syslinux_assets if not os.path.isfile(path)
        ]

        # Los RPM locales se publican como repositorio con createrepo_c y se
        # inspeccionan con rpm antes de iniciar la compilacion.
        rpm_helpers = []
        if self._uses_local_rpm():
            rpm_helpers = [
                binary
                for binary in ("rpm", "createrepo_c")
                if shutil.which(binary) is None
            ]

        problems = []
        if missing:
            problems.append(
                "faltan herramientas: {}".format(", ".join(missing))
            )
        if missing_assets:
            problems.append(
                "faltan archivos de syslinux: {}".format(
                    ", ".join(missing_assets)
                )
            )
        if rpm_helpers:
            problems.append(
                "faltan herramientas para RPM locales: {}".format(
                    ", ".join(rpm_helpers)
                )
            )

        if problems:
            raise RuntimeError(
                "El host no esta listo para compilar: "
                + "; ".join(problems)
                + ". Instala las dependencias con: sudo dnf install "
                "livecd-tools openssl lorax xorriso syslinux"
                + (" createrepo_c" if rpm_helpers else "")
            )

        self._priv = self._privilege_prefix()
        self._check_repo()

    def _privilege_prefix(self):
        """Devuelve el prefijo para correr livecd-creator como root sin colgarse."""
        return detect_privilege_prefix(self.log_signal.emit)

    def _repo_lines(self):
        """Lineas ``repo`` del Kickstart (mirrorlist oficial o mirror fijo)."""
        if self.mirror:
            lines = (
                f"repo --name=fedora --baseurl={self.mirror}/releases/"
                f"{self.release}/Everything/{FEDORA_ARCH}/os/\n"
                f"repo --name=updates --baseurl={self.mirror}/updates/"
                f"{self.release}/Everything/{FEDORA_ARCH}/"
            )
        else:
            lines = (
                f"repo --name=fedora --mirrorlist={self.mirrorlist}"
                f"?repo=fedora-{self.release}&arch={FEDORA_ARCH}\n"
                f"repo --name=updates --mirrorlist={self.mirrorlist}"
                f"?repo=updates-released-f{self.release}&arch={FEDORA_ARCH}"
            )
        local_repo = getattr(self, "local_rpm_repo", "")
        if local_repo:
            lines += f'\nrepo --name=creador-local-rpms --baseurl="file://{local_repo}"'
        return lines

    def _check_repo(self):
        if self.mirror:
            url = (
                f"{self.mirror}/releases/{self.release}/Everything/"
                f"{FEDORA_ARCH}/os/repodata/repomd.xml"
            )
            self.log_signal.emit(f"🌐 Repos: mirror fijo {self.mirror}")
            try:
                request = urllib.request.Request(
                    url, method="HEAD", headers={"User-Agent": "Creador-kiosk/2.0"}
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    if response.status != 200:
                        self.log_signal.emit(
                            f"⚠ El repositorio respondio HTTP {response.status}: {url}"
                        )
            except Exception as exc:  # noqa: BLE001 - solo es un aviso
                self.log_signal.emit(
                    f"⚠ No pude verificar el repositorio ({exc}). "
                    f"Si el build falla con 404, revisa KIOSK_MIRROR={self.mirror}"
                )
            return

        url = (
            f"{self.mirrorlist}?repo=fedora-{self.release}"
            f"&arch={FEDORA_ARCH}"
        )
        self.log_signal.emit(
            "🌐 Repos: mirrorlist oficial de Fedora (failover automatico)"
        )
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "Creador-kiosk/2.0"}
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                mirrors = [
                    line.strip()
                    for line in response.read().decode("utf-8", "replace").splitlines()
                    if line.strip().startswith(("http://", "https://"))
                ]
            if not mirrors:
                self.log_signal.emit(
                    "⚠ El mirrorlist no devolvio mirrors utilizables."
                )
        except Exception as exc:  # noqa: BLE001 - solo es un aviso
            self.log_signal.emit(
                f"⚠ No pude consultar el mirrorlist ({exc}). dnf lo "
                "reintentara durante la compilacion."
            )

    def _prepare_dirs(self):
        # El cache lo escribe dnf como root; el arbol de trabajo queda a nombre
        # del usuario para poder escribir el Kickstart y leer los logs.
        # Un solo comando privilegiado: con pkexec evita varios prompts.
        script = " && ".join(
            [
                "install -d -m 0755 "
                + " ".join(
                    shlex.quote(path) for path in (self.build_root, self.cache_dir)
                ),
                "install -d -m 0755 "
                + " ".join(
                    shlex.quote(path) for path in (self.work_dir, self.tmp_dir)
                ),
                "chown -R {}:{} {}".format(
                    self.owner_uid, self.owner_gid, shlex.quote(self.work_dir)
                ),
            ]
        )
        self._must(
            self._run(self._priv + ["sh", "-c", script]),
            "preparar los directorios de trabajo",
        )

    def _cleanup_stale_builds(self):
        """Desmonta restos de builds anteriores (livecd-creator no siempre limpia)."""
        stale = sorted(glob.glob(os.path.join(self.tmp_dir, "imgcreate-*")))
        if not stale:
            return

        probe = subprocess.run(
            ["pgrep", "-f", "livecd-creator"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
        if probe.returncode == 0:
            self.log_signal.emit(
                "⚠ Hay un livecd-creator en ejecucion; no toco los restos."
            )
            return

        marker = os.path.join(self.tmp_dir, "imgcreate-")
        script = []
        for directory in stale:
            root = os.path.join(directory, "install_root")
            script.append(f"umount -R {shlex.quote(root)} 2>/dev/null || true")
        script.append(
            "losetup -a | grep -F "
            + shlex.quote(marker)
            + ' | cut -d: -f1 | while read dev; do '
            'losetup -d "$dev" 2>/dev/null || true; done'
        )
        for directory in stale:
            script.append(f"rm -rf {shlex.quote(directory)}")

        result = self._run(self._priv + ["sh", "-c", "; ".join(script)])
        if result.returncode == 0:
            self.log_signal.emit(
                f"🧹 Limpie restos de {len(stale)} compilacion(es) anterior(es)."
            )
        else:
            detail = (result.stderr or result.stdout or "").strip()
            self.log_signal.emit(
                "⚠ No pude limpiar restos de compilaciones anteriores"
                + (f": {detail}" if detail else ".")
            )

    def _check_disk(self):
        free = shutil.disk_usage(self.work_dir).free
        if free < MIN_FREE_BYTES:
            raise RuntimeError(
                "Espacio insuficiente en {}: {:.1f} GiB libres; se requieren "
                "al menos 12 GiB para iniciar la compilacion.".format(
                    self.work_dir, free / 1024 ** 3
                )
            )

        try:
            result = subprocess.run(
                ["findmnt", "-n", "-o", "FSTYPE", "-T", self.work_dir],
                capture_output=True,
                text=True,
                timeout=10,
            )
            fstype = result.stdout.strip()
        except Exception:  # noqa: BLE001
            fstype = ""

        if fstype == "tmpfs":
            raise RuntimeError(
                "El directorio de trabajo esta en tmpfs (RAM). Define "
                "KIOSK_BUILD_ROOT en un sistema de archivos respaldado por disco."
            )

    # -- Utilidades de proceso ----------------------------------------------

    @staticmethod
    def _run(cmd):
        """Fachada compatible para el ejecutor modular de procesos."""
        return process_runner.run_command(cmd)

    @staticmethod
    def _must(result, action):
        """Fachada compatible para validar el resultado de un proceso."""
        return process_runner.must(result, action)

    @staticmethod
    def _password_hash():
        """El motor Kiosco no configura contrasenas: arranca como Live."""
        return ""

    def _expand_owner_path(self, path):
        if not path.startswith("~"):
            return path
        try:
            user = os.environ.get("SUDO_USER")
            home = (
                pwd.getpwnam(user).pw_dir
                if user
                else pwd.getpwuid(self.owner_uid).pw_dir
            )
        except KeyError:
            home = os.path.expanduser("~")
        return path.replace("~", home, 1)

    # -- Resolucion de la aplicacion ----------------------------------------

    def _resolve_app(self):
        mode = (self.config.get("app_mode") or "").lower()
        if not mode:
            # Compatibilidad con configuraciones viejas sin app_mode.
            mode = "custom" if self.config.get("app_path") else "chromium"
        url = (self.config.get("app_url") or "http://localhost").strip()

        if mode == "chromium":
            return {
                "exec": self._chromium_exec(url, self.chromium_no_sandbox),
                "packages": ["chromium"],
                "copy": "",
                "chmod": "",
            }

        if mode == "firefox":
            return {
                "exec": self._firefox_exec(url),
                "packages": ["firefox", "firefox-langpacks"],
                "copy": "",
                "chmod": "",
            }

        if mode == "firefox-es":
            return self._firefox_es_app(url)

        if mode != "custom":
            raise RuntimeError(f"Modo de aplicacion desconocido: {mode}")

        source = os.path.abspath((self.config.get("app_path") or "").strip())
        if not source or not os.path.exists(source):
            raise RuntimeError(
                "Selecciona un binario o una carpeta valida para "
                "'Aplicacion local'."
            )

        if os.path.isfile(source) and source.lower().endswith(".rpm"):
            return self._resolve_rpm_app(source)

        if os.path.isfile(source):
            name = _sanitize(os.path.basename(source), 64, "kiosk-app")
            installed = f"/usr/local/bin/{name}"
            is_python = source.endswith(".py")
            target = f"/usr/bin/python3 {installed}" if is_python else installed
            copy = (
                "%post --nochroot\n"
                f"install -D -m 0755 {shlex.quote(source)} "
                f'"$INSTALL_ROOT/usr/local/bin/{name}"\n'
                "%end\n"
            )
            return {
                "exec": target,
                "packages": self._custom_runtime_packages(
                    os.path.dirname(source) or ".", source, is_python
                ),
                "copy": copy,
                "chmod": "",
            }

        base = os.path.basename(os.path.normpath(source))
        binary = None
        for candidate in (base, base + ".sh"):
            full = os.path.join(source, candidate)
            if os.path.isfile(full):
                binary = candidate
                break

        if binary is None:
            appimages = sorted(
                name
                for name in os.listdir(source)
                if name.lower().endswith(".appimage")
            )
            if len(appimages) == 1:
                binary = appimages[0]

        python_app = False
        if binary is None and os.path.isfile(os.path.join(source, "main.py")):
            python_app = True

        if binary is None and not python_app:
            raise RuntimeError(
                "No pude detectar el ejecutable dentro de la carpeta. "
                "Renombra el binario igual que la carpeta, deja un unico "
                ".AppImage o un main.py."
            )

        if python_app:
            target = "/usr/bin/python3 /opt/kiosk_app/main.py"
            chmod = ""
        else:
            # Se conserva el nombre real del binario, solo se cita para shell.
            target = "/opt/kiosk_app/" + binary
            chmod = "chmod +x " + shlex.quote(target)

        if os.path.isdir(os.path.join(source, ".venv")) or os.path.isdir(
            os.path.join(source, "venv")
        ):
            self.log_signal.emit(
                "⚠ La app incluye un entorno virtual. Se copiara, pero lo "
                "recomendado es usar los paquetes Qt/Python del sistema."
            )

        copy = (
            "%post --nochroot\n"
            'mkdir -p "$INSTALL_ROOT/opt/kiosk_app"\n'
            f"cp -a {shlex.quote(source)}/. \"$INSTALL_ROOT/opt/kiosk_app/\"\n"
            "%end\n"
        )

        return {
            "exec": target,
            "packages": self._custom_runtime_packages(source, source, python_app),
            "copy": copy,
            "chmod": chmod,
        }

    @staticmethod
    def _chromium_exec(url, no_sandbox=False):
        args = [
            "/usr/bin/chromium",
            "--ozone-platform=wayland",
            "--kiosk",
        ]
        if no_sandbox:
            args.append("--no-sandbox")
        args.extend(
            [
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-infobars",
                "--disable-session-crashed-bubble",
                "--password-store=basic",
                "--autoplay-policy=no-user-gesture-required",
                shlex.quote(url),
            ]
        )
        return " ".join(args)

    @staticmethod
    def _firefox_exec(url):
        return "/usr/bin/firefox --kiosk " + shlex.quote(url)

    def _firefox_es_app(self, url):
        """Firefox con la interfaz en espanol (es-AR).

        El Kickstart ya define lang es_AR.UTF-8 y glibc-langpack-es, pero la
        politica RequestedLocales fuerza el idioma de la interfaz aunque la
        sesion del kiosco no propague LANG.
        """
        return {
            "exec": self._firefox_exec(url),
            "packages": ["firefox", "firefox-langpacks"],
            "copy": "",
            "chmod": "",
            "post": (
                "# --- Firefox en espanol (es-AR): RequestedLocales ---\n"
                "install -d -m 0755 /etc/firefox/policies\n"
                "cat > /etc/firefox/policies/policies.json <<'KIOSK_EOF'\n"
                "{\n"
                '  "policies": {\n'
                '    "RequestedLocales": ["es-AR"]\n'
                "  }\n"
                "}\n"
                "KIOSK_EOF\n"
            ),
        }

    def _resolve_app2(self):
        """Resuelve la segunda aplicacion del modo multiventana.

        La segunda app puede ser un navegador (Chromium/Firefox), un comando
        que ya exista en la imagen (se puede instalar con 'Paquetes
        adicionales') o un archivo local (binario, script o RPM).
        """
        mode = self.app2_mode
        if mode == "chromium":
            return {
                "exec": self._chromium_exec(
                    self.app2_url, self.chromium_no_sandbox
                ),
                "packages": ["chromium"],
            }
        if mode == "firefox":
            return {
                "exec": self._firefox_exec(self.app2_url),
                "packages": ["firefox", "firefox-langpacks"],
            }
        if mode == "firefox-es":
            return self._firefox_es_app(self.app2_url)
        if mode == "local":
            source = os.path.abspath(self.app2_path)
            if not source or not os.path.isfile(source):
                raise RuntimeError(
                    "Selecciona un archivo valido para la segunda aplicacion "
                    "local."
                )
            if source.lower().endswith(".rpm"):
                return self._resolve_rpm_app(source, suffix="2")

            name = _sanitize(
                "kiosk-app2-" + os.path.basename(source), 64, "kiosk-app2"
            )
            installed = f"/usr/local/bin/{name}"
            is_python = source.endswith(".py")
            target = f"/usr/bin/python3 {installed}" if is_python else installed
            copy = (
                "%post --nochroot\n"
                f"install -D -m 0755 {shlex.quote(source)} "
                f'"$INSTALL_ROOT/usr/local/bin/{name}"\n'
                "%end\n"
            )
            return {
                "exec": target,
                "packages": self._custom_runtime_packages(
                    os.path.dirname(source) or ".", source, is_python
                ),
                "copy": copy,
                "chmod": "",
            }
        if mode != "custom":
            raise RuntimeError(f"Modo de segunda aplicacion desconocido: {mode}")

        command = self.app2_command.strip()
        if not command:
            raise RuntimeError(
                "Indica el comando de la segunda aplicacion para el modo "
                "multiventana."
            )
        if "\n" in command or "\r" in command:
            raise RuntimeError(
                "El comando de la segunda aplicacion no puede tener saltos de "
                "linea."
            )

        # Si el comando es un navegador, aseguramos su paquete. Para cualquier
        # otro programa, el usuario debe agregarlo en 'Paquetes adicionales'.
        packages = []
        try:
            first = shlex.split(command)[0]
        except (ValueError, IndexError):
            first = ""
        binary = os.path.basename(first)
        if binary in ("chromium", "chromium-browser"):
            packages = ["chromium"]
        elif binary in ("firefox", "firefox-bin"):
            packages = ["firefox", "firefox-langpacks"]

        return {"exec": command, "packages": packages}

    def _resolve_rpm_app(self, source, suffix=""):
        """Instala un RPM de la app dentro de la imagen y detecta su binario."""
        if shutil.which("rpm") is None:
            raise RuntimeError(
                "Falta el comando 'rpm' en el host para inspeccionar el paquete."
            )

        try:
            rpm_info = inspect_local_rpm(
                source,
                allow_unsigned=bool(self.config.get("allow_unsigned_rpms", False)),
            )
        except ValueError as exc:
            raise RuntimeError(
                "Se rechazó el RPM local. Las firmas inválidas, claves desconocidas "
                "y digests incorrectos o no verificables nunca se aceptan. " + str(exc)
            ) from exc
        if rpm_info["unsigned"]:
            self.log_signal.emit(
                "⚠ ADVERTENCIA: RPM sin firma aceptado por decisión explícita "
                "del usuario. Los digests del paquete fueron verificados."
            )
        package_name = rpm_info["name"]

        listing = self._must(
            self._run(
                [
                    "rpm",
                    "-qp",
                    "--qf",
                    "[%{FILENAMES}\t%{FILEMODES:perms}\n]",
                    source,
                ]
            ),
            "listar el contenido del RPM",
        ).stdout

        candidates = []
        for line in listing.splitlines():
            if "\t" not in line:
                continue
            path, perms = line.rsplit("\t", 1)
            if perms[:1] in ("d", "l") or "x" not in perms[:10]:
                continue
            if path.startswith(
                ("/usr/bin/", "/usr/local/bin/", "/usr/libexec/", "/opt/")
            ):
                candidates.append(path)

        if not candidates:
            raise RuntimeError(
                f"El RPM {os.path.basename(source)} no instala un ejecutable en "
                "/usr/bin, /usr/local/bin, /usr/libexec ni /opt. Selecciona "
                "directamente el binario de la aplicacion."
            )

        matching = [
            path
            for path in candidates
            if package_name
            and package_name.lower() in os.path.basename(path).lower()
        ]
        if len(candidates) == 1:
            target = candidates[0]
        elif len(matching) == 1:
            target = matching[0]
        else:
            listed = ", ".join(sorted(candidates)[:6])
            raise RuntimeError(
                f"El RPM instala varios ejecutables ({listed}). Selecciona "
                "directamente el binario que debe arrancar el kiosco."
            )

        if shutil.which("createrepo_c") is None:
            raise RuntimeError(
                "Falta 'createrepo_c' en el host para publicar el RPM local. "
                "Instalalo con: sudo dnf install createrepo_c"
            )

        # Publicamos el RPM como repositorio local: asi dnf resuelve sus
        # dependencias en la misma transaccion que el resto de la imagen, sin
        # volver a descargar metadatos desde dentro del chroot.
        repo_name = "kiosk-app" + suffix
        repo_dir = os.path.join(self.work_dir, "apprepo" + suffix)
        shutil.rmtree(repo_dir, ignore_errors=True)
        os.makedirs(repo_dir, exist_ok=True)
        shutil.copy2(source, os.path.join(repo_dir, os.path.basename(source)))
        self._must(
            self._run(["createrepo_c", "--quiet", repo_dir]),
            "crear el repositorio local de la aplicacion",
        )

        self.log_signal.emit(
            f"📦 Se instalara {package_name} desde {os.path.basename(source)} "
            f"y el kiosco arrancara con {target}"
        )

        return {
            "exec": shlex.quote(target),
            "packages": [package_name, "qt6-qtwayland"],
            "copy": "",
            "repo": f'repo --name={repo_name} --baseurl="file://{repo_dir}"',
            "chmod": "",
        }

    def _custom_runtime_packages(self, directory, source, python_app=False):
        packages = [
            "qt6-qtbase-gui",
            "qt6-qtwayland",
            "mesa-libEGL",
            "libglvnd-egl",
            "fontconfig",
            "dejavu-sans-fonts",
            "google-noto-sans-fonts",
        ]

        if python_app:
            packages.append("python3")
            detected = self._python_bindings(directory or os.path.dirname(source))
            if detected:
                packages.extend(detected)
            else:
                # Sin imports detectables asumimos PySide6, que es el stack del
                # proyecto. Si la app usa otra cosa, el log de dnf lo mostrara.
                packages.append("python3-pyside6")

        return _dedupe(packages)

    def _python_bindings(self, directory):
        if not directory or not os.path.isdir(directory):
            return []

        mapping = {
            "PySide6": ["python3-pyside6", "qt6-qtwayland"],
            "PyQt6": ["python3-pyqt6", "qt6-qtwayland"],
            "PyQt5": ["python3-qt5", "qt5-qtwayland"],
            "PySide2": None,
        }
        found = []
        for root, dirs, files in os.walk(directory):
            dirs[:] = [
                name
                for name in dirs
                if name
                not in (".git", "__pycache__", "node_modules", "venv", ".venv")
            ]
            depth = root[len(directory):].count(os.sep)
            if depth > 2:
                dirs[:] = []

            for name in files:
                if not name.endswith(".py"):
                    continue
                try:
                    with open(
                        os.path.join(root, name), "r", errors="ignore"
                    ) as handle:
                        text = handle.read(200_000)
                except OSError:
                    continue

                for module, packages in mapping.items():
                    if f"import {module}" in text or f"from {module}" in text:
                        if packages is None:
                            raise RuntimeError(
                                "La aplicacion usa PySide2, que no esta "
                                "disponible en Fedora 44. Migrala a PySide6."
                            )
                        found.extend(packages)

            if found:
                break

        return _dedupe(found)

    # -- Kickstart -----------------------------------------------------------

    def _generate_kickstart(self, password_hash):
        if self.boot_mode not in ("dual", "uefi"):
            raise RuntimeError(f"Modo de arranque desconocido: {self.boot_mode}")
        if self.resolution != "auto" and not re.fullmatch(
            r"\d{3,4}x\d{3,4}", self.resolution
        ):
            raise RuntimeError(f"Resolucion invalida: {self.resolution}")

        if self.boot_mode == "uefi":
            self.log_signal.emit(
                "⚠ livecd-creator 31 no genera ISOs exclusivamente UEFI. "
                "Se creara una ISO hibrida con arranque EFI incluido."
            )

        self._local_rpm_metadata = inspect_local_rpms(
            self.config.get("local_rpm_paths", []),
            allow_unsigned=bool(self.config.get("allow_unsigned_rpms", False)),
        )
        if self._local_rpm_metadata:
            if shutil.which("createrepo_c") is None:
                raise RuntimeError("Falta createrepo_c para publicar los RPM locales seleccionados.")
            self.local_rpm_repo = os.path.join(self.work_dir, "kiosk-local-rpms")
            shutil.rmtree(self.local_rpm_repo, ignore_errors=True)
            os.makedirs(self.local_rpm_repo, exist_ok=True)
            for item in self._local_rpm_metadata:
                shutil.copy2(item["path"], os.path.join(self.local_rpm_repo, os.path.basename(item["path"])))
            self._must(self._run(["createrepo_c", "--quiet", self.local_rpm_repo]),
                       "crear el repositorio de RPM locales del Kiosco")
            self.log_signal.emit("📦 RPM locales del Kiosco: " + ", ".join(item["name"] for item in self._local_rpm_metadata))
        self._app = self._resolve_app()
        app2 = self._resolve_app2() if self.multi_app else None
        if app2 is not None:
            self.log_signal.emit(
                "🪟 Modo multiventana: Sway con dos aplicaciones. "
                "Cambio de ventana: Super+1 / Super+2 / Super+Tab "
                "(tambien Alt+1 / Alt+2 / Alt+Tab). Alt+9 configura la "
                "red WiFi."
            )
        if self.product_name:
            self.log_signal.emit(
                f"🏷 Producto: {self.product_name}. Anaconda y el sistema "
                "instalado mostraran este nombre en lugar de Fedora Linux."
            )
        plymouth = self._plymouth_section()

        packages = self._package_lines(self._app, app2)
        copy_sections = [self._app["copy"].strip()]
        if app2 is not None:
            copy_sections.append(app2.get("copy", "").strip())
        copy_section = "\n".join(
            section for section in copy_sections if section
        )
        post_sections = [
            self._post_base(
                password_hash,
                include_chmod=self._app["chmod"],
            ),
            self._branding_section(),
            self._app.get("post", ""),
            app2.get("post", "") if app2 is not None else "",
            plymouth,
            self._installer_section(),
            self._installer_access_section(),
            self._vt_section(),
            self._service_section(self._app, app2),
            self._final_check_section(self._app, app2),
        ]
        post_body = "\n".join(
            section.strip() for section in post_sections if section.strip()
        )
        app_repo = "\n".join(
            section
            for section in (
                self._app.get("repo", "").strip(),
                app2.get("repo", "").strip() if app2 is not None else "",
            )
            if section
        )
        repo_lines = self._repo_lines()
        plymouth_sync = self._plymouth_sync_section() if plymouth else ""
        installer_boot = self._installer_boot_section()
        boot_menu_splash = self._boot_menu_splash_section()

        firewall_line = (
            "firewall --enabled" + (" --service=ssh" if self.enable_ssh else "")
            if self.enable_firewall
            else "firewall --disabled"
        )
        services = "NetworkManager,seatd"
        if self.enable_ssh:
            services += ",sshd"
        if self.enable_firewall:
            services += ",firewalld"

        ks_content = f"""# Kickstart generado por Creador-kiosk - {time.strftime('%Y-%m-%d %H:%M:%S')}
# Autor: {self.developer}
# Base: Fedora {self.release} / {FEDORA_ARCH} / {('Sway' if self.multi_app else 'Cage')} + Wayland
text
lang es_AR.UTF-8
keyboard la-latin1
timezone America/Buenos_Aires
authselect select minimal --force
rootpw --lock
selinux --enforcing
{firewall_line}
services --enabled={services}
bootloader --location=mbr --timeout=3 --append="loglevel=7"

# --- PARTICIONAMIENTO -------------------------------------------------------
zerombr
clearpart --all
part / --size 20480 --fstype ext4

# --- REPOSITORIOS -----------------------------------------------------------
# Mirrorlist oficial (con failover) o mirror fijo via KIOSK_MIRROR.
{repo_lines}
{app_repo}

%packages
{packages}
%end

{copy_section}

%post --erroronfail
{post_body}
%end

{plymouth_sync}

{installer_boot}

{boot_menu_splash}
"""
        with open(self.ks_path, "w", encoding="utf-8") as handle:
            handle.write(ks_content)
        # El Kickstart queda restringido al propietario por contener datos
        # internos de la receta de compilacion.
        os.chmod(self.ks_path, 0o600)

    def _validate_generated_kickstart(self):
        """Valida la receta escrita antes de invocar livecd-creator."""
        report = validate_kickstart_file(
            self.ks_path, release=str(self.config.get("release") or self.release)
        )
        for kind, message in report["issues"]:
            prefix = "❌" if kind == "error" else "⚠"
            self.log_signal.emit(f"{prefix} Kickstart: {message}")
        if not report["ok"]:
            raise RuntimeError("El Kickstart no superó la validación previa; se canceló la compilación.")
        if report.get("official"):
            self.log_signal.emit("✅ ksvalidator aprobó la receta Kickstart.")
        else:
            self.log_signal.emit("⚠ Validación estructural interna completada; ksvalidator oficial no disponible.")
        return report

    def _package_lines(self, app, app2=None):
        compositor = "sway" if self.multi_app else "cage"
        base = [
            "@core",
            "kernel",
            "dracut",
            "dracut-live",
            "dracut-config-generic",
            "plymouth",
            "plymouth-system-theme",
            "memtest86+",
            "kbd",
            "glibc-langpack-es",
            "seatd",
            compositor,
            "authselect",
            "xorg-x11-server-Xwayland",
            "mesa-dri-drivers",
            "mesa-libEGL",
            "libglvnd-egl",
            "fontconfig",
            "dejavu-sans-fonts",
            "google-noto-sans-fonts",
        ]
        # El tema personalizado usa ModuleName=script y sin este plugin
        # Plymouth no puede cargarlo (se veria el tema por defecto).
        if (self.config.get("plymouth_image") or "").strip():
            base.append("plymouth-plugin-script")

        network = [
            "NetworkManager",
            "NetworkManager-wifi",
            "wpa_supplicant",
            "iw",
            "iproute",
            "linux-firmware",
        ]
        if self.multi_app:
            # Alt+9 abre nm-connection-editor dentro de la sesion Sway. La
            # regla polkit del kiosco le permite guardar las conexiones como
            # sistema sin pedir contrasena (no hay agente polkit).
            network.extend(
                [
                    "network-manager-applet",
                    # nm-connection-editor es un paquete separado de
                    # network-manager-applet; Alt+9 lo ejecuta directamente.
                    "nm-connection-editor",
                    "polkit",
                    # nm-connection-editor es una GtkApplication: la sesion
                    # del kiosco no tiene bus de sesion, dbus-run-session
                    # crea uno temporal al abrirlo.
                    "dbus-daemon",
                ]
            )
        admin = ["sudo", "shadow-utils"]
        if self.enable_firewall:
            admin.append("firewalld")
        if self.enable_ssh:
            admin.extend(["openssh-server", "openssh-clients"])

        uefi = []
        if self.boot_mode in ("dual", "uefi"):
            uefi = [
                "shim-x64",
                "grub2-efi-x64",
                "grub2-efi-x64-cdboot",
                "grub2-tools",
            ]

        extra_packages_raw = " ".join([
            str(self.config.get("extra_packages", "") or ""),
            *[item["name"] for item in getattr(self, "_local_rpm_metadata", [])],
        ]).strip()
        extra = [pkg for pkg in re.split(r"[\s,]+", extra_packages_raw) if pkg]
        package_policy = validate_packages_list(extra_packages_raw)
        invalid = package_policy["invalid"]
        blocked = package_policy["blocked"]
        if invalid:
            raise RuntimeError(
                "Nombre de paquete no valido en 'Paquetes adicionales': "
                + ", ".join(f"'{name}'" for name in invalid)
                + ". Usa solo letras, numeros y . _ + -"
            )
        if blocked:
            raise RuntimeError(
                "Se rechazaron paquetes bloqueados por la política de seguridad: "
                + ", ".join(blocked)
            )

        resolution = ["wlr-randr"] if self.resolution != "auto" else []

        installer_pkgs = []
        if self.enable_installer:
            installer_pkgs = [
                "anaconda",
                "anaconda-live",
                "anaconda-install-env-deps",
                "anaconda-widgets",
                "anaconda-webui",
                "firefox",
                "polkit",
                "gsettings-desktop-schemas",
            ]

        groups = [
            ("Base del sistema", base),
            ("Red y conectividad", network),
            ("Administracion remota", admin),
            ("Aplicacion kiosco", app["packages"]),
        ]
        if app2 is not None:
            groups.append(("Segunda aplicacion kiosco", app2["packages"]))
        groups.extend(
            [
                ("Instalador en disco", installer_pkgs),
                ("Arranque UEFI", uefi),
                ("Resolucion fija", resolution),
                ("Paquetes adicionales", extra),
            ]
        )

        lines = []
        seen = set()
        for title, items in groups:
            unique = []
            for item in items:
                if item not in seen:
                    seen.add(item)
                    unique.append(item)
            if not unique:
                continue
            lines.append(f"# --- {title} ---")
            lines.extend(unique)
        return "\n".join(lines)

    def _post_base(self, password_hash="", include_chmod=""):
        """Configura kioskuser bloqueado y listo para el arranque automatico."""
        chmod_block = ""
        if include_chmod:
            chmod_block = (
                'if [ -d /opt/kiosk_app ]; then\n'
                f"    {include_chmod}\n"
                "fi\n"
            )

        sudoers_line = (
            "%wheel ALL=(ALL) NOPASSWD: ALL"
            if self.sudo_nopasswd
            else "%wheel ALL=(ALL) ALL"
        )
        ssh_password = "yes" if self.ssh_password_auth else "no"
        ssh_block = ""
        if self.enable_ssh:
            ssh_block = f"""
# --- SSH: habilitado de forma explicita por el usuario ---
mkdir -p /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/00-kiosk.conf <<'KIOSK_EOF'
PasswordAuthentication {ssh_password}
KbdInteractiveAuthentication {ssh_password}
PermitRootLogin no
KIOSK_EOF
systemctl enable sshd.service >/dev/null 2>&1
"""
        firewall_block = ""
        if self.enable_firewall:
            ssh_firewall_rule = (
                "firewall-offline-cmd --zone=public --add-service=ssh >/dev/null 2>&1 || true"
                if self.enable_ssh else ": # SSH deshabilitado por defecto"
            )
            firewall_block = f"""
# --- Firewall: solo los servicios explicitamente habilitados ---
systemctl enable firewalld.service >/dev/null 2>&1
if command -v firewall-offline-cmd >/dev/null 2>&1; then
    {ssh_firewall_rule}
fi
"""

        return f"""
# --- Entorno de los %post ---
# livecd-creator ejecuta los scripts con un entorno vacio y /bin/sh no
# exporta su PATH por defecto. dracut-install aborta con "PATH is not set"
# si no encuentra la variable, asi que la exportamos explicitamente.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# --- Autenticacion local: cuenta de servicio sin contrasena interactiva ---
authselect select minimal --force || echo "AVISO: authselect fallo"

# --- kiosk.service es dueno de tty1: evita la carrera con getty ---
systemctl mask getty@tty1.service >/dev/null 2>&1 || true

# --- Usuario kioskuser y grupos de acceso a hardware ---
getent group seat >/dev/null 2>&1 || groupadd -r seat
getent group render >/dev/null 2>&1 || groupadd -r render
id kioskuser >/dev/null 2>&1 || useradd -m -c "Kiosk User" \
    -G wheel,video,render,input,audio,seat kioskuser
usermod -aG wheel,video,render,input,audio,seat kioskuser
# La cuenta no acepta contrasenas; kiosk.service la ejecuta directamente.
usermod -L kioskuser

# --- Log de la sesion de kiosco, escribible por kioskuser ---
touch /var/log/kiosk-session.log
chown kioskuser:kioskuser /var/log/kiosk-session.log

# --- sudo para administracion (la politica se controla por la opcion avanzada) ---
echo {shlex.quote(sudoers_line)} > /etc/sudoers.d/wheel
chmod 0440 /etc/sudoers.d/wheel
visudo -cf /etc/sudoers.d/wheel >/dev/null 2>&1 || echo "AVISO: sudoers.d/wheel invalido"

{ssh_block}

# --- Red gestionada por NetworkManager (wpa_supplicant va por D-Bus) ---
systemctl enable NetworkManager.service >/dev/null 2>&1
systemctl enable seatd.service >/dev/null 2>&1 || \
    systemctl enable seatd.socket >/dev/null 2>&1 || true
{firewall_block}
# --- Permisos de la app inyectada ---
if [ -d /opt/kiosk_app ]; then
    chown -R kioskuser:kioskuser /opt/kiosk_app
fi
{chmod_block}
# Restaurar etiquetas SELinux de los recursos instalados y personalizados.
if command -v restorecon >/dev/null 2>&1; then
    restorecon -RF /etc /usr/local /opt/kiosk_app /var/log/kiosk-session.log 2>/dev/null || true
fi
"""

    def _plymouth_section(self):
        image = (self.config.get("plymouth_image") or "").strip()
        if not image:
            return ""
        if not os.path.isfile(image):
            raise RuntimeError(f"No existe la imagen de Plymouth: {image}")

        with open(image, "rb") as handle:
            data = handle.read()
        if len(data) > MAX_PLYMOUTH_BYTES:
            raise RuntimeError(
                "La imagen de Plymouth supera los 4 MiB. Usa un PNG mas liviano."
            )

        encoded = base64.b64encode(data).decode("ascii")
        wrapped = "\n".join(
            encoded[index:index + 76] for index in range(0, len(encoded), 76)
        )

        return f"""
# --- Tema Plymouth personalizado ---
mkdir -p /usr/share/plymouth/themes/kiosk /etc/plymouth
base64 -d > /usr/share/plymouth/themes/kiosk/logo.png <<'KIOSK_B64'
{wrapped}
KIOSK_B64
cat > /usr/share/plymouth/themes/kiosk/kiosk.plymouth <<'KIOSK_EOF'
[Plymouth Theme]
Name=Kiosk
Description=Tema personalizado del kiosco
ModuleName=script

[script]
ImageDir=/usr/share/plymouth/themes/kiosk
ScriptFile=/usr/share/plymouth/themes/kiosk/kiosk.script
KIOSK_EOF
cat > /usr/share/plymouth/themes/kiosk/kiosk.script <<'KIOSK_EOF'
logo_image = Image("logo.png");
logo_sprite = Sprite(logo_image);
logo_sprite.SetX(Window.GetWidth() / 2 - logo_image.GetWidth() / 2);
logo_sprite.SetY(Window.GetHeight() / 2 - logo_image.GetHeight() / 2);
KIOSK_EOF
cat > /etc/dracut.conf.d/99-kiosk-plymouth.conf <<'KIOSK_EOF'
add_dracutmodules+=" plymouth "
KIOSK_EOF
plymouth-set-default-theme kiosk >/dev/null 2>&1 || \\
    printf '[Daemon]\\nTheme=kiosk\\n' > /etc/plymouth/plymouthd.conf

# livecd-creator copia /boot/initramfs-*.img tal cual: hay que regenerarlo
# para que el tema entre en la imagen de arranque.
kernelver=$(ls /lib/modules | sort -V | tail -n1)
rm -f /boot/.kiosk-plymouth-ok
if [ -n "$kernelver" ]; then
    if dracut --force --kver "$kernelver" "/boot/initramfs-$kernelver.img"; then
        touch /boot/.kiosk-plymouth-ok
    else
        echo "AVISO: no se pudo regenerar el initramfs con el tema Plymouth"
    fi
fi
"""

    def _branding_section(self):
        """Aplica identidad del producto sin interpolar datos arbitrarios en shell."""
        if not self.product_name:
            return ""
        error = validate_product_name(self.product_name)
        if error is not None:
            raise RuntimeError(error)

        pretty = f"{self.product_name} {self.version}".strip()
        system_release = f"{self.product_name} release {self.release}"
        name_b64 = base64.b64encode(self.product_name.encode("utf-8")).decode("ascii")
        pretty_b64 = base64.b64encode(pretty.encode("utf-8")).decode("ascii")
        release_b64 = base64.b64encode(system_release.encode("utf-8")).decode("ascii")

        return f"""
# --- Identidad del producto (base64 evita interpolacion shell) ---
rm -f /etc/os-release
if [ -f /usr/lib/os-release ]; then
    sed -e '/^NAME=/d' -e '/^PRETTY_NAME=/d' /usr/lib/os-release > /etc/os-release
else
    printf 'ID=fedora\nVERSION_ID=%s\n' '{self.release}' > /etc/os-release
fi
printf '%s' '{name_b64}' | base64 -d > /tmp/kiosk-name
printf '%s' '{pretty_b64}' | base64 -d > /tmp/kiosk-pretty
printf 'NAME="%s"\n' "$(cat /tmp/kiosk-name)" >> /etc/os-release
printf 'PRETTY_NAME="%s"\n' "$(cat /tmp/kiosk-pretty)" >> /etc/os-release
chmod 0644 /etc/os-release
printf '%s' '{release_b64}' | base64 -d > /etc/system-release
rm -f /tmp/kiosk-name /tmp/kiosk-pretty
"""

    def _installer_section(self):
        if not self.enable_installer:
            return ""
        banner = (self.config.get("installer_banner") or "").strip()
        text = (self.config.get("installer_text") or "").strip()
        if not banner and not text:
            return ""

        lines = ["# --- Configuracion del Instalador y Branding ---"]
        if banner:
            if not os.path.isfile(banner):
                raise RuntimeError(f"No existe la imagen banner del instalador: {banner}")
            with open(banner, "rb") as handle:
                data = handle.read()
            if len(data) > MAX_PLYMOUTH_BYTES:
                raise RuntimeError(
                    "La imagen banner del instalador supera los 4 MiB. Usa una imagen mas liviana."
                )
            encoded = base64.b64encode(data).decode("ascii")
            wrapped = "\n".join(
                encoded[index:index + 76] for index in range(0, len(encoded), 76)
            )
            lines.append(f"""
mkdir -p /usr/share/anaconda/pixmaps /usr/share/pixmaps
base64 -d > /usr/share/anaconda/pixmaps/top-banner.png <<'KIOSK_B64'
{wrapped}
KIOSK_B64
cp -f /usr/share/anaconda/pixmaps/top-banner.png /usr/share/anaconda/pixmaps/banner.png || true
cp -f /usr/share/anaconda/pixmaps/top-banner.png /usr/share/pixmaps/installer-banner.png || true
""")

        if text:
            escaped_text = shlex.quote(text)
            lines.append(f"""
mkdir -p /etc /usr/share/anaconda/help
echo {escaped_text} > /etc/kiosk-installer-message.txt
echo {escaped_text} > /usr/share/anaconda/help/welcome.txt
""")

        return "\n".join(lines)

    def _installer_access_section(self):
        """Permite a kioskuser lanzar liveinst sin autenticacion interactiva.

        liveinst se re-ejecuta con pkexec. En el kiosco no hay agente polkit
        (Cage/Sway no traen uno), asi que sin esta regla el instalador no
        podria abrirse. kioskuser ya es administrador del equipo.
        """
        if not self.enable_installer:
            return ""

        return """
# --- Acceso al instalador (liveinst) sin agente polkit ---
install -d -m 0755 /etc/polkit-1/rules.d
cat > /etc/polkit-1/rules.d/49-kiosk-liveinst.rules <<'KIOSK_EOF'
polkit.addRule(function(action, subject) {
    if (action.id == "org.fedoraproject.pkexec.liveinst" &&
        subject.user == "kioskuser" && subject.local && subject.active) {
        return polkit.Result.YES;
    }
    // liveinst (ya como root) usa pkexec --user para restaurar el entorno
    // grafico del usuario del instalador. root ya tiene control total.
    if (action.id == "org.freedesktop.policykit.exec" &&
        subject.user == "root") {
        return polkit.Result.YES;
    }
});
KIOSK_EOF
"""

    def _installer_boot_section(self):
        """Agrega una entrada de arranque que inicia Anaconda (liveinst).

        livecd-creator genera isolinux.cfg y EFI/BOOT/grub.cfg antes de los
        %post --nochroot. Duplicamos la entrada "linux0" y le agregamos el
        parametro kiosk.mode=installer, que kiosk-session/kiosk-sway-start
        interpretan para abrir liveinst en lugar de la app del kiosco.
        """
        if not self.enable_installer:
            return ""

        script = r"""
%post --nochroot
# $LIVE_ROOT lo define livecd-creator para los scripts --nochroot.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if [ -n "$LIVE_ROOT" ]; then
    isolinux="$LIVE_ROOT/isolinux/isolinux.cfg"
    if [ -f "$isolinux" ] && ! grep -q 'kiosk.mode=installer' "$isolinux"; then
        kernel=$(awk '/^[[:space:]]*label linux0[[:space:]]*$/{found=1} found && /^[[:space:]]*kernel /{print $2; exit}' "$isolinux")
        append=$(awk '/^[[:space:]]*label linux0[[:space:]]*$/{found=1} found && /^[[:space:]]*append /{sub(/^[[:space:]]*append /, ""); print; exit}' "$isolinux")
        if [ -n "$kernel" ] && [ -n "$append" ]; then
            {
                echo ""
                echo "label installer0"
                echo "  menu label ^Instalar en disco (Anaconda)"
                echo "  kernel $kernel"
                echo "  append $append kiosk.mode=installer"
            } >> "$isolinux"
            echo "Entrada de instalador agregada a isolinux.cfg"
        fi
    fi

    grub="$LIVE_ROOT/EFI/BOOT/grub.cfg"
    if [ -f "$grub" ] && ! grep -q 'kiosk.mode=installer' "$grub"; then
        # livecd-creator usa "linuxefi/initrdefi" en UEFI (y "linux/initrd"
        # en BIOS). Se conserva el comando original: reescribirlo como
        # "linux/initrd" puede fallar en UEFI, sobre todo con Secure Boot.
        linux_line=$(awk '/^[[:space:]]*(linuxefi|linux)[[:space:]]+/{sub(/^[[:space:]]+/, ""); print; exit}' "$grub")
        initrd_line=$(awk '/^[[:space:]]*(initrdefi|initrd)[[:space:]]+/{sub(/^[[:space:]]+/, ""); print; exit}' "$grub")
        if [ -n "$linux_line" ] && [ -n "$initrd_line" ]; then
            {
                echo ""
                echo "menuentry 'Instalar en disco (Anaconda)' --class fedora --class gnu-linux --class gnu --class os {"
                echo "    $linux_line kiosk.mode=installer"
                echo "    $initrd_line"
                echo "}"
            } >> "$grub"
            echo "Entrada de instalador agregada a grub.cfg"
        fi
    fi
fi
%end
"""
        if self.config.get("auto_install_enabled"):
            raise RuntimeError(
                "Kickstart desatendido no es compatible con Live ISO de Anaconda. "
                "Usa un medio Netinstall, estándar o boot.iso."
            )
        return script

    def _boot_menu_splash_section(self):
        """Aplica la imagen elegida a los menús BIOS/UEFI del ISO.

        La imagen ya fue instalada por _plymouth_section() dentro del chroot.
        Aquí se copia al staging del medio y se configura Syslinux/GRUB. Cada
        cargador conserva una ruta de arranque de texto si el modo gráfico o
        sus módulos no están disponibles.
        """
        if not (self.config.get("plymouth_image") or "").strip():
            return ""

        return r"""
%post --nochroot
# Fondo del menú inicial BIOS/Legacy (Syslinux) y UEFI (GRUB).
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if [ -n "$LIVE_ROOT" ] && [ -f "$INSTALL_ROOT/usr/share/plymouth/themes/kiosk/logo.png" ]; then
    splash="$INSTALL_ROOT/usr/share/plymouth/themes/kiosk/logo.png"

    # Syslinux/vesamenu: MENU BACKGROUND admite PNG. La imagen se mantiene
    # con sus dimensiones originales; para mejores resultados usar 640x480.
    if [ -d "$LIVE_ROOT/isolinux" ]; then
        cp -f "$splash" "$LIVE_ROOT/isolinux/kiosk-splash.png"
        isolinux="$LIVE_ROOT/isolinux/isolinux.cfg"
        if [ -f "$isolinux" ]; then
            if ! grep -Eq '^[[:space:]]*MENU[[:space:]]+BACKGROUND[[:space:]]+' "$isolinux"; then
                tmp="${isolinux}.kiosk-tmp"
                {
                    echo "MENU BACKGROUND kiosk-splash.png"
                    if ! grep -Eq '^[[:space:]]*(UI[[:space:]]+.*vesamenu|DEFAULT[[:space:]]+vesamenu)' "$isolinux"; then
                        echo "UI vesamenu.c32"
                    fi
                    cat "$isolinux"
                } > "$tmp" && mv -f "$tmp" "$isolinux"
            fi
        fi
    fi

    # GRUB UEFI: activar gfxterm solo si el módulo carga; ante un fallo se
    # conserva la salida de consola y el menú sigue siendo utilizable.
    grub="$LIVE_ROOT/EFI/BOOT/grub.cfg"
    if [ -f "$grub" ]; then
        cp -f "$splash" "$LIVE_ROOT/EFI/BOOT/kiosk-splash.png"
        if ! grep -q 'kiosk-splash.png' "$grub"; then
            tmp="${grub}.kiosk-tmp"
            {
                cat <<'KIOSK_GRUB'
# Fondo personalizado (opcional): fallback automatico a consola/texto.
set gfxmode=auto
if insmod all_video; then true; fi
if insmod gfxterm; then
    terminal_output gfxterm
    if insmod png; then
        if [ -f "$prefix/kiosk-splash.png" ]; then
            background_image --mode=stretch "$prefix/kiosk-splash.png"
        fi
    fi
fi
KIOSK_GRUB
                cat "$grub"
            } > "$tmp" && mv -f "$tmp" "$grub"
        fi
    fi
    echo "Fondo de menú de arranque instalado para BIOS/UEFI"
else
    echo "AVISO: no se encontró el splash Plymouth en INSTALL_ROOT; se omite el fondo de menú"
fi
%end
"""

    def _plymouth_sync_section(self):
        """Reemplaza el initramfs ya copiado al staging del ISO.

        livecd-creator ejecuta _create_bootconfig() (que copia vmlinuz e
        initrd a isolinux/) ANTES de los %post. Por eso, tras regenerar el
        initramfs en el chroot, hay que sincronizar la copia del ISO.
        El nombre real que usan las entradas de arranque BIOS y UEFI es
        ``initrd0.img`` (indice 0), no ``initrd.img``.
        """
        return """
%post --nochroot
# $LIVE_ROOT y $INSTALL_ROOT los define livecd-creator para --nochroot.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if [ -n "$LIVE_ROOT" ] && [ -d "$LIVE_ROOT/isolinux" ]; then
    kernelver=$(ls "$INSTALL_ROOT/lib/modules" 2>/dev/null | sort -V | tail -n1)
    initrd="$INSTALL_ROOT/boot/initramfs-$kernelver.img"
    if [ -f "$INSTALL_ROOT/boot/.kiosk-plymouth-ok" ] && [ -f "$initrd" ]; then
        cp -f "$initrd" "$LIVE_ROOT/isolinux/initrd0.img"
        echo "initramfs con tema Plymouth sincronizado en initrd0.img"
    else
        echo "AVISO: el initramfs con tema no se genero; se conserva initrd0.img original"
    fi
fi
%end
"""

    def _vt_section(self):
        if not self.block_vt:
            return ""

        return """
# --- Bloqueo de consolas virtuales ---
# Se desactivan los getty de tty2..tty6 y el auto-spawn de VTs. El cambio de
# VT a nivel kernel/wlroots sigue existiendo, pero no habra login local: la
# administracion queda por SSH.
mkdir -p /etc/systemd/logind.conf.d
cat > /etc/systemd/logind.conf.d/99-kiosk.conf <<'KIOSK_EOF'
[Login]
NAutoVTs=0
KIOSK_EOF
for t in 2 3 4 5 6; do
    systemctl mask getty@tty$t.service >/dev/null 2>&1 || true
done
systemctl mask ctrl-alt-del.target >/dev/null 2>&1 || true
"""

    def _session_enable_lines(self):
        """Activa el servicio del kiosco como sesion automatica tipo Live."""
        return (
            "systemctl enable kiosk.service >/dev/null 2>&1\n"
            "systemctl set-default multi-user.target >/dev/null 2>&1"
        )

    def _service_section(self, app, app2=None):
        if app2 is not None:
            return self._sway_service_section(app["exec"], app2["exec"])
        return self._cage_service_section(app["exec"])

    def _systemd_escape(self, value):
        """Escapa un valor para un campo de systemd (Description, etc.)."""
        return (value or "").replace("%", "%%")

    def _cage_service_section(self, exec_cmd):
        if "\n" in exec_cmd or "\r" in exec_cmd:
            raise RuntimeError(
                "El comando de la aplicacion no puede contener saltos de linea."
            )

        # El comando va en un script codificado en base64. Asi una URL con
        # caracteres especiales (por ejemplo %20) no se interpreta como
        # especificador de systemd en ExecStart.
        app_script = "#!/bin/sh\nexec " + exec_cmd + "\n"
        app_b64 = base64.b64encode(app_script.encode("utf-8")).decode("ascii")

        restart = "always" if self.restart_on_crash else "no"
        resolution_env = ""
        if self.resolution != "auto":
            resolution_env = f"Environment=KIOSK_RESOLUTION={self.resolution}\n"

        return f"""
# --- Sesion de kiosco: Cage sobre TTY1 ---
cat > /usr/local/bin/kiosk-session <<'KIOSK_EOF'
#!/bin/sh
# Si se arranco la entrada "Instalar en disco", abrir Anaconda.
if grep -q 'kiosk.mode=installer' /proc/cmdline 2>/dev/null && [ -x /usr/bin/liveinst ]; then
    /usr/bin/liveinst || echo "AVISO: liveinst termino con error" >> /var/log/kiosk-session.log
    exit 0
fi

# Ajuste best-effort de resolucion (cage usa el modo preferido del monitor).
if [ -n "$KIOSK_RESOLUTION" ] && [ "$KIOSK_RESOLUTION" != "auto" ]; then
    (
        i=0
        while [ $i -lt 5 ]; do
            out=$(wlr-randr 2>/dev/null | head -n1 | cut -d' ' -f1)
            [ -n "$out" ] && break
            i=$((i+1))
            sleep 1
        done
        if [ -n "$out" ]; then
            wlr-randr --output "$out" --mode "$KIOSK_RESOLUTION" >/dev/null 2>&1 || \\
                echo "No se pudo fijar $KIOSK_RESOLUTION" >> /var/log/kiosk-session.log
        fi
    ) &
fi
exec "$@"
KIOSK_EOF
chmod 0755 /usr/local/bin/kiosk-session

printf '%s' '{app_b64}' | base64 -d > /usr/local/bin/kiosk-app.cmd
chmod 0755 /usr/local/bin/kiosk-app.cmd

cat > /etc/systemd/system/kiosk.service <<'KIOSK_EOF'
[Unit]
Description=Kiosk {self._systemd_escape(self.iso_name)} - {self._systemd_escape(self.developer)} (Cage/Wayland)
After=systemd-user-sessions.service network.target sound.target seatd.service NetworkManager.service
Wants=seatd.service
Conflicts=getty@tty1.service

[Service]
Type=simple
User=kioskuser
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
StandardInput=tty
StandardOutput=tty
StandardError=tty
RuntimeDirectory=user/%U
RuntimeDirectoryMode=0700
Environment=XDG_RUNTIME_DIR=/run/user/%U
Environment=XDG_SESSION_TYPE=wayland
Environment=XDG_CURRENT_DESKTOP=cage
Environment=XDG_SESSION_DESKTOP=cage
Environment=MOZ_ENABLE_WAYLAND=1
Environment=QT_QPA_PLATFORM=wayland
Environment=XKB_DEFAULT_LAYOUT=latam
{resolution_env}ExecStart=/usr/bin/cage -- /usr/local/bin/kiosk-session /usr/local/bin/kiosk-app.cmd
Restart={restart}
RestartSec=2

[Install]
WantedBy=multi-user.target
KIOSK_EOF

{self._session_enable_lines()}
"""

    def _sway_app_script(self, number, workspace):
        """Script que mantiene una app en su workspace (Sway)."""
        restart = self.restart_on_crash
        lines = [
            "#!/bin/sh",
            f"# Mantiene la aplicacion {number} en el workspace {workspace}.",
        ]
        if restart:
            lines.append("while :; do")
            indent = "    "
        else:
            indent = ""

        lines.extend(
            [
                f"{indent}/usr/local/bin/kiosk-app-{number}.cmd &",
                f"{indent}app_pid=$!",
                f"{indent}i=0",
                f'{indent}while [ "$i" -lt 60 ]; do',
                f'{indent}    if /usr/bin/swaymsg -t get_tree 2>/dev/null | '
                f'grep -Eq "\\"pid\\":[[:space:]]*$app_pid([^0-9]|$)"; then',
                f'{indent}        /usr/bin/swaymsg -q '
                f'"[pid=$app_pid] move container to workspace {workspace}"',
                f"{indent}        break",
                f"{indent}    fi",
                f"{indent}    i=$((i+1))",
                f"{indent}    sleep 0.5",
                f"{indent}done",
                f'{indent}wait "$app_pid"',
            ]
        )
        if restart:
            lines.append("    sleep 2")
            lines.append("done")
        return "\n".join(lines) + "\n"

    def _sway_service_section(self, exec1, exec2):
        for label, command in (("primera", exec1), ("segunda", exec2)):
            if "\n" in command or "\r" in command:
                raise RuntimeError(
                    f"El comando de la {label} aplicacion no puede contener "
                    "saltos de linea."
                )

        # El comando se guarda en un script propio codificado en base64: asi
        # no puede romper el here-doc del %post aunque tenga comillas.
        app1_script = "#!/bin/sh\nexec " + exec1 + "\n"
        app2_script = "#!/bin/sh\nexec " + exec2 + "\n"
        app1_b64 = base64.b64encode(app1_script.encode("utf-8")).decode("ascii")
        app2_b64 = base64.b64encode(app2_script.encode("utf-8")).decode("ascii")
        app1_wrapper = self._sway_app_script(1, 1)
        app2_wrapper = self._sway_app_script(2, 2)

        restart = "always" if self.restart_on_crash else "no"
        resolution_env = ""
        resolution_exec = ""
        resolution_script = ""
        if self.resolution != "auto":
            resolution_env = f"Environment=KIOSK_RESOLUTION={self.resolution}\n"
            resolution_exec = "exec /usr/local/bin/kiosk-resolution\n"
            resolution_script = """
cat > /usr/local/bin/kiosk-resolution <<'KIOSK_EOF'
#!/bin/sh
# Ajuste best-effort de la resolucion dentro de la sesion Sway.
i=0
while [ "$i" -lt 20 ]; do
    out=$(wlr-randr 2>/dev/null | head -n1 | cut -d' ' -f1)
    if [ -n "$out" ]; then
        wlr-randr --output "$out" --mode "$KIOSK_RESOLUTION" >/dev/null 2>&1 && exit 0
    fi
    i=$((i+1))
    sleep 1
done
echo "No se pudo fijar $KIOSK_RESOLUTION" >> /var/log/kiosk-session.log
KIOSK_EOF
chmod 0755 /usr/local/bin/kiosk-resolution
"""

        sway_conf = f"""# Configuracion de kiosco multiventana (Sway)
set $mod Mod4
default_border none
default_floating_border none
hide_edge_borders both
gaps inner 0
gaps outer 0
focus_follows_mouse no
mouse_warping none
xwayland enable
input type:keyboard xkb_layout latam

# Cambio entre las dos aplicaciones
bindsym $mod+1 workspace 1
bindsym $mod+2 workspace 2
bindsym $mod+Tab workspace next_on_output
bindsym $mod+Shift+Tab workspace prev_on_output
bindsym $mod+Right workspace next_on_output
bindsym $mod+Left workspace prev_on_output
bindsym Mod1+1 workspace 1
bindsym Mod1+2 workspace 2
bindsym Mod1+Tab workspace next_on_output
bindsym Mod1+Shift+Tab workspace prev_on_output
bindsym Mod1+Right workspace next_on_output
bindsym Mod1+Left workspace prev_on_output

# Configuracion de red WiFi (Alt+9 / Super+9)
bindsym $mod+9 exec /usr/local/bin/kiosk-wifi
bindsym Mod1+9 exec /usr/local/bin/kiosk-wifi
for_window [app_id="nm-connection-editor"] floating enable, move position center, sticky enable

{resolution_exec}exec /usr/local/bin/kiosk-sway-start
"""

        return f"""
# --- Sesion de kiosco: Sway sobre TTY1 (multiventana) ---
install -d -m 0755 /etc/sway
cat > /etc/sway/kiosk.conf <<'KIOSK_EOF'
{sway_conf}KIOSK_EOF

printf '%s' '{app1_b64}' | base64 -d > /usr/local/bin/kiosk-app-1.cmd
chmod 0755 /usr/local/bin/kiosk-app-1.cmd
printf '%s' '{app2_b64}' | base64 -d > /usr/local/bin/kiosk-app-2.cmd
chmod 0755 /usr/local/bin/kiosk-app-2.cmd

cat > /usr/local/bin/kiosk-app-1 <<'KIOSK_EOF'
{app1_wrapper}KIOSK_EOF
chmod 0755 /usr/local/bin/kiosk-app-1

cat > /usr/local/bin/kiosk-app-2 <<'KIOSK_EOF'
{app2_wrapper}KIOSK_EOF
chmod 0755 /usr/local/bin/kiosk-app-2

cat > /usr/local/bin/kiosk-sway-start <<'KIOSK_EOF'
#!/bin/sh
# Si se arranco la entrada "Instalar en disco", abrir Anaconda.
if grep -q 'kiosk.mode=installer' /proc/cmdline 2>/dev/null && [ -x /usr/bin/liveinst ]; then
    /usr/bin/liveinst || echo "AVISO: liveinst termino con error" >> /var/log/kiosk-session.log
    exit 0
fi

# Arranque secuencial: la app 1 se mapea en el workspace 1 antes de pasar al 2.
i=0
while [ "$i" -lt 30 ]; do
    /usr/bin/swaymsg -q workspace 1 >/dev/null 2>&1 && break
    i=$((i+1))
    sleep 1
done

/usr/local/bin/kiosk-app-1 &
app1_pid=$!

i=0
while [ "$i" -lt 60 ]; do
    if /usr/bin/swaymsg -t get_tree 2>/dev/null | \
        grep -Eq '"(app_id|class)":[[:space:]]*"[^"]'; then
        break
    fi
    i=$((i+1))
    sleep 0.5
done

/usr/bin/swaymsg -q workspace 2
/usr/local/bin/kiosk-app-2 &
app2_pid=$!

sleep 1
/usr/bin/swaymsg -q workspace 1
wait "$app1_pid" "$app2_pid"
KIOSK_EOF
chmod 0755 /usr/local/bin/kiosk-sway-start

cat > /usr/local/bin/kiosk-wifi <<'KIOSK_EOF'
#!/bin/sh
# Alt+9: configurar la red WiFi del kiosco (nm-connection-editor).
# La sesion del kiosco no tiene bus de sesion (no hay escritorio): se
# crea uno temporal para que la GtkApplication pueda arrancar.
if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    exec /usr/bin/dbus-run-session -- /usr/bin/nm-connection-editor
fi
exec /usr/bin/nm-connection-editor
KIOSK_EOF
chmod 0755 /usr/local/bin/kiosk-wifi

# --- Alt+9: kioskuser administra la red sin agente polkit ---
install -d -m 0755 /etc/polkit-1/rules.d
cat > /etc/polkit-1/rules.d/49-kiosk-network.rules <<'KIOSK_EOF'
polkit.addRule(function(action, subject) {{
    if (action.id.indexOf("org.freedesktop.NetworkManager.") == 0 &&
        subject.user == "kioskuser" && subject.local && subject.active) {{
        return polkit.Result.YES;
    }}
}});
KIOSK_EOF
{resolution_script}
cat > /etc/systemd/system/kiosk.service <<'KIOSK_EOF'
[Unit]
Description=Kiosk {self._systemd_escape(self.iso_name)} - {self._systemd_escape(self.developer)} (Sway/Wayland)
After=systemd-user-sessions.service network.target sound.target seatd.service NetworkManager.service
Wants=seatd.service
Conflicts=getty@tty1.service

[Service]
Type=simple
User=kioskuser
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
KillMode=control-group
StandardInput=tty
StandardOutput=tty
StandardError=tty
RuntimeDirectory=user/%U
RuntimeDirectoryMode=0700
Environment=XDG_RUNTIME_DIR=/run/user/%U
Environment=XDG_SESSION_TYPE=wayland
Environment=XDG_CURRENT_DESKTOP=sway
Environment=XDG_SESSION_DESKTOP=sway
Environment=MOZ_ENABLE_WAYLAND=1
Environment=QT_QPA_PLATFORM=wayland
Environment=XKB_DEFAULT_LAYOUT=latam
{resolution_env}ExecStart=/usr/bin/sway --config /etc/sway/kiosk.conf
Restart={restart}
RestartSec=2

[Install]
WantedBy=multi-user.target
KIOSK_EOF

{self._session_enable_lines()}
"""

    # -- Autoverificacion del %post ------------------------------------------

    @staticmethod
    def _exec_binaries(exec_cmd):
        """Ejecutables absolutos (y el primero relativo) de un comando."""
        try:
            parts = shlex.split(exec_cmd or "")
        except ValueError:
            return []
        binaries = [
            part
            for index, part in enumerate(parts)
            if index == 0 or part.startswith("/")
        ]
        return _dedupe(binaries)

    def _final_check_section(self, app, app2=None):
        """Comprueba lo critico al final del %post y aborta si falta.

        livecd-creator ignora los fallos de %post salvo ``--erroronfail``.
        Como el script no usa ``set -e`` (hay pasos opcionales), se acumulan
        los errores y se devuelve un codigo distinto de cero al final.
        """
        files = ["/etc/systemd/system/kiosk.service"]
        binaries = ["/usr/bin/" + ("sway" if self.multi_app else "cage")]
        checks = []

        if self.multi_app:
            files.extend(
                [
                    "/usr/local/bin/kiosk-app-1.cmd",
                    "/usr/local/bin/kiosk-app-2.cmd",
                    "/usr/local/bin/kiosk-sway-start",
                ]
            )
            for command in (app.get("exec", ""), (app2 or {}).get("exec", "")):
                checks.extend(self._exec_binaries(command))
        else:
            files.extend(
                [
                    "/usr/local/bin/kiosk-app.cmd",
                    "/usr/local/bin/kiosk-session",
                ]
            )
            checks.extend(self._exec_binaries(app.get("exec", "")))

        if self.enable_installer:
            files.append("/usr/bin/liveinst")
        if self.enable_ssh:
            files.append("/usr/sbin/sshd")

        lines = [
            "",
            "# --- Autoverificacion del %post ---",
            "# Con --erroronfail, un fallo critico detiene el build en lugar de",
            "# producir una ISO incompleta marcada como exitosa.",
            "__kiosk_fail=0",
            "__kiosk_file() {",
            '    if [ ! -e "$1" ]; then',
            '        echo "ERROR: falta $1"',
            "        __kiosk_fail=1",
            "    fi",
            "}",
            "__kiosk_bin() {",
            '    if ! command -v "$1" >/dev/null 2>&1; then',
            '        echo "ERROR: no se encuentra el ejecutable $1"',
            "        __kiosk_fail=1",
            "    fi",
            "}",
            "if ! id kioskuser >/dev/null 2>&1; then",
            '    echo "ERROR: no existe el usuario kioskuser"',
            "    __kiosk_fail=1",
            "fi",
            "if ! awk -F: '$1 == \"kioskuser\" && $2 ~ /^!/ { ok=1 } END { exit !ok }' /etc/shadow; then",
            '    echo "ERROR: kioskuser no tiene la contrasena bloqueada para el modo Live"',
            "    __kiosk_fail=1",
            "fi",
        ]
        lines.extend(f"__kiosk_file {shlex.quote(path)}" for path in _dedupe(files))
        lines.extend(
            f"__kiosk_bin {shlex.quote(binary)}" for binary in _dedupe(binaries + checks)
        )
        lines.extend(
            [
                'if [ "$__kiosk_fail" -ne 0 ]; then',
                '    echo "ERROR: la configuracion del sistema no se completo; '
                'se aborta la ISO."',
                "    exit 1",
                "fi",
                'echo "Autoverificacion del %post: correcta"',
            ]
        )
        return "\n".join(lines)


    # -- Ejecucion y salida --------------------------------------------------

    def _track_phase(self, line):
        low = line.lower()
        if low.startswith("installing:") or "installing:" in low:
            self.progress_signal.emit(45)
        elif "mksquashfs" in low or "squash" in low:
            self.progress_signal.emit(75)
        elif "creating iso" in low or "xorriso" in low or "writing iso" in low:
            self.progress_signal.emit(88)

    @staticmethod
    def _signal_process_group(process, sig):
        """Fachada compatible para señalizar el grupo del proceso."""
        return process_runner.signal_process_group(process, sig)

    def _terminate_process_tree(self, process):
        """Fachada compatible para cancelar todo el arbol de procesos."""
        return process_runner.terminate_process_tree(process, timeout=10)

    def _run_livecd(self):
        started = time.time()
        expected_iso = os.path.join(self.work_dir, f"{self.fslabel}.iso")
        try:
            os.unlink(expected_iso)
        except OSError:
            pass

        cmd = self._priv + [
            "livecd-creator",
            f"--config={self.ks_path}",
            f"--fslabel={self.fslabel}",
            f"--releasever={self.release}",
            f"--product={self.iso_name}",
            f"--title={self.iso_name}",
            f"--tmpdir={self.tmp_dir}",
        ]
        if self.cache_enabled:
            cmd.append(f"--cache={self.cache_dir}")
        else:
            self.log_signal.emit("ℹ Caché persistente desactivada para esta compilación.")

        self.log_signal.emit("🚀 " + " ".join(shlex.quote(part) for part in cmd))
        self.log_signal.emit(
            "⏳ livecd-creator puede estar varios minutos en silencio mientras "
            "descarga metadatos. Se mostrara un latido cada 20 s."
        )
        self.progress_signal.emit(25)

        # Log propio y legible (evita el archivo root-owned de --logfile).
        try:
            os.unlink(self.log_path)
        except OSError:
            pass
        try:
            log_handle = open(self.log_path, "w", encoding="utf-8", buffering=1)
        except OSError as exc:
            self.log_signal.emit(f"⚠ No pude abrir {self.log_path}: {exc}")
            log_handle = None

        def emit(line):
            line = line.rstrip("\r\n")
            if not line.strip():
                return
            # Ruido conocido de urlgrabber con Python 3.14 (inofensivo).
            if "UserWarning: pkg_resources is deprecated" in line:
                return
            if line.strip() == "from pkg_resources import get_distribution":
                return
            if log_handle is not None:
                log_handle.write(line + "\n")
            self.log_signal.emit(line)
            self._track_phase(line)

            missing = re.search(
                r"(?:Failed to find package|No match for argument:|"
                r"No hay coincidencias para el argumento:?)\s*'?"
                r"([A-Za-z0-9._+:-]+)'?",
                line,
            )
            if missing:
                self.log_signal.emit(
                    f"💡 El paquete '{missing.group(1)}' no existe en Fedora "
                    f"{self.release}. Revisa el campo 'Paquetes adicionales' "
                    "de la GUI y quitalo o corrige el nombre."
                )

        self._raise_if_cancelled()

        # Grupo de procesos propio: permite cancelar con senales a todo el
        # arbol (sudo/pkexec, livecd-creator, dnf, mksquashfs...).
        process = subprocess.Popen(
            cmd,
            cwd=self.work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

        buffer = b""
        last_beat = time.time()
        cancelled = False
        try:
            fd = process.stdout.fileno()
            while True:
                if self.cancel_event is not None and self.cancel_event.is_set():
                    cancelled = True
                    self.log_signal.emit(
                        "🛑 Cancelando livecd-creator; puede tardar unos "
                        "segundos..."
                    )
                    self._terminate_process_tree(process)
                    break
                ready, _, _ = select.select([fd], [], [], 1.0)
                if ready:
                    chunk = os.read(fd, 8192)
                    if not chunk:
                        break
                    buffer += chunk
                    if b"\n" in buffer:
                        last_beat = time.time()
                    while b"\n" in buffer:
                        raw, buffer = buffer.split(b"\n", 1)
                        emit(raw.decode("utf-8", "replace"))
                elif process.poll() is not None:
                    # Sin datos pendientes y proceso terminado: drenar el resto.
                    while True:
                        chunk = os.read(fd, 8192)
                        if not chunk:
                            break
                        buffer += chunk
                    break

                if time.time() - last_beat >= 20:
                    elapsed = int(time.time() - started)
                    self.log_signal.emit(
                        "⏳ livecd-creator sigue trabajando... "
                        f"({elapsed // 60}m {elapsed % 60}s transcurridos)"
                    )
                    last_beat = time.time()
        finally:
            process.stdout.close()

        if not cancelled and buffer.strip():
            emit(buffer.decode("utf-8", "replace"))

        rc = process.wait()
        if log_handle is not None:
            log_handle.close()

        if cancelled:
            self.log_signal.emit("🛑 Compilacion cancelada por el usuario.")
            self._cleanup_stale_builds()
            return False

        if rc != 0:
            self.log_signal.emit(
                f"❌ livecd-creator fallo con codigo {rc}. "
                f"Log completo: {self.log_path}"
            )
            # livecd-creator a veces no logra desmontar (bug conocido de
            # imgcreate); dejamos el arbol limpio para el proximo intento.
            self._cleanup_stale_builds()
            return False

        self.progress_signal.emit(90)
        iso_path = self._locate_iso()
        if iso_path is not None:
            try:
                if os.path.getmtime(iso_path) < started - 5:
                    iso_path = None
            except OSError:
                # Sin permiso para leer el mtime (p. ej. /root): seguimos, la
                # reubicacion privilegiada valida que el archivo exista.
                pass
        if iso_path is None:
            self.log_signal.emit(
                "❌ livecd-creator termino bien pero no encontre la ISO en "
                f"{self.work_dir}"
            )
            return False

        destination = self._publish_iso(iso_path)
        self.last_iso_path = destination
        self.progress_signal.emit(100)
        size_gib = os.path.getsize(destination) / 1024 ** 3
        self.log_signal.emit(
            f"🎉 ISO creada con exito: {destination} ({size_gib:.2f} GiB)"
        )
        for message in self._build_success_messages():
            self.log_signal.emit(message)
        return True

    def _build_success_messages(self):
        """Mensajes de cierre del motor Kiosco (el motor Desktop los reemplaza)."""
        if self.enable_ssh:
            return [
                "💡 Usuario: kioskuser. Administración remota habilitada: "
                "ssh kioskuser@<ip> (usa clave pública si desactivaste contraseña)."
            ]
        return [
            "🔒 Usuario: kioskuser. SSH permanece deshabilitado; "
            "habilitá administración remota en la configuración si la necesitás."
        ]

    def _locate_iso(self):
        expected = os.path.join(self.work_dir, f"{self.fslabel}.iso")
        if os.path.isfile(expected):
            return expected
        candidates = glob.glob(os.path.join(self.work_dir, "*.iso"))
        if candidates:
            return max(candidates, key=os.path.getmtime)

        # Red de seguridad: un pkexec sin --keep-cwd deja la ISO en /root.
        fallback = os.path.join("/root", f"{self.fslabel}.iso")
        probe = self._run(self._priv + ["test", "-f", fallback])
        if probe.returncode == 0:
            self.log_signal.emit(
                f"📦 La ISO quedo en {fallback}; la muevo a la carpeta de salida."
            )
            return fallback
        return None

    def _publish_iso(self, source):
        output_dir = self._expand_owner_path(self.output_dir)
        os.makedirs(output_dir, exist_ok=True)

        destination = os.path.join(output_dir, self.iso_filename)
        if os.path.lexists(destination):
            stamp = time.strftime("%Y%m%d-%H%M%S")
            base = self.iso_filename[:-4]
            candidate = os.path.join(output_dir, f"{base}-{stamp}.iso")
            suffix = 1
            destination = candidate
            while os.path.lexists(destination):
                destination = os.path.join(
                    output_dir, f"{base}-{stamp}-{suffix}.iso"
                )
                suffix += 1

        script = " && ".join(
            [
                "mv -f {} {}".format(
                    shlex.quote(source), shlex.quote(destination)
                ),
                "chown {}:{} {}".format(
                    self.owner_uid, self.owner_gid, shlex.quote(destination)
                ),
            ]
        )
        self._must(
            self._run(self._priv + ["sh", "-c", script]),
            "publicar la ISO en la carpeta de salida",
        )
        return destination
