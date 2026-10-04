# File Transfer Easy

Para la app actual de escritorio, el build universal de macOS y los paquetes de Linux, usa la
[versión Go](go-app/README.md). La documentación siguiente corresponde a la
versión original en Python.

App de escritorio para compartir archivos desde tu ordenador con una web cuidada para clientes y un panel admin integrado en una ventana nativa. Publica con Tailscale Funnel, Cloudflare Quick Tunnel o un puerto propio.

El runtime es single-file: el HTML, CSS y JavaScript del panel admin y de la web pública viven embebidos dentro de `app.py`. No hacen falta carpetas `templates/` ni `static/` para ejecutar o compilar.

## Uso rápido

Para usuarios finales, genera el ejecutable:

```powershell
.\build.ps1
```

El resultado queda en:

```text
dist\FileTransferEasy.exe
```

Ese `.exe` se abre con doble clic y muestra el panel admin nativo (Qt) dentro de la propia app, sin navegador ni WebView para el host. La URL publica del cliente es aparte y no contiene controles admin.

Para usar sin compilar:

```text
iniciar.bat
```

También puedes ejecutar:

```powershell
python app.py
```

También puedes ejecutar directamente el `.py` en macOS o Linux:

```bash
python3 app.py
```

Si falta Flask, Waitress o PySide6, el script prepara un entorno Python del
usuario, instala las dependencias y vuelve a arrancar dentro de él. Funciona
también al copiar solo `app.py`: las versiones necesarias están declaradas en
el script. Si encuentra `requirements.txt` junto al archivo, usa ese archivo.
Las siguientes ejecuciones reutilizan el entorno y los paquetes instalados.

El entorno automático se guarda en `~/FileTransferEasy/python/` en macOS/Linux
y en `%LOCALAPPDATA%\FileTransferEasy\python\` en Windows. Si ejecutas la app
desde un entorno virtual propio, instala ahí los paquetes que falten. La primera
instalación necesita conexión a Internet y una instalación de Python con `venv`.

En versiones recientes de macOS, la app prepara automáticamente una ruta de compatibilidad para el plugin gráfico Cocoa antes de crear la ventana.

Si la instalación falla, se conserva el diagnóstico de pip en el mensaje de error.

La UI host/admin funciona solo con `PySide6` (sin `tkinter`) y es totalmente nativa Qt.
El idioma de la app host (EN/ES) controla también los textos de la web pública.

## Funciones

- Panel nativo Qt organizado en cuatro áreas: archivos, publicación, seguridad y actividad.
- Configuración opcional guardada en `%LOCALAPPDATA%\FileTransferEasy\settings.json`.
- Seleccionar archivos individuales desde diálogos nativos.
- Seleccionar carpetas completas, con opción de incluir subcarpetas.
- Proteger toda la sesión con contraseña global.
- Proteger archivos concretos con contraseña propia.
- Proteger carpetas completas; sus archivos heredan la clave salvo override por archivo.
- Expirar el enlace por minutos, limitar descargas por archivo y bloquear/desbloquear IPs.
- Exigir contraseña global para subir aunque la página pública sea visible.
- Permitir o bloquear subidas de clientes en vivo.
- Elegir carpeta donde se guardan las subidas.
- Descargar archivos individuales o ZIP con los archivos desbloqueados.
- Ver descargas activas con IP, progreso real, velocidad y estado.
- Anular descargas activas desde el panel admin.
- Menú contextual en archivos, carpetas y descargas.
- Guardar historial persistente en SQLite y exportar CSV.

Por defecto la app pregunta cada vez. Si marcas **Guardar esta configuración y no preguntarme la próxima vez**, guarda rutas, modo de publicación, puertos, subidas y opciones avanzadas no secretas. No guarda contraseñas, hashes ni tokens.

## Publicación

Modos disponibles:

- **Tailscale Funnel**: usa `tailscale funnel --https=<443|8443|10000> http://127.0.0.1:<puerto>`.
- **Cloudflare Quick Tunnel**: usa `cloudflared tunnel --url http://127.0.0.1:<puerto>`.
- **Puerto propio**: muestra una URL LAN/local; el router y el firewall quedan a cargo del host.

Si Cloudflare está seleccionado y `cloudflared` no existe, la app intenta descargarlo en `%LOCALAPPDATA%\FileTransferEasy\bin`. Si falla, intenta `winget`:

```powershell
winget install --id Cloudflare.cloudflared --accept-package-agreements --accept-source-agreements
```

## Seguridad

La URL pública incluye un token único de sesión. Si activas una contraseña global, el cliente debe introducirla antes de ver la página, subir archivos o descargar ZIP.

Las subidas se validan siempre en el servidor. Aunque un cliente tenga una página antigua abierta, si el host desactiva subidas, `POST /upload` devuelve `403` y no guarda nada.

El servidor público solo registra rutas `/s/<token>...`. Las rutas `/admin/<token>...` existen únicamente en el servidor admin local, separado del puerto publicado por Tailscale, Cloudflare o puerto propio.

Las contraseñas se guardan como hash PBKDF2-SHA256 en memoria mientras la app está abierta. No se guardan en texto plano.

## Estadísticas

La base de datos local se guarda en:

```text
%LOCALAPPDATA%\FileTransferEasy\file_transfer_easy.db
```

La app registra subidas, descargas, ZIP, IP detectada, user-agent, bytes enviados y estado. La IP se obtiene en modo best-effort desde `CF-Connecting-IP`, `X-Forwarded-For`, `X-Real-IP` o la IP directa.

## Desarrollo

Instala dependencias:

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

Ejecuta pruebas:

```powershell
python -m unittest discover -s tests
```
