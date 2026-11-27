"""Inspección y política común de seguridad para paquetes RPM locales."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from core.security.rpm_verifier import verify_rpm_signature

_QUERY = "%{NAME}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SUMMARY}"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


class LocalRPMError(ValueError):
    """RPM local inválido, no inspeccionable o no confiable."""


def inspect_local_rpm(path: str | os.PathLike, *, allow_unsigned: bool = False) -> dict:
    """Devuelve metadatos de un RPM tras verificar digest y firma.

    Los paquetes sin firma solo se devuelven si el usuario los autorizó
    explícitamente; los digests incorrectos o no verificables siempre fallan.
    """
    source = Path(path).expanduser()
    if not source.is_file() or source.is_symlink():
        raise LocalRPMError(f"El archivo RPM no existe o no es un archivo regular: {source}")
    source = source.resolve(strict=True)
    if source.suffix.lower() != ".rpm":
        raise LocalRPMError(f"El archivo no tiene extensión .rpm: {source.name}")
    rpm = shutil.which("rpm")
    if not rpm:
        raise LocalRPMError("No está instalado rpm; no se puede inspeccionar el paquete.")

    verification = verify_rpm_signature(str(source))
    if not verification.get("digest_ok"):
        raise LocalRPMError(verification.get("error") or "Digest RPM no verificable.")
    if not verification.get("trusted") and not (
        verification.get("unsigned") and allow_unsigned
    ):
        reason = verification.get("error") or "La firma no es confiable."
        if verification.get("unsigned"):
            reason += " Activa la autorización explícita para RPM sin firma si aceptas el riesgo."
        raise LocalRPMError(reason)

    try:
        result = subprocess.run(
            [rpm, "-qp", "--qf", _QUERY, str(source)],
            capture_output=True, text=True, timeout=20,
            stdin=subprocess.DEVNULL, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LocalRPMError(f"No se pudieron leer los metadatos RPM: {exc}") from exc
    if result.returncode != 0:
        raise LocalRPMError((result.stderr or "rpm no pudo leer el paquete.").strip())
    fields = (result.stdout or "").strip().split("\t", 4)
    if len(fields) != 5 or not _NAME_RE.fullmatch(fields[0]) or not fields[3]:
        raise LocalRPMError("El RPM devolvió metadatos incompletos o inválidos.")
    name, version, release, arch, summary = fields
    return {
        "path": str(source), "name": name, "version": version,
        "release": release, "arch": arch, "summary": summary,
        "signed": bool(verification.get("signed")),
        "trusted": bool(verification.get("trusted")),
        "unsigned": bool(verification.get("unsigned")),
        "digest_ok": bool(verification.get("digest_ok")),
        "verification": verification,
    }


def inspect_local_rpms(paths, *, allow_unsigned: bool = False) -> list[dict]:
    """Inspecciona una lista completa y rechaza duplicados por nombre/arquitectura."""
    results = []
    seen = set()
    for path in paths or []:
        item = inspect_local_rpm(path, allow_unsigned=allow_unsigned)
        key = (item["name"], item["arch"])
        if key in seen:
            raise LocalRPMError(f"Hay más de un RPM seleccionado para {item['name']} ({item['arch']}).")
        seen.add(key)
        results.append(item)
    return results
