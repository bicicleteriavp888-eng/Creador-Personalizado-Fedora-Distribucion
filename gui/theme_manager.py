"""Gestor de temas centralizado para Creador Personalizado.

Genera hojas de estilo QSS dinámicas para los modos Claro/Oscuro siguiendo
el lenguaje visual Fluent Design / WinUI 3 (Windows 11 Settings).

Uso básico::

    from gui.theme_manager import ThemeManager

    manager = ThemeManager(app)
    manager.set_theme("light")   # o "dark"
    manager.toggle_theme()

El gestor expone la paleta activa mediante ``manager.tokens`` y notifica
cambios con la señal ``theme_changed(str)``.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


# ---------------------------------------------------------------------------
# Tokens de diseño
# ---------------------------------------------------------------------------

LIGHT_TOKENS = {
    # Fondos / superficies
    "WINDOW_BG": "#F3F3F3",       # Mica / navegación
    "CONTENT_BG": "#F9F9F9",      # Área de contenido
    "SURFACE": "#FFFFFF",         # Tarjetas y filas
    "SURFACE_HOVER": "#F5F5F5",   # Hover de tarjetas/botones
    "SURFACE_PRESSED": "#EDEDED",
    "SURFACE_ALT": "#F7F7F7",
    # Bordes
    "BORDER": "#E5E5E5",
    "BORDER_CARD_BOTTOM": "#D8D8D8",
    "BORDER_STRONG": "#D0D0D0",
    # Texto
    "TEXT": "#1A1A1A",
    "TEXT_SECONDARY": "#5D5D5D",
    "TEXT_DISABLED": "#9A9A9A",
    # Acento
    "ACCENT": "#0067C0",
    "ACCENT_HOVER": "#005A9E",
    "ACCENT_PRESSED": "#004C87",
    "ACCENT_TEXT": "#FFFFFF",
    "ACCENT_SOFT": "#E6F2FB",
    # Navegación
    "NAV_ACTIVE_BG": "#EAEAEA",
    "NAV_HOVER_BG": "#EBEBEB",
    # Estados
    "SUCCESS": "#0F7B0F",
    "SUCCESS_BG": "#DFF6DD",
    "WARNING": "#9D5D00",
    "WARNING_BG": "#FFF4CE",
    "DANGER": "#C42B1C",
    "DANGER_BG": "#FDE7E9",
    # Controles
    "INPUT_BG": "#FFFFFF",
    "INPUT_BORDER": "#D1D1D1",
    "INPUT_BORDER_BOTTOM": "#8A8A8A",
    # Scrollbar
    "SCROLLBAR_BG": "transparent",
    "SCROLLBAR_HANDLE": "#8A8A8A",
    "SCROLLBAR_HANDLE_HOVER": "#6E6E6E",
    # Overlay / misc
    "DIVIDER": "#E5E5E5",
    "TOGGLE_OFF_BG": "#FFFFFF",
    "TOGGLE_OFF_BORDER": "#5D5D5D",
    "TOGGLE_OFF_KNOB": "#5D5D5D",
    "TOGGLE_ON_KNOB": "#FFFFFF",
}

DARK_TOKENS = {
    "WINDOW_BG": "#202020",
    "CONTENT_BG": "#1C1C1C",
    "SURFACE": "#2B2B2B",
    "SURFACE_HOVER": "#323232",
    "SURFACE_PRESSED": "#292929",
    "SURFACE_ALT": "#303030",
    "BORDER": "#383838",
    "BORDER_CARD_BOTTOM": "#383838",
    "BORDER_STRONG": "#454545",
    "TEXT": "#FFFFFF",
    "TEXT_SECONDARY": "#CCCCCC",
    "TEXT_DISABLED": "#787878",
    "ACCENT": "#4CC2FF",
    "ACCENT_HOVER": "#42B0E8",
    "ACCENT_PRESSED": "#3AA0D4",
    "ACCENT_TEXT": "#000000",
    "ACCENT_SOFT": "#243B4A",
    "NAV_ACTIVE_BG": "#2D2D2D",
    "NAV_HOVER_BG": "#2A2A2A",
    "SUCCESS": "#6CCB5F",
    "SUCCESS_BG": "#1F3A1F",
    "WARNING": "#FCE100",
    "WARNING_BG": "#433519",
    "DANGER": "#FF99A4",
    "DANGER_BG": "#442726",
    "INPUT_BG": "#313131",
    "INPUT_BORDER": "#454545",
    "INPUT_BORDER_BOTTOM": "#9A9A9A",
    "SCROLLBAR_BG": "transparent",
    "SCROLLBAR_HANDLE": "#9A9A9A",
    "SCROLLBAR_HANDLE_HOVER": "#CFCFCF",
    "DIVIDER": "#383838",
    "TOGGLE_OFF_BG": "#1C1C1C",
    "TOGGLE_OFF_BORDER": "#CCCCCC",
    "TOGGLE_OFF_KNOB": "#CCCCCC",
    "TOGGLE_ON_KNOB": "#000000",
}

THEMES: dict[str, dict[str, str]] = {
    "light": LIGHT_TOKENS,
    "dark": DARK_TOKENS,
}


# ---------------------------------------------------------------------------
# Plantilla QSS
# ---------------------------------------------------------------------------

_QSS_TEMPLATE = r"""
/* ============================================================
   Base / ventana
   ============================================================ */
QMainWindow, QWidget#appRoot {
    background: @WINDOW_BG@;
    color: @TEXT@;
}
QWidget {
    color: @TEXT@;
    font-family: "Segoe UI Variable Text", "Segoe UI", "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: 13px;
}
QWidget#contentArea, QWidget#contentRoot, QWidget#pageContent {
    background: @CONTENT_BG@;
}
QLabel {
    background: transparent;
    color: @TEXT@;
}
QLabel:disabled {
    color: @TEXT_DISABLED@;
}
QFrame {
    background: transparent;
}
QToolTip {
    background: @SURFACE@;
    color: @TEXT@;
    border: 1px solid @BORDER@;
    padding: 6px 8px;
    border-radius: 6px;
}

/* ============================================================
   Barra lateral (NavigationSidebar)
   ============================================================ */
QFrame#sidebar {
    background: @WINDOW_BG@;
    border-right: 1px solid @BORDER@;
}
QLabel#sidebarAppTitle {
    color: @TEXT@;
    font-size: 18px;
    font-weight: 700;
}
QLabel#sidebarSubtitle {
    color: @TEXT_SECONDARY@;
    font-size: 12px;
}
QPushButton#sidebarNewProjectButton {
    background: @SURFACE@;
    color: @TEXT@;
    border: 1px solid @BORDER@;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    font-weight: 500;
    text-align: left;
}
QPushButton#sidebarNewProjectButton:hover {
    background: @SURFACE_HOVER@;
}
QPushButton#sidebarNewProjectButton:pressed {
    background: @SURFACE_PRESSED@;
}

QLabel#sidebarSectionLabel {
    color: @TEXT_SECONDARY@;
    font-size: 11px;
    font-weight: 600;
    padding: 12px 12px 4px 12px;
}
QLabel#sidebarEnvLabel {
    color: @TEXT_SECONDARY@;
    font-size: 11px;
    padding: 4px 12px;
}

QFrame#sidebarDivider, QFrame#navSeparator {
    background: @DIVIDER@;
    min-height: 1px;
    max-height: 1px;
    border: none;
    margin: 8px 8px;
}

/* Botón de navegación WinUI 3 */
QPushButton#navButton {
    background: transparent;
    color: @TEXT@;
    border: none;
    border-radius: 6px;
    padding: 8px 12px 8px 36px;
    text-align: left;
    font-size: 13px;
    font-weight: 400;
    min-height: 20px;
}
QPushButton#navButton:hover {
    background: @NAV_HOVER_BG@;
}
QPushButton#navButton:checked {
    background: @NAV_ACTIVE_BG@;
    font-weight: 600;
}
QPushButton#navButton:disabled {
    color: @TEXT_DISABLED@;
}

/* Indicador de píldora activa (QFrame posicionado por NavigationSidebar) */
QFrame#navActivePill {
    background: @ACCENT@;
    border-radius: 2px;
    min-width: 3px;
    max-width: 3px;
    min-height: 16px;
    max-height: 16px;
}

/* Footer de sidebar: combos compactos */
QFrame#sidebarFooter QComboBox, QFrame#sidebarFooterCompact QComboBox {
    min-height: 30px;
    padding: 4px 8px;
    font-size: 12px;
}

/* ============================================================
   Área de contenido / encabezados
   ============================================================ */
QScrollArea#pageScrollArea, QScrollArea#contentScrollArea {
    background: transparent;
    border: none;
}
QScrollArea#pageScrollArea > QWidget > QWidget,
QScrollArea#contentScrollArea > QWidget > QWidget {
    background: transparent;
}

QLabel#pageTitle, QLabel#breadcrumbTitle {
    color: @TEXT@;
    font-size: 26px;
    font-weight: 600;
}
QLabel#pageSubtitle, QLabel#pageDescription {
    color: @TEXT_SECONDARY@;
    font-size: 13px;
}
QLabel#breadcrumbPath {
    color: @TEXT_SECONDARY@;
    font-size: 13px;
}

/* Contenedor de contenido centrado */
QWidget#contentContainer {
    background: transparent;
}

/* ============================================================
   Tarjetas / SettingRowCard / SettingExpanderCard
   ============================================================ */
QFrame#settingRowCard, QFrame#settingExpanderCard, QFrame#settingsCard {
    background: @SURFACE@;
    border: 1px solid @BORDER@;
    border-bottom: 1px solid @BORDER_CARD_BOTTOM@;
    border-radius: 8px;
}
QFrame#settingRowCard:hover, QFrame#settingExpanderCard:hover, QFrame#settingsCard:hover {
    background: @SURFACE_HOVER@;
}
QFrame#settingExpanderCard[expanded="true"] {
    background: @SURFACE@;
}

QLabel#settingTitle, QLabel#cardTitle {
    color: @TEXT@;
    font-size: 14px;
    font-weight: 600;
}
QLabel#settingDescription, QLabel#cardDescription, QLabel#cardDetail {
    color: @TEXT_SECONDARY@;
    font-size: 12px;
}
QLabel#settingIcon, QLabel#cardIcon {
    color: @TEXT@;
    font-size: 16px;
    min-width: 20px;
    max-width: 20px;
}

/* Cuerpo expandido */
QFrame#expanderBody {
    background: @SURFACE_ALT@;
    border: 1px solid @BORDER@;
    border-top: none;
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
}
QPushButton#expanderToggle {
    background: transparent;
    border: none;
    color: @TEXT_SECONDARY@;
    font-size: 14px;
    padding: 4px;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
}
QPushButton#expanderToggle:hover {
    background: @SURFACE_HOVER@;
    border-radius: 4px;
    color: @TEXT@;
}

/* ============================================================
   StatusMetricCard
   ============================================================ */
QFrame#statusMetricCard {
    background: @SURFACE@;
    border: 1px solid @BORDER@;
    border-bottom: 1px solid @BORDER_CARD_BOTTOM@;
    border-radius: 8px;
}
QLabel#metricTitle {
    color: @TEXT_SECONDARY@;
    font-size: 12px;
    font-weight: 600;
}
QLabel#metricValue {
    color: @TEXT@;
    font-size: 20px;
    font-weight: 600;
}
QLabel#metricPath, QLabel#metricDetail {
    color: @TEXT_SECONDARY@;
    font-size: 12px;
}

QLabel#statusPill {
    padding: 2px 10px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
}
QLabel#statusPill[state="ok"], QLabel#statusPill[state="ready"], QLabel#statusPill[state="verified"] {
    background: @SUCCESS_BG@;
    color: @SUCCESS@;
}
QLabel#statusPill[state="warn"], QLabel#statusPill[state="pending"] {
    background: @WARNING_BG@;
    color: @WARNING@;
}
QLabel#statusPill[state="error"], QLabel#statusPill[state="danger"] {
    background: @DANGER_BG@;
    color: @DANGER@;
}
QLabel#statusPill[state="info"], QLabel#statusPill[state="neutral"] {
    background: @ACCENT_SOFT@;
    color: @ACCENT@;
}

/* ============================================================
   Controles de entrada
   ============================================================ */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit {
    background: @INPUT_BG@;
    color: @TEXT@;
    border: 1px solid @INPUT_BORDER@;
    border-bottom: 1px solid @INPUT_BORDER_BOTTOM@;
    border-radius: 6px;
    padding: 0 10px;
    min-height: 32px;
    max-height: 32px;
    selection-background-color: @ACCENT@;
    selection-color: @ACCENT_TEXT@;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus {
    border: 1px solid @INPUT_BORDER@;
    border-bottom: 2px solid @ACCENT@;
    padding-bottom: -1px;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    background: @SURFACE_ALT@;
    color: @TEXT_DISABLED@;
    border-color: @BORDER@;
}
QLineEdit[readOnly="true"] {
    background: @SURFACE_ALT@;
    color: @TEXT_SECONDARY@;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border: none;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid @TEXT_SECONDARY@;
    margin-right: 8px;
}
QComboBox QAbstractItemView {
    background: @SURFACE@;
    color: @TEXT@;
    border: 1px solid @BORDER@;
    border-radius: 6px;
    padding: 4px;
    outline: none;
    selection-background-color: @SURFACE_HOVER@;
    selection-color: @TEXT@;
}

QTextEdit, QPlainTextEdit {
    background: @INPUT_BG@;
    color: @TEXT@;
    border: 1px solid @INPUT_BORDER@;
    border-radius: 6px;
    padding: 8px 10px;
    selection-background-color: @ACCENT@;
    selection-color: @ACCENT_TEXT@;
}
QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid @ACCENT@;
}

/* ============================================================
   Botones
   ============================================================ */
QPushButton {
    background: @SURFACE@;
    color: @TEXT@;
    border: 1px solid @BORDER@;
    border-bottom-color: @BORDER_CARD_BOTTOM@;
    border-radius: 6px;
    padding: 6px 14px;
    min-height: 20px;
    font-size: 13px;
    font-weight: 500;
}
QPushButton:hover {
    background: @SURFACE_HOVER@;
}
QPushButton:pressed {
    background: @SURFACE_PRESSED@;
    color: @TEXT_SECONDARY@;
}
QPushButton:disabled {
    background: @SURFACE_ALT@;
    color: @TEXT_DISABLED@;
    border-color: @BORDER@;
}

/* Primario: una sola acción principal */
QPushButton#primaryButton, QPushButton#primaryAction {
    background: @ACCENT@;
    color: @ACCENT_TEXT@;
    border: 1px solid @ACCENT@;
    font-weight: 600;
}
QPushButton#primaryButton:hover, QPushButton#primaryAction:hover {
    background: @ACCENT_HOVER@;
    border-color: @ACCENT_HOVER@;
}
QPushButton#primaryButton:pressed, QPushButton#primaryAction:pressed {
    background: @ACCENT_PRESSED@;
    border-color: @ACCENT_PRESSED@;
}
QPushButton#primaryButton:disabled, QPushButton#primaryAction:disabled {
    background: @BORDER@;
    color: @TEXT_DISABLED@;
    border-color: @BORDER@;
}

/* Botón sutil / ghost */
QPushButton#subtleButton, QPushButton#ghostButton, QPushButton#ghostAction {
    background: transparent;
    border: 1px solid transparent;
    color: @TEXT@;
}
QPushButton#subtleButton:hover, QPushButton#ghostButton:hover, QPushButton#ghostAction:hover {
    background: @SURFACE_HOVER@;
    border-color: @SURFACE_HOVER@;
}

/* Botón de peligro */
QPushButton#dangerButton, QPushButton#dangerAction {
    background: @DANGER@;
    color: #FFFFFF;
    border: 1px solid @DANGER@;
    font-weight: 600;
}
QPushButton#dangerButton:hover, QPushButton#dangerAction:hover {
    background: #B3271A;
}

/* ============================================================
   Toggle Switch estilo Windows 11 (QCheckBox)
   Usar: check.setObjectName("toggleSwitch") o propiedad toggleSwitch=true
   ============================================================ */
QCheckBox#toggleSwitch, QCheckBox[toggleSwitch="true"] {
    spacing: 0px;
    min-width: 40px;
    max-width: 40px;
    min-height: 20px;
    max-height: 20px;
}
QCheckBox#toggleSwitch::indicator, QCheckBox[toggleSwitch="true"]::indicator {
    width: 40px;
    height: 20px;
    border-radius: 10px;
    border: 1px solid @TOGGLE_OFF_BORDER@;
    background: @TOGGLE_OFF_BG@;
}
QCheckBox#toggleSwitch::indicator:hover, QCheckBox[toggleSwitch="true"]::indicator:hover {
    background: @SURFACE_HOVER@;
}
QCheckBox#toggleSwitch::indicator:checked, QCheckBox[toggleSwitch="true"]::indicator:checked {
    background: @ACCENT@;
    border: 1px solid @ACCENT@;
}
QCheckBox#toggleSwitch::indicator:checked:hover, QCheckBox[toggleSwitch="true"]::indicator:checked:hover {
    background: @ACCENT_HOVER@;
    border-color: @ACCENT_HOVER@;
}
QCheckBox#toggleSwitch::indicator:disabled, QCheckBox[toggleSwitch="true"]::indicator:disabled {
    background: @SURFACE_ALT@;
    border-color: @TEXT_DISABLED@;
}
/* Nota: QSS no puede dibujar el knob interno del toggle con fidelidad total.
   Para un toggle Win11 pixel-perfect, usar el widget ToggleSwitch de
   ui_components.py. Esta regla QSS ofrece un fallback funcional. */

/* Checkbox estándar */
QCheckBox {
    spacing: 8px;
    color: @TEXT@;
    background: transparent;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid @INPUT_BORDER_BOTTOM@;
    background: @INPUT_BG@;
}
QCheckBox::indicator:hover {
    background: @SURFACE_HOVER@;
}
QCheckBox::indicator:checked {
    background: @ACCENT@;
    border-color: @ACCENT@;
}
QCheckBox::indicator:disabled {
    border-color: @TEXT_DISABLED@;
    background: @SURFACE_ALT@;
}

/* Radio */
QRadioButton {
    spacing: 8px;
    color: @TEXT@;
    background: transparent;
}
QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border-radius: 10px;
    border: 1px solid @INPUT_BORDER_BOTTOM@;
    background: @INPUT_BG@;
}
QRadioButton::indicator:checked {
    background: @ACCENT@;
    border-color: @ACCENT@;
}

/* ============================================================
   Barra de acciones inferior (Footer)
   ============================================================ */
QFrame#actionFooter, QFrame#wizardFooter {
    background: @CONTENT_BG@;
    border-top: 1px solid @BORDER@;
}
QLabel#footerProgress, QLabel#wizardStatus {
    color: @TEXT_SECONDARY@;
    font-size: 12px;
}

/* ============================================================
   Scrollbars delgados estilo Windows 11
   ============================================================ */
QScrollBar:vertical {
    background: @SCROLLBAR_BG@;
    width: 10px;
    margin: 2px 2px 2px 2px;
    border: none;
}
QScrollBar::handle:vertical {
    background: @SCROLLBAR_HANDLE@;
    min-height: 30px;
    border-radius: 3px;
    margin: 0px;
}
QScrollBar::handle:vertical:hover {
    background: @SCROLLBAR_HANDLE_HOVER@;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    border: none;
    background: transparent;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}

QScrollBar:horizontal {
    background: @SCROLLBAR_BG@;
    height: 10px;
    margin: 2px 2px 2px 2px;
    border: none;
}
QScrollBar::handle:horizontal {
    background: @SCROLLBAR_HANDLE@;
    min-width: 30px;
    border-radius: 3px;
}
QScrollBar::handle:horizontal:hover {
    background: @SCROLLBAR_HANDLE_HOVER@;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    border: none;
    background: transparent;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}

/* ============================================================
   Tablas / listas
   ============================================================ */
QTableWidget, QTableView {
    background: @SURFACE@;
    alternate-background-color: @SURFACE_ALT@;
    color: @TEXT@;
    border: 1px solid @BORDER@;
    border-radius: 8px;
    gridline-color: @BORDER@;
    selection-background-color: @ACCENT_SOFT@;
    selection-color: @TEXT@;
    outline: none;
}
QTableWidget::item, QTableView::item {
    padding: 6px 8px;
    border-bottom: 1px solid @BORDER@;
}
QTableWidget::item:selected, QTableView::item:selected {
    background: @ACCENT_SOFT@;
    color: @TEXT@;
}
QHeaderView::section {
    background: @SURFACE_ALT@;
    color: @TEXT_SECONDARY@;
    border: none;
    border-bottom: 1px solid @BORDER@;
    padding: 8px;
    font-size: 12px;
    font-weight: 600;
}
QListWidget, QListView {
    background: @SURFACE@;
    color: @TEXT@;
    border: 1px solid @BORDER@;
    border-radius: 8px;
    outline: none;
    padding: 4px;
}
QListWidget::item:selected, QListView::item:selected {
    background: @ACCENT_SOFT@;
    color: @TEXT@;
    border-radius: 4px;
}

/* ============================================================
   Compatibilidad con nombres existentes del proyecto
   ============================================================ */
QLabel#brandTitle { color: @TEXT@; font-size: 18px; font-weight: 700; }
QLabel#brandSubtitle { color: @TEXT_SECONDARY@; font-size: 12px; }
QLabel#sidebarSection { color: @TEXT_SECONDARY@; font-size: 11px; font-weight: 600; padding: 12px 12px 4px 12px; }
QLabel#sidebarFooter { color: @TEXT_SECONDARY@; font-size: 11px; padding: 4px 12px; }
QToolButton#sidebarToggle {
    background: @SURFACE@; color: @TEXT@; border: 1px solid @BORDER@;
    border-radius: 6px; padding: 6px 9px; font-weight: 600;
}
QToolButton#sidebarToggle:hover { background: @SURFACE_HOVER@; border-color: @BORDER_STRONG@; }

QFrame#topBar { background: transparent; border: none; }
QLabel#breadcrumb { color: @TEXT_SECONDARY@; font-size: 13px; font-weight: 500; }
QLabel#globalStatus {
    background: @SURFACE@; color: @TEXT_SECONDARY@; border: 1px solid @BORDER@;
    border-radius: 6px; padding: 6px 10px; font-size: 12px;
}
QLabel#pageTitle { color: @TEXT@; font-size: 26px; font-weight: 600; }
QLabel#pageSubtitle { color: @TEXT_SECONDARY@; font-size: 13px; }
QWidget#pageHeader { background: transparent; }

QFrame#statusCard {
    background: @SURFACE@; border: 1px solid @BORDER@; border-bottom: 1px solid @BORDER_CARD_BOTTOM@;
    border-radius: 8px;
}
QLabel#cardTitle { color: @TEXT_SECONDARY@; font-size: 12px; font-weight: 600; }
QLabel#cardValue { color: @TEXT@; font-size: 20px; font-weight: 600; }
QLabel#cardDetail { color: @TEXT_SECONDARY@; font-size: 12px; }
QLabel#cardBadge {
    background: @ACCENT_SOFT@; color: @ACCENT@; border: 1px solid @BORDER@;
    border-radius: 10px; padding: 2px 10px; font-size: 11px; font-weight: 600;
}
QLabel#cardBadge[state="ok"] { background: @SUCCESS_BG@; color: @SUCCESS@; border-color: @SUCCESS_BG@; }
QLabel#cardBadge[state="warn"] { background: @WARNING_BG@; color: @WARNING@; border-color: @WARNING_BG@; }
QLabel#cardBadge[state="error"] { background: @DANGER_BG@; color: @DANGER@; border-color: @DANGER_BG@; }
QLabel#cardBadge[state="info"] { background: @ACCENT_SOFT@; color: @ACCENT@; border-color: @ACCENT_SOFT@; }

QFrame#sectionCard, QFrame#emptyState {
    background: @SURFACE@; border: 1px solid @BORDER@; border-bottom: 1px solid @BORDER_CARD_BOTTOM@;
    border-radius: 8px;
}
QLabel#sectionTitle, QLabel#emptyTitle { color: @TEXT@; font-size: 14px; font-weight: 600; }
QLabel#sectionSubtitle, QLabel#emptyDetail { color: @TEXT_SECONDARY@; font-size: 12px; }

QFrame#helpPanel {
    background: @SURFACE@; border: 1px solid @BORDER@; border-radius: 8px;
}
QLabel#helpTitle { color: @ACCENT@; font-size: 13px; font-weight: 600; }
QTextBrowser#helpBody { background: transparent; border: none; color: @TEXT@; }

QTextEdit#console, QPlainTextEdit#console {
    background: #101010; color: #E6E6E6; border: 1px solid @BORDER@;
    border-radius: 8px; font-family: "Cascadia Mono", "Consolas", monospace;
}

/* ============================================================
   Misceláneos
   ============================================================ */
QGroupBox {
    background: @SURFACE@;
    border: 1px solid @BORDER@;
    border-radius: 8px;
    margin-top: 20px;
    padding: 20px 16px 16px 16px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    color: @TEXT@;
}
QSplitter::handle {
    background: @BORDER@;
}
QSplitter::handle:hover {
    background: @ACCENT@;
}
QProgressBar {
    background: @SURFACE_ALT@;
    border: 1px solid @BORDER@;
    border-radius: 4px;
    text-align: center;
    color: @TEXT@;
    min-height: 8px;
}
QProgressBar::chunk {
    background: @ACCENT@;
    border-radius: 4px;
}
QMenu {
    background: @SURFACE@;
    color: @TEXT@;
    border: 1px solid @BORDER@;
    border-radius: 8px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 24px;
    border-radius: 4px;
}
QMenu::item:selected {
    background: @SURFACE_HOVER@;
}
"""


def build_stylesheet(theme: str = "light") -> str:
    """Devuelve la hoja QSS completa para el tema indicado."""
    tokens = THEMES.get(theme, LIGHT_TOKENS)
    qss = _QSS_TEMPLATE
    for key, value in tokens.items():
        qss = qss.replace(f"@{key}@", value)
    return qss


class ThemeManager(QObject):
    """Aplica y gestiona el tema global de la aplicación."""

    theme_changed = Signal(str)

    def __init__(self, app: QApplication | None = None, theme: str = "light"):
        super().__init__()
        self._app = app or QApplication.instance()
        self._theme = "light"
        self.set_theme(theme)

    @property
    def theme(self) -> str:
        return self._theme

    @property
    def tokens(self) -> dict[str, str]:
        return dict(THEMES.get(self._theme, LIGHT_TOKENS))

    def available_themes(self) -> tuple[str, ...]:
        return tuple(THEMES.keys())

    def set_theme(self, theme: str) -> None:
        theme = theme if theme in THEMES else "light"
        self._theme = theme
        tokens = self.tokens
        qss = build_stylesheet(theme)
        if self._app is not None:
            self._app.setStyleSheet(qss)
        self.theme_changed.emit(theme)

    def toggle_theme(self) -> str:
        next_theme = "dark" if self._theme == "light" else "light"
        self.set_theme(next_theme)
        return next_theme

    def token(self, name: str) -> str:
        return self.tokens.get(name, "")


# Compatibilidad simple: función módulo-level.
def apply_theme(app: QApplication | None = None, theme: str = "light") -> ThemeManager:
    return ThemeManager(app=app, theme=theme)
