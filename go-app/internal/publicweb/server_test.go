package publicweb

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"testing/fstest"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/activity"
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/core"
)

const testToken = "token-de-prueba"

func testAssets() fstest.MapFS {
	return fstest.MapFS{
		"index.html": {Data: []byte(`<script>window.__FTE_BASE__="__FTE_BASE__";</script>`)},
		"style.css":  {Data: []byte("body{}")},
		"app.js":     {Data: []byte("// app")},
	}
}

// newFixture builds a server over a small shared set and returns it with the
// store and tracker behind it.
func newFixture(t *testing.T) (http.Handler, *core.Store, *activity.Tracker, string) {
	t.Helper()

	root := t.TempDir()
	write := func(rel, body string) {
		path := filepath.Join(root, rel)
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	write("informe.txt", "contenido del informe")
	write("fotos/a.txt", "foto a")
	write("fotos/b.txt", "foto b")

	store := core.NewStore(nil)
	if _, err := store.AddPaths([]string{
		filepath.Join(root, "informe.txt"),
		filepath.Join(root, "fotos"),
	}); err != nil {
		t.Fatal(err)
	}

	tracker := activity.New(nil)
	return New(testAssets(), store, tracker, testToken), store, tracker, root
}

func get(t *testing.T, handler http.Handler, path string) *httptest.ResponseRecorder {
	t.Helper()
	request := httptest.NewRequest(http.MethodGet, path, nil)
	request.Header.Set("User-Agent", "Mozilla/5.0 (Macintosh) Chrome/120")
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	return recorder
}

func TestPageSubstitutesBaseWithoutBreakingIdentifier(t *testing.T) {
	handler, _, _, _ := newFixture(t)

	response := get(t, handler, "/s/"+testToken+"/")
	if response.Code != http.StatusOK {
		t.Fatalf("esperaba 200, hubo %d", response.Code)
	}

	body := response.Body.String()
	want := `window.__FTE_BASE__="/s/` + testToken + `"`
	if !strings.Contains(body, want) {
		t.Errorf("la página no define la base correctamente:\n%s", body)
	}
	if strings.Contains(body, `"__FTE_BASE__"`) {
		t.Error("el marcador no se sustituyó")
	}
}

func TestBareShareLinkRedirectsToTrailingSlash(t *testing.T) {
	handler, _, _, _ := newFixture(t)

	// Without this the page's relative asset links would resolve to /s/assets/.
	response := get(t, handler, "/s/"+testToken)
	if response.Code != http.StatusFound {
		t.Fatalf("esperaba 302, hubo %d", response.Code)
	}
	if location := response.Header().Get("Location"); location != "/s/"+testToken+"/" {
		t.Errorf("redirección incorrecta: %q", location)
	}
}

func TestAssetsAreServed(t *testing.T) {
	handler, _, _, _ := newFixture(t)

	response := get(t, handler, "/s/"+testToken+"/assets/style.css")
	if response.Code != http.StatusOK {
		t.Fatalf("esperaba 200, hubo %d", response.Code)
	}
	if contentType := response.Header().Get("Content-Type"); !strings.Contains(contentType, "css") {
		t.Errorf("tipo de contenido inesperado: %q", contentType)
	}
}

func TestWrongTokenIsRejected(t *testing.T) {
	handler, _, _, _ := newFixture(t)

	cases := []struct {
		path string
		want int
	}{
		{"/s/otro/api/manifest", http.StatusGone},
		{"/s/otro/", http.StatusGone},
		{"/s/otro/download/loquesea", http.StatusGone},
		{"/s/otro/zip", http.StatusGone},
		{"/s/otro/assets/style.css", http.StatusNotFound},
	}
	for _, testCase := range cases {
		if got := get(t, handler, testCase.path).Code; got != testCase.want {
			t.Errorf("%s: esperaba %d, hubo %d", testCase.path, testCase.want, got)
		}
	}
}

func TestManifestListsEverything(t *testing.T) {
	handler, _, _, _ := newFixture(t)

	response := get(t, handler, "/s/"+testToken+"/api/manifest")
	if response.Code != http.StatusOK {
		t.Fatalf("esperaba 200, hubo %d", response.Code)
	}

	var payload manifest
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatalf("manifiesto ilegible: %v", err)
	}
	if payload.Totals.Files != 3 {
		t.Errorf("esperaba 3 archivos, hay %d", payload.Totals.Files)
	}
	if len(payload.Folders) != 1 || payload.Folders[0].Name != "fotos" {
		t.Errorf("carpetas inesperadas: %+v", payload.Folders)
	}

	// Loose files come first and carry no folder; folder files name their owner.
	if payload.Files[0].Folder != "" {
		t.Errorf("el primer archivo debería ser suelto, tiene carpeta %q", payload.Files[0].Folder)
	}
	var grouped int
	for _, file := range payload.Files {
		if file.Folder == "fotos" {
			grouped++
		}
	}
	if grouped != 2 {
		t.Errorf("esperaba 2 archivos en la carpeta, hay %d", grouped)
	}
}

func TestDownloadStreamsFileAndCounts(t *testing.T) {
	handler, store, tracker, _ := newFixture(t)

	var target core.Entry
	for _, entry := range store.Entries() {
		if entry.Name == "informe.txt" {
			target = entry
		}
	}
	if target.ID == "" {
		t.Fatal("no se encontró el archivo de prueba")
	}

	response := get(t, handler, "/s/"+testToken+"/download/"+target.ID)
	if response.Code != http.StatusOK {
		t.Fatalf("esperaba 200, hubo %d", response.Code)
	}
	if body := response.Body.String(); body != "contenido del informe" {
		t.Errorf("contenido inesperado: %q", body)
	}

	disposition := response.Header().Get("Content-Disposition")
	if !strings.Contains(disposition, `filename="informe.txt"`) {
		t.Errorf("cabecera de descarga inesperada: %q", disposition)
	}

	_, transfers, stats, _ := tracker.Snapshot()
	if stats.Downloads != 1 {
		t.Errorf("esperaba 1 descarga contabilizada, hay %d", stats.Downloads)
	}
	if len(transfers) != 1 || transfers[0].Status != "done" {
		t.Errorf("la transferencia no se cerró como completada: %+v", transfers)
	}
}

func TestDownloadOfUnknownFileIs404(t *testing.T) {
	handler, _, _, _ := newFixture(t)

	if got := get(t, handler, "/s/"+testToken+"/download/inventada").Code; got != http.StatusNotFound {
		t.Errorf("esperaba 404, hubo %d", got)
	}
}

func TestZipContainsEveryFile(t *testing.T) {
	handler, _, _, _ := newFixture(t)

	response := get(t, handler, "/s/"+testToken+"/zip")
	if response.Code != http.StatusOK {
		t.Fatalf("esperaba 200, hubo %d", response.Code)
	}

	raw := response.Body.Bytes()
	archive, err := zip.NewReader(bytes.NewReader(raw), int64(len(raw)))
	if err != nil {
		t.Fatalf("el zip no es válido: %v", err)
	}

	found := make(map[string]string, len(archive.File))
	for _, file := range archive.File {
		reader, err := file.Open()
		if err != nil {
			t.Fatalf("no se pudo abrir %s: %v", file.Name, err)
		}
		content, err := io.ReadAll(reader)
		reader.Close()
		if err != nil {
			t.Fatal(err)
		}
		found[file.Name] = string(content)
	}

	want := map[string]string{
		"informe.txt": "contenido del informe",
		"fotos/a.txt": "foto a",
		"fotos/b.txt": "foto b",
	}
	if len(found) != len(want) {
		t.Fatalf("esperaba %d entradas, hay %d: %v", len(want), len(found), found)
	}
	for name, content := range want {
		if found[name] != content {
			t.Errorf("%s: esperaba %q, hay %q", name, content, found[name])
		}
	}
}

func TestPingRegistersVisitor(t *testing.T) {
	handler, _, tracker, _ := newFixture(t)

	request := httptest.NewRequest(http.MethodPost, "/s/"+testToken+"/ping", strings.NewReader("{}"))
	request.RemoteAddr = "127.0.0.1:44000"
	request.Header.Set("CF-Connecting-IP", "203.0.113.9")
	request.Header.Set("User-Agent", "Mozilla/5.0 (iPhone) Safari/605")
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("esperaba 200, hubo %d", recorder.Code)
	}

	visitors, _, _, _ := tracker.Snapshot()
	if len(visitors) != 1 {
		t.Fatalf("esperaba 1 visitante, hay %d", len(visitors))
	}
	if visitors[0].IP != "203.0.113.9" {
		t.Errorf("IP incorrecta: %q", visitors[0].IP)
	}
	if visitors[0].Label != "Safari · iPhone" {
		t.Errorf("etiqueta inesperada: %q", visitors[0].Label)
	}
	if !visitors[0].Online() {
		t.Error("un visitante recién visto debería estar en línea")
	}
}

func TestClientIPPrefersCloudflareHeader(t *testing.T) {
	cases := []struct {
		name    string
		headers map[string]string
		remote  string
		want    string
	}{
		{"cloudflare gana", map[string]string{
			"CF-Connecting-IP": "1.1.1.1",
			"X-Forwarded-For":  "2.2.2.2",
		}, "127.0.0.1:100", "1.1.1.1"},
		{"forwarded-for toma el primero", map[string]string{
			"X-Forwarded-For": "2.2.2.2, 4.4.4.4",
		}, "[::1]:100", "2.2.2.2"},
		{"LAN no puede suplantar una IP", map[string]string{"CF-Connecting-IP": "1.1.1.1", "X-Forwarded-For": "2.2.2.2"}, "192.0.2.9:100", "192.0.2.9"},
		{"sin cabeceras usa la conexión", nil, "3.3.3.3:100", "3.3.3.3"},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			request := httptest.NewRequest(http.MethodGet, "/", nil)
			request.RemoteAddr = testCase.remote
			for key, value := range testCase.headers {
				request.Header.Set(key, value)
			}
			if got := clientIP(request); got != testCase.want {
				t.Errorf("esperaba %q, hubo %q", testCase.want, got)
			}
		})
	}
}

func TestContentDispositionHandlesUnicode(t *testing.T) {
	got := contentDisposition("informe año ñ.pdf")

	if !strings.Contains(got, `filename="informe a_o _.pdf"`) {
		t.Errorf("falta el nombre ASCII de reserva: %q", got)
	}
	if !strings.Contains(got, "filename*=UTF-8''") {
		t.Errorf("falta la forma codificada: %q", got)
	}
}
