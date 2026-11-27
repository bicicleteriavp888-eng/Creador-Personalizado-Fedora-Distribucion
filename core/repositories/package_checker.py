"""Comprobaciones estrictas de nombres y existencia de paquetes Fedora."""

import re
import shutil
import subprocess

PACKAGE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")


def split_package_names(raw):
    return [pkg for pkg in re.split(r"[\s,]+", raw or "") if pkg]


def invalid_package_names(raw):
    return [pkg for pkg in split_package_names(raw) if not PACKAGE_RE.fullmatch(pkg)]


def validate_product_name(value):
    value = (value or "").strip()
    if len(value) > 80:
        return "El nombre del producto admite hasta 80 caracteres."
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return "El nombre del producto no puede contener caracteres de control ni saltos de linea."
    if '"' in value or "\\" in value or "$" in value:
        return "El nombre del producto no puede contener comillas dobles, barras invertidas ni el caracter $."
    return None


def check_package_exists(pkg_name):
    """Comprueba un paquete con DNF; cualquier fallo de consulta es fail-closed.

    El resultado False significa que el paquete no pudo confirmarse como
    disponible. No distingue entre inexistencia y fallo de repositorio; los
    llamadores que necesiten el motivo deben usar DnfQuery directamente.
    """
    pkg_name = (pkg_name or "").strip()
    if not pkg_name or not PACKAGE_RE.fullmatch(pkg_name):
        return False
    dnf_bin = shutil.which("dnf5") or shutil.which("dnf")
    if not dnf_bin:
        return False
    try:
        result = subprocess.run(
            [dnf_bin, "-q", "repoquery", "--available", "--qf", "%{name}", pkg_name],
            capture_output=True, text=True, timeout=20,
            stdin=subprocess.DEVNULL, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    return any(line.strip() == pkg_name for line in (result.stdout or "").splitlines())
