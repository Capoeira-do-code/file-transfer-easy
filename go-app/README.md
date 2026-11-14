# File Transfer Easy — versión Go

Envía archivos entre dispositivos que no están en la misma red.

App de escritorio para macOS, Linux y Windows. Arrastras un archivo o una carpeta a la
ventana, la app genera un enlace público, y ves en vivo quién lo abre y qué se
está descargando. Se queda en la bandeja del sistema, así que puedes cerrar la
ventana y seguir compartiendo.

Reescritura en Go de la app original en Python/PySide6, que sigue en la raíz del
repositorio. Un ejecutable con webview del sistema; Linux requiere GTK3 y WebKitGTK 4.1.

## Descargar la versión 1.1.0

Los instaladores de Windows, el portable, el DMG universal de macOS y los paquetes
Linux AMD64/ARM64 están en la [release 1.1.0](https://github.com/Capoeira-do-code/file-transfer-easy/releases/tag/v1.1.0).
Consulta las [notas de la versión](../RELEASE_NOTES.md) para las novedades, los
enlaces directos, las sumas SHA-256 y las comprobaciones realizadas.

Antes de abrir la nueva versión, cierra la anterior con **«Salir»** desde la
bandeja del sistema. macOS lleva firma ad hoc y no está notarizado por Apple.

## Ajustes y acceso en 1.1.0

El botón de configuración está en la esquina superior derecha. El tema claro
es el predeterminado; al cambiarlo se actualizan la app y las páginas públicas
abiertas. Los ajustes se guardan entre sesiones.

- **Seguridad**: contraseña para toda la página y aprobación manual de cada
  visitante. Las solicitudes aparecen en la app, también si la ventana estaba
  oculta; el propietario puede aceptar o rechazar cada conexión.
- **Archivos y carpetas**: clic derecho o botón de opciones para mostrar en el
  explorador, quitar de la lista o establecer/cambiar/quitar una contraseña.
  Las carpetas protegen sus archivos; el ZIP incluye los archivos desbloqueados.
- **Recepción**: habilita las subidas, elige la carpeta de destino y limita el
  tamaño por envío. Se puede crear un enlace sólo para recibir archivos. Las
  subidas terminadas aparecen en la app y no sobrescriben archivos existentes.
- **Visitantes**: quitar de la lista actual o bloquear su IP. El bloqueo revoca
  permisos y cancela sus transferencias activas. El historial conserva visitas
  entre sesiones y permite asignar nombres a las IP para reconocerlas después.

Las contraseñas se guardan como hashes PBKDF2 con sal; los permisos del navegador
caducan y no se restauran al reiniciar. La configuración, los nombres y el
historial se guardan en `access.json` dentro del directorio de configuración del
usuario (`%APPDATA%\\FileTransferEasy` en Windows). No se incluyen en los paquetes
ni en las instantáneas de fuentes.

---

## Cómo funciona

- **Ventana**: [Wails v3](https://wails.io) muestra una webview nativa
  (WKWebView en macOS, WebKitGTK en Linux, WebView2 en Windows).
- **Interfaz**: HTML, CSS y JavaScript planos. Sin npm, sin frameworks, sin CDN.
- **Enlace público**: un túnel rápido de Cloudflare mediante `cloudflared`, que
  la app descarga sola la primera vez que compartes algo.
- **Sin nube**: los archivos nunca se suben a ningún sitio. El túnel apunta a un
  servidor local que lee directamente del disco.

Hay **dos servidores HTTP** y la separación es deliberada:

| | Escucha en | Quién entra | Qué expone |
|---|---|---|---|
| Interfaz | `127.0.0.1`, puerto aleatorio | solo la ventana, con un token por ejecución | todo el control de la app |
| Público | todas las interfaces, puerto aleatorio | visitantes autorizados por el túnel o la red local | descargas y, si se habilitan, subidas bajo `/s/<token>` |

Aunque el enlace del túnel se filtrara, no da acceso a ningún control: esas
rutas solo existen en el servidor de la interfaz, que está atado a loopback y
protegido por un token distinto.

## Detalle que importa: la espera del DNS

`cloudflared` imprime la URL **antes** de que Cloudflare publique el registro
DNS — unos 14 segundos antes, medido. Y `trycloudflare.com` no tiene registro
comodín y su SOA marca un TTL negativo de **1800 segundos**.

Es decir: quien consulte el nombre demasiado pronto se guarda un `NXDOMAIN` en
caché durante media hora y ve el enlace roto todo ese rato.

Por eso la app **no entrega el enlace hasta que el nombre resuelve de verdad**
([`internal/tunnel/dns.go`](internal/tunnel/dns.go)). Mientras espera, la
ventana muestra "Creando el enlace…" y el botón de copiar está desactivado. La
comprobación consulta resolutores públicos directamente, para que nuestro propio
sondeo no sea lo que envenene la caché del sistema del usuario.

---

## Compilar

La versión predeterminada está en [VERSION](VERSION). Los comandos, toolchains,
nombres de artefactos y el snapshot de fuentes están en [BUILDING.md](BUILDING.md).

Necesitas la versión de Go indicada en `go.mod` (actualmente Go 1.27). En macOS, las Command Line Tools de Xcode.

```bash
cd go-app

# macOS: paquete .app universal + .dmg en dist/
./scripts/build-macos.sh

# Solo tu arquitectura: la mitad de tiempo, ideal mientras desarrollas
ARCH=arm64 ./scripts/build-macos.sh

# Linux: .deb y .tar.gz para la arquitectura de la máquina
./scripts/build-linux.sh

# Linux AMD64 + ARM64 desde macOS (Zig y SDK de Debian)
python3 scripts/build-linux-cross.py

# Windows: .exe, también desde macOS o Linux
./scripts/build-windows.sh
```

El `.dmg` queda en `go-app/dist/FileTransferEasy-<versión>.dmg`. Para fijar la
versión, `VERSION=1.2.0 ./scripts/build-macos.sh`.

El `.exe` no necesita cgo ni una máquina Windows: Wails v3 habla con WebView2
mediante bindings en Go puro. El instalador NSIS sí hay que construirlo en
Windows, con `scripts\build-windows.ps1`.

Para publicar una release con los artefactos de las tres plataformas, empuja un tag y deja que actúe
[el workflow](../.github/workflows/build.yml):

```bash
git tag vX.Y.Z && git push origin vX.Y.Z
```

### Desarrollo

```bash
go run .                       # arranca la app
go test ./internal/...         # pruebas
go test -race ./internal/...   # con detector de carreras
swift scripts/test-ui.swift    # arranque, estados y controles de la UI (macOS)
node scripts/test-windows-ui.mjs # WebView2, recuperación y bandeja (Windows, Node 22+)
node scripts/test-sharing-features.mjs # contraseñas, solicitudes, recepción y temas con dos WebView2 reales
./scripts/test-native-macos.sh # receptor AppKit de archivos y menú (macOS)
go run ./cmd/genicons          # regenera todos los iconos
```

La interfaz se sirve por HTTP normal, así que también puedes abrirla en un
navegador: arranca la app, mira el puerto que abre en `127.0.0.1` y pega la URL.
El token va inyectado en la propia página.

---

## Añadir archivos con la ventana oculta

- **macOS**: suelta archivos o carpetas sobre el **icono del Dock** o el de la
  **barra de menús**. Se añaden a la sesión y se abre la ventana. La barra usa
  un receptor nativo AppKit; el Dock usa `CFBundleDocumentTypes`.
- **Windows**: suelta archivos sobre el `.exe` o sobre un acceso directo. Se
  lanza una segunda instancia cuyos argumentos se reenvían a la que ya corre.
- **Linux**: usa «Abrir con File Transfer Easy» desde el gestor de archivos.
  Los argumentos se añaden tanto al iniciar como en una sesión existente.
- **Desde la bandeja**: el menú tiene "Añadir archivos…" y "Añadir carpeta…".

El arrastre sobre el icono superior se implementa en macOS. La bandeja de Linux
depende del escritorio; si no aparece, abre la app de nuevo desde el lanzador.

## Estructura

```
main.go                 ventana, bandeja, drag & drop nativo
desktop.go              implementación de las capacidades nativas sobre Wails
frontend/               UI de la ventana (HTML/CSS/JS planos)
public/                 página que ve quien recibe el enlace
cmd/genicons/           genera todos los iconos desde una definición vectorial
internal/
  app/                  orquestador: estado, ciclo de compartición, bus SSE
  core/                 archivos y carpetas compartidos
  activity/             visitantes, transferencias, registro
  tunnel/               cloudflared: localizar, instalar, ejecutar, esperar DNS
  publicweb/            servidor público
  uiserver/             servidor local de la interfaz
  format/               tamaños, velocidades y fechas en español
scripts/                empaquetado por plataforma
```

## Pruebas

```bash
go test ./internal/...
```

Hay además una prueba de extremo a extremo que abre un túnel real de Cloudflare,
descarga el archivo de vuelta por internet y comprueba que coincide byte a byte.
Necesita red, así que está desactivada por defecto:

```bash
FTE_E2E=1 go test ./internal/app/ -run EndToEnd -v -timeout 5m
```

## Notas de distribución

- El `.app` va firmado de forma **ad-hoc**, no con un Developer ID de Apple. Gatekeeper puede bloquearlo en otros equipos. Para distribución pública hace
  falta Developer ID y notarización. Consulta [la guía de macOS](MACOS_RELEASE.md).
- En Windows hace falta el runtime de **WebView2**, ya presente en Windows 11 y
  en Windows 10 actualizado.
- `cloudflared` no se empaqueta: la app lo descarga de la release oficial de
  Cloudflare la primera vez, y lo guarda en el directorio de configuración del
  usuario.

## Entrega macOS y Linux 1.0.1

El build genera `dist/File Transfer Easy.app`, `dist/FileTransferEasy-1.0.1.dmg`
y `dist/FileTransferEasy-1.0.1.dmg.sha256`. Compatible desde macOS 13, universal
Apple Silicon + Intel. El script comprueba ambas arquitecturas, el plist, la
firma ad hoc y la integridad del DMG antes de entregar los artefactos.

La interfaz usa tipografía del sistema, tema claro/oscuro automático y assets
locales. Añadir contenido crea el enlace automáticamente. Puedes cancelar la
preparación, reintentar y seguir usando el enlace LAN si falla la conexión
pública. El enlace público solo se puede copiar cuando su DNS está verificado y
el túnel sigue activo. Los atajos son ⌘O (archivos) y ⇧⌘O (carpetas) en macOS.

Los archivos y la actividad pertenecen a la sesión actual: no se restauran al
salir. Quitar un archivo de la lista no lo borra del disco. Mantén el equipo
encendido y la app abierta mientras compartes; cerrar la ventana la deja en la
barra de menús, y «Salir» detiene la sesión.

Linux incluye paquetes `.deb` y `.tar.gz` para AMD64 y ARM64. Instalación,
dependencias y compilación: [LINUX_RELEASE.md](LINUX_RELEASE.md). Los controles
realizados y pendientes están en [VALIDATION.md](VALIDATION.md).
