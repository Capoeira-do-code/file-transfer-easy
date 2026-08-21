# File Transfer Easy — versión Go

Envía archivos entre dispositivos que no están en la misma red.

App de escritorio para macOS y Windows. Arrastras un archivo o una carpeta a la
ventana, la app genera un enlace público, y ves en vivo quién lo abre y qué se
está descargando. Se queda en la bandeja del sistema, así que puedes cerrar la
ventana y seguir compartiendo.

Reescritura en Go de la app original en Python/PySide6, que sigue en la raíz del
repositorio. Un único binario sin dependencias de runtime.

---

## Cómo funciona

- **Ventana**: [Wails v3](https://wails.io) muestra una webview nativa
  (WKWebView en macOS, WebView2 en Windows).
- **Interfaz**: HTML, CSS y JavaScript planos. Sin npm, sin frameworks, sin CDN.
- **Enlace público**: un túnel rápido de Cloudflare mediante `cloudflared`, que
  la app descarga sola la primera vez que compartes algo.
- **Sin nube**: los archivos nunca se suben a ningún sitio. El túnel apunta a un
  servidor local que lee directamente del disco.

Hay **dos servidores HTTP** y la separación es deliberada:

| | Escucha en | Quién entra | Qué expone |
|---|---|---|---|
| Interfaz | `127.0.0.1`, puerto aleatorio | solo la ventana, con un token por ejecución | todo el control de la app |
| Público | todas las interfaces, puerto aleatorio | el túnel y la red local | solo lectura, bajo `/s/<token>` |

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

Necesitas Go 1.24 o superior. En macOS, las Command Line Tools de Xcode.

```bash
cd go-app

# macOS: paquete .app universal + .dmg en dist/
./scripts/build-macos.sh

# Solo tu arquitectura: la mitad de tiempo, ideal mientras desarrollas
ARCH=arm64 ./scripts/build-macos.sh

# Windows: .exe, también desde macOS o Linux
./scripts/build-windows.sh
```

El `.dmg` queda en `go-app/dist/FileTransferEasy-<versión>.dmg`. Para fijar la
versión, `VERSION=1.2.0 ./scripts/build-macos.sh`.

El `.exe` no necesita cgo ni una máquina Windows: Wails v3 habla con WebView2
mediante bindings en Go puro. El instalador NSIS sí hay que construirlo en
Windows, con `scripts\build-windows.ps1`.

Para publicar una release con ambos artefactos, empuja un tag y deja que actúe
[el workflow](../.github/workflows/build.yml):

```bash
git tag v1.0.0 && git push origin v1.0.0
```

### Desarrollo

```bash
go run .                       # arranca la app
go test ./internal/...         # pruebas
go test -race ./internal/...   # con detector de carreras
go run ./cmd/genicons          # regenera todos los iconos
```

La interfaz se sirve por HTTP normal, así que también puedes abrirla en un
navegador: arranca la app, mira el puerto que abre en `127.0.0.1` y pega la URL.
El token va inyectado en la propia página.

---

## Añadir archivos con la ventana oculta

- **macOS**: suelta archivos sobre el **icono del Dock**. El paquete declara
  `CFBundleDocumentTypes`, así que el Dock acepta cualquier archivo o carpeta y
  la app los añade al momento.
- **Windows**: suelta archivos sobre el `.exe` o sobre un acceso directo. Se
  lanza una segunda instancia cuyos argumentos se reenvían a la que ya corre.
- **Desde la bandeja**: el menú tiene "Añadir archivos…" y "Añadir carpeta…".

Soltar directamente sobre el icono de la barra de menús no es posible: ni Wails
ni las plataformas exponen ese punto de entrada.

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

- El `.app` va firmado de forma **ad-hoc**, no con un Developer ID de Apple. La
  primera vez hay que abrirlo con clic derecho › Abrir. Para distribuirlo de
  verdad hace falta una cuenta de desarrollador y notarización.
- En Windows hace falta el runtime de **WebView2**, ya presente en Windows 11 y
  en Windows 10 actualizado.
- `cloudflared` no se empaqueta: la app lo descarga de la release oficial de
  Cloudflare la primera vez, y lo guarda en el directorio de configuración del
  usuario.
