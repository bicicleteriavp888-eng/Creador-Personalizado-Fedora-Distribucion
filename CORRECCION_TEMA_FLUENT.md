# Corrección del tema Fluent — alpha9

## Cambio aplicado
En `gui/theme_manager.py`, dentro de `ThemeManager.set_theme()`, se añadió
`tokens = self.tokens` inmediatamente después de asignar `self._theme`.
Esto garantiza que la paleta activa quede resuelta en una variable local al
cambiar el tema.

## Comprobaciones ejecutadas en este entorno
- `python -m compileall -q`: correcto.
- Prueba aislada del gestor de temas con dobles mínimos de Qt: correcto;
  se comprobó el ciclo claro → oscuro → claro, la actualización de QSS y
  la coherencia con los tokens de ambos temas.
- Suite parcial sin los módulos que requieren PySide6 y excluyendo una prueba
  que importa `core.builder` (también requiere PySide6): 151 pruebas aprobadas.
- Pruebas específicas: `test_branding_3.py` (3), `test_software_policy.py` (9),
  `test_process_runner.py` (3) y `test_project_store.py` (8): todas aprobadas.

## Limitaciones
Este entorno no tiene PySide6 instalado. Por eso no fue posible iniciar una
QApplication real ni verificar visualmente la ventana. La recolección completa
de pytest falla en seis módulos por `ModuleNotFoundError: PySide6`; una prueba
adicional de `test_desktops.py` también intenta importar ese módulo.
La prueba aislada con dobles verifica la lógica de selección y generación QSS,
pero no sustituye una ejecución gráfica real en Fedora.
