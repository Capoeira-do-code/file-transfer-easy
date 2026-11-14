# File Transfer Easy 1.1.0

Publicada el 14 de noviembre de 2026.

## Novedades

- Interfaz compacta, con menos textos auxiliares y controles de uso directo.
- Temas claro y oscuro sincronizados entre la app y las páginas públicas abiertas.
- Ajustes de uso, seguridad, recepción e historial que se conservan entre sesiones.
- Contraseñas para archivos, carpetas o toda la página. Los archivos de una carpeta
  heredan su contraseña salvo que tengan una propia.
- Subidas configurables, con carpeta de destino y límite de tamaño. También se
  pueden crear enlaces sólo para recibir archivos.
- Historial de visitantes con nombres asociados a las IP.
- Bloqueo de IP, con revocación de permisos y cancelación de transferencias activas.
- Aprobación o rechazo de visitantes desde la app.
- Errores que muestran el motivo concreto del fallo.
- Correcciones de Windows: ventana vacía, elementos duplicados en la bandeja y
  sustitución de la «W» por el icono de File Transfer Easy en la barra de tareas.

## Descargas

| Plataforma | Archivo |
| --- | --- |
| Windows x64 — instalador | [FileTransferEasy-Setup-1.1.0.exe](https://github.com/Capoeira-do-code/file-transfer-easy/releases/download/v1.1.0/FileTransferEasy-Setup-1.1.0.exe) |
| Windows x64 — portable | [FileTransferEasy-1.1.0-windows-amd64.exe](https://github.com/Capoeira-do-code/file-transfer-easy/releases/download/v1.1.0/FileTransferEasy-1.1.0-windows-amd64.exe) |
| macOS — universal, Intel y Apple Silicon | [FileTransferEasy-1.1.0.dmg](https://github.com/Capoeira-do-code/file-transfer-easy/releases/download/v1.1.0/FileTransferEasy-1.1.0.dmg) |
| Linux AMD64 — Debian/Ubuntu | [FileTransferEasy-1.1.0-linux-amd64.deb](https://github.com/Capoeira-do-code/file-transfer-easy/releases/download/v1.1.0/FileTransferEasy-1.1.0-linux-amd64.deb) |
| Linux ARM64 — Debian/Ubuntu | [FileTransferEasy-1.1.0-linux-arm64.deb](https://github.com/Capoeira-do-code/file-transfer-easy/releases/download/v1.1.0/FileTransferEasy-1.1.0-linux-arm64.deb) |
| Linux AMD64 — archivo con instalador por usuario | [FileTransferEasy-1.1.0-linux-amd64.tar.gz](https://github.com/Capoeira-do-code/file-transfer-easy/releases/download/v1.1.0/FileTransferEasy-1.1.0-linux-amd64.tar.gz) |
| Linux ARM64 — archivo con instalador por usuario | [FileTransferEasy-1.1.0-linux-arm64.tar.gz](https://github.com/Capoeira-do-code/file-transfer-easy/releases/download/v1.1.0/FileTransferEasy-1.1.0-linux-arm64.tar.gz) |
| Fuentes utilizadas para las compilaciones | [FileTransferEasy-1.1.0-source.zip](https://github.com/Capoeira-do-code/file-transfer-easy/releases/download/v1.1.0/FileTransferEasy-1.1.0-source.zip) |

Cada paquete incluye un archivo `.sha256` correspondiente en los adjuntos de la
release. También están disponibles las
[sumas SHA-256 conjuntas](https://github.com/Capoeira-do-code/file-transfer-easy/releases/download/v1.1.0/FileTransferEasy-1.1.0-SHA256SUMS.txt),
el [manifiesto de archivos](https://github.com/Capoeira-do-code/file-transfer-easy/releases/download/v1.1.0/FileTransferEasy-1.1.0-artifacts.json)
y el [informe de validación](https://github.com/Capoeira-do-code/file-transfer-easy/releases/download/v1.1.0/FileTransferEasy-1.1.0-validation.json).

## Instalación y actualización

**Cierra la versión anterior con «Salir» desde la bandeja del sistema antes de
abrir la nueva.**

- **Windows:** ejecuta el instalador o abre el portable. Se necesita el runtime
  WebView2.
- **macOS:** abre el DMG y arrastra la app a Aplicaciones. El paquete universal
  sirve para Intel y Apple Silicon y requiere macOS 13 o posterior. Lleva firma
  ad hoc, sin notarización de Apple; Gatekeeper puede bloquearlo al abrirlo en
  otro equipo. Consulta la [guía de macOS](https://github.com/Capoeira-do-code/file-transfer-easy/blob/main/go-app/MACOS_RELEASE.md).
- **Linux:** elige tu arquitectura. En Debian 12 o Ubuntu 24.04 y posteriores,
  instala el DEB con `sudo apt install ./FileTransferEasy-1.1.0-linux-amd64.deb`
  (usa `arm64` si corresponde). El TAR.GZ incluye un instalador por usuario.
  Se necesitan GTK3 y WebKitGTK 4.1; la bandeja depende del entorno de escritorio.

La primera vez que compartas archivos, la app descarga `cloudflared` si no está
disponible.

## Comprobaciones realizadas

- Pruebas de acceso, contraseñas, aprobación de visitantes, descargas individuales
  y ZIP, y subidas reales mediante Cloudflare.
- Pruebas de la ventana, el ciclo de vida de la bandeja, los ajustes y las
  transferencias con WebView2 en Windows.
- Pruebas de Go y `go vet`; detector de carreras en Ubuntu y macOS.
- Compilación universal de macOS y comprobaciones de interfaz y recepción nativa:
  [ejecución de GitHub Actions completada correctamente](https://github.com/Capoeira-do-code/file-transfer-easy/actions/runs/43573901266).
- Verificación de los paquetes Linux AMD64/ARM64, dependencias, permisos y sumas
  SHA-256. La validación local de Linux fue estructural, sin ejecutar un escritorio
  Linux en este equipo.

La preparación y validación de esta entrega se completó en aproximadamente una hora.
