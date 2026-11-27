"""Small linear SVG icons for the WinUI3-inspired UI."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

try:
    from PySide6.QtSvg import QSvgRenderer
except Exception:  # pragma: no cover - optional dependency
    QSvgRenderer = None


def _svg(stroke: str, body: str, size: int = 16) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{stroke}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        f"{body}</svg>"
    )


_ICONS = {
    "home": '<path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-4.5v-5.5h-5V21H5a1 1 0 0 1-1-1z"/>',
    "identity": '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M8 9h8M8 13h5"/>',
    "appearance": '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.5v2.2M12 19.3v2.2M4.22 4.22l1.56 1.56M18.22 18.22l1.56 1.56M2.5 12h2.2M19.3 12h2.2M4.22 19.78l1.56-1.56M18.22 5.78l1.56-1.56"/>',
    "software": '<path d="M21 8l-9 5-9-5 9-5 9 5z"/><path d="M3 8v8l9 5 9-5V8"/><path d="M12 13v8"/>',
    "installer": '<path d="M12 3v11"/><path d="M8 10l4 4 4-4"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
    "security": '<path d="M12 3l7 3v5c0 5-3 7.5-7 10-4-2.5-7-5-7-10V6z"/><path d="M9.5 12.5l1.8 1.8 3.4-4"/>',
    "build": '<path d="M4 20h16"/><path d="M7 16V9"/><path d="M12 16V5"/><path d="M17 16v-7"/>',
    "usb": '<path d="M12 2v11"/><path d="M12 6h3v2"/><path d="M12 9H9v2"/><circle cx="12" cy="18" r="2"/><path d="M15 8v2.5a2 2 0 0 1-2 2h-1M9 11v1.5a2 2 0 0 0 2 2h1"/>',
    "manager": '<rect x="3" y="4" width="8" height="7" rx="1.5"/><rect x="13" y="4" width="8" height="7" rx="1.5"/><rect x="3" y="13" width="8" height="7" rx="1.5"/><path d="M17 13v7M13.5 16.5H20.5"/>',
    "kiosk": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "disc": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.2"/>',
    "tag": '<path d="M20 13l-7 7-9-9V4h7z"/><circle cx="7.5" cy="7.5" r="1"/>',
    "version": '<path d="M7 20h10"/><path d="M9 16l-2-4 5-8 5 8-2 4"/>',
    "user": '<circle cx="12" cy="8" r="3.2"/><path d="M4.5 20a7.5 7.5 0 0 1 15 0"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.5-2.3 1a7 7 0 0 0-1.7-1L14.5 3h-5L9.1 6a7 7 0 0 0-1.7 1l-2.3-1-2 3.5L5 11a7 7 0 0 0 0 2l-1.9 1.5 2 3.5 2.3-1a7 7 0 0 0 1.7 1l.4 3h5l.4-3a7 7 0 0 0 1.7-1l2.3 1 2-3.5L18.9 13a7 7 0 0 0 .1-1z"/>',
    "linux": '<circle cx="12" cy="8" r="3"/><path d="M9 11c-2 1.5-3 3.5-3 5.5A3 3 0 0 0 9 20h6a3 3 0 0 0 3-3.5c0-2-1-4-3-5.5"/><path d="M10 20v-2M14 20v-2"/>',
    "boot": '<path d="M12 3v10"/><path d="M8.5 9.5L12 13l3.5-3.5"/><path d="M5 15a7 7 0 1 0 14 0"/>',
    "desktop": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "display": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M7 20h10"/>',
    "network": '<circle cx="12" cy="18" r="1.5"/><path d="M8.5 14.5a5 5 0 0 1 7 0"/><path d="M5.5 11.5a9 9 0 0 1 13 0"/><path d="M2.5 8.5a13 13 0 0 1 19 0"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "key": '<circle cx="8.5" cy="10.5" r="3"/><path d="M11.2 12.8L20 21"/><path d="M17 18l2 2M15 20l2-2"/>',
    "warning": '<path d="M12 3l9 16H3z"/><path d="M12 9v4"/><circle cx="12" cy="16" r=".8" fill="currentColor" stroke="none"/>',
    "folder": '<path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "package": '<path d="M21 8l-9 5-9-5 9-5 9 5z"/><path d="M3 8v8l9 5 9-5V8"/>',
    "toolbox": '<path d="M4 8h16v11a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z"/><path d="M9 8V6a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/><path d="M4 12h16"/>',
    "bolt": '<path d="M13 2L4 14h7l-1 8 10-12h-7z"/>',
    "restart": '<path d="M4 4v5h5"/><path d="M20 20v-5h-5"/><path d="M6.5 9A7 7 0 0 1 19 12"/><path d="M17.5 15A7 7 0 0 1 5 12"/>',
    "terminal": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3"/><path d="M12 15h5"/>',
    "window": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/><path d="M8 15h8"/>',
}


@lru_cache(maxsize=64)
def icon(name: str, color: str = "#5D5D5D", size: int = 16) -> QIcon:
    body = _ICONS.get(name)
    if not body or QSvgRenderer is None:
        return QIcon()
    renderer = QSvgRenderer(QByteArray(_svg(color, body, size).encode("utf-8")))
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()
    return QIcon(pix)


def nav_icon(name: str, active: bool = False, theme: str = "light") -> QIcon:
    if active:
        color = "#0067C0" if theme == "light" else "#4CC2FF"
    else:
        color = "#5D5D5D" if theme == "light" else "#CCCCCC"
    return icon(name, color=color, size=16)


_EMOJI_ALIASES = {
    "🧩": "identity",
    "💿": "disc",
    "🏷": "tag",
    "🔢": "version",
    "👤": "user",
    "⚙": "settings",
    "🐧": "linux",
    "🚀": "boot",
    "👥": "user",
    "🔒": "lock",
    "🖥": "display",
    "💾": "installer",
    "🛡": "security",
    "🔐": "lock",
    "🔑": "key",
    "⚡": "bolt",
    "📁": "folder",
    "📦": "package",
    "🧰": "toolbox",
    "🪟": "window",
    "📺": "display",
    "📱": "kiosk",
    "🌐": "network",
    "🔁": "restart",
    "🧪": "warning",
    "⌨": "terminal",
    "⚠": "warning",
}


def resolve_icon(name_or_emoji: str, color: str | None = None, size: int = 20):
    """Return QIcon for a known key or emoji alias; empty QIcon if unknown."""
    if not name_or_emoji:
        return QIcon()
    key = _EMOJI_ALIASES.get(str(name_or_emoji).strip(), str(name_or_emoji).strip())
    if color is None:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        is_dark = False
        if app is not None:
            is_dark = app.palette().window().color().lightness() < 128
        color = "#CCCCCC" if is_dark else "#5D5D5D"
    return icon(key, color=color, size=size)
