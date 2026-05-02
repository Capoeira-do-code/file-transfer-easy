# File Transfer Easy

App de escritorio en Python para compartir archivos desde tu ordenador con una web local cuidada. Puede publicar con Tailscale Funnel, Cloudflare Quick Tunnel o un puerto propio, y permite subidas si el host lo activa.

## Uso Rapido

Para usuarios finales, genera el ejecutable:

```powershell
.\build.ps1
```

El resultado queda en:

```text
dist\FileTransferEasy.exe
```

Ese `.exe` se abre con doble clic y no necesita instalar paquetes Python en el equipo final.

Para usar el proyecto sin compilar, abre con doble clic:

```text
iniciar.bat
```

El launcher crea `.venv`, instala dependencias y abre la app. Tambien puedes ejecutar:

```powershell
python app.py
```

Si faltan dependencias, `app.py` intenta instalarlas automaticamente desde `requirements.txt`.

## Funciones

- Seleccionar archivos individuales.
- Seleccionar una carpeta compartida, con opcion de incluir subcarpetas.
- Permitir o bloquear subidas de clientes.
- Elegir carpeta donde se guardan las subidas.
- Proteger toda la sesion con contrasena global.
- Proteger archivos concretos con contrasena propia.
- Descargar archivos individuales o ZIP con los archivos desbloqueados.
- Ver descargas activas con IP, progreso, velocidad y estado.
- Anular descargas activas desde la app.
- Guardar historial persistente en SQLite con IP, archivo, bytes y estado.
- Exportar historial a CSV.

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

La URL incluye un token unico de sesion. Si activas contrasena global, el cliente debe introducirla antes de ver la pagina, subir archivos o descargar ZIP. Si un archivo tiene contrasena propia, aparece en la lista pero no se descarga hasta desbloquearlo.

Las contrasenas se guardan como hash PBKDF2-SHA256 en memoria mientras la app esta abierta. No se guardan en texto plano.

## Estadisticas

La base de datos local se guarda en:

```text
%LOCALAPPDATA%\FileTransferEasy\file_transfer_easy.db
```

La app registra subidas, descargas, ZIP, IP detectada, user-agent, bytes enviados y estado. La IP se obtiene en modo best-effort desde `CF-Connecting-IP`, `X-Forwarded-For`, `X-Real-IP` o la IP directa. Detras de tuneles o proxies puede aparecer la IP del proxy si no se reenvia la IP real.

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
