package uiserver

import (
	"bufio"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"testing/fstest"
	"time"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/app"
)

const testToken = "token-de-interfaz"

// stubNative stands in for the Wails desktop layer.
type stubNative struct {
	files     []string
	folder    string
	clipboard string
	revealed  string
	opened    string
	hidden    bool
}

func (s *stubNative) PickFiles() ([]string, error)   { return s.files, nil }
func (s *stubNative) PickFolder() (string, error)    { return s.folder, nil }
func (s *stubNative) Reveal(path string) error       { s.revealed = path; return nil }
func (s *stubNative) SetClipboard(text string) bool  { s.clipboard = text; return true }
func (s *stubNative) MinimiseWindow()                {}
func (s *stubNative) HideWindow()                    { s.hidden = true }
func (s *stubNative) ShowWindow()                    {}
func (s *stubNative) OpenInBrowser(url string) error { s.opened = url; return nil }
func (s *stubNative) StateChanged(app.Summary)       {}

func newFixture(t *testing.T) (*Server, *app.App, *stubNative) {
	t.Helper()

	assets := fstest.MapFS{
		"index.html": {Data: []byte(`<script>window.__FTE_TOKEN__="__FTE_TOKEN__";</script>`)},
		"app.css":    {Data: []byte("body{}")},
		"app.js":     {Data: []byte("// ui")},
	}

	native := &stubNative{}
	core := app.New(t.TempDir(), native, fstest.MapFS{})
	t.Cleanup(core.Close)

	return New(core, assets, testToken), core, native
}

func request(method, path string, body string, withToken bool) *http.Request {
	var reader *strings.Reader
	if body == "" {
		reader = strings.NewReader("")
	} else {
		reader = strings.NewReader(body)
	}
	req := httptest.NewRequest(method, path, reader)
	if withToken {
		req.Header.Set("X-FTE-Token", testToken)
	}
	return req
}

func do(t *testing.T, server *Server, method, path, body string, withToken bool) *httptest.ResponseRecorder {
	t.Helper()
	recorder := httptest.NewRecorder()
	server.ServeHTTP(recorder, request(method, path, body, withToken))
	return recorder
}

func TestUnauthorisedRequestsAreRejected(t *testing.T) {
	server, _, _ := newFixture(t)

	paths := []string{"/api/state", "/api/qr.png"}
	for _, path := range paths {
		if got := do(t, server, http.MethodGet, path, "", false).Code; got != http.StatusUnauthorized {
			t.Errorf("GET %s sin token: esperaba 401, hubo %d", path, got)
		}
	}
	if got := do(t, server, http.MethodPost, "/api/items/clear", "", false).Code; got != http.StatusUnauthorized {
		t.Errorf("POST sin token: esperaba 401, hubo %d", got)
	}
}

func TestIndexInjectsTokenWithoutBreakingIdentifier(t *testing.T) {
	server, _, _ := newFixture(t)

	// The page itself is not token-guarded: it is what receives the token.
	response := do(t, server, http.MethodGet, "/", "", false)
	if response.Code != http.StatusOK {
		t.Fatalf("esperaba 200, hubo %d", response.Code)
	}

	body := response.Body.String()
	if !strings.Contains(body, `window.__FTE_TOKEN__="`+testToken+`"`) {
		t.Errorf("el token no se inyectó correctamente: %s", body)
	}
	if strings.Contains(body, `"__FTE_TOKEN__"`) {
		t.Error("el marcador sigue presente")
	}
}

func TestAssetsAreServedFromRoot(t *testing.T) {
	server, _, _ := newFixture(t)

	// index.html links these by bare relative path.
	for _, name := range []string{"/app.css", "/app.js"} {
		response := do(t, server, http.MethodGet, name, "", false)
		if response.Code != http.StatusOK {
			t.Errorf("GET %s: esperaba 200, hubo %d", name, response.Code)
		}
	}
	if got := do(t, server, http.MethodGet, "/no-existe.css", "", false).Code; got != http.StatusNotFound {
		t.Errorf("un asset inexistente debería dar 404, dio %d", got)
	}
}

func TestStateReflectsSharedItems(t *testing.T) {
	server, core, _ := newFixture(t)

	file := filepath.Join(t.TempDir(), "nota.txt")
	if err := os.WriteFile(file, []byte("hola"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := core.Store.AddPaths([]string{file}); err != nil {
		t.Fatal(err)
	}

	response := do(t, server, http.MethodGet, "/api/state", "", true)
	if response.Code != http.StatusOK {
		t.Fatalf("esperaba 200, hubo %d", response.Code)
	}

	var state app.State
	if err := json.Unmarshal(response.Body.Bytes(), &state); err != nil {
		t.Fatalf("estado ilegible: %v", err)
	}
	if len(state.Items) != 1 || state.Items[0].Name != "nota.txt" {
		t.Fatalf("elementos inesperados: %+v", state.Items)
	}
	if state.Items[0].SizeText != "4 B" {
		t.Errorf("tamaño formateado inesperado: %q", state.Items[0].SizeText)
	}
	if state.Totals.Files != 1 {
		t.Errorf("totales incorrectos: %+v", state.Totals)
	}
	// Nothing is shared yet, so there must be no link on offer.
	if state.Share.Status != string(app.StatusIdle) || state.Share.URL != "" {
		t.Errorf("estado de compartición inesperado: %+v", state.Share)
	}
}

func TestActionEnvelopeReportsFailure(t *testing.T) {
	server, _, _ := newFixture(t)

	response := do(t, server, http.MethodPost, "/api/items/reveal", `{"id":"inventada"}`, true)
	if response.Code != http.StatusOK {
		t.Fatalf("las acciones responden 200 con el error en el cuerpo, hubo %d", response.Code)
	}

	var payload struct {
		OK    bool   `json:"ok"`
		Error string `json:"error"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload.OK {
		t.Error("revelar una id inexistente debería fallar")
	}
	if payload.Error == "" {
		t.Error("falta el mensaje de error")
	}
}

func TestRevealPassesPathToNativeLayer(t *testing.T) {
	server, core, native := newFixture(t)

	file := filepath.Join(t.TempDir(), "nota.txt")
	if err := os.WriteFile(file, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	core.Store.AddPaths([]string{file})
	id := core.Store.Items()[0].ID

	response := do(t, server, http.MethodPost, "/api/items/reveal", `{"id":"`+id+`"}`, true)
	if response.Code != http.StatusOK {
		t.Fatalf("esperaba 200, hubo %d", response.Code)
	}
	if native.revealed == "" {
		t.Fatal("no se llamó a la capa nativa")
	}
	if filepath.Base(native.revealed) != "nota.txt" {
		t.Errorf("ruta inesperada: %q", native.revealed)
	}
}

func TestCopyLinkFailsWithoutAShare(t *testing.T) {
	server, _, native := newFixture(t)

	response := do(t, server, http.MethodPost, "/api/share/copy", "", true)
	var payload struct {
		OK bool `json:"ok"`
	}
	json.Unmarshal(response.Body.Bytes(), &payload)

	if payload.OK {
		t.Error("no debería poder copiarse un enlace inexistente")
	}
	if native.clipboard != "" {
		t.Error("el portapapeles no debería haberse tocado")
	}
}

func TestOpenPublicPageFailsWithoutAShare(t *testing.T) {
	server, _, native := newFixture(t)

	response := do(t, server, http.MethodPost, "/api/share/open", "", true)
	var payload struct {
		OK bool `json:"ok"`
	}
	json.Unmarshal(response.Body.Bytes(), &payload)

	if payload.OK {
		t.Error("no debería abrirse una página que todavía no existe")
	}
	if native.opened != "" {
		t.Errorf("no debería haberse abierto nada, se abrió %q", native.opened)
	}
}

func TestWindowHideReachesNativeLayer(t *testing.T) {
	server, _, native := newFixture(t)

	do(t, server, http.MethodPost, "/api/window/hide", "", true)
	if !native.hidden {
		t.Error("la ventana debería haberse ocultado")
	}
}

func TestQRIsUnavailableUntilLive(t *testing.T) {
	server, _, _ := newFixture(t)

	if got := do(t, server, http.MethodGet, "/api/qr.png", "", true).Code; got != http.StatusNotFound {
		t.Errorf("sin enlace el QR debería dar 404, dio %d", got)
	}
}

func TestEventStreamSendsInitialState(t *testing.T) {
	server, core, _ := newFixture(t)

	live := httptest.NewServer(server)
	defer live.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// EventSource cannot set headers, so the token rides in the query string.
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, live.URL+"/api/events?t="+testToken, nil)
	if err != nil {
		t.Fatal(err)
	}
	response, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()

	if contentType := response.Header.Get("Content-Type"); contentType != "text/event-stream" {
		t.Fatalf("tipo de contenido inesperado: %q", contentType)
	}

	reader := bufio.NewReader(response.Body)
	event, err := reader.ReadString('\n')
	if err != nil {
		t.Fatal(err)
	}
	if strings.TrimSpace(event) != "event: state" {
		t.Fatalf("primer evento inesperado: %q", event)
	}

	data, err := reader.ReadString('\n')
	if err != nil {
		t.Fatal(err)
	}
	payload := strings.TrimPrefix(strings.TrimSpace(data), "data: ")

	var state app.State
	if err := json.Unmarshal([]byte(payload), &state); err != nil {
		t.Fatalf("el primer fotograma no es estado válido: %v\n%s", err, payload)
	}
	if state.Share.StatusText == "" {
		t.Error("el estado debería traer una etiqueta legible")
	}

	// A change must reach the already-open stream.
	file := filepath.Join(t.TempDir(), "nuevo.txt")
	os.WriteFile(file, []byte("x"), 0o644)
	core.Store.AddPaths([]string{file})

	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		line, err := reader.ReadString('\n')
		if err != nil {
			t.Fatalf("el flujo se cortó: %v", err)
		}
		if !strings.HasPrefix(line, "data: ") {
			continue
		}
		var pushed app.State
		if err := json.Unmarshal([]byte(strings.TrimPrefix(strings.TrimSpace(line), "data: ")), &pushed); err != nil {
			continue
		}
		if len(pushed.Items) == 1 && pushed.Items[0].Name == "nuevo.txt" {
			return
		}
	}
	t.Fatal("el cambio no llegó por el flujo de eventos")
}

func TestEventStreamRejectsBadToken(t *testing.T) {
	server, _, _ := newFixture(t)

	if got := do(t, server, http.MethodGet, "/api/events?t=incorrecto", "", false).Code; got != http.StatusUnauthorized {
		t.Errorf("esperaba 401, hubo %d", got)
	}
}
