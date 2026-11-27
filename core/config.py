"""Configuración tipada de compilación y compatibilidad con project.json."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class BuildConfig:
    """Modelo tipado; los campos no reconocidos se conservan en ``extra``."""

    engine: str = ""
    project_type: str = "kiosk"
    iso_name: str = "Fedora-Custom"
    version: str = "1.0"
    release: str = "44"
    boot_mode: str = "dual"
    desktop_environment: str = "gnome"
    display_server: str = "wayland"
    hardware_modules: list[str] = field(default_factory=list)
    extra_packages: str = ""
    extra_groups: str = ""
    local_rpm_paths: list[str] = field(default_factory=list)
    output_dir: str = "~/ISOs"
    cache_dir: str = ""
    cache_enabled: bool = True
    auto_install_enabled: bool = False
    auto_install_kickstart_url: str = ""
    qemu_smoke_test: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, values: dict[str, Any] | None) -> "BuildConfig":
        source = dict(values or {})
        names = set(cls.__dataclass_fields__) - {"extra"}
        known = {key: source.pop(key) for key in list(source) if key in names}
        known["extra"] = source
        return cls(**known)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        extra = result.pop("extra")
        result.update(extra)
        return result

    def validate(self) -> None:
        if self.engine and self.engine not in {"desktop", "kiosk"}:
            raise ValueError("engine debe ser 'desktop' o 'kiosk'.")
        if self.auto_install_enabled:
            raise ValueError(
                "Anaconda no admite Kickstart automatizado desde Live ISO. "
                "Usa una ISO Netinstall, estándar o boot.iso para ese flujo."
            )


def load_project_config(path: str | Path) -> dict[str, Any]:
    """Lee un project.json y devuelve su configuración sin secretos implícitos."""
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("El archivo de proyecto debe contener un objeto JSON.")
    config = payload.get("config", payload)
    if not isinstance(config, dict):
        raise ValueError("La propiedad 'config' debe ser un objeto JSON.")
    model = BuildConfig.from_mapping(config)
    model.validate()
    return model.to_dict()
