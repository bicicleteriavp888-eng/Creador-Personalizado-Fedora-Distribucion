"""Paso 2: apariencia (splash de Plymouth y resolución)."""

from core.builder import MAX_PLYMOUTH_BYTES
from gui.components import configure_image_preview
from gui.images import ImageField
from gui.layouts import add_page
from gui.ui_components import SettingRowCard
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

HELP = """
<p><b>Apariencia y personalización</b></p>
<p>La imagen seleccionada se muestra en el menú inicial de arranque (BIOS/Legacy
y UEFI) y durante la carga del sistema mediante Plymouth. Si no elegís una
imagen se conserva el tema del sistema. Se convierte a PNG y se limita a 4 MiB.</p>
<p>La resolución se aplica con <code>wlr-randr</code> dentro de la sesión Cage o
Sway. Si el monitor no soporta el modo elegido, se usa el preferido por el hardware.</p>
"""


class AestheticTabMixin:
    """Paso 2: estética (splash y resolución) (mixin de KioskBuilderGUI)."""

    def init_tab_aesthetic(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # --- Imagen de inicio (tarjeta visual) ---
        splash_card = QFrame()
        splash_card.setObjectName("settingRowCard")
        splash_layout = QVBoxLayout(splash_card)
        splash_layout.setContentsMargins(16, 14, 16, 14)
        splash_layout.setSpacing(10)

        splash_header = QLabel("Imagen de inicio · Plymouth")
        splash_header.setObjectName("settingTitle")
        splash_layout.addWidget(splash_header)
        splash_desc = QLabel(
            "Se muestra en el arranque y durante la carga del sistema. Si no elegís una imagen, se usa el tema predeterminado."
        )
        splash_desc.setObjectName("settingDescription")
        splash_desc.setWordWrap(True)
        splash_layout.addWidget(splash_desc)

        self.plymouth_preview = QLabel("Sin imagen · tema del sistema")
        self.plymouth_preview.setObjectName("imagePreview")
        configure_image_preview(self.plymouth_preview)
        splash_layout.addWidget(self.plymouth_preview, 0)

        self.btn_plymouth = QPushButton("Seleccionar imagen…")
        self.btn_plymouth.setToolTip(
            "Selecciona la imagen que se mostrará en el menú de arranque y durante Plymouth."
        )
        self.lbl_plymouth = QLabel("Por defecto · tema del sistema")
        self.lbl_plymouth.setWordWrap(True)
        self.lbl_plymouth.setObjectName("inlineHint")
        self.btn_plymouth_clear = QPushButton("Quitar imagen")
        self.plymouth_field = ImageField(
            self, self.plymouth_preview, self.lbl_plymouth,
            "Seleccionar imagen de boot splash", "plymouth-splash.png",
            MAX_PLYMOUTH_BYTES, "4 MiB", "Sin imagen · tema del sistema",
            "Por defecto · tema del sistema",
        )
        self.btn_plymouth.clicked.connect(self.plymouth_field.select)
        self.btn_plymouth_clear.clicked.connect(self.plymouth_field.clear)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.btn_plymouth)
        actions.addWidget(self.btn_plymouth_clear)
        actions.addStretch(1)
        splash_layout.addLayout(actions)
        splash_layout.addWidget(self.lbl_plymouth)
        hint = QLabel(
            "PNG, JPG, WebP o BMP. Se convierte y optimiza a PNG (máximo 4 MiB). "
            "Para el menú BIOS/Legacy se recomienda una imagen de 640 × 480."
        )
        hint.setObjectName("settingDescription")
        hint.setWordWrap(True)
        splash_layout.addWidget(hint)
        layout.addWidget(splash_card)

        # --- Resolución ---
        self.combo_res = QComboBox()
        self.combo_res.addItem("Autodetectar (recomendado)", "auto")
        for resolution in ("1360x768", "1920x1080", "1280x720"):
            self.combo_res.addItem(resolution, resolution)
        self.card_resolution = SettingRowCard(
            "Resolución de pantalla",
            "Se aplica con wlr-randr en Cage/Sway. Si el modo no está disponible, se usa la resolución preferida por el monitor.",
            "🖥",
            self.combo_res,
        )
        layout.addWidget(self.card_resolution)

        self.group_kiosk_display = self.card_resolution
        layout.addStretch(1)

        self._register_advanced(self.card_resolution)
        add_page(
            self, "step2", tab, "Apariencia y personalización",
            "Personalizá la pantalla de inicio y el comportamiento de pantalla.",
            HELP, step=2,
        )