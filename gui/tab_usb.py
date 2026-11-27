"""Solapa 6: escritura de la ISO a un USB con dd."""

import os

from gui.components import prepare_combo
from gui.layouts import add_page
from gui.ui_components import SettingRowCard, ToggleSwitch
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
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
from core.usb import USBWriterWorker, list_usb_disks, size_gib

HELP = """
<p><b>Escritura en USB</b></p>
<p>La escritura reemplaza todo el contenido del dispositivo seleccionado. La
aplicacion revalida identidad, tamano, modelo y numero de serie antes de
escribir, y compara la lectura posterior con la ISO original.</p>
<p>Marca la casilla de confirmacion y revisa dos veces el dispositivo elegido.
Esta operacion no forma parte del asistente de configuracion y requiere
autorizacion administrativa.</p>
"""


class UsbTabMixin:
    """Solapa 6: escritura de la ISO a un USB con dd (mixin de KioskBuilderGUI)."""

    def init_tab_usb(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        intro = QLabel(
            "Prepará un medio de arranque a partir de una ISO. Revisá cuidadosamente "
            "el dispositivo de destino: la escritura reemplaza todos sus datos."
        )
        intro.setObjectName("inlineHint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # --- ISO ---
        iso_card = QFrame()
        iso_card.setObjectName("settingRowCard")
        iso_layout = QVBoxLayout(iso_card)
        iso_layout.setContentsMargins(16, 14, 16, 14)
        iso_layout.setSpacing(10)
        iso_title = QLabel("Imagen ISO")
        iso_title.setObjectName("settingTitle")
        iso_layout.addWidget(iso_title)

        iso_row = QHBoxLayout()
        iso_row.setSpacing(8)
        self.txt_usb_iso = QLineEdit()
        self.txt_usb_iso.setPlaceholderText(
            "Selecciona el archivo .iso que quieres escribir en el USB"
        )
        self.txt_usb_iso.textChanged.connect(self.update_usb_controls)
        self.btn_usb_iso = QPushButton("Examinar...")
        self.btn_usb_iso.clicked.connect(self.select_usb_iso)
        iso_row.addWidget(self.txt_usb_iso, 1)
        iso_row.addWidget(self.btn_usb_iso)
        iso_layout.addLayout(iso_row)
        self.lbl_usb_iso = QLabel("Sin ISO seleccionada")
        self.lbl_usb_iso.setObjectName("settingDescription")
        self.lbl_usb_iso.setWordWrap(True)
        iso_layout.addWidget(self.lbl_usb_iso)
        layout.addWidget(iso_card)

        # --- Dispositivo ---
        dev_card = QFrame()
        dev_card.setObjectName("settingRowCard")
        dev_layout = QVBoxLayout(dev_card)
        dev_layout.setContentsMargins(16, 14, 16, 14)
        dev_layout.setSpacing(10)
        dev_title = QLabel("Dispositivo USB de destino")
        dev_title.setObjectName("settingTitle")
        dev_layout.addWidget(dev_title)

        dev_row = QHBoxLayout()
        dev_row.setSpacing(8)
        self.combo_usb = QComboBox()
        prepare_combo(self.combo_usb, 20)
        self.combo_usb.currentIndexChanged.connect(self.on_usb_device_changed)
        self.btn_usb_refresh = QPushButton("Actualizar")
        self.btn_usb_refresh.clicked.connect(self.refresh_usb_devices)
        dev_row.addWidget(self.combo_usb, 1)
        dev_row.addWidget(self.btn_usb_refresh)
        dev_layout.addLayout(dev_row)
        self.lbl_usb_info = QLabel("No se detectaron dispositivos USB.")
        self.lbl_usb_info.setObjectName("settingDescription")
        self.lbl_usb_info.setWordWrap(True)
        dev_layout.addWidget(self.lbl_usb_info)
        warning = QLabel("⚠ Se borrará todo el contenido del dispositivo seleccionado.")
        warning.setObjectName("warningText")
        warning.setWordWrap(True)
        dev_layout.addWidget(warning)
        layout.addWidget(dev_card)

        # --- Confirmación y acción ---
        self.check_usb_confirm = ToggleSwitch(checked=False)
        self.check_usb_confirm.toggled.connect(self.update_usb_controls)
        self.card_usb_confirm = SettingRowCard(
            "Confirmar borrado del dispositivo",
            "Entiendo que se borrarán todos los datos del dispositivo seleccionado.",
            "⚠",
            self.check_usb_confirm,
        )
        layout.addWidget(self.card_usb_confirm)

        self.btn_usb_write = QPushButton("Crear unidad USB")
        self.btn_usb_write.setObjectName("dangerAction")
        self.btn_usb_write.setEnabled(False)
        self.btn_usb_write.clicked.connect(self.start_usb_write)
        layout.addWidget(self.btn_usb_write)

        # --- Progreso y log ---
        progress_card = QFrame()
        progress_card.setObjectName("settingRowCard")
        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(16, 14, 16, 14)
        progress_layout.setSpacing(10)
        progress_title = QLabel("Progreso de escritura")
        progress_title.setObjectName("settingTitle")
        progress_layout.addWidget(progress_title)
        self.usb_progress = QProgressBar()
        self.usb_progress.setValue(0)
        progress_layout.addWidget(self.usb_progress)
        progress_layout.addWidget(QLabel("Registro de escritura y verificación:"))
        self.txt_usb_log = QTextEdit()
        self.txt_usb_log.setObjectName("console")
        self.txt_usb_log.setReadOnly(True)
        self.txt_usb_log.setMinimumHeight(170)
        progress_layout.addWidget(self.txt_usb_log)
        layout.addWidget(progress_card, 1)

        self.usb_page = add_page(
            self,
            "usb",
            tab,
            "Unidad USB",
            "Escritura verificada de una ISO en un dispositivo extraible.",
            HELP,
            step=None,
        )
        self.refresh_usb_devices()

    def select_usb_iso(self):
        start_dir = self.txt_output.text().strip()
        if not os.path.isdir(start_dir):
            start_dir = os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar imagen ISO",
            start_dir,
            "Imagenes ISO (*.iso);;Todos los archivos (*)",
        )
        if path:
            self.txt_usb_iso.setText(path)

    def refresh_usb_devices(self):
        current = self.combo_usb.currentData()
        current_path = current.get("path") if isinstance(current, dict) else None

        self.combo_usb.blockSignals(True)
        self.combo_usb.clear()
        try:
            disks = list_usb_disks()
            error = ""
        except Exception as exc:  # noqa: BLE001 - se muestra en la GUI
            disks = []
            error = str(exc)

        for disk in disks:
            label = f"{disk['path']}  ·  {size_gib(disk['size']):.1f} GiB"
            if disk["model"]:
                label += f"  ·  {disk['model']}"
            if disk["serial"]:
                label += f"  ·  S/N {disk['serial']}"
            self.combo_usb.addItem(label, disk)

        if error:
            self.combo_usb.addItem(f"No se pudieron listar los USB: {error}", None)
        elif not disks:
            self.combo_usb.addItem("No hay dispositivos USB conectados", None)

        if current_path:
            found = False
            for index in range(self.combo_usb.count()):
                item = self.combo_usb.itemData(index)
                if isinstance(item, dict) and item.get("path") == current_path:
                    self.combo_usb.setCurrentIndex(index)
                    found = True
                    break
            if not found:
                self.combo_usb.insertItem(0, "Selecciona un dispositivo USB", None)
                self.combo_usb.setCurrentIndex(0)

        self.combo_usb.blockSignals(False)
        self.update_usb_controls()

    def on_usb_device_changed(self, *args):
        # Cambiar de dispositivo exige volver a confirmar el borrado.
        self.check_usb_confirm.setChecked(False)
        self.update_usb_controls()

    def update_usb_controls(self, *args):
        iso = self.txt_usb_iso.text().strip()
        iso_ok = bool(iso) and os.path.isfile(iso)
        iso_size = os.path.getsize(iso) if iso_ok else 0

        if not iso:
            self.lbl_usb_iso.setText("Sin ISO seleccionada")
        elif not iso_ok:
            self.lbl_usb_iso.setText(f"⚠ No existe el archivo: {iso}")
        else:
            self.lbl_usb_iso.setText(f"{iso}  ({size_gib(iso_size):.2f} GiB)")

        disk = self.combo_usb.currentData()
        if isinstance(disk, dict):
            mounts = list(disk["mountpoints"])
            model = f"  ·  {disk['model']}" if disk["model"] else ""
            extra = f"  ·  Montado en {', '.join(mounts)}" if mounts else ""
            self.lbl_usb_info.setText(
                f"Destino: {disk['path']} ({size_gib(disk['size']):.1f} GiB){model}{extra}"
            )
        else:
            self.lbl_usb_info.setText("No hay un dispositivo USB seleccionado.")

        too_big = bool(iso_ok and isinstance(disk, dict) and iso_size > disk["size"])
        if too_big:
            self.lbl_usb_info.setText(
                self.lbl_usb_info.text() + "  — ⚠ La ISO es mas grande que el dispositivo."
            )

        busy = self.usb_worker is not None and self.usb_worker.isRunning()
        self.btn_usb_write.setEnabled(
            iso_ok
            and isinstance(disk, dict)
            and self.check_usb_confirm.isChecked()
            and not too_big
            and not busy
        )

    def start_usb_write(self):
        if self.usb_worker is not None and self.usb_worker.isRunning():
            return

        iso = self.txt_usb_iso.text().strip()
        disk = self.combo_usb.currentData()

        if not iso or not os.path.isfile(iso):
            QMessageBox.warning(self, "Falta la ISO", "Selecciona un archivo .iso valido.")
            return
        if not isinstance(disk, dict):
            QMessageBox.warning(self, "Falta el dispositivo", "Selecciona un dispositivo USB.")
            return
        if not self.check_usb_confirm.isChecked():
            QMessageBox.warning(
                self,
                "Confirmacion",
                "Marca la casilla de confirmacion antes de escribir.",
            )
            return

        reply = QMessageBox.warning(
            self,
            "Confirmar escritura",
            "Se escribira:\n{}\n\nen:\n{} ({} GiB)\n\n"
            "TODO el contenido del dispositivo sera reemplazado.\n\n"
            "¿Continuar?".format(iso, disk["path"], f"{size_gib(disk['size']):.1f}"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.usb_progress.setValue(0)
        self.txt_usb_log.clear()
        self.btn_usb_write.setEnabled(False)
        self.btn_usb_write.setText("Escribiendo ISO...")
        self.btn_usb_refresh.setEnabled(False)
        self.btn_usb_iso.setEnabled(False)
        self.combo_usb.setEnabled(False)
        self.check_usb_confirm.setEnabled(False)

        self.usb_worker = USBWriterWorker(iso, disk["path"], device_snapshot=disk)
        self.usb_worker.log_signal.connect(self.txt_usb_log.append)
        self.usb_worker.progress_signal.connect(self.usb_progress.setValue)
        self.usb_worker.finished_signal.connect(self.usb_finished)
        self.usb_worker.finished.connect(self.update_usb_controls)
        self.usb_worker.start()

    def usb_finished(self, ok, message):
        self.btn_usb_write.setText("Crear unidad USB")
        self.btn_usb_refresh.setEnabled(True)
        self.btn_usb_iso.setEnabled(True)
        self.combo_usb.setEnabled(True)
        self.check_usb_confirm.setEnabled(True)
        self.check_usb_confirm.setChecked(False)

        if ok:
            self.usb_progress.setValue(100)
            self.txt_usb_log.append(f"\n✅ {message}")
            QMessageBox.information(self, "USB creado", message)
        else:
            self.txt_usb_log.append(f"\n❌ {message}")
            QMessageBox.critical(self, "Error al crear el USB", message)

        self.refresh_usb_devices()
