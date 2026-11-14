# Validación

## Interfaz e iconos de Windows 1.0.3 — 14 de noviembre de 2026

- Interfaz de escritorio con superficies neutras, acento azul, tipografía del
  sistema y controles compactos. Se retiran el título de portada, las
  ilustraciones decorativas, las sombras de las tarjetas y las etiquetas redundantes.
- Capturas de WebView2 con datos simulados, sin iniciar túneles: vista vacía y
  sesión activa en claro/oscuro, a 1024 × 681 y 820 × 520. Sin desbordamiento
  horizontal; contraste de texto superior a 4.5:1 en ambas paletas.
- El ICO se incrusta como recurso `#3`, que espera Wails. Se asignan también
  los iconos grande, pequeño y de clase de la ventana de Windows.
- `node scripts/test-windows-ui.mjs` compara los iconos nativos con el ICO
  píxel a píxel y comprueba bandeja, reapertura y recuperación tras caídas.
- `go test ./...`, `go vet ./...` y estados de frontend vacío, preparación,
  enlace activo y error.

El ejecutable se entrega como `dist/FileTransferEasy-1.0.3.exe` para conservar
la versión anterior mientras está abierta.

## Corrección de Windows — 14 de noviembre de 2026

- Wails actualizado de `v3.0.0-beta.11` a `v3.0.0`: recupera la WebView tras
  caídas del renderer o del proceso del navegador, que antes dejaban la ventana vacía.
- Eliminado el segundo `tray.Run()`: `SystemTray.New()` ya inicia el icono.
  Un arranque instrumentado con `WndProcInterceptor` pasó de cuatro ventanas
  nativas a tres al eliminar la creación extra del tray.
- JavaScript y CSS se sirven con tipos MIME explícitos, independientemente de
  las asociaciones del registro de Windows. La regresión simula `.js=text/csv`
  y `.css=application/octet-stream`: fallaba antes y pasa con la corrección.
- Los controles para añadir archivos se muestran desde el HTML inicial,
  mientras llega el estado del servidor.
- `node scripts/test-windows-ui.mjs`: WebView2 real con MIME incorrecto,
  opciones y estilos, ocultar/reabrir sin duplicados y recuperación tras
  `Page.crash` y `Browser.crash` manteniendo la misma sesión local.
- `go test ./...`, `go vet ./...` y estados de frontend vacío, preparación,
  enlace activo y error con un user-agent de Windows.

El controlador visual del escritorio no estaba disponible. Estas comprobaciones
usan el protocolo de diagnóstico de WebView2; no sustituyen una revisión manual
de los menús y del icono sobre la barra de tareas.

## Validación 1.0.1 — macOS y Linux

Realizada el 4 de octubre de 2026 desde Apple Silicon, macOS 27.2.
Los artefactos están generados; las comprobaciones nativas pendientes se indican abajo.

## Controles superados en 1.0.1

- `go vet ./internal/...`, `go test -race ./internal/...` y `go test -race .`.
  Regresiones de reapertura: omitir el ejecutable y resolver rutas de la segunda instancia.
- `swift scripts/test-ui.swift`: HTML/JavaScript real, arranque, estados,
  controles de copia/apertura/reintento, página pública y contraste de ambas paletas.
- `./scripts/test-native-macos.sh`: receptor AppKit con archivos y carpetas reales
  temporales, espacios, acentos y comillas; rechazo de texto, URL web y operaciones
  de movimiento; despacho del menú. Las rutas recibidas siguen apuntando al archivo
  original aunque AppKit descomponga Unicode.
- Compilación macOS universal, arquitecturas `arm64` y `x86_64`, versión `1.0.1`,
  mínimo `13.0` en plist y ambas órdenes `LC_BUILD_VERSION`.
- Firma ad hoc estricta de la app dentro del DMG y de la copia extraída a Descargas.
  Montaje de solo lectura, enlace a `/Applications` y checksum SHA-256.
- Compilación Linux AMD64 y ARM64 con Zig 0.15.2 y SDK oficial de Debian Bookworm.
- `python3 scripts/verify-linux.py`: formato DEB y TAR, ELF y arquitectura, cargador
  dinámico, GTK3/WebKitGTK 4.1, símbolos glibc compatibles con Debian 12, ausencia de RPATH al SDK local, permisos, entrada del
  lanzador, sintaxis y escape de rutas del instalador, checksums.
- Sintaxis del workflow y de los scripts Python; `git diff --check`.

## Comprobaciones de la versión anterior

En 1.0.0 se probó la transferencia real por Cloudflare:
`FTE_E2E=1 go test -race ./internal/app/ -run EndToEnd -v -timeout 5m`.
Pasaron la descarga individual y ZIP con comparación de bytes. El backend no ha
cambiado entre 1.0.0 y 1.0.1.

También se revisaron ambas interfaces en claro y oscuro, ventana de 820 × 560,
página pública de 320 px, selección nativa mediante ⌘O y ⇧⌘O, copia, QR, vista
pública, cancelación de transferencia y cancelación/reintento durante preparación.
No se observaron excepciones de JavaScript. En 1.0.1 se han simplificado los textos
sin cambiar la distribución de las vistas, salvo retirar el bloque de frases inicial.

Las regresiones internas cubren cancelación de descarga, arranque y DNS; DNS sin
verificar; caída del túnel; reintentos sin servidores anteriores y cierre definitivo.

## Comprobaciones pendientes

- Arrastre manual desde Finder sobre ventana, Dock y nuevo icono de la barra de menús.
- Recuperar la ventana desde el nuevo menú y el Dock conservando la sesión.
- Revisión visual y ejecución en un escritorio Linux.
- Ejecutar la nueva CI Linux: incluye instalación del DEB y prueba GTK/WebKit bajo
  Xvfb/DBus, archivo inicial, carpeta desde segunda instancia y cancelación.

El control del escritorio falló con `cgWindowNotFound` durante la revisión anterior;
esta sesión no dispone del controlador. La prueba AppKit comprueba el receptor,
pero no sustituye un arrastre manual sobre el icono del sistema.

La ejecución Intel y en macOS 13 necesita equipos con esas condiciones. La entrega
macOS usa firma ad hoc; no se ha realizado firma Developer ID ni notarización.

## Artefactos

Todos los instaladores, checksums y la `.app` extraída están en
`~/Downloads/FileTransferEasy-1.0.1/`. Las instrucciones están en
[MACOS_RELEASE.md](MACOS_RELEASE.md) y [LINUX_RELEASE.md](LINUX_RELEASE.md).
Cierra una versión anterior con «Salir» antes de abrir la nueva.

La copia de Descargas y la del DMG conservan una firma estricta válida. Documentos
está sincronizado mediante File Provider, que puede volver a añadir FinderInfo a
la `.app` de `dist/` y alterar su firma; usa el DMG o la copia de Descargas.

```text
4e5fd100c4ff0db50017e3840bd0b3db3310da54714c12f8167c1de4d059fd1c  FileTransferEasy-1.0.1-linux-amd64.deb
bf4f57f0c5b50918989017842077eece1a74a4d2f731716e9b9ca0a4acc62be9  FileTransferEasy-1.0.1-linux-amd64.tar.gz
feef9f21d150058030bcc11758c3555cbc83824fbf4ca69c4f2ea6eb323cc4f9  FileTransferEasy-1.0.1-linux-arm64.deb
ea860679c718d410651a14bc997f4993cb4cfb9a234bc432f65a8b7adcfb2e2f  FileTransferEasy-1.0.1-linux-arm64.tar.gz
6b72c665527c2313896c180c3f03e32601095161dc1ec1f5e5ef7f754de73103  FileTransferEasy-1.0.1.dmg
```
