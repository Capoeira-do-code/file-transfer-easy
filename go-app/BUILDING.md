# Compilaciones de escritorio

La versión predeterminada está en `VERSION`. `VERSION=X.Y.Z` permite
sobrescribirla. Los scripts generan artefactos de producción y checksums SHA-256
en `dist/`, conservando otras versiones presentes.

| Plataforma | Comando desde `go-app` | Entrega |
|---|---|---|
| Windows AMD64 | `./scripts/build-windows.ps1` | EXE portable versionado; instalador si encuentra NSIS |
| macOS universal | `bash scripts/build-macos.sh` | DMG para Apple Silicon e Intel, con firma ad hoc |
| Linux nativo | `bash scripts/build-linux.sh` | DEB y TAR.GZ de la arquitectura del host |
| Linux AMD64 + ARM64 desde Windows/macOS | `python scripts/build-linux-cross.py` | DEB y TAR.GZ de ambas arquitecturas |

Se necesitan Go de `go.mod` y Python 3. macOS requiere Xcode Command Line Tools,
incluidos SDK, clang, lipo, iconutil, hdiutil y codesign. Linux nativo requiere
GTK3, WebKitGTK 4.1, X11 y pkg-config. Windows usa WebView2 del sistema.

El cross-build de Linux descarga Zig 0.15.2 y paquetes SDK de Debian 12 con sus
checksums. En Windows extrae pkgconf 3.0.10 dentro de la caché, sin instalar
software en el sistema. `--prepare-only` prepara herramientas sin compilar.
`ARCH=amd64` o `ARCH=arm64` selecciona una arquitectura; `FTE_CROSS_CACHE`
cambia la caché. En Unix debe existir pkg-config. Los binarios apuntan a glibc
2.36, GTK3 y WebKitGTK 4.1; no incluyen esas bibliotecas.

En PowerShell puede usarse `-Version 1.1.0 -SkipInstaller`. El EXE portable se
llama `FileTransferEasy-<versión>-windows-amd64.exe`; no sobrescribe otro EXE
que esté abierto. El instalador se llama `FileTransferEasy-Setup-<versión>.exe`.

El workflow `.github/workflows/build.yml` construye los tres sistemas. Su
ejecución manual acepta una versión y produce artefactos conservados 14 días.
Sólo un tag `v*` activa la publicación de una release; una compilación manual
no publica. macOS usa el runner `macos-15`; `macos-14` ya no está disponible.

Para preparar una copia exacta del código local, incluidos cambios sin commit:

```text
python scripts/package-source.py --check-only
python scripts/package-source.py
```

El ZIP contiene únicamente fuentes y assets de escritorio, el workflow y un
`BUILD-SNAPSHOT.json` con hashes de cada archivo. Excluye `.git`, cachés,
configuración de usuario y ejecutables anteriores. No sube archivos ni cambia
repositorios remotos. Los scripts `.sh` usan finales de línea LF en el ZIP para
poder ejecutarse también al extraerlo en macOS o Linux.

## Compilación macOS desde este equipo Windows

`scripts/macos-ci.py prepare` crea únicamente una carpeta local revisable a
partir del ZIP de fuentes. Sustituye el workflow de esa copia por
`scripts/macos-artifacts.yml`: pruebas Ubuntu (vet y race), pruebas Swift y
nativas de macOS, DMG universal y checksum, sin jobs de publicación ni builds
repetidos de Windows/Linux.

```text
python scripts/macos-ci.py prepare --source dist/FileTransferEasy-1.1.0-source.zip --directory dist/macos-ci-1.1.0
```

Tras elegir y autorizar el destino, `submit` puede crear un repositorio privado
nuevo (`--mode private`) o una rama pública nueva (`--mode public-branch`). La
ruta debe indicarse explícitamente; no se toca `main` en modo público. La
autenticación usa Git Credential Manager en memoria y no guarda tokens.

```text
python scripts/macos-ci.py submit --directory dist/macos-ci-1.1.0 --mode private --repository USUARIO/REPOSITORIO-PRIVADO-NUEVO --branch main
python scripts/macos-ci.py status --directory dist/macos-ci-1.1.0
python scripts/macos-ci.py download --directory dist/macos-ci-1.1.0 --output dist
```

Para la rama pública autorizada, el envío se realiza con
`--mode public-branch --repository Capoeira-do-code/file-transfer-easy
--branch build/1.1.0-macos-...`. Una nueva carpeta preparada puede actualizar
esa misma rama con `--update-branch`: sólo permite avanzar su historial, sin
force push. `cancel` detiene únicamente la corrida del snapshot indicado cuando
otra corrección lo deja obsoleto.

`status` es de lectura. `download` comprueba SHA-256 y la firma de formato UDIF
del DMG. El helper conserva el repositorio o la rama remotos; no crea tags, PRs
ni releases y nunca los borra automáticamente.
