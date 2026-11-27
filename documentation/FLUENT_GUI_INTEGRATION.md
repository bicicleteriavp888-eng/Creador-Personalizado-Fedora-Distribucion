# Integración GUI Fluent — alpha.9

## Cambios incluidos
- `ThemeManager` queda conectado a la aplicación Qt como propietario del tema global.
- El selector claro/oscuro conserva `QSettings` y refresca los iconos de navegación.
- La navegación de Kiosco permanece visible, pero deshabilitada en perfiles Desktop.
- El gestor de software utiliza un `QSplitter` adaptable: vertical en ventanas compactas y horizontal en ventanas amplias.
- Las tablas y tarjetas del gestor pueden reducir su ancho; se mantiene intacta la consulta DNF5 y la simulación de dependencias.
- Se reduce el ancho mínimo de la ventana para permitir su uso en pantallas más pequeñas.

## Umbrales de adaptación
- Menos de 1440 px: catálogo y cambios pendientes apilados.
- 1440 px o más: paneles lado a lado.

## Validación
Este paquete debe probarse en Fedora con PySide6 disponible. La compilación sintáctica no sustituye las pruebas de GUI ni una prueba funcional de DNF5.
