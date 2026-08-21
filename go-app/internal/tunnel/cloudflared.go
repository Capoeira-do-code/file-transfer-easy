// Package tunnel locates, installs and runs cloudflared so a local port can be
// reached from the internet through a Cloudflare quick tunnel.
package tunnel

import (
	"archive/tar"
	"compress/gzip"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"time"
)

const releaseBase = "https://github.com/cloudflare/cloudflared/releases/latest/download"

// downloadTimeout bounds the cloudflared download so a stalled network cannot
// hang the share flow forever.
const downloadTimeout = 3 * time.Minute

// Logf receives human-readable progress messages.
type Logf func(level, format string, args ...any)

// binaryName is the filename cached inside the app's bin directory. The .exe
// suffix is harmless on Unix and keeps one name across platforms.
const binaryName = "cloudflared.exe"

// Locate finds an existing cloudflared: first on PATH, then next to the running
// executable, then in the app's own bin directory.
func Locate(binDir string) string {
	if path, err := exec.LookPath("cloudflared"); err == nil {
		return path
	}

	var candidates []string
	if self, err := os.Executable(); err == nil {
		dir := filepath.Dir(self)
		candidates = append(candidates,
			filepath.Join(dir, "cloudflared"),
			filepath.Join(dir, "cloudflared.exe"),
		)
	}
	candidates = append(candidates,
		filepath.Join(binDir, "cloudflared"),
		filepath.Join(binDir, binaryName),
	)

	for _, candidate := range candidates {
		if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
			return candidate
		}
	}
	return ""
}

// downloadURL returns the official asset for this platform and whether it is a
// gzipped tar rather than a bare binary.
func downloadURL() (string, bool, error) {
	arch := "amd64"
	if runtime.GOARCH == "arm64" {
		arch = "arm64"
	}

	switch runtime.GOOS {
	case "windows":
		// Cloudflare does not ship a windows/arm64 build; the amd64 one runs
		// fine under emulation on ARM devices.
		return releaseBase + "/cloudflared-windows-amd64.exe", false, nil
	case "darwin":
		return fmt.Sprintf("%s/cloudflared-darwin-%s.tgz", releaseBase, arch), true, nil
	case "linux":
		return fmt.Sprintf("%s/cloudflared-linux-%s", releaseBase, arch), false, nil
	default:
		return "", false, fmt.Errorf("plataforma no soportada: %s", runtime.GOOS)
	}
}

// Ensure returns a usable cloudflared path, downloading the official release
// into binDir when it is not already installed.
func Ensure(binDir string, log Logf) (string, error) {
	if existing := Locate(binDir); existing != "" {
		return existing, nil
	}
	if log != nil {
		log("info", "Descargando cloudflared desde la versión oficial de Cloudflare…")
	}

	url, isArchive, err := downloadURL()
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(binDir, 0o755); err != nil {
		return "", fmt.Errorf("no se pudo crear %s: %w", binDir, err)
	}
	target := filepath.Join(binDir, binaryName)

	if err := download(url, target, isArchive); err != nil {
		os.Remove(target)
		return "", fmt.Errorf("no se pudo descargar cloudflared: %w", err)
	}
	if err := os.Chmod(target, 0o755); err != nil {
		return "", fmt.Errorf("no se pudo dar permisos a cloudflared: %w", err)
	}
	if log != nil {
		log("info", "cloudflared instalado en "+target)
	}
	return target, nil
}

func download(url, target string, isArchive bool) error {
	client := &http.Client{Timeout: downloadTimeout}
	response, err := client.Get(url)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("respuesta %s al descargar %s", response.Status, url)
	}

	if isArchive {
		return extractBinary(response.Body, target)
	}

	file, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o755)
	if err != nil {
		return err
	}
	if _, err := io.Copy(file, response.Body); err != nil {
		file.Close()
		return err
	}
	return file.Close()
}

// extractBinary pulls the single cloudflared binary out of the macOS .tgz.
func extractBinary(body io.Reader, target string) error {
	gz, err := gzip.NewReader(body)
	if err != nil {
		return err
	}
	defer gz.Close()

	archive := tar.NewReader(gz)
	for {
		header, err := archive.Next()
		if errors.Is(err, io.EOF) {
			return errors.New("el paquete oficial no contiene el binario cloudflared")
		}
		if err != nil {
			return err
		}
		if header.Typeflag != tar.TypeReg || filepath.Base(header.Name) != "cloudflared" {
			continue
		}
		file, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o755)
		if err != nil {
			return err
		}
		if _, err := io.Copy(file, archive); err != nil {
			file.Close()
			return err
		}
		return file.Close()
	}
}
