# Creador Personalizado alpha.9 — paquete de trabajo corregido

## Cambios aplicados
1. `gui/tab_build.py`: las cuatro acciones de validación/compilación del paso 6
   pasan de una fila horizontal a una cuadrícula de dos columnas. Esto reduce
   el ancho mínimo exigido por los controles en ventanas de 1080x720.
2. `main.py`: al terminar de restaurar preferencias y modo de interfaz, se
   vuelve a aplicar la visibilidad de controles dependientes del motor. La
   página Configuración Kiosco queda gobernada por el perfil activo.

## Componentes de RPM y DNF encontrados en la base
La copia recibida ya incluye `core/software/local_rpm.py`, integración de
rutas RPM en configuración/validación y llamadas desde Desktop y Builder.
También incluye política fail-closed en `core/repositories/package_checker.py`
y pruebas de `tests/test_package_checker.py` y `tests/test_local_rpm.py`.
No se duplicó ni se reemplazó ese mecanismo.

## Pruebas ejecutadas en este entorno
- `tests/test_package_checker.py` + `tests/test_local_rpm.py`: 10 aprobadas.
- Las dos pruebas GUI reportadas no se pudieron ejecutar aquí porque el
  entorno de revisión no tiene instalado PySide6 (`ModuleNotFoundError`).
- Por lo tanto, los cambios visuales requieren repetición de las pruebas GUI
  en el Fedora del usuario. No se afirma que los dos fallos estén verificados
  como resueltos en ejecución Qt.

## Importante
Este ZIP es una copia de trabajo. No contiene commits ni operaciones contra
GitHub. Se preservaron las firmas/digests RPM y no se añadieron opciones para
omitir conflictos DNF.
