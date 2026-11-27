"""Compatibilidad de tema para Creador Personalizado.

Este módulo mantiene la API histórica (`build_stylesheet`, `THEMES`, etc.)
pero delega el diseño al nuevo Design System Fluent/WinUI 3 implementado en
`gui.theme_manager`.
"""

from gui.theme_manager import DARK_TOKENS as DARK
from gui.theme_manager import LIGHT_TOKENS as LIGHT
from gui.theme_manager import THEMES
from gui.theme_manager import build_stylesheet


# Compatibilidad con el nombre anterior.
APP_STYLESHEET = build_stylesheet("light")

__all__ = ["LIGHT", "DARK", "THEMES", "build_stylesheet", "APP_STYLESHEET"]