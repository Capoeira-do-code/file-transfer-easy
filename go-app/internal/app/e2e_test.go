package app

import (
	"bytes"
	"encoding/json"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/cookiejar"
	neturl "net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"testing/fstest"
	"time"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/access"
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
// downloads a file back over the public internet, then verifies HTTPS cookie
// authorization, host approval, file unlocking and multipart receiving.
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
	// Only cloudflared is shared between runs. Reset policy before and after
	// the test so a failed previous run cannot retain a test password or point
	// the next run at a directory that t.TempDir has already removed.
	light, empty, title := "light", "", "Archivos compartidos"
	disabled, maximum := false, int64(100)
	defaultUploads := filepath.Join(dataDir, "Uploads")
	reset := access.SettingsPatch{Theme: &light, PageTitle: &title, ErrorMessage: &empty,
		PagePassword: &empty, RequireApproval: &disabled, UploadsEnabled: &disabled,
		UploadDir: &defaultUploads, MaxUploadMB: &maximum}
	if err := core.UpdateSettings(reset); err != nil {
		core.Close()
		t.Fatalf("no se pudo preparar la configuración de prueba: %v", err)
	}
	defer func() {
		if err := core.UpdateSettings(reset); err != nil {
			t.Errorf("no se pudo restablecer la configuración de prueba: %v", err)
		}
		core.Close()
	}()
	for _, visitor := range core.Access.History() {
		if visitor.Blocked {
			if err := core.Access.SetBlocked(visitor.IP, false); err != nil {
				t.Fatal(err)
			}
		}
	}

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

	jar, err := cookiejar.New(nil)
	if err != nil {
		t.Fatal(err)
	}
	client := &http.Client{Timeout: 30 * time.Second, Jar: jar}

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
	t.Log("descarga y ZIP verificados a través de Cloudflare")

	// Exercise the same HTTPS origin, HttpOnly cookie and access policy that
	// a real recipient browser uses. Everything sent is synthetic test data.
	parsed, err := neturl.Parse(url)
	if err != nil {
		t.Fatal(err)
	}
	origin := parsed.Scheme + "://" + parsed.Host
	send := func(method, path string, body io.Reader, contentType string) ([]byte, int, []*http.Cookie) {
		t.Helper()
		request, err := http.NewRequest(method, url+path, body)
		if err != nil {
			t.Fatal(err)
		}
		request.Header.Set("Origin", origin)
		if contentType != "" {
			request.Header.Set("Content-Type", contentType)
		}
		response, err := client.Do(request)
		if err != nil {
			t.Fatalf("%s %s a través de Cloudflare: %v", method, path, err)
		}
		defer response.Body.Close()
		payload, err := io.ReadAll(response.Body)
		if err != nil {
			t.Fatalf("lectura de %s: %v", path, err)
		}
		return payload, response.StatusCode, response.Cookies()
	}
	post := func(path string, value any) ([]byte, int) {
		t.Helper()
		encoded, err := json.Marshal(value)
		if err != nil {
			t.Fatal(err)
		}
		body, code, _ := send(http.MethodPost, path, bytes.NewReader(encoded), "application/json")
		return body, code
	}

	// Configure both gates before login so the recipient authorizes against
	// one consistent policy throughout the network round trip.
	owner := core.Store.Items()[0].ID
	if err := core.SetItemPassword(owner, "synthetic file password"); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if err := core.Access.SetItemPassword(owner, ""); err != nil {
			t.Errorf("no se pudo limpiar la contraseña de archivo de prueba: %v", err)
		}
	}()

	dark, pagePassword, enabled := "dark", "synthetic page password", true
	uploadDir := filepath.Join(work, "received")
	if err := core.UpdateSettings(access.SettingsPatch{Theme: &dark, PagePassword: &pagePassword,
		RequireApproval: &enabled, UploadsEnabled: &enabled, UploadDir: &uploadDir}); err != nil {
		t.Fatal(err)
	}
	body, status, cookies := send(http.MethodGet, "/api/access", nil, "")
	if status != http.StatusOK || decodeJSON(t, body)["status"] != "password" {
		t.Fatalf("la página protegida no exigió contraseña: HTTP %d", status)
	}
	secureCookie := false
	for _, cookie := range cookies {
		if cookie.Name == "fte_session" {
			secureCookie = cookie.HttpOnly && cookie.Secure && cookie.SameSite == http.SameSiteStrictMode
		}
	}
	if !secureCookie {
		t.Fatal("la sesión HTTPS no recibió una cookie Secure, HttpOnly y SameSite=Strict")
	}
	if _, code, _ := send(http.MethodGet, "/api/manifest", nil, ""); code != http.StatusUnauthorized {
		t.Fatalf("el manifiesto sin contraseña devolvió HTTP %d", code)
	}
	body, status = post("/api/access", map[string]string{"password": "incorrect synthetic password"})
	passwordError, _ := decodeJSON(t, body)["error"].(string)
	if status != http.StatusUnauthorized || passwordError == "" {
		t.Fatalf("la contraseña incorrecta no devolvió un motivo concreto: HTTP %d", status)
	}
	body, status = post("/api/access", map[string]string{"password": pagePassword, "name": "E2E recipient"})
	decision := decodeJSON(t, body)
	if status != http.StatusOK || decision["status"] != "pending" {
		t.Fatalf("la contraseña correcta no quedó pendiente de aprobación: HTTP %d, estado %v", status, decision["status"])
	}
	requestID, _ := decision["requestId"].(string)
	if requestID == "" {
		t.Fatal("la solicitud pendiente no tiene identificador")
	}
	if _, code, _ := send(http.MethodGet, "/api/manifest", nil, ""); code != http.StatusForbidden {
		t.Fatalf("el manifiesto pendiente de aprobación devolvió HTTP %d", code)
	}
	if err := core.Access.Respond(requestID, true); err != nil {
		t.Fatal(err)
	}
	body, status, _ = send(http.MethodGet, "/api/access", nil, "")
	if status != http.StatusOK || decodeJSON(t, body)["status"] != "allowed" {
		t.Fatalf("la aprobación no habilitó la sesión existente: HTTP %d", status)
	}
	body, status, _ = send(http.MethodGet, "/api/manifest", nil, "")
	manifest = decodeJSON(t, body)
	settings, _ := manifest["settings"].(map[string]any)
	if status != http.StatusOK || settings["theme"] != "dark" || settings["uploadsEnabled"] != true {
		t.Fatalf("el manifiesto autorizado no sincronizó el tema y la recepción: HTTP %d", status)
	}
	t.Log("cookie HTTPS, contraseña, aprobación y tema sincronizado verificados")

	if _, code, _ := send(http.MethodGet, "/download/"+id, nil, ""); code != http.StatusForbidden {
		t.Fatalf("el archivo protegido se descargó sin desbloquear: HTTP %d", code)
	}
	body, status = post("/api/unlock", map[string]string{"id": id, "password": "synthetic file password"})
	if status != http.StatusOK || decodeJSON(t, body)["ok"] != true {
		t.Fatalf("no se pudo desbloquear el archivo por HTTPS: HTTP %d", status)
	}
	body, status, _ = send(http.MethodGet, "/download/"+id, nil, "")
	if status != http.StatusOK || string(body) != payload {
		t.Fatalf("el archivo desbloqueado no coincide: HTTP %d, %d bytes", status, len(body))
	}
	t.Log("contraseña de archivo y descarga desbloqueada verificadas")

	var upload bytes.Buffer
	multipartBody := multipart.NewWriter(&upload)
	uploadName := "recibido con ñ.txt"
	uploadPayload := strings.Repeat("synthetic upload over Cloudflare\n", 100)
	part, err := multipartBody.CreateFormFile("files", uploadName)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := io.WriteString(part, uploadPayload); err != nil {
		t.Fatal(err)
	}
	if err := multipartBody.Close(); err != nil {
		t.Fatal(err)
	}
	body, status, _ = send(http.MethodPost, "/upload", &upload, multipartBody.FormDataContentType())
	if status != http.StatusOK || decodeJSON(t, body)["ok"] != true {
		t.Fatalf("la subida multipart falló: HTTP %d, motivo %v", status, decodeJSON(t, body)["error"])
	}
	saved, err := os.ReadFile(filepath.Join(uploadDir, uploadName))
	if err != nil {
		t.Fatal(err)
	}
	if string(saved) != uploadPayload {
		t.Fatalf("el contenido recibido no coincide (%d bytes)", len(saved))
	}
	_, transfers, stats, _ = core.Tracker.Snapshot()
	uploadRecorded := false
	for _, transfer := range transfers {
		if transfer.Kind == "upload" && transfer.Status == "done" && transfer.Bytes == int64(len(saved)) {
			uploadRecorded = true
		}
	}
	if !uploadRecorded || stats.Downloads < 2 {
		t.Fatalf("la actividad no registró la subida y las descargas: upload=%t, downloads=%d", uploadRecorded, stats.Downloads)
	}
	t.Logf("subida multipart y bytes en disco verificados (%d bytes sintéticos)", len(saved))

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
