package uiserver

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/app"
)

func TestSettingsAndVisitorEndpointsRequireDesktopToken(t *testing.T) {
	server, _, _ := newFixture(t)
	for _, route := range []string{"/api/settings", "/api/settings/upload-folder", "/api/items/password", "/api/visitors/block", "/api/visitors/name", "/api/history/delete", "/api/requests/respond"} {
		if got := do(t, server, http.MethodPost, route, "{}", false).Code; got != http.StatusUnauthorized {
			t.Errorf("POST %s without desktop token = %d", route, got)
		}
	}
}

func TestSettingsRejectsOversizedOrMultipleJSONDocuments(t *testing.T) {
	server, core, _ := newFixture(t)
	for _, body := range []string{`{"theme":"dark"} {"theme":"light"}`, `{"pageTitle":"` + strings.Repeat("a", 70<<10) + `"}`} {
		response := do(t, server, http.MethodPost, "/api/settings", body, true)
		if !strings.Contains(response.Body.String(), `"ok":false`) || core.Access.Settings().Theme != "light" {
			t.Fatalf("invalid request changed settings: %s", response.Body.String())
		}
	}
}

func TestSettingsAndPasswordsReachDesktopStateWithoutSecrets(t *testing.T) {
	server, core, _ := newFixture(t)
	response := do(t, server, http.MethodPost, "/api/settings", `{"theme":"dark","pagePassword":"test-page-secret","requireApproval":true,"errorMessage":"Contacta conmigo si no puedes entrar"}`, true)
	if !strings.Contains(response.Body.String(), `"ok":true`) {
		t.Fatal(response.Body.String())
	}
	file := filepath.Join(t.TempDir(), "private.txt")
	if err := os.WriteFile(file, []byte("test only"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := core.Store.AddPaths([]string{file}); err != nil {
		t.Fatal(err)
	}
	id := core.Store.Items()[0].ID
	body, _ := json.Marshal(map[string]string{"id": id, "password": "test-file-secret"})
	response = do(t, server, http.MethodPost, "/api/items/password", string(body), true)
	if !strings.Contains(response.Body.String(), `"ok":true`) {
		t.Fatal(response.Body.String())
	}
	response = do(t, server, http.MethodGet, "/api/state", "", true)
	var state app.State
	if err := json.Unmarshal(response.Body.Bytes(), &state); err != nil {
		t.Fatal(err)
	}
	if state.Settings.Theme != "dark" || !state.Settings.PagePasswordSet || !state.Settings.RequireApproval || !state.Items[0].Protected {
		t.Fatalf("settings/protection not represented in state: %+v", state)
	}
	if strings.Contains(response.Body.String(), "test-page-secret") || strings.Contains(response.Body.String(), "test-file-secret") {
		t.Fatal("desktop state leaked a configured password")
	}
	response = do(t, server, http.MethodPost, "/api/settings", `{"theme":"light"}`, true)
	if !core.Access.Settings().PagePasswordSet {
		t.Fatal("unrelated settings change cleared page password")
	}
	response = do(t, server, http.MethodPost, "/api/settings", `{"pagePassword":""}`, true)
	if core.Access.Settings().PagePasswordSet {
		t.Fatal("explicit empty password did not remove protection")
	}
}

func TestBlockingVisitorCancelsTheirActiveTransfer(t *testing.T) {
	server, core, _ := newFixture(t)
	const ip = "192.0.2.42"
	core.Tracker.Seen(ip, "test browser")
	transfer := core.Tracker.StartTransfer("file", "test.txt", ip, 100)
	response := do(t, server, http.MethodPost, "/api/visitors/block", `{"ip":"192.0.2.42","blocked":true}`, true)
	if !strings.Contains(response.Body.String(), `"ok":true`) {
		t.Fatal(response.Body.String())
	}
	select {
	case <-transfer.Cancelled():
	default:
		t.Fatal("blocking did not cancel the active transfer")
	}
	if !core.Access.IsBlocked(ip) {
		t.Fatal("IP was not blocked")
	}
	response = do(t, server, http.MethodPost, "/api/visitors/name", `{"ip":"192.0.2.42","name":"Equipo de Ana"}`, true)
	if core.Access.Name(ip) != "Equipo de Ana" {
		t.Fatal(response.Body.String())
	}
	response = do(t, server, http.MethodPost, "/api/visitors/block", `{"ip":"192.0.2.42","blocked":false}`, true)
	if core.Access.IsBlocked(ip) {
		t.Fatal("IP remained blocked")
	}
}

func TestUploadDirectoryPickerDoesNotChangeSettingsUntilSaved(t *testing.T) {
	server, core, native := newFixture(t)
	before := core.Access.Settings().UploadDir
	native.folder = t.TempDir()
	response := do(t, server, http.MethodPost, "/api/settings/upload-folder", "", true)
	var result struct {
		OK   bool   `json:"ok"`
		Path string `json:"path"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if !result.OK || result.Path != native.folder {
		t.Fatal(response.Body.String())
	}
	if core.Access.Settings().UploadDir != before {
		t.Fatal("picker saved an unapplied setting")
	}
}
