package app

import (
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"testing/fstest"
	"time"
)

// noopNative satisfies the Native interface without a desktop behind it.
type noopNative struct{ clipboard, opened string }

func (n *noopNative) PickFiles() ([]string, error)   { return nil, nil }
func (n *noopNative) PickFolder() (string, error)    { return "", nil }
func (n *noopNative) Reveal(string) error            { return nil }
func (n *noopNative) SetClipboard(text string) bool  { n.clipboard = text; return true }
func (n *noopNative) MinimiseWindow()                {}
func (n *noopNative) HideWindow()                    {}
func (n *noopNative) ShowWindow()                    {}
func (n *noopNative) OpenInBrowser(url string) error { n.opened = url; return nil }
func (n *noopNative) StateChanged(Summary)           {}

func testAssets() fstest.MapFS {
	return fstest.MapFS{
		"index.html": {Data: []byte(`<script>window.__FTE_BASE__="__FTE_BASE__";</script>`)},
	}
}

// TestEndToEndOverCloudflare drives the real thing: it starts the public
// server, opens a genuine Cloudflare quick tunnel, then fetches the share page
// and downloads a file back over the public internet.
//
// It needs network access and downloads cloudflared on first run, so it only
// runs when asked for:
//
//	FTE_E2E=1 go test ./internal/app/ -run EndToEnd -v -timeout 5m
func TestEndToEndOverCloudflare(t *testing.T) {
	if os.Getenv("FTE_E2E") != "1" {
		t.Skip("prueba de extremo a extremo desactivada (usa FTE_E2E=1)")
	}

	// cloudflared is cached here between runs so repeat runs are quick.
	dataDir := filepath.Join(os.TempDir(), "fte-e2e")
	if err := os.MkdirAll(dataDir, 0o755); err != nil {
		t.Fatal(err)
	}

	native := &noopNative{}
	core := New(dataDir, native, testAssets())
	defer core.Close()

	// Something to actually share.
	work := t.TempDir()
	payload := strings.Repeat("file transfer easy\n", 500)
	file := filepath.Join(work, "informe.txt")
	if err := os.WriteFile(file, []byte(payload), 0o644); err != nil {
		t.Fatal(err)
	}

	// AddPaths triggers the share automatically, which is the real flow, but
	// the test drives it explicitly so failures are attributable.
	if _, err := core.Store.AddPaths([]string{file}); err != nil {
		t.Fatal(err)
	}
	if err := core.StartShare(); err != nil {
		t.Fatalf("no se pudo abrir el túnel: %v", err)
	}
	t.Cleanup(func() { core.StopShare() })

	url := core.PublicURL()
	if url == "" {
		t.Fatal("el túnel no devolvió ninguna URL")
	}
	t.Logf("enlace público: %s", url)

	if core.Status() != StatusLive {
		t.Fatalf("estado inesperado: %s", core.Status())
	}

	client := &http.Client{Timeout: 45 * time.Second}

	// Cloudflare needs a moment to route a brand new hostname.
	var manifest map[string]any
	deadline := time.Now().Add(60 * time.Second)
	for time.Now().Before(deadline) {
		body, status := fetch(t, client, url+"/api/manifest")
		if status == http.StatusOK {
			manifest = decodeJSON(t, body)
			break
		}
		time.Sleep(3 * time.Second)
	}
	if manifest == nil {
		t.Fatal("el manifiesto nunca respondió a través del túnel")
	}

	files, _ := manifest["files"].([]any)
	if len(files) != 1 {
		t.Fatalf("esperaba 1 archivo en el manifiesto, hay %d", len(files))
	}
	entry, _ := files[0].(map[string]any)
	id, _ := entry["id"].(string)
	if name, _ := entry["name"].(string); name != "informe.txt" {
		t.Errorf("nombre inesperado: %q", name)
	}

	// Download it back and compare byte for byte.
	body, status := fetch(t, client, url+"/download/"+id)
	if status != http.StatusOK {
		t.Fatalf("la descarga devolvió %d", status)
	}
	if string(body) != payload {
		t.Errorf("el contenido descargado no coincide (%d bytes frente a %d)", len(body), len(payload))
	}

	// The host side must have noticed the visitor and the completed download.
	visitors, transfers, stats, _ := core.Tracker.Snapshot()
	if len(visitors) == 0 {
		t.Error("no se registró ningún visitante")
	}
	if stats.Downloads != 1 {
		t.Errorf("esperaba 1 descarga contabilizada, hay %d", stats.Downloads)
	}
	if len(transfers) == 0 || transfers[0].Status != "done" {
		t.Errorf("la transferencia no quedó como completada: %+v", transfers)
	}

	// The zip route must work through the tunnel too.
	body, status = fetch(t, client, url+"/zip")
	if status != http.StatusOK {
		t.Fatalf("el zip devolvió %d", status)
	}
	if len(body) < 100 {
		t.Errorf("el zip parece vacío (%d bytes)", len(body))
	}

	// Copying the link goes through the native layer.
	if err := core.CopyLink(); err != nil {
		t.Errorf("CopyLink: %v", err)
	}
	if native.clipboard != url {
		t.Errorf("el portapapeles tiene %q", native.clipboard)
	}

	// Stopping must retire the link.
	if err := core.StopShare(); err != nil {
		t.Fatalf("StopShare: %v", err)
	}
	if core.PublicURL() != "" {
		t.Error("la URL debería quedar vacía tras detener")
	}
}

func fetch(t *testing.T, client *http.Client, url string) ([]byte, int) {
	t.Helper()
	response, err := client.Get(url)
	if err != nil {
		t.Logf("petición fallida a %s: %v", url, err)
		return nil, 0
	}
	defer response.Body.Close()

	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Logf("lectura fallida de %s: %v", url, err)
		return nil, response.StatusCode
	}
	return body, response.StatusCode
}

func decodeJSON(t *testing.T, body []byte) map[string]any {
	t.Helper()
	var out map[string]any
	if err := json.Unmarshal(body, &out); err != nil {
		t.Fatalf("respuesta ilegible: %v\n%s", err, body)
	}
	return out
}
