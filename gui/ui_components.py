"""Componentes reutilizables del Design System Fluent/WinUI 3.

Incluye tarjetas de configuración, métricas, toggle switch, barra lateral de
navegación y pie de acciones. Los componentes dependen de los objectName y
propiedades QSS definidos en ``gui.theme_manager``.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    Signal,
    Property,
)
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def elide_text(text: str, max_chars: int = 72) -> str:
    text = str(text or "")
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return "…"
    return text[: max_chars - 1].rstrip() + "…"


def _make_icon_label(icon: str | QWidget | None, object_name: str, size: int = 20) -> QWidget:
    if isinstance(icon, QWidget):
        icon.setObjectName(object_name)
        return icon
    label = QLabel()
    label.setObjectName(object_name)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setFixedSize(size, size)
    text = str(icon or "").strip()
    if text:
        try:
            from gui.icons import resolve_icon

            qicon = resolve_icon(text, size=size)
            if not qicon.isNull():
                label.setPixmap(qicon.pixmap(size, size))
                label.setProperty("iconKey", text)
                return label
        except Exception:
            pass
        label.setText(text)
    return label


# ---------------------------------------------------------------------------
# Toggle Switch WinUI 3
# ---------------------------------------------------------------------------


class ToggleSwitch(QToolButton):
    """Interruptor estilo Windows 11.

    Usa pintura personalizada para representar fielmente el estado on/off.
    Expone la API de QAbstractButton (``isChecked``, ``toggled``).
    """

    def __init__(self, checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._knob_pos = 1.0 if checked else 0.0

        self._anim = QPropertyAnimation(self, b"knobPos", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._on_toggled)

    def sizeHint(self) -> QSize:
        return QSize(40, 20)

    def minimumSizeHint(self) -> QSize:
        return QSize(40, 20)

    def getKnobPos(self) -> float:
        return self._knob_pos

    def setKnobPos(self, pos: float) -> None:
        self._knob_pos = max(0.0, min(1.0, float(pos)))
        self.update()

    knobPos = Property(float, getKnobPos, setKnobPos)

    def _on_toggled(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._knob_pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = rect.height() / 2
        checked = self.isChecked()
        enabled = self.isEnabled()
        has_focus = self.hasFocus()

        # Colores tomados del tema activo; fallback seguro.
        app = QApplication.instance()
        is_dark = False
        if app is not None:
            bg = app.palette().window().color().lightness()
            is_dark = bg < 128

        if checked:
            track_bg = QColor("#4CC2FF" if is_dark else "#0067C0")
            track_border = track_bg
            knob_color = QColor("#000000" if is_dark else "#FFFFFF")
        else:
            track_bg = QColor("#1C1C1C" if is_dark else "#FFFFFF")
            track_border = QColor("#CCCCCC" if is_dark else "#5D5D5D")
            knob_color = QColor("#CCCCCC" if is_dark else "#5D5D5D")

        if not enabled:
            track_bg = QColor("#2B2B2B" if is_dark else "#F3F3F3")
            track_border = QColor("#787878" if is_dark else "#9A9A9A")
            knob_color = track_border

        p.setPen(QPen(track_border, 1))
        p.setBrush(track_bg)
        p.drawRoundedRect(rect, radius, radius)

        # Knob
        margin = 3
        knob_d = rect.height() - margin * 2
        x_off = margin + self._knob_pos * (rect.width() - margin * 2 - knob_d)
        knob_rect = QRect(
            int(rect.x() + x_off),
            int(rect.y() + margin),
            int(knob_d),
            int(knob_d),
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(knob_color)
        p.drawEllipse(knob_rect)

        if has_focus:
            focus_pen = QPen(QColor("#4CC2FF" if is_dark else "#0067C0"), 2)
            focus_pen.setStyle(Qt.PenStyle.DotLine)
            p.setPen(focus_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), radius + 1, radius + 1)

        p.end()

    def hitButton(self, pos: QPoint) -> bool:  # noqa: N802
        return self.rect().contains(pos)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return):
            self.toggle()
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# SettingRowCard
# ---------------------------------------------------------------------------


class SettingRowCard(QFrame):
    """Fila de configuración estilo Windows 11.

    Estructura: [icono] [título + descripción] [control].
    """

    clicked = Signal()

    def __init__(
        self,
        title: str,
        description: str = "",
        icon: str | QWidget | None = None,
        control: QWidget | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("settingRowCard")
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(16, 12, 16, 12)
        self._layout.setSpacing(14)

        self.icon_widget = _make_icon_label(icon, "settingIcon", 20)
        self._layout.addWidget(self.icon_widget, 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("settingTitle")
        self.title_label.setWordWrap(True)
        text_col.addWidget(self.title_label)

        self.description_label = QLabel(description)
        self.description_label.setObjectName("settingDescription")
        self.description_label.setWordWrap(True)
        self.description_label.setVisible(bool(description))
        text_col.addWidget(self.description_label)

        self._layout.addLayout(text_col, 1)

        self._control: QWidget | None = None
        self.control_container = QHBoxLayout()
        self.control_container.setContentsMargins(0, 0, 0, 0)
        self.control_container.setSpacing(8)
        self.control_container.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._layout.addLayout(self.control_container)
        if control is not None:
            self.set_control(control)

    def set_control(self, control: QWidget) -> None:
        if self._control is not None:
            self.control_container.removeWidget(self._control)
            self._control.setParent(None)
        self._control = control
        self._apply_control_defaults(control)
        self.control_container.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def control(self) -> QWidget | None:
        return self._control

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)

    def set_description(self, text: str) -> None:
        self.description_label.setText(text)
        self.description_label.setVisible(bool(text))

    @staticmethod
    def _apply_control_defaults(control: QWidget) -> None:
        # Anchos consistentes para controles de formulario, sin tocar toggles/botones.
        if isinstance(control, (QComboBox,)) or control.metaObject().className() in {"QLineEdit", "QSpinBox", "QDoubleSpinBox"}:
            control.setMinimumWidth(260)
            control.setMaximumWidth(320)
            control.setMinimumHeight(34)
        if isinstance(control, ToggleSwitch):
            return

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


# ---------------------------------------------------------------------------
# SettingExpanderCard
# ---------------------------------------------------------------------------


class SettingExpanderCard(QFrame):
    """Tarjeta de configuración expandible."""

    expanded_changed = Signal(bool)

    def __init__(
        self,
        title: str,
        description: str = "",
        icon: str | QWidget | None = None,
        control: QWidget | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("settingExpanderCard")
        self.setProperty("expanded", False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        self._expanded = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        self.header = QFrame()
        self.header.setObjectName("expanderHeader")
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setMinimumHeight(64)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.setSpacing(14)

        self.icon_widget = _make_icon_label(icon, "settingIcon", 20)
        header_layout.addWidget(self.icon_widget, 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("settingTitle")
        self.title_label.setWordWrap(True)
        text_col.addWidget(self.title_label)
        self.description_label = QLabel(description)
        self.description_label.setObjectName("settingDescription")
        self.description_label.setWordWrap(True)
        self.description_label.setVisible(bool(description))
        text_col.addWidget(self.description_label)
        header_layout.addLayout(text_col, 1)

        self._control: QWidget | None = None
        self.control_container = QHBoxLayout()
        self.control_container.setContentsMargins(0, 0, 0, 0)
        self.control_container.setSpacing(8)
        header_layout.addLayout(self.control_container)
        if control is not None:
            self.set_control(control)

        self.chevron = QLabel("⌄")
        self.chevron.setObjectName("expanderChevron")
        self.chevron.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chevron.setFixedSize(24, 24)
        header_layout.addWidget(self.chevron, 0, Qt.AlignmentFlag.AlignVCenter)

        root.addWidget(self.header)

        # Body
        self.body = QFrame()
        self.body.setObjectName("expanderBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(16, 12, 16, 16)
        self.body_layout.setSpacing(10)
        self.body.setVisible(False)
        root.addWidget(self.body)

        self.header.mouseReleaseEvent = self._header_clicked  # type: ignore[assignment]

    def set_control(self, control: QWidget) -> None:
        if self._control is not None:
            self.control_container.removeWidget(self._control)
            self._control.setParent(None)
        self._control = control
        self.control_container.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def add_widget(self, widget: QWidget) -> QWidget:
        self.body_layout.addWidget(widget)
        return widget

    def add_layout(self, layout) -> None:
        self.body_layout.addLayout(layout)

    def _header_clicked(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self.body.setVisible(self._expanded)
        self.chevron.setText("⌃" if self._expanded else "⌄")
        self.setProperty("expanded", self._expanded)
        self.style().unpolish(self)
        self.style().polish(self)
        self.expanded_changed.emit(self._expanded)

    def is_expanded(self) -> bool:
        return self._expanded


# ---------------------------------------------------------------------------
# StatusMetricCard
# ---------------------------------------------------------------------------


class StatusMetricCard(QFrame):
    """Tarjeta de métrica/estado para paneles."""

    def __init__(
        self,
        title: str,
        value: str = "—",
        detail: str = "",
        badge: str = "",
        badge_state: str = "info",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("statusMetricCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("metricTitle")
        self.title_label.setWordWrap(True)
        top.addWidget(self.title_label, 1)

        self.badge_label = QLabel(badge)
        self.badge_label.setObjectName("statusPill")
        self.badge_label.setProperty("state", badge_state)
        self.badge_label.setVisible(bool(badge))
        top.addWidget(self.badge_label, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        self.value_label.setWordWrap(True)
        layout.addWidget(self.value_label)

        detail_row = QHBoxLayout()
        detail_row.setSpacing(8)
        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("metricDetail")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail_row.addWidget(self.detail_label, 1)

        self.copy_button = QPushButton("Copiar")
        self.copy_button.setObjectName("subtleButton")
        self.copy_button.setFixedHeight(28)
        self.copy_button.setVisible(False)
        self.copy_button.clicked.connect(self._copy_detail)
        detail_row.addWidget(self.copy_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(detail_row)
        layout.addStretch(1)

        self._raw_detail = detail

    def set_content(
        self,
        value: str | None = None,
        detail: str | None = None,
        badge: str | None = None,
        state: str | None = None,
        copyable: bool | None = None,
    ) -> None:
        if value is not None:
            self.value_label.setText(str(value))
        if detail is not None:
            self._raw_detail = str(detail)
            self.detail_label.setText(elide_text(self._raw_detail, 96))
            self.detail_label.setToolTip(self._raw_detail)
        if badge is not None:
            self.badge_label.setText(str(badge))
            self.badge_label.setVisible(bool(badge))
        if state is not None:
            self.badge_label.setProperty("state", state)
            self.badge_label.style().unpolish(self.badge_label)
            self.badge_label.style().polish(self.badge_label)
        if copyable is not None:
            self.copy_button.setVisible(bool(copyable) and bool(self._raw_detail))
        elif detail is not None:
            # auto: mostrar copiar si parece ruta o valor largo
            self.copy_button.setVisible(len(self._raw_detail) > 32 or "/" in self._raw_detail)

    def _copy_detail(self) -> None:
        QApplication.clipboard().setText(self._raw_detail)
        old = self.copy_button.text()
        self.copy_button.setText("Copiado")
        from PySide6.QtCore import QTimer

        QTimer.singleShot(1200, lambda: self.copy_button.setText(old))


# ---------------------------------------------------------------------------
# NavigationSidebar
# ---------------------------------------------------------------------------


class _NavButton(QPushButton):
    def __init__(self, key: str, label: str, icon: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.key = key
        self.setObjectName("navButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._icon_text = icon
        self.setText(f"{label}")
        if icon:
            # Icono como texto lineal; se dibuja por paint overlay para control fino.
            self.setProperty("iconText", icon)

    def icon_text(self) -> str:
        return self._icon_text


class NavigationSidebar(QFrame):
    """Barra lateral WinUI 3 con píldora de acento activa."""

    navigation_requested = Signal(str)
    new_project_requested = Signal()
    mode_changed = Signal(str)
    theme_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(260)

        self._buttons: dict[str, _NavButton] = {}
        self._active_key: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 16, 12, 12)
        root.setSpacing(4)

        # Header
        self.app_title = QLabel("Creador Personalizado")
        self.app_title.setObjectName("sidebarAppTitle")
        root.addWidget(self.app_title)

        self.app_subtitle = QLabel("Constructor de distribuciones Fedora")
        self.app_subtitle.setObjectName("sidebarSubtitle")
        root.addWidget(self.app_subtitle)

        root.addSpacing(8)
        self.new_project_btn = QPushButton("+  Nuevo proyecto")
        self.new_project_btn.setObjectName("sidebarNewProjectButton")
        self.new_project_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_project_btn.clicked.connect(self.new_project_requested.emit)
        root.addWidget(self.new_project_btn)

        root.addSpacing(8)

        # Nav container (para posicionar píldora)
        self.nav_container = QWidget()
        self.nav_container.setObjectName("navContainer")
        self.nav_layout = QVBoxLayout(self.nav_container)
        self.nav_layout.setContentsMargins(0, 0, 0, 0)
        self.nav_layout.setSpacing(2)
        root.addWidget(self.nav_container, 1)

        self.active_pill = QFrame(self.nav_container)
        self.active_pill.setObjectName("navActivePill")
        self.active_pill.setFixedSize(3, 16)
        self.active_pill.hide()
        self.active_pill.raise_()

        # Footer
        footer_div = QFrame()
        footer_div.setObjectName("sidebarDivider")
        footer_div.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(footer_div)

        footer = QFrame()
        footer.setObjectName("sidebarFooterCompact")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(4, 4, 4, 4)
        footer_layout.setSpacing(8)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Modo"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Básico", "basic")
        self.mode_combo.addItem("Avanzado", "advanced")
        self.mode_combo.currentIndexChanged.connect(
            lambda: self.mode_changed.emit(str(self.mode_combo.currentData()))
        )
        mode_row.addWidget(self.mode_combo, 1)
        footer_layout.addLayout(mode_row)

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Tema"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Claro", "light")
        self.theme_combo.addItem("Oscuro", "dark")
        self.theme_combo.currentIndexChanged.connect(
            lambda: self.theme_changed.emit(str(self.theme_combo.currentData()))
        )
        theme_row.addWidget(self.theme_combo, 1)
        footer_layout.addLayout(theme_row)

        root.addWidget(footer)

        bottom_div = QFrame()
        bottom_div.setObjectName("sidebarDivider")
        bottom_div.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(bottom_div)

        self.env_label = QLabel("Fedora 44 · Python + PySide6")
        self.env_label.setObjectName("sidebarEnvLabel")
        self.env_label.setWordWrap(True)
        root.addWidget(self.env_label)

    def add_section(self, title: str) -> QLabel:
        label = QLabel(title.upper())
        label.setObjectName("sidebarSectionLabel")
        self.nav_layout.addWidget(label)
        return label

    def add_nav_item(self, key: str, label: str, icon: str = "") -> QPushButton:
        btn = _NavButton(key, label, icon, self.nav_container)
        btn.clicked.connect(lambda: self._on_nav_clicked(key))
        self.nav_layout.addWidget(btn)
        self._buttons[key] = btn
        return btn

    def add_stretch(self) -> None:
        self.nav_layout.addStretch(1)

    def add_divider(self) -> QFrame:
        div = QFrame()
        div.setObjectName("sidebarDivider")
        div.setFrameShape(QFrame.Shape.HLine)
        self.nav_layout.addWidget(div)
        return div

    def set_active(self, key: str) -> None:
        if key not in self._buttons:
            return
        self._active_key = key
        for k, btn in self._buttons.items():
            btn.setChecked(k == key)
        self._reposition_pill()

    def _on_nav_clicked(self, key: str) -> None:
        self.set_active(key)
        self.navigation_requested.emit(key)

    def _reposition_pill(self) -> None:
        if not self._active_key or self._active_key not in self._buttons:
            self.active_pill.hide()
            return
        btn = self._buttons[self._active_key]
        # Posición relativa al nav_container
        btn_pos = btn.mapTo(self.nav_container, QPoint(0, 0))
        y = btn_pos.y() + (btn.height() - 16) // 2
        self.active_pill.move(4, max(0, y))
        self.active_pill.show()
        self.active_pill.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._reposition_pill()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._reposition_pill()

    def set_mode(self, mode: str) -> None:
        idx = self.mode_combo.findData(mode)
        if idx >= 0:
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(idx)
            self.mode_combo.blockSignals(False)

    def set_theme(self, theme: str) -> None:
        idx = self.theme_combo.findData(theme)
        if idx >= 0:
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(idx)
            self.theme_combo.blockSignals(False)

    def button(self, key: str) -> QPushButton | None:
        return self._buttons.get(key)


# ---------------------------------------------------------------------------
# ActionFooter
# ---------------------------------------------------------------------------


class ActionFooter(QFrame):
    """Barra de acciones inferior con progreso y botones."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("actionFooter")
        self.setFixedHeight(64)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(12)

        self.progress_label = QLabel("")
        self.progress_label.setObjectName("footerProgress")
        layout.addWidget(self.progress_label)
        layout.addStretch(1)

        self.buttons_layout = QHBoxLayout()
        self.buttons_layout.setSpacing(8)
        layout.addLayout(self.buttons_layout)

    def set_progress(self, current: int, total: int, label: str = "Paso") -> None:
        self.progress_label.setText(f"{label} {current} de {total}")

    def add_button(self, text: str, *, primary: bool = False, object_name: str | None = None) -> QPushButton:
        btn = QPushButton(text)
        if object_name:
            btn.setObjectName(object_name)
        elif primary:
            btn.setObjectName("primaryButton")
        self.buttons_layout.addWidget(btn)
        return btn
