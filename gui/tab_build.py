"""Paso 6: compilación, validación, progreso y cancelación."""

import os

from gui.layouts import add_page
from gui.ui_components import SettingRowCard, ToggleSwitch
from PySide6.QtCore import QThread, Signal
from core.cache import cache_info
from core.iso.quick_audit import audit_iso_quick
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

HELP = """
<p><b>Compilación y validación</b></p>
<p>Antes de compilar podés validar toda la configuración. La validación
comprueba los datos de las etapas, las imágenes elegidas, los paquetes
adicionales, las dependencias del host y el espacio disponible.</p>
<p>La compilación se ejecuta en segundo plano con <code>livecd-creator</code>.
La interfaz sigue respondiendo, muestra el progreso y el registro, y permite
cancelar. Al finalizar se guarda la ruta, el tamaño y el SHA-256 de la ISO.</p>
<p>Una ISO <b>generada</b> no está automáticamente <b>validada</b> ni
<b>probada</b>. Esas comprobaciones se realizan en las etapas de laboratorio.</p>
"""


class IsoQuickAuditWorker(QThread):
    """Ejecuta la auditoría ISO fuera del hilo de interfaz."""
    completed = Signal(dict)

    def __init__(self, iso_path, parent=None):
        super().__init__(parent)
        self.iso_path = iso_path

    def run(self):
        self.completed.emit(audit_iso_quick(self.iso_path))


class BuildTabMixin:
    """Paso 6: compilación y validación (mixin de KioskBuilderGUI)."""

    def init_tab_build(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # --- Destino ---
        output_control = QWidget()
        output_row = QHBoxLayout(output_control)
        output_row.setContentsMargins(0, 0, 0, 0)
        output_row.setSpacing(8)
        self.txt_output = QLineEdit(os.path.expanduser("~/ISOs"))
        self.txt_output.setPlaceholderText("Carpeta donde se guardará la ISO")
        self.txt_output.setMinimumWidth(260)
        self.btn_output = QPushButton("Examinar…")
        self.btn_output.clicked.connect(self.select_output_dir)
        output_row.addWidget(self.txt_output, 1)
        output_row.addWidget(self.btn_output)
        self.card_output = SettingRowCard(
            "Destino de la imagen",
            "Carpeta donde se guardará la ISO generada.",
            "📁",
            output_control,
        )
        layout.addWidget(self.card_output)

        # --- Resumen ---
        summary_card = QFrame()
        summary_card.setObjectName("settingRowCard")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(16, 14, 16, 14)
        summary_layout.setSpacing(8)
        summary_title = QLabel("Resumen del proyecto")
        summary_title.setObjectName("settingTitle")
        summary_layout.addWidget(summary_title)
        self.lbl_build_summary = QLabel("Todavía no hay un resumen disponible.")
        self.lbl_build_summary.setObjectName("cardDetail")
        self.lbl_build_summary.setWordWrap(True)
        summary_layout.addWidget(self.lbl_build_summary)
        layout.addWidget(summary_card)

        # --- Validación y acciones ---
        validation_card = QFrame()
        validation_card.setObjectName("settingRowCard")
        validation_layout = QVBoxLayout(validation_card)
        validation_layout.setContentsMargins(16, 14, 16, 14)
        validation_layout.setSpacing(10)
        validation_title = QLabel("Validación y compilación")
        validation_title.setObjectName("settingTitle")
        validation_layout.addWidget(validation_title)
        self.lbl_validation = QLabel("La configuración todavía no fue validada en esta sesión.")
        self.lbl_validation.setObjectName("cardDetail")
        self.lbl_validation.setWordWrap(True)
        validation_layout.addWidget(self.lbl_validation)

        actions = QGridLayout()
        actions.setHorizontalSpacing(10)
        actions.setVerticalSpacing(8)
        self.btn_validate = QPushButton("Validar configuración")
        self.btn_validate.setToolTip(
            "Comprueba las etapas, las dependencias del host y el espacio disponible antes de compilar."
        )
        self.btn_validate.clicked.connect(self.validate_configuration)
        self.btn_preview_kickstart = QPushButton("Ver Kickstart generado")
        self.btn_preview_kickstart.clicked.connect(self.preview_kickstart)
        self.btn_build = QPushButton("Generar imagen ISO")
        self.btn_build.setObjectName("primaryAction")
        self.btn_build.clicked.connect(self.start_build_process)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setToolTip("Aborta livecd-creator y limpia el árbol de trabajo para el próximo intento.")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_build)
        actions.addWidget(self.btn_validate, 0, 0)
        actions.addWidget(self.btn_preview_kickstart, 0, 1)
        actions.addWidget(self.btn_build, 1, 0)
        actions.addWidget(self.btn_cancel, 1, 1)
        actions.setColumnStretch(0, 1)
        actions.setColumnStretch(1, 1)
        validation_layout.addLayout(actions)

        # Toggles de opciones
        self.check_cache_enabled = ToggleSwitch(checked=True)
        self.check_cache_enabled.setToolTip(
            "Reutiliza los paquetes/metadatos guardados por livecd-creator. La caché se conserva entre compilaciones."
        )
        self.check_qemu_bios = ToggleSwitch(checked=False)
        self.check_qemu_uefi = ToggleSwitch(checked=False)

        # Las presentamos como filas compactas dentro de la tarjeta
        for label, desc, control in (
            ("Caché local persistente", "Reutiliza paquetes/metadatos para acelerar compilaciones.", self.check_cache_enabled),
            ("Prueba BIOS Legacy en QEMU", "Ejecuta una prueba de humo BIOS al terminar la compilación.", self.check_qemu_bios),
            ("Prueba UEFI en QEMU", "Ejecuta una prueba de humo UEFI al terminar la compilación.", self.check_qemu_uefi),
        ):
            row = QHBoxLayout()
            row.setSpacing(12)
            text_col = QVBoxLayout()
            text_col.setSpacing(2)
            t = QLabel(label)
            t.setObjectName("settingTitle")
            d = QLabel(desc)
            d.setObjectName("settingDescription")
            d.setWordWrap(True)
            text_col.addWidget(t)
            text_col.addWidget(d)
            row.addLayout(text_col, 1)
            row.addWidget(control, 0)
            validation_layout.addLayout(row)

        cache_row = QHBoxLayout()
        self.btn_cache_info = QPushButton("Estado de la caché")
        self.btn_cache_info.clicked.connect(self.refresh_cache_info)
        cache_row.addWidget(self.btn_cache_info)
        cache_row.addStretch(1)
        validation_layout.addLayout(cache_row)
        self.lbl_cache_info = QLabel("Caché persistente: estado sin consultar.")
        self.lbl_cache_info.setObjectName("inlineHint")
        self.lbl_cache_info.setWordWrap(True)
        validation_layout.addWidget(self.lbl_cache_info)

        iso_audit_row = QHBoxLayout()
        self.btn_quick_iso_audit = QPushButton("Auditoría rápida de ISO")
        self.btn_quick_iso_audit.setToolTip(
            "Inspecciona el catálogo ISO con xorriso, comprueba GRUB y lista squashfs. No arranca la ISO."
        )
        self.btn_quick_iso_audit.clicked.connect(self.quick_audit_last_iso)
        self.btn_choose_iso_audit = QPushButton("Elegir otra ISO…")
        self.btn_choose_iso_audit.clicked.connect(self.choose_iso_for_quick_audit)
        iso_audit_row.addWidget(self.btn_quick_iso_audit)
        iso_audit_row.addWidget(self.btn_choose_iso_audit)
        iso_audit_row.addStretch(1)
        validation_layout.addLayout(iso_audit_row)
        self.lbl_iso_audit = QLabel("Auditoría ISO: todavía no ejecutada.")
        self.lbl_iso_audit.setObjectName("inlineHint")
        self.lbl_iso_audit.setWordWrap(True)
        validation_layout.addWidget(self.lbl_iso_audit)
        self._iso_audit_worker = None
        layout.addWidget(validation_card)

        # --- Progreso ---
        progress_card = QFrame()
        progress_card.setObjectName("settingRowCard")
        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(16, 14, 16, 14)
        progress_layout.setSpacing(10)
        progress_title = QLabel("Estado de compilación")
        progress_title.setObjectName("settingTitle")
        progress_layout.addWidget(progress_title)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        self.txt_logs = QTextEdit()
        self.txt_logs.setObjectName("console")
        self.txt_logs.setReadOnly(True)
        self.txt_logs.setMinimumHeight(180)
        progress_layout.addWidget(QLabel("Registro de livecd-creator:"))
        progress_layout.addWidget(self.txt_logs, 1)
        layout.addWidget(progress_card, 1)

        add_page(
            self, "step6", tab, "Compilación y validación",
            "Revisá el proyecto, validá sus requisitos y generá la imagen ISO.",
            HELP, step=6,
        )

    def quick_audit_last_iso(self):
        """Audita la última ISO generada, sin bloquear la interfaz."""
        path = getattr(self, "_last_iso_path", "") or str(
            self._settings.value("last_iso_path", "") if hasattr(self, "_settings") else ""
        )
        if not path or not os.path.isfile(path):
            QMessageBox.information(self, "Auditoría ISO", "Todavía no hay una ISO generada. Elegí un archivo ISO para auditar.")
            return
        self._start_quick_iso_audit(path)

    def choose_iso_for_quick_audit(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar imagen ISO", os.path.expanduser("~/ISOs"), "Imágenes ISO (*.iso);;Todos los archivos (*)")
        if path:
            self._start_quick_iso_audit(path)

    def _start_quick_iso_audit(self, path):
        if self._iso_audit_worker is not None and self._iso_audit_worker.isRunning():
            return
        self.btn_quick_iso_audit.setEnabled(False)
        self.btn_choose_iso_audit.setEnabled(False)
        self.lbl_iso_audit.setText(f"Auditando {os.path.basename(path)}…")
        self._iso_audit_worker = IsoQuickAuditWorker(path, self)
        self._iso_audit_worker.completed.connect(self._show_quick_iso_audit)
        self._iso_audit_worker.finished.connect(self._quick_iso_audit_finished)
        self._iso_audit_worker.start()

    def _show_quick_iso_audit(self, report):
        status = report.get("status", "UNAVAILABLE")
        details = [f"Resultado: {status}"]
        details.extend(f"✓ {item['name']}" for item in report.get("checks", []) if item.get("status") == "PASS")
        details.extend(f"✗ {item['name']}" for item in report.get("checks", []) if item.get("status") == "FAIL")
        details.extend(f"Aviso: {item}" for item in report.get("warnings", []))
        details.extend(f"Error: {item}" for item in report.get("errors", []))
        details.append("Esta auditoría no sustituye una prueba de arranque en QEMU o hardware real.")
        self.lbl_iso_audit.setText("\n".join(details))
        if hasattr(self, "txt_logs"):
            self.txt_logs.append("\n[AUDITORÍA ISO] " + " | ".join(details))

    def _quick_iso_audit_finished(self):
        self.btn_quick_iso_audit.setEnabled(True)
        self.btn_choose_iso_audit.setEnabled(True)

    def refresh_build_summary(self):
        """Refresca el resumen de la configuración antes de compilar."""
        config = self.collect_config()
        engine = str(config.get("engine") or "kiosk")
        environment = str(config.get("desktop_environment") or "—")
        lines = [
            f"Motor: {engine} · Escritorio: {environment} · Servidor: {str(config.get('display_server') or '—').upper()} · Usuario: {config.get('desktop_user') or '—'}",
            f"ISO: {config.get('iso_name') or '—'} {config.get('version') or '—'} · Producto: {config.get('product_name') or 'Fedora Linux'}",
            f"Arranque: {config.get('boot_mode') or '—'} · Resolución: {config.get('resolution') or 'auto'}",
            f"Paquetes adicionales: {config.get('extra_packages') or '—'} · Grupos: {config.get('extra_groups') or '—'}",
            f"Firewall: {'ON' if config.get('enable_firewall') else 'OFF'} · SSH: {'ON' if config.get('enable_ssh') else 'OFF'} · Instalador: {'ON' if config.get('enable_installer') else 'OFF'}",
        ]
        if engine == "kiosk":
            lines.insert(3, f"App: {config.get('app_mode') or '—'} · URL: {config.get('app_url') or '—'}")
        self.lbl_build_summary.setText("\n".join(lines))

    def select_output_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "Seleccionar carpeta de salida", self.txt_output.text()
        )
        if path:
            self.txt_output.setText(path)

    def build_finished(self, success):
        self.btn_build.setEnabled(True)
        self.btn_build.setText("Generar imagen ISO")
        self.btn_validate.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setText("Cancelar")
        cancelled = (
            self.worker is not None
            and not success
            and self.worker.cancel_event.is_set()
        )
        if success:
            self.txt_logs.append("\n[PROCESO COMPLETADO] La ISO se generó con éxito.")
        elif cancelled:
            self.txt_logs.append("\n[CANCELADO] Compilación abortada por el usuario.")
        else:
            self.txt_logs.append("\n[ERROR] Falló la creación de la ISO. Revisá los registros.")
        if hasattr(self, "_record_build_finished"):
            self._record_build_finished(success, cancelled)

    def cancel_build(self):
        if self.worker is None or not self.worker.isRunning():
            return
        reply = QMessageBox.question(
            self,
            "Cancelar compilación",
            "¿Abortar la compilación en curso?\n\n"
            "Se terminará livecd-creator y se limpiará el árbol de trabajo "
            "para el próximo intento.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setText("CANCELANDO…")
        self.worker.cancel_event.set()

    def refresh_cache_info(self):
        """Muestra tamaño y ubicación de la caché persistente."""
        try:
            info = cache_info()
            size_mib = info.get("size_bytes", 0) / (1024 * 1024)
            self.lbl_cache_info.setText(
                f"Caché: {info['path']} · "
                + (f"{size_mib:.1f} MiB ocupados" if info.get("exists") else "todavía no creada")
                + (f" · {info['error']}" if info.get("error") else "")
            )
        except Exception as exc:
            self.lbl_cache_info.setText(f"No se pudo consultar la caché: {exc}")