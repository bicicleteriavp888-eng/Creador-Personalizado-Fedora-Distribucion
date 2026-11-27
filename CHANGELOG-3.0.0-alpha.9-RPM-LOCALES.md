# Integración de RPM locales — Creador Personalizado 3.0.0 alpha.9

## Cambios incluidos

- Se incorpora `core.software.local_rpm` como servicio compartido de inspección de RPM.
- La inspección obtiene nombre, versión, release, arquitectura y resumen con `rpm -qp`.
- La aceptación exige digest verificable y firma confiable, salvo RPM sin firma autorizados expresamente por el usuario.
- Un digest incorrecto o no verificable, una firma inválida, una clave no confiable o la ausencia de herramientas de inspección provocan rechazo.
- Fedora Desktop puede agregar varios RPM locales como paquetes del sistema mediante un repositorio local generado con `createrepo_c`.
- Kiosco puede agregar RPM locales como paquetes del sistema y conserva su flujo separado para RPM de aplicación/launcher.
- El flujo de aplicación RPM de Kiosco reutiliza el servicio común de inspección; no se mezclan launchers, servicios ni componentes Kiosco con Desktop.
- El gestor gráfico permite agregar, revisar y quitar RPM locales; la selección se guarda en la configuración del proyecto.
- `check_package_exists` ahora falla de forma cerrada: DNF ausente, error, timeout o resultado no concluyente nunca se consideran confirmación de existencia.

## Dependencias y resolución

Los RPM se publican en un repositorio local temporal. La transacción de instalación y la resolución final de dependencias ocurren durante la construcción de la imagen Fedora de destino, no instalando paquetes en el Fedora anfitrión. La vista previa DNF del gestor sigue enfocada en paquetes y grupos de repositorios habilitados; no sustituye la resolución final del entorno de construcción.

## Seguridad

- No se introduce `--skip-broken` ni `--allowerasing`.
- No se modifica la política de digest/firma para aceptar archivos inválidos.
- Los RPM sin firma solo se aceptan con la opción explícita existente y con digest correcto.
- Los RPM locales también pasan por la política de nombres de paquetes y la lista de paquetes bloqueados.

## Validaciones realizadas en este entorno

- `python -m compileall -q core gui main.py`: correcto.
- Pruebas de paquetes, RPM locales, seguridad, política de software y motor Desktop: **65 aprobadas**.
- Una prueba de regresión de Kiosco quedó excluida del subconjunto porque este entorno de ejecución no tiene PySide6.
- La suite completa no pudo recolectarse aquí: faltó la dependencia `PySide6`. Debe ejecutarse en el Fedora del usuario con `pip install -r requirements.txt` y luego `python -m pytest -q`.
- No se construyó una ISO en este entorno; por tanto no se declara validación de arranque ni de instalación real.
