---
name: creador-personalizado
description: Use when working on Creador Personalizado, a PySide6/Fedora image builder app. Provides project architecture, UI conventions, validation commands, and safe-change rules for this codebase.
---

# Creador Personalizado

Skill para agentes de IA que trabajan en este repositorio.

## Qué es este proyecto

- Aplicación de escritorio **PySide6** para crear distribuciones/imágenes Fedora personalizadas.
- Punto de entrada: `main.py` (`KioskBuilderGUI`).
- Core de dominio/build: `core/` (config, builders, kickstart, proyectos, software/DNF, USB, ISO, hardware).
- GUI: `gui/` (mixins por paso, componentes, tema, layouts, validación).

## Arquitectura rápida

- `main.py`: ventana principal, navegación, estado global, persistencia QSettings/proyectos, dashboard, compilación.
- `gui/tab_*.py`: mixins de cada paso del asistente. No son widgets independientes; agregan métodos a `KioskBuilderGUI`.
- `gui/custom_distro.py`: gestor de software Fedora (DNF5, grupos Comps, RPM locales). Tiene estado propio y workers.
- `gui/tab_usb.py`: escritura/verificación de ISO a USB.
- `gui/theme_manager.py`: fuente de verdad de tokens/QSS WinUI3 claro/oscuro.
- `gui/ui_components.py`: componentes reutilizables WinUI3 (`SettingRowCard`, `SettingExpanderCard`, `StatusMetricCard`, `ToggleSwitch`, `NavigationSidebar`, etc.).
- `gui/components.py`: componentes legacy; mantener solo por compatibilidad, evitar nuevos usos.
- `gui/validation.py`: validación por paso/configuración completa.
- `core/config.py`: `BuildConfig` normaliza/valida configuración; preservar compatibilidad del dict.

## Convenciones UI (WinUI 3 / Fluent)

- Usar `gui/theme_manager.py` y `gui/ui_components.py` para UI nueva.
- Contenido centrado, ancho máximo ~960px; tarjetas con borde sutil 1px, radio 8px, sin sombras pesadas.
- Preferir `SettingRowCard` para ajustes simples y `SettingExpanderCard` para opciones avanzadas.
- `ToggleSwitch` es compatible con uso tipo QCheckBox: `isChecked/setChecked/toggled/setEnabled`.
- Íconos: preferir SVG lineales 16x16/20x20 vía `gui/icons.py`; emojis solo como fallback temporal.
- No agregar estilos inline ad-hoc si pueden vivir en QSS/tokens.

## Reglas críticas al modificar

- **Preservar contratos existentes**: nombres de atributos `txt_*`, `combo_*`, `check_*`, `btn_*`, `lbl_*`, `group_*`, `card_*`, métodos `refresh_*`, `collect_config`, `init_tab_*`, `_register_advanced`, señales y workers.
- **No romper la lógica**: cambios visuales no deben alterar payload de `collect_config()`, validación, persistencia de proyectos, DNF, build o USB.
- **Compatibilidad de proyecto/config**: si se agrega un campo, normalizarlo en `core/config.py` y considerar carga de proyectos antiguos.
- **Hilos Qt**: workers deben emitir señales; no actualizar UI desde hilos secundarios.
- **Cambios pequeños y verificables**: este repo no tiene git inicializado; evitar refactors masivos mezclados con cambios funcionales.

## Comandos útiles

Ejecutar app:

```bash
python3 main.py
```

Chequeo rápido de sintaxis:

```bash
python -m py_compile main.py gui/*.py core/config.py
```

Compilación más amplia (ajustar según archivos tocados):

```bash
python -m py_compile gui/ui_components.py gui/theme_manager.py gui/layouts.py gui/tab_*.py gui/custom_distro.py main.py
```

## Dónde tocar según el objetivo

- **Tema/estilo global**: `gui/theme_manager.py`, `gui/theme.py` (wrapper compat), `gui/layouts.py`.
- **Componentes reutilizables**: `gui/ui_components.py`.
- **Paso del asistente**: `gui/tab_meta.py`, `tab_aesthetic.py`, `tab_software.py`, `tab_installer.py`, `tab_security.py`, `tab_build.py`.
- **Gestor software/DNF**: `gui/custom_distro.py`, `core/repositories/dnf_query.py`, `core/software/*`.
- **USB**: `gui/tab_usb.py`, `core/usb/*`.
- **Config/validación**: `core/config.py`, `gui/validation.py`.
- **Build**: `core/builders/*`, `core/builder/*`, `gui/tab_build.py`, `main.py`.

## Checklist antes de entregar

- [ ] `py_compile` pasa en archivos tocados.
- [ ] No se renombraron atributos públicos usados por otros mixins/main.
- [ ] `collect_config()` sigue incluyendo claves esperadas.
- [ ] UI nueva usa componentes/tokens WinUI3.
- [ ] Estados error/vacío/carga siguen siendo visibles.
- [ ] Si se tocó navegación/tema, verificar modo claro/oscuro y páginas condicionales (Kiosco/Desktop).