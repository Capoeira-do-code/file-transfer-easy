# File Transfer Easy

App de escritorio para compartir archivos desde tu ordenador con una web bonita para clientes y un panel admin integrado en una ventana nativa. Publica con Tailscale Funnel, Cloudflare Quick Tunnel o un puerto propio.

El runtime es single-file: el HTML, CSS y JavaScript del panel admin y de la web publica viven embebidos dentro de `app.py`. No hacen falta carpetas `templates/` ni `static/` para ejecutar o compilar.

## Uso Rapido

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

Tambien puedes ejecutar:

```powershell
python app.py
```

Si faltan dependencias, la app intenta instalarlas automaticamente desde `requirements.txt`.

La UI host/admin funciona solo con `PySide6` (sin `tkinter`) y es totalmente nativa Qt.
El idioma de la app host (EN/ES) controla tambien los textos de la web publica.

## Funciones

- Panel admin HTML integrado con asistente de 4 pasos: que compartir, acceso, publicacion y enlace listo.
- Configuracion opcional guardada en `%LOCALAPPDATA%\FileTransferEasy\settings.json`.
- Seleccionar archivos individuales desde dialogos nativos.
- Seleccionar carpetas completas, con opcion de incluir subcarpetas.
- Proteger toda la sesion con contrasena global.
- Proteger archivos concretos con contrasena propia.
- Proteger carpetas completas; sus archivos heredan la clave salvo override por archivo.
- Expirar enlace por minutos, limitar descargas por archivo y bloquear/desbloquear IPs.
- Exigir contrasena global para subir aunque la pagina publica sea visible.
- Permitir o bloquear subidas de clientes en vivo.
- Elegir carpeta donde se guardan las subidas.
- Descargar archivos individuales o ZIP con los archivos desbloqueados.
- Ver descargas activas con IP, progreso, velocidad y estado.
- Anular descargas activas desde el panel admin.
- Menu contextual en archivos, carpetas y descargas.
- Guardar historial persistente en SQLite y exportar CSV.

Por defecto la app pregunta cada vez. Si marcas **Guardar esta configuracion y no preguntarme la proxima vez**, guarda rutas, modo de publicacion, puertos, subidas y opciones avanzadas no secretas. No guarda contrasenas, hashes ni tokens.

## Publicacion

Modos disponibles:

- **Tailscale Funnel**: usa `tailscale funnel --https=<443|8443|10000> http://127.0.0.1:<puerto>`.
- **Cloudflare Quick Tunnel**: usa `cloudflared tunnel --url http://127.0.0.1:<puerto>`.
- **Puerto propio**: muestra URL LAN/local; router y firewall quedan a cargo del host.

Si Cloudflare esta seleccionado y `cloudflared` no existe, la app intenta descargarlo en `%LOCALAPPDATA%\FileTransferEasy\bin`. Si falla, intenta `winget`:

```powershell
winget install --id Cloudflare.cloudflared --accept-package-agreements --accept-source-agreements
```

## Seguridad

La URL publica incluye un token unico de sesion. Si activas contrasena global, el cliente debe introducirla antes de ver la pagina, subir archivos o descargar ZIP.

Las subidas se validan siempre en el servidor. Aunque un cliente tenga una pagina antigua abierta, si el host desactiva subidas, `POST /upload` devuelve `403` y no guarda nada.

El servidor publico solo registra rutas `/s/<token>...`. Las rutas `/admin/<token>...` existen unicamente en el servidor admin local, separado del puerto publicado por Tailscale, Cloudflare o puerto propio.

Las contrasenas se guardan como hash PBKDF2-SHA256 en memoria mientras la app esta abierta. No se guardan en texto plano.

## Estadisticas

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
