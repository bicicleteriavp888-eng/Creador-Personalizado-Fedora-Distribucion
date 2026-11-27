"""Pruebas de humo de la interfaz 2.0 con Qt offscreen."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from core.repositories.dnf_query import DnfGroup, DnfRepository
from main import KioskBuilderGUI, STEP_KEYS


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    widget = KioskBuilderGUI()
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    app.processEvents()


def test_window_has_dashboard_six_steps_and_usb(window, app):
    expected = {
        "dashboard",
        "custom_distro",
        "step1",
        "step2",
        "step3",
        "step4",
        "step5",
        "step6",
        "kiosk_config",
        "usb",
    }
    assert set(window._pages) == expected
    # dashboard, seis pasos, configuración Kiosco y dos herramientas.
    assert len(window._nav_buttons) == 10
    assert window.stack.count() == 10
    assert window.combo_ui_mode.count() == 2
    assert window.combo_theme.count() == 2
    assert window._navigate("step1", validate=False)
    app.processEvents()
    assert window.stack.currentWidget() is window._pages["step1"]["widget"]
    assert window.lbl_breadcrumb.text() == "Asistente · Paso 1 de 6"


def test_theme_switch_changes_stylesheet(window):
    window._apply_theme("dark")
    assert "#0f1722" in window.styleSheet()
    assert window.theme_name == "dark"
    window._apply_theme("light")
    assert "#f3f6fb" in window.styleSheet()
    assert window.theme_name == "light"


def test_simple_mode_hides_advanced_options_and_resets_them(window, app):
    window._navigate("step1", validate=False)
    window._apply_ui_mode("advanced", confirm=False)
    app.processEvents()
    assert window.combo_base.isVisible()
    assert window.combo_boot.isVisible()

    window.check_multi_app.setChecked(True)
    window._apply_ui_mode("simple", confirm=False)
    app.processEvents()
    assert window.ui_mode == "simple"
    assert not window.combo_base.isVisible()
    assert not window.combo_boot.isVisible()
    assert not window.check_multi_app.isChecked()


def test_wizard_blocks_progress_with_invalid_step(window):
    shown = []
    window._show_issues = lambda issues: shown.extend(issues)
    # El perfil Desktop exige contraseña inicial; Kiosco no la usa.
    window.combo_project_type.setCurrentIndex(
        window.combo_project_type.findData("office")
    )
    window.txt_password.setText("")
    assert window._navigate("step1", validate=False)
    assert window._navigate("step2", validate=True)
    assert shown
    assert window._current_key == "step1"

    window.txt_password.setText("clave-segura-123")
    assert window._navigate("step2", validate=True)
    assert window._current_key == "step2"


def test_step_indicators_mark_complete_steps(window):
    window.txt_password.setText("clave-segura-123")
    window._refresh_step_indicators()
    assert window._nav_buttons["step1"].text().startswith("✓")


def test_help_panel_matches_current_page(window, app):
    window._navigate("step3", validate=False)
    window._on_help()
    app.processEvents()
    assert window.help_panel.isVisible()
    assert "Selección de software" in window.help_panel.title.text()
    window._on_help()
    app.processEvents()
    assert not window.help_panel.isVisible()


def test_dashboard_shows_real_environment_data(window):
    window.refresh_dashboard()
    assert window.card_deps.value.text() != "—"
    assert window.card_disk.value.text() != "—"
    assert window.card_services.value.text() != "—"
    assert window.card_config.value.text() == window.txt_name.text()


def test_settings_restore_but_never_persist_password(window, app, tmp_path, monkeypatch):
    window.txt_name.setText("PerfilPrueba")
    window.txt_password.setText("clave-segura-123")
    window._on_save()
    window._settings.sync()
    window.close()
    app.processEvents()

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    restored = KioskBuilderGUI()
    restored.show()
    app.processEvents()
    try:
        assert restored.txt_name.text() == "PerfilPrueba"
        assert restored.txt_password.text() == ""
    finally:
        restored.close()
        app.processEvents()


def test_all_wizard_pages_are_reachable_with_valid_config(window):
    window.txt_password.setText("clave-segura-123")
    window._show_issues = lambda issues: pytest.fail(str(issues))
    for key in STEP_KEYS:
        assert window._navigate(key, validate=True)
        assert window._current_key == key


def test_collect_config_keeps_backend_compatibility(window):
    window.combo_project_type.setCurrentIndex(
        window.combo_project_type.findData("kiosk")
    )
    window.txt_password.setText("clave-segura-123")
    config = window.collect_config()
    expected = {
        "iso_name",
        "version",
        "developer",
        "product_name",
        "release",
        "boot_mode",
        "password",
        "enable_firewall",
        "enable_ssh",
        "ssh_password_auth",
        "sudo_nopasswd",
        "chromium_no_sandbox",
        "resolution",
        "plymouth_image",
        "installer_banner",
        "installer_text",
        "enable_installer",
        "app_mode",
        "app_url",
        "app_path",
        "multi_app",
        "app2_mode",
        "app2_url",
        "app2_command",
        "app2_path",
        "extra_packages",
        "extra_groups",
        "restart_on_crash",
        "block_vt",
        "output_dir",
    }
    assert expected <= set(config)
    assert config["password"] == "clave-segura-123"
    assert config["release"] == "44"
    assert config["engine"] == "kiosk"


def test_collect_config_resuelve_el_motor_del_perfil(window):
    window._project_type = "office"
    config = window.collect_config()
    assert config["project_type"] == "office"
    assert config["engine"] == "desktop"
    assert config["desktop_environment"] == "gnome"
    assert config["desktop_user"] == "fedora"


def test_collect_config_prioriza_perfil_si_motor_auxiliar_quedo_desactualizado(window):
    window._project_type = "office"
    window._build_engine = "kiosk"

    config = window.collect_config()

    assert config["project_type"] == "office"
    assert config["engine"] == "desktop"


def test_stage4_project_type_oficina_selecciona_motor_desktop(window, app):
    window.combo_project_type.setCurrentIndex(
        window.combo_project_type.findData("office")
    )
    app.processEvents()

    assert window._project_type == "office"
    assert window.collect_config()["engine"] == "desktop"
    assert not window.group_desktop_env.isHidden()


def test_stage4_desktop_environment_seleccionable_hasta_kde(window, app):
    window.combo_project_type.setCurrentIndex(
        window.combo_project_type.findData("gaming")
    )
    window.combo_desktop_env.setCurrentIndex(window.combo_desktop_env.findData("kde"))
    app.processEvents()

    assert window._desktop_environment == "kde"
    assert window.collect_config()["engine"] == "desktop"
    assert window.collect_config()["desktop_environment"] == "kde"


def test_stage4_kiosk_no_muestra_selector_de_escritorio(window, app):
    window.combo_project_type.setCurrentIndex(
        window.combo_project_type.findData("kiosk")
    )
    app.processEvents()

    assert window._project_type == "kiosk"
    assert window.collect_config()["engine"] == "kiosk"
    assert window.group_desktop_env.isHidden()


def test_stage4_build_summary_refresca_desde_collect_config(window, app):
    window.combo_project_type.setCurrentIndex(
        window.combo_project_type.findData("office")
    )
    window.combo_desktop_env.setCurrentIndex(window.combo_desktop_env.findData("kde"))
    window.refresh_build_summary()
    app.processEvents()

    summary = window.lbl_build_summary.text()
    assert "Motor: desktop" in summary
    assert "Escritorio: kde" in summary
    assert "ISO: " in summary


def test_validate_step_button_is_only_visible_for_wizard_steps(window, app):
    window._navigate("dashboard", validate=False)
    app.processEvents()
    assert not window.btn_validate_step.isVisible()

    window._navigate("step1", validate=False)
    app.processEvents()
    assert window.btn_validate_step.isVisible()

    window._navigate("usb", validate=False)
    app.processEvents()
    assert not window.btn_validate_step.isVisible()


def test_validate_step_button_reports_issues_without_advancing(window, app):
    shown = []
    window._show_issues = lambda issues: shown.extend(issues)
    window.txt_password.setText("")
    assert window._navigate("step1", validate=False)
    app.processEvents()

    window.btn_validate_step.click()
    app.processEvents()

    assert shown
    assert window._current_key == "step1"
    assert "error" in window.lbl_wizard_status.text().lower()

    window.txt_password.setText("clave-segura-123")
    window.btn_validate_step.click()
    app.processEvents()

    assert "sin errores criticos" in window.lbl_wizard_status.text()
    assert window._current_key == "step1"


def test_dashboard_hashes_existing_iso_in_background(window, app, tmp_path):
    import hashlib

    iso = tmp_path / "Prueba.iso"
    payload = b"contenido-de-prueba" * 1024
    iso.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()

    window._settings.setValue("last_iso_path", str(iso))
    window._settings.setValue("last_iso_size", iso.stat().st_size)
    window._settings.setValue("last_iso_mtime", int(iso.stat().st_mtime))
    window._settings.setValue("last_iso_sha256", "")
    window._settings.setValue("last_build_status", "ok")

    window.refresh_dashboard()
    assert window.hash_worker is not None
    assert window.hash_worker.wait(5000)
    for _ in range(5):
        app.processEvents()

    assert expected in window.card_hash.detail.text()
    assert window._settings.value("last_iso_sha256") == expected


def test_custom_distro_group_selection_is_applied(window, app):
    window._show_groups([DnfGroup("office", "Office/Productivity", False)])
    window.combo_dnf_group.setCurrentIndex(0)

    window._add_custom_group()
    app.processEvents()

    assert "@office" in window._custom_groups
    assert window.list_groups_selected.item(0).text() == "@office"

    window.apply_custom_distro_selection()
    app.processEvents()
    assert window.txt_extra_groups.text() == "@office"
    assert window.collect_config()["extra_groups"] == "@office"


def test_custom_distro_rejects_invalid_group_before_adding(window, app, monkeypatch):
    warnings = []
    monkeypatch.setattr(
        "gui.custom_distro.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append(args),
    )
    window.combo_dnf_group.clear()
    window.combo_dnf_group.addItem("Grupo inválido", "@grupo con espacios")
    window.combo_dnf_group.setCurrentIndex(0)

    window._add_custom_group()
    app.processEvents()

    assert window._custom_groups == set()
    assert warnings


def test_custom_distro_shows_enabled_repositories(window):
    window._show_repositories(
        [
            DnfRepository("fedora", "Fedora 44 - x86_64"),
            DnfRepository("updates", "Fedora 44 - x86_64 - Updates"),
        ]
    )
    assert "2 repositorios habilitados" in window.lbl_repos_status.text()
    assert "fedora — Fedora 44 - x86_64" in window.lbl_repos_status.toolTip()


def test_step3_muestra_catalogo_y_servidor_grafico_compatible(window, app):
    window._project_type = "office"
    window._build_engine = "desktop"
    window._desktop_environment = "gnome"
    window._display_server = "wayland"
    window.refresh_desktop_environment_fields()
    app.processEvents()

    assert window.group_kiosk_app.isHidden()
    assert window.group_software is not None
    assert window.btn_open_software_manager.text() == "Abrir gestor de software Fedora…"
    assert not window.group_desktop_env.isHidden()
    assert window.combo_display_server.findData("wayland") >= 0
    assert window.combo_display_server.findData("x11") >= 0
    assert not window.combo_display_server.model().item(
        window.combo_display_server.findData("x11")
    ).isEnabled()

    window._desktop_environment = "xfce"
    window._display_server = "x11"
    window.refresh_desktop_environment_fields()
    assert window.combo_display_server.currentData() == "x11"
    assert not window.combo_display_server.model().item(
        window.combo_display_server.findData("wayland")
    ).isEnabled()


def test_kiosk_configuration_is_separate_from_desktop_configuration(window, app):
    kiosk_button = window._nav_buttons["kiosk_config"]
    assert kiosk_button.isVisible()
    assert window._navigate("kiosk_config", validate=False)
    assert window.stack.currentWidget() is window._pages["kiosk_config"]["widget"]

    window.combo_project_type.setCurrentIndex(
        window.combo_project_type.findData("office")
    )
    app.processEvents()
    assert not kiosk_button.isVisible()
    assert not window.group_desktop_account.isHidden()
    assert not window.group_desktop_env.isHidden()
    assert window.group_kiosk_app.isHidden()
    assert not window._navigate("kiosk_config", validate=False)

    window.combo_project_type.setCurrentIndex(
        window.combo_project_type.findData("kiosk")
    )
    app.processEvents()
    assert kiosk_button.isVisible()
    assert window.group_desktop_account.isHidden()
    assert not window.group_kiosk_app.isHidden()
    assert not window.group_kiosk_security.isHidden()


def test_installer_branding_remains_available_in_simple_mode(window, app, tmp_path):
    banner = tmp_path / "banner.png"
    banner.write_bytes(b"per-project-banner")
    window.banner_field.path = str(banner)
    window.banner_field.source_path = str(banner)
    window._navigate("step4", validate=False)
    window._apply_ui_mode("simple", confirm=False)
    app.processEvents()
    assert not window.group_installer_banner.isHidden()
    assert not window.group_installer_text.isHidden()
    assert window.banner_field.path == str(banner)


def test_named_profile_id_is_preserved_when_applying_project_defaults(window):
    window._apply_profile_defaults(
        "Estación de trabajo de prueba", "office", profile_id="estacion-trabajo"
    )
    config = window.collect_config()
    assert window._active_profile_id == "estacion-trabajo"
    assert config["profile_id"] == "estacion-trabajo"
