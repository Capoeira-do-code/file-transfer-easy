# Linux 1.0.1

Paquetes de 64 bits para AMD64 (Intel/AMD) y ARM64. La base de compatibilidad es
Debian 12 o Ubuntu 24.04 y posteriores, con glibc 2.36, GTK3 y WebKitGTK 4.1.

## Instalar

Descarga el `.deb` correspondiente a tu equipo y, desde su carpeta, ejecuta:

```bash
sudo apt install ./FileTransferEasy-1.0.1-linux-amd64.deb
```

En ARM64, sustituye `amd64` por `arm64`. APT instala las dependencias. Abre
File Transfer Easy desde el lanzador de aplicaciones.

Para instalar sin administrador, extrae el `.tar.gz` de tu arquitectura y ejecuta
`./install.sh` dentro de la carpeta extraída. Instala el ejecutable en
`~/.local/bin` y el acceso del lanzador en el directorio de datos del usuario.
Necesita Python 3 para el instalador. En Debian/Ubuntu, las dependencias son:

```bash
sudo apt install libgtk-3-0 libwebkit2gtk-4.1-0 libx11-6 xdg-utils python3
```

El `.tar.gz` puede usarse en otras distribuciones que proporcionen esas mismas
bibliotecas. No es un AppImage y no incluye GTK ni WebKit.

Añade archivos y carpetas desde la ventana o mediante «Abrir con» en el gestor
de archivos. La bandeja depende del escritorio y sus extensiones. Si no aparece,
vuelve a abrir la app desde el lanzador para recuperar la ventana. Mantén el
equipo encendido y la app abierta durante las descargas. La primera sesión
descarga cloudflared desde Cloudflare.

Cada paquete tiene un archivo `.sha256`. Por ejemplo:

```bash
sha256sum -c FileTransferEasy-1.0.1-linux-amd64.deb.sha256
```

## Compilar

En Linux, instala Go según `go.mod` y las cabeceras:

```bash
sudo apt install build-essential pkg-config python3 libgtk-3-dev libwebkit2gtk-4.1-dev libx11-dev
VERSION=1.0.1 ./scripts/build-linux.sh
```

La arquitectura predeterminada es la de Go. Para compilar desde este Mac:

```bash
brew install pkgconf
VERSION=1.0.1 python3 scripts/build-linux-cross.py
VERSION=1.0.1 python3 scripts/verify-linux.py
```

El script descarga Zig 0.15.2 y paquetes oficiales de Debian Bookworm y comprueba
sus SHA-256. Guarda las herramientas en `~/Library/Caches/FileTransferEasyBuild`;
`FTE_CROSS_CACHE` permite cambiar esa carpeta. Usa `ARCH=amd64` o `ARCH=arm64`
para generar solo una arquitectura. Los artefactos se escriben en `dist/`.

La CI compila en runners Linux de ambas arquitecturas, instala el `.deb` y
ejecuta una prueba de arranque GTK/WebKit con Xvfb y DBus, apertura de archivo,
segunda instancia con carpeta y cancelación. Ese workflow está preparado,
pero no se ha ejecutado desde esta entrega local.

Los binarios entregados se han compilado y comprobado desde macOS. La ejecución
y revisión visual en un escritorio Linux quedan pendientes. Consulta
[VALIDATION.md](VALIDATION.md).

## Desinstalar

Si usaste APT: `sudo apt remove file-transfer-easy`.

Si usaste el instalador por usuario, elimina `~/.local/bin/file-transfer-easy`,
`org.wails.file_transfer_easy.desktop` de la carpeta `applications` de tu
directorio de datos y `com.filetransfereasy.desktop.png` de
`icons/hicolor/256x256/apps` del mismo directorio.
