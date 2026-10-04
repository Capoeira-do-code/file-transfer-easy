# macOS 1.0.1

Entrega de prueba para macOS 13 o superior. El ejecutable contiene arm64 y
x86_64, y la app usa WKWebView del sistema. No requiere instalar Python ni npm.

## Instalar y usar

1. Cierra la versión anterior con «Salir». Abre `FileTransferEasy-1.0.1.dmg` y arrastra la app a Aplicaciones.
2. Abre File Transfer Easy y añade archivos o carpetas, o arrástralos a la ventana, al Dock o al icono de la barra de menús.
3. Espera a «Compartiendo», copia el enlace y envíalo. El destinatario descarga
   desde su navegador, sin cuenta.

La primera sesión necesita descargar cloudflared de la fuente oficial de
Cloudflare. Necesitas conexión para compartir por Internet. Si el túnel falla,
el acceso «En la misma red» permite abrir la página desde la red local.

Mantén el equipo encendido y la app abierta. Puedes ocultar la ventana y volver
desde su icono de la barra de menús. «Dejar de compartir» cancela las descargas;
«Salir» detiene el túnel y el servidor. Retirar archivos de la lista conserva
los originales. Quien tenga el enlace puede descargar: esta versión no añade
contraseñas ni caducidad programada.

Este paquete tiene firma **ad hoc** y **no está notarizado**. La firma se valida
en el build, pero no acredita un Developer ID. Gatekeeper puede bloquearlo en
otros equipos; esta entrega sirve para pruebas. No desactives Gatekeeper.

Comprueba el checksum desde la carpeta que contiene el DMG:

```bash
shasum -a 256 -c FileTransferEasy-1.0.1.dmg.sha256
```

## Reproducir el build

Instala la versión de Go indicada en `go.mod` y las Command Line Tools de Xcode.
Desde `go-app`:

```bash
go vet ./internal/...
go test -race ./internal/...
swift scripts/test-ui.swift
./scripts/test-native-macos.sh
VERSION=1.0.1 ./scripts/build-macos.sh
```

El script acepta `ARCH=universal` (por defecto), `arm64` o `amd64`, y una versión
numérica `X.Y.Z`. macOS mínimo: `MACOSX_DEPLOYMENT_TARGET=13.0`. Un build fallido
conserva la app anterior y elimina su directorio temporal. Los diagnósticos del
compilador y la firma se muestran completos.

## Distribución pública posterior

Requiere una identidad **Developer ID Application** y credenciales de
notarización configuradas en tu llavero. No se guardan credenciales en el repo.
Sigue la [guía de Apple para notarizar software](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
y su [flujo por línea de comandos](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow).

La secuencia de release será:

1. Firmar la app con Developer ID, timestamp y hardened runtime; validar la firma.
2. Crear un ZIP con `ditto`, enviarlo mediante `xcrun notarytool submit --wait`
   usando un perfil de llavero y comprobar que Apple lo acepta.
3. Adjuntar el ticket a la app con `xcrun stapler staple` y validarlo.
4. Crear el DMG con esa app, firmarlo, enviarlo a notarización y adjuntar su ticket.
5. Validar app y DMG con `stapler validate`, comprobar Gatekeeper con
   `spctl --assess --type execute` y regenerar el checksum del DMG final.
6. Probar el paquete descargado en un Mac sin las credenciales de desarrollo.

Esta ruta no se ha ejecutado: la entrega solicitada usa firma ad hoc.
La arquitectura Intel se comprueba en el binario universal; su ejecución nativa
necesita un Mac Intel. El mínimo macOS 13 se declara y se comprueba en los binarios;
esta máquina valida ejecución en su versión instalada de macOS.

Los controles realizados y los pendientes de esta entrega están registrados en
[VALIDATION.md](VALIDATION.md).
