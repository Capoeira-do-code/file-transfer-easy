package app

import (
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/access"
)

func TestReceiveOnlyShareStaysAvailableWithoutFiles(t *testing.T) {
	a, _ := lifecycleFixture(t)
	a.Store.Clear()
	enabled := true
	if err := a.UpdateSettings(access.SettingsPatch{UploadsEnabled: &enabled}); err != nil {
		t.Fatal(err)
	}
	if err := a.StartShare(); err != nil {
		t.Fatal(err)
	}
	if a.Status() != StatusLive {
		t.Fatal(a.Snapshot().Share)
	}
	if err := a.ClearItems(); err != nil {
		t.Fatal(err)
	}
	if a.Status() != StatusLive {
		t.Fatal("clearing files stopped receive-only sharing")
	}
	file := filepath.Join(t.TempDir(), "received.txt")
	if err := os.WriteFile(file, []byte("received test bytes"), 0600); err != nil {
		t.Fatal(err)
	}
	token := a.ShareToken()
	if err := a.ReceivePaths([]string{file}); err != nil {
		t.Fatal(err)
	}
	if len(a.Snapshot().Items) != 1 || a.ShareToken() != token {
		t.Fatal("receiving a file replaced the current share")
	}
}

type requestNative struct {
	noopNative
	shows atomic.Int32
}

func (n *requestNative) ShowWindow() { n.shows.Add(1) }

func TestAccessRequestBringsWindowForwardOnlyOncePerPendingRequest(t *testing.T) {
	native := &requestNative{}
	a := New(t.TempDir(), native, testAssets())
	defer a.Close()
	request := access.Request{ID: "test-request", Status: "pending"}
	a.notifyAccessRequests([]access.Request{request})
	a.notifyAccessRequests([]access.Request{request})
	if native.shows.Load() != 1 {
		t.Fatal("same request repeatedly interrupted the host")
	}
	request.ID = "another-request"
	a.notifyAccessRequests([]access.Request{request})
	if native.shows.Load() != 2 {
		t.Fatal("new request did not bring the app forward")
	}
	request.Status = "approved"
	a.notifyAccessRequests([]access.Request{request})
	if native.shows.Load() != 2 {
		t.Fatal("approved request interrupted the host")
	}
}

func TestBrokenSavedSettingsCannotSilentlyOpenAnUnprotectedShare(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "access.json"), []byte("broken test configuration"), 0600); err != nil {
		t.Fatal(err)
	}
	a := New(dir, &noopNative{}, testAssets())
	defer a.Close()
	if err := a.StartShare(); err == nil || !strings.Contains(err.Error(), "configuración") {
		t.Fatalf("sharing did not fail closed with the configuration error: %v", err)
	}
	theme := "light"
	if err := a.UpdateSettings(access.SettingsPatch{Theme: &theme}); err != nil {
		t.Fatal(err)
	}
	if a.Status() != StatusIdle {
		t.Fatal("saving replacement settings did not clear configuration error")
	}
}

func TestSettingsSurviveAppRestart(t *testing.T) {
	dir := t.TempDir()
	a := New(dir, &noopNative{}, testAssets())
	theme, password, name := "dark", "private-setting-password", "Ana"
	if err := a.UpdateSettings(access.SettingsPatch{Theme: &theme, PagePassword: &password}); err != nil {
		t.Fatal(err)
	}
	if err := a.Access.SetName("192.0.2.15", name); err != nil {
		t.Fatal(err)
	}
	a.Close()
	b := New(dir, &noopNative{}, testAssets())
	defer b.Close()
	if b.Snapshot().Settings.Theme != theme || !b.Snapshot().Settings.PagePasswordSet || b.Access.Name("192.0.2.15") != name {
		t.Fatal("saved settings/visitor names were lost on restart")
	}
}

func TestRememberedNameAppearsOnFutureAccessRequests(t *testing.T) {
	a := New(t.TempDir(), &noopNative{}, testAssets())
	defer a.Close()
	const ip = "192.0.2.75"
	if err := a.Access.SetName(ip, "Equipo de Ana"); err != nil {
		t.Fatal(err)
	}
	require := true
	if err := a.UpdateSettings(access.SettingsPatch{RequireApproval: &require}); err != nil {
		t.Fatal(err)
	}
	session, err := a.Access.NewSession(ip)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := a.Access.Access(session, ip, "test browser", "Nombre del navegador", "", false); err != nil {
		t.Fatal(err)
	}
	requests := a.Snapshot().Requests
	if len(requests) != 1 || requests[0].Name != "Equipo de Ana" {
		t.Fatalf("remembered name was lost or replaced by an unverified browser name: %+v", requests)
	}
}

func TestStoppingAndRestartingShareRevokesBrowserApproval(t *testing.T) {
	a, _ := lifecycleFixture(t)
	require := true
	if err := a.UpdateSettings(access.SettingsPatch{RequireApproval: &require}); err != nil {
		t.Fatal(err)
	}
	if err := a.StartShare(); err != nil {
		t.Fatal(err)
	}
	const ip = "192.0.2.49"
	id, err := a.Access.NewSession(ip)
	if err != nil {
		t.Fatal(err)
	}
	decision, err := a.Access.Access(id, ip, "test browser", "", "", false)
	if err != nil {
		t.Fatal(err)
	}
	if err := a.Access.Respond(decision.RequestID, true); err != nil {
		t.Fatal(err)
	}
	if a.Access.Authorize(id, ip).Status != "allowed" {
		t.Fatal("initial approval failed")
	}
	if err := a.StopShare(); err != nil {
		t.Fatal(err)
	}
	if a.Access.ValidSession(id, ip) || len(a.Access.Requests()) != 0 {
		t.Fatal("old browser permissions survived share stop")
	}
	if err := a.StartShare(); err != nil {
		t.Fatal(err)
	}
	if a.Access.Authorize(id, ip).Status == "allowed" {
		t.Fatal("replayed old cookie bypassed approval on new share")
	}
}
