"""Pruebas del motor Fedora Desktop independiente (Etapa 1 · 2.4)."""

import os
import stat

import pytest

from core.desktops import (
    DESKTOP_ENVIRONMENTS,
    DesktopKickstartError,
    DesktopKickstartGenerator,
    DesktopPackageError,
    KIOSK_ONLY_ENTRIES,
    UnknownDesktopEnvironmentError,
    desktop_environment_keys,
    get_desktop_environment,
    list_desktop_environments,
    supported_display_servers,
    resolve_desktop_packages,
    validate_group_names,
    validate_package_names,
)
from core.kickstart.parser import parse_packages_from_kickstart
from core.kickstart.validator import validate_kickstart_content

FAKE_HASH = "$6$testsalt$" + ("x" * 86)


def _entries(sections):
    return [entry for _title, entries in sections for entry in entries]


def _config(**overrides):
    config = {
        "desktop_environment": "gnome",
        "iso_name": "Fedora Desktop Test",
        "version": "1.0",
        "developer": "Tester",
        "release": "44",
        "boot_mode": "dual",
        "desktop_user": "tester",
        "password_hash": FAKE_HASH,
        "extra_packages": "",
        "enable_installer": True,
        "enable_firewall": True,
        "enable_ssh": False,
    }
    config.update(overrides)
    return config


def test_catalogo_tiene_los_tres_entornos_y_sus_gestores():
    assert desktop_environment_keys() == ("gnome", "kde", "xfce")
    assert get_desktop_environment("gnome")["session_manager"] == "GDM"
    assert get_desktop_environment("kde")["session_manager"] == "SDDM"
    assert get_desktop_environment("xfce")["session_manager"] == "LightDM"
    assert {key for key, _name, _manager in list_desktop_environments()} == {
        "gnome",
        "kde",
        "xfce",
    }



def test_servidores_graficos_disponibles_por_escritorio_en_fedora_44():
    assert supported_display_servers("gnome") == ("wayland",)
    assert supported_display_servers("kde") == ("wayland",)
    assert supported_display_servers("xfce") == ("x11",)


def test_resolver_rechaza_servidor_grafico_no_disponible():
    with pytest.raises(DesktopPackageError, match="no ofrece sesión x11"):
        resolve_desktop_packages("gnome", display_server="x11")
    with pytest.raises(DesktopPackageError, match="no ofrece sesión wayland"):
        resolve_desktop_packages("xfce", display_server="wayland")


def test_paquetes_de_escritorio_corresponden_al_servidor_grafico():
    kde_wayland = _entries(resolve_desktop_packages("kde", display_server="wayland"))
    xfce_x11 = _entries(resolve_desktop_packages("xfce", display_server="x11"))
    assert "plasma-workspace-wayland" in kde_wayland
    assert "xorg-x11-server-Xorg" in xfce_x11


def test_kickstart_declara_servidor_grafico_seleccionado():
    kickstart = DesktopKickstartGenerator(
        _config(desktop_environment="xfce", display_server="x11")
    ).render()
    assert "# Servidor gráfico: X11" in kickstart
    assert "# Sesión seleccionada por el proyecto: X11" in kickstart

def test_catalogo_devuelve_copias_aisladas():
    first = get_desktop_environment("gnome")
    first["packages"].append("paquete-inyectado")
    second = get_desktop_environment("gnome")
    assert "paquete-inyectado" not in second["packages"]
    assert "paquete-inyectado" not in DESKTOP_ENVIRONMENTS["gnome"]["packages"]


def test_entorno_desconocido_se_rechaza():
    with pytest.raises(UnknownDesktopEnvironmentError):
        get_desktop_environment("unity")
    with pytest.raises(UnknownDesktopEnvironmentError):
        resolve_desktop_packages("cinnamon")
    with pytest.raises(UnknownDesktopEnvironmentError):
        DesktopKickstartGenerator(_config(desktop_environment="cinnamon"))


@pytest.mark.parametrize("environment", ["gnome", "kde", "xfce"])
def test_paquetes_de_escritorio_no_incluyen_componentes_de_kiosco(environment):
    sections = resolve_desktop_packages(environment)
    entries = _entries(sections)
    assert not (set(entries) & KIOSK_ONLY_ENTRIES)
    assert get_desktop_environment(environment)["display_manager"] in entries
    assert get_desktop_environment(environment)["groups"][0] in entries
    assert "@core" in entries


@pytest.mark.parametrize(
    "environment,manager,service",
    [
        ("gnome", "gdm", "gdm.service"),
        ("kde", "sddm", "sddm.service"),
        ("xfce", "lightdm", "lightdm.service"),
    ],
)
def test_kickstart_selecciona_el_gestor_correcto(environment, manager, service):
    generator = DesktopKickstartGenerator(_config(desktop_environment=environment))
    kickstart = generator.render()
    packages = parse_packages_from_kickstart(kickstart)

    assert manager in packages
    assert service in kickstart
    assert "graphical.target" in kickstart
    assert "authselect select local --force" in kickstart
    assert "rootpw --lock" in kickstart
    assert "%post --erroronfail" in kickstart
    assert "repo --name=fedora" in kickstart
    assert get_desktop_environment(environment)["groups"][0] in packages

    # Los componentes del motor Kiosco no deben aparecer ni como paquete ni
    # como servicio en la receta de escritorio.
    for forbidden in ("cage", "sway", "seatd", "kioskuser", "kiosk.service"):
        assert forbidden not in packages
        assert forbidden not in kickstart


def test_kickstart_incluye_rpm_local_como_paquete_y_repo():
    generator = DesktopKickstartGenerator(
        _config(
            local_rpm_packages=["sample-local-app"],
            local_rpm_repo="/var/tmp/creador/local-rpms",
        )
    )
    kickstart = generator.render()
    packages = parse_packages_from_kickstart(kickstart)
    assert "sample-local-app" in packages
    assert 'repo --name=creador-local-rpms --baseurl="file:///var/tmp/creador/local-rpms"' in kickstart


def test_kickstart_incluye_grupos_extra_seleccionados():
    generator = DesktopKickstartGenerator(
        _config(extra_groups="@office @multimedia")
    )
    packages = parse_packages_from_kickstart(generator.render())
    assert "@office" in packages
    assert "@multimedia" in packages


@pytest.mark.parametrize("environment", ["gnome", "kde", "xfce"])
def test_kickstart_generado_pasa_el_validador(environment):
    kickstart = DesktopKickstartGenerator(
        _config(desktop_environment=environment)
    ).render()
    errors = [
        message
        for level, message in validate_kickstart_content(kickstart)
        if level == "error"
    ]
    assert errors == []


def test_paquetes_adicionales_validos_se_incluyen():
    sections = resolve_desktop_packages("gnome", extra_packages="htop, git")
    entries = _entries(sections)
    assert "htop" in entries
    assert "git" in entries


def test_paquete_invalido_se_rechaza():
    with pytest.raises(DesktopPackageError) as excinfo:
        resolve_desktop_packages("gnome", extra_packages="htop;rm -rf /")
    assert "nombres inválidos" in str(excinfo.value)


def test_paquete_bloqueado_se_rechaza():
    with pytest.raises(DesktopPackageError) as excinfo:
        resolve_desktop_packages("gnome", extra_packages="telnet")
    assert "bloqueados" in str(excinfo.value)


def test_grupo_como_paquete_se_rechaza():
    result = validate_package_names(["@gnome-desktop"])
    assert result["allowed"] == []
    assert "@gnome-desktop" in result["invalid"]


def test_politica_de_grupos_es_separada_de_la_de_paquetes():
    valid = validate_group_names(
        ["@gnome-desktop", "@^workstation-product-environment"]
    )
    assert valid["invalid"] == []
    invalid = validate_group_names(["gnome-desktop", "@bad group"])
    assert "gnome-desktop" in invalid["invalid"]
    assert "@bad group" in invalid["invalid"]

    sections = resolve_desktop_packages(
        "gnome", extra_groups=["@development-tools"]
    )
    assert "@development-tools" in _entries(sections)

    with pytest.raises(DesktopPackageError):
        resolve_desktop_packages("gnome", extra_groups=["development-tools"])


def test_modo_de_arranque_desconocido_se_rechaza():
    with pytest.raises(DesktopKickstartError):
        DesktopKickstartGenerator(_config(boot_mode="floppy")).render()
    with pytest.raises(DesktopPackageError):
        resolve_desktop_packages("gnome", boot_mode="floppy")


def test_modo_bios_no_incluye_paquetes_uefi():
    sections = resolve_desktop_packages("gnome", boot_mode="bios")
    assert "shim-x64" not in _entries(sections)


def test_instalador_se_puede_desactivar():
    with_installer = parse_packages_from_kickstart(
        DesktopKickstartGenerator(_config(enable_installer=True)).render()
    )
    without_installer = parse_packages_from_kickstart(
        DesktopKickstartGenerator(_config(enable_installer=False)).render()
    )
    assert "anaconda" in with_installer
    assert "anaconda" not in without_installer


def test_ssh_solo_se_configura_cuando_se_habilita():
    disabled = DesktopKickstartGenerator(_config(enable_ssh=False)).render()
    enabled = DesktopKickstartGenerator(_config(enable_ssh=True)).render()

    assert "00-creador-desktop.conf" not in disabled
    assert "sshd" not in disabled.split("%packages", 1)[1].split("%end", 1)[0]
    assert "00-creador-desktop.conf" in enabled
    assert "sshd" in enabled


def test_firewall_se_puede_desactivar():
    kickstart = DesktopKickstartGenerator(
        _config(enable_firewall=False)
    ).render()
    packages = parse_packages_from_kickstart(kickstart)
    assert "firewall --disabled" in kickstart
    assert "firewalld" not in packages
    assert "systemctl enable firewalld.service" not in kickstart


def test_hash_de_contrasena_invalido_se_rechaza():
    generator = DesktopKickstartGenerator(_config())
    for value in ("texto-plano", "$6$solo-salt", "$1$md5$hash"):
        with pytest.raises(DesktopKickstartError):
            generator.render(value)


def test_sin_contrasena_ni_hash_se_rechaza():
    config = _config()
    config.pop("password_hash")
    with pytest.raises(DesktopKickstartError):
        DesktopKickstartGenerator(config).render()


def test_usuario_invalido_se_rechaza():
    for username in ("Root", "1usuario", "usuario con espacio", "usuario;rm"):
        with pytest.raises(DesktopKickstartError):
            DesktopKickstartGenerator(_config(desktop_user=username)).render()


def test_nombre_de_producto_inseguro_se_rechaza():
    with pytest.raises(DesktopKickstartError):
        DesktopKickstartGenerator(
            _config(product_name='Producto"$(rm -rf /)')
        ).render()


def test_write_es_atomico_y_privado(tmp_path):
    target = tmp_path / "desktop.ks"
    result = DesktopKickstartGenerator(_config()).write(target)
    assert result == str(target)
    mode = stat.S_IMODE(os.stat(target).st_mode)
    assert mode == 0o600
    assert "%packages" in target.read_text(encoding="utf-8")
    assert not list(tmp_path.glob(".desktop-kickstart-*"))


def test_el_perfil_kiosco_conserva_sus_componentes():
    """Regresión: el motor Desktop no altera la receta Kiosco existente."""
    from core.builder import KioskISOBuilder

    builder = KioskISOBuilder(
        {"iso_name": "TestKiosk", "app_mode": "chromium", "app_url": "http://x"}
    )
    packages = builder._package_lines(builder._resolve_app())
    assert "cage" in packages
    assert "seatd" in packages


def test_kickstart_incluye_banner_y_mensaje_personalizados_del_instalador(tmp_path):
    import base64

    banner = tmp_path / "desktop-installer.png"
    banner.write_bytes(b"desktop-banner-bytes")
    welcome = "Bienvenido a TallerArgOS\nInstalación personalizada"
    kickstart = DesktopKickstartGenerator(
        _config(installer_banner=str(banner), installer_text=welcome)
    ).render()

    assert base64.b64encode(b"desktop-banner-bytes").decode("ascii") in kickstart
    assert base64.b64encode(welcome.encode("utf-8")).decode("ascii") in kickstart
    assert "/usr/share/anaconda/pixmaps/top-banner.png" in kickstart
    assert "/usr/share/anaconda/help/welcome.txt" in kickstart
    assert "/etc/creador-personalizado/installer-message.txt" in kickstart
    assert not [issue for level, issue in validate_kickstart_content(kickstart) if level == "error"]


def test_kickstart_no_incluye_branding_del_instalador_si_anaconda_esta_deshabilitado(tmp_path):
    banner = tmp_path / "desktop-installer.png"
    banner.write_bytes(b"desktop-banner-bytes")
    kickstart = DesktopKickstartGenerator(
        _config(enable_installer=False, installer_banner=str(banner),
                installer_text="No debe aparecer")
    ).render()
    assert "top-banner.png" not in kickstart
    assert "installer-message.txt" not in kickstart


def test_kickstart_rechaza_banner_de_instalador_inexistente():
    with pytest.raises(DesktopKickstartError, match="No existe la imagen banner"):
        DesktopKickstartGenerator(
            _config(installer_banner="/ruta/inexistente/banner.png")
        ).render()
