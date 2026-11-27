"""Validacion por etapas del asistente, independiente de la interfaz."""

import os
import re
import shutil
from dataclasses import dataclass

from core.builder import (
    BUILD_ROOT,
    DEFAULT_OUTPUT_DIR,
    MAX_PLYMOUTH_BYTES,
    MIN_FREE_BYTES,
    validate_product_name,
)
from core.builders import BuildEngineError, resolve_build_engine
from core.desktops.environments import (
    UnknownDesktopEnvironmentError,
    get_desktop_environment,
)
from core.desktops.kickstart import USERNAME_PATTERN
from core.desktops.packages import DesktopPackageError, resolve_desktop_packages
from core.projects.catalog import list_project_types
from core.software.policy import validate_group_names, validate_package_names

MIN_OUTPUT_FREE_BYTES = 2 * 1024 ** 3


@dataclass(frozen=True)
class Issue:
    step: int
    title: str
    message: str


def _expanded(value):
    return os.path.abspath(os.path.expanduser((value or "").strip()))


def _existing_parent(path):
    candidate = path
    while not os.path.exists(candidate):
        parent = os.path.dirname(candidate)
        if parent == candidate:
            return candidate
        candidate = parent
    return candidate


def _check_image(path, max_bytes, label):
    if not path:
        return None
    path = _expanded(path)
    if not os.path.isfile(path):
        return (f"Falta la imagen de {label}", f"El archivo ya no existe:\n{path}")
    if os.path.getsize(path) > max_bytes:
        limit = max_bytes // (1024 * 1024)
        return (
            f"Imagen de {label} demasiado grande",
            f"El archivo supera el limite de {limit} MiB.",
        )
    return None


def _uses_local_rpm(config):
    """Misma regla que el builder para RPM locales seleccionados."""
    app_mode = str(config.get("app_mode") or "").lower()
    app_path = str(config.get("app_path") or "").lower()
    if app_mode == "custom" and app_path.endswith(".rpm"):
        return True
    return bool(
        config.get("multi_app")
        and str(config.get("app2_mode") or "").lower() == "local"
        and str(config.get("app2_path") or "").lower().endswith(".rpm")
    )


def validate_identity(config):
    issues = []
    iso_name = (config.get("iso_name") or "").strip()
    version = (config.get("version") or "").strip()
    developer = (config.get("developer") or "").strip()
    password = config.get("password") or ""

    project_type = str(config.get("project_type") or "kiosk").strip().lower()
    valid_project_types = {
        key for key, _name, _tagline in list_project_types()
    }
    if project_type and project_type not in valid_project_types:
        issues.append(
            Issue(
                1,
                "Tipo de distribución no válido",
                f"Tipo de proyecto desconocido: {project_type}. "
                f"Válidos: {', '.join(sorted(valid_project_types))}.",
            )
        )

    if not iso_name or not version or not developer:
        issues.append(Issue(1, "Datos incompletos", "Completa el nombre de la ISO, la version y el creador."))
    if iso_name and (
        len(iso_name) > 60
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", iso_name)
    ):
        issues.append(Issue(1, "Nombre de ISO no valido", "Usa hasta 60 caracteres: letras, numeros, punto, guion y guion bajo."))
    if version and (
        len(version) > 20
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", version)
    ):
        issues.append(Issue(1, "Version no valida", "Usa hasta 20 caracteres alfanumericos, punto, guion, guion bajo o +."))
    if developer and (len(developer) > 80 or any(ord(ch) < 32 for ch in developer)):
        issues.append(Issue(1, "Creador no valido", "El nombre del creador debe tener hasta 80 caracteres en una sola linea."))

    product_error = validate_product_name((config.get("product_name") or "").strip())
    if product_error is not None:
        issues.append(Issue(1, "Nombre del producto no valido", product_error))

    if project_type != "kiosk" and (
        not password or len(password) > 128
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in password)
    ):
        issues.append(Issue(1, "Contrasena inicial no valida", "Ingresa una contrasena no vacia de hasta 128 caracteres, sin caracteres de control ni saltos de linea."))
    return issues


def validate_appearance(config):
    issues = []
    problem = _check_image(config.get("plymouth_image"), MAX_PLYMOUTH_BYTES, "boot splash")
    if problem:
        issues.append(Issue(2, *problem))
    return issues


def _engine_for_validation(config):
    try:
        return resolve_build_engine(config)
    except BuildEngineError:
        return "kiosk"


def _validate_desktop_software(config):
    """Validación del paso de software cuando el motor es Desktop."""
    issues = []
    environment = config.get("desktop_environment") or "gnome"
    try:
        get_desktop_environment(environment)
    except UnknownDesktopEnvironmentError as exc:
        issues.append(Issue(3, "Escritorio no válido", str(exc)))

    username = str(config.get("desktop_user") or "fedora").strip()
    if not USERNAME_PATTERN.fullmatch(username):
        issues.append(
            Issue(
                3,
                "Usuario de escritorio no válido",
                "Usá minúsculas, números, guion o guion bajo, hasta 32 "
                "caracteres y sin empezar por número.",
            )
        )

    try:
        resolve_desktop_packages(
            environment,
            extra_packages=config.get("extra_packages") or "",
            extra_groups=config.get("extra_groups") or (),
            enable_firewall=bool(config.get("enable_firewall", True)),
            enable_ssh=bool(config.get("enable_ssh", False)),
            enable_installer=bool(config.get("enable_installer", True)),
            boot_mode=config.get("boot_mode") or "dual",
            display_server=config.get("display_server"),
            hardware_modules=config.get("hardware_modules"),
            wifi_live_assistant=bool(config.get("wifi_live_assistant", False)),
        )
    except (DesktopPackageError, UnknownDesktopEnvironmentError) as exc:
        issues.append(Issue(3, "Selección de software no válida", str(exc)))
    return issues


def validate_software(config):
    issues = []
    for rpm_path in config.get("local_rpm_paths") or []:
        expanded = _expanded(str(rpm_path))
        if not expanded.lower().endswith(".rpm") or not os.path.isfile(expanded):
            issues.append(Issue(
                3, "RPM local no disponible",
                f"El archivo RPM seleccionado no existe o no es válido: {expanded}",
            ))
    package_result = validate_package_names(config.get("extra_packages") or "")
    if package_result["invalid"]:
        names = ", ".join(f"'{name}'" for name in package_result["invalid"])
        issues.append(Issue(3, "Paquetes no validos", f"Nombres de paquete no validos: {names}. Usa solo letras, numeros, punto, guion, guion bajo o +."))
    if package_result["blocked"]:
        names = ", ".join(package_result["blocked"])
        issues.append(Issue(3, "Paquetes bloqueados", f"Paquetes bloqueados por politica de seguridad: {names}."))

    group_result = validate_group_names(config.get("extra_groups") or "")
    if group_result["invalid"]:
        names = ", ".join(f"'{name}'" for name in group_result["invalid"])
        issues.append(Issue(3, "Grupos no validos", f"Grupos de paquetes no validos: {names}. Deben empezar con @ y usar solo letras, numeros, punto, guion, guion bajo o +."))

    if _engine_for_validation(config) == "desktop":
        issues.extend(_validate_desktop_software(config))
        return issues

    mode = config.get("app_mode") or "chromium"
    if mode == "custom":
        path = config.get("app_path") or ""
        if not path or not os.path.exists(_expanded(path)):
            issues.append(Issue(3, "Falta la aplicacion", "Selecciona el archivo o la carpeta de la aplicacion local."))
    elif not (config.get("app_url") or "").strip():
        issues.append(Issue(3, "Falta la URL", "Indica la URL que abrira el navegador."))

    if config.get("multi_app"):
        mode2 = config.get("app2_mode") or "chromium"
        if mode2 in ("chromium", "firefox", "firefox-es") and not (config.get("app2_url") or "").strip():
            issues.append(Issue(3, "Falta la URL de la segunda app", "Indica la URL que abrira la segunda aplicacion."))
        elif mode2 == "custom":
            command = config.get("app2_command") or ""
            if not command.strip():
                issues.append(Issue(3, "Falta la segunda aplicacion", "Indica el comando de la segunda aplicacion."))
            elif "\n" in command or "\r" in command:
                issues.append(Issue(3, "Comando no valido", "El comando de la segunda aplicacion debe ser una sola linea."))
        elif mode2 == "local":
            path = config.get("app2_path") or ""
            if not path or not os.path.isfile(_expanded(path)):
                issues.append(Issue(3, "Falta la segunda aplicacion", "Selecciona el archivo, script o RPM de la segunda aplicacion local."))
    return issues


def validate_installer(config):
    issues = []
    if config.get("auto_install_enabled"):
        issues.append(Issue(
            4, "Kickstart desatendido no compatible con Live ISO",
            "Anaconda no admite Kickstart automatizado desde Live ISO. "
            "Usa una ISO Netinstall, estándar o boot.iso."
        ))
    problem = _check_image(config.get("installer_banner"), MAX_PLYMOUTH_BYTES, "banner del instalador")
    if problem:
        issues.append(Issue(4, *problem))
    return issues


def validate_security(config):
    issues = []
    if config.get("ssh_password_auth") and not config.get("enable_ssh"):
        issues.append(Issue(5, "SSH incoherente", "La autenticacion SSH por contrasena requiere habilitar SSH."))
    return issues


def validate_build(config):
    issues = []
    from gui.status import check_dependencies

    dependencies = check_dependencies()
    if not dependencies["ok"]:
        names = ", ".join(
            f"{item['name']} ({item['package']})" for item in dependencies["missing"]
        )
        issues.append(Issue(6, "Dependencias faltantes", f"Faltan herramientas o activos: {names}. Instalalos antes de compilar."))

    if _uses_local_rpm(config):
        missing = [
            binary
            for binary in ("rpm", "createrepo_c")
            if shutil.which(binary) is None
        ]
        if missing:
            issues.append(
                Issue(
                    6,
                    "Herramientas para RPM locales",
                    "La selección incluye un RPM local y el host no tiene: "
                    + ", ".join(missing)
                    + ". Instalalos con: sudo dnf install rpm createrepo_c.",
                )
            )

    output = _expanded(config.get("output_dir") or DEFAULT_OUTPUT_DIR)
    if os.path.exists(output) and not os.path.isdir(output):
        issues.append(Issue(6, "Carpeta de salida no valida", f"La ruta existe pero no es una carpeta:\n{output}"))
    else:
        parent = _existing_parent(output)
        if not os.path.isdir(parent):
            issues.append(Issue(6, "Carpeta de salida no valida", f"No se puede determinar una carpeta contenedora para:\n{output}"))
        else:
            if not os.access(parent, os.W_OK):
                issues.append(Issue(6, "Sin permiso de escritura", f"No hay permiso para escribir en:\n{parent}"))
            try:
                free = shutil.disk_usage(parent).free
            except OSError as exc:
                issues.append(Issue(6, "No se puede consultar el espacio", f"{parent}: {exc}"))
            else:
                if free < MIN_OUTPUT_FREE_BYTES:
                    issues.append(Issue(6, "Espacio insuficiente para la ISO", f"Quedan {free / 1024 ** 3:.1f} GiB en {parent}; se recomiendan al menos 2 GiB para la ISO."))

    try:
        work_root = os.environ.get("KIOSK_BUILD_ROOT") or BUILD_ROOT
        work_free = shutil.disk_usage(_existing_parent(work_root)).free
    except OSError:
        work_free = None
    if work_free is not None and work_free < MIN_FREE_BYTES:
        issues.append(
            Issue(
                6,
                "Espacio insuficiente para compilar",
                f"El arbol de trabajo requiere al menos 12 GiB libres y quedan {work_free / 1024 ** 3:.1f} GiB.",
            )
        )
    return issues


VALIDATORS = {
    1: validate_identity,
    2: validate_appearance,
    3: validate_software,
    4: validate_installer,
    5: validate_security,
    6: validate_build,
}


def validate_step(step, config):
    validator = VALIDATORS.get(step)
    return validator(config) if validator else []


def validate_all(config):
    issues = []
    for step in range(1, 7):
        issues.extend(validate_step(step, config))
    return issues


def validate_until(step, config):
    if step <= 0:
        return []
    issues = []
    for current in range(1, step + 1):
        issues.extend(validate_step(current, config))
    return issues
