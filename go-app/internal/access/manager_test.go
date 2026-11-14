package access

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

func value[T any](v T) *T { return &v }
func manager(t *testing.T) *Manager {
	t.Helper()
	m, err := New(t.TempDir(), nil)
	if err != nil {
		t.Fatal(err)
	}
	return m
}

func TestSettingsPasswordsAndAllHistorySurviveRestart(t *testing.T) {
	dir := t.TempDir()
	m, err := New(dir, nil)
	if err != nil {
		t.Fatal(err)
	}
	if got := m.Settings(); got.Theme != "light" || got.UploadsEnabled || got.MaxUploadMB != 1024 || got.UploadDir != filepath.Join(dir, "Uploads") {
		t.Fatalf("bad defaults: %+v", got)
	}
	if err := m.UpdateSettings(SettingsPatch{Theme: value("dark"), UploadsEnabled: value(true), PagePassword: value("page secret"), RequireApproval: value(true)}); err != nil {
		t.Fatal(err)
	}
	if err := m.SetItemPassword("folder", "folder secret"); err != nil {
		t.Fatal(err)
	}
	for i := 1; i <= 75; i++ {
		ip := "192.0.2." + strconv.Itoa(i)
		if err := m.Observe(ip, "Browser", true); err != nil {
			t.Fatal(err)
		}
	}
	if err := m.SetName("192.0.2.1", "Cliente principal"); err != nil {
		t.Fatal(err)
	}
	if err := m.RecordDownload("192.0.2.1", 123); err != nil {
		t.Fatal(err)
	}
	if err := m.SetBlocked("192.0.2.2", true); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(filepath.Join(dir, "access.json"))
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), "page secret") || strings.Contains(string(raw), "folder secret") {
		t.Fatal("plaintext password persisted")
	}
	restored, err := New(dir, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(restored.History()) != 75 || restored.Name("192.0.2.1") != "Cliente principal" || !restored.IsBlocked("192.0.2.2") || !restored.ItemProtected("folder") {
		t.Fatal("settings/history did not persist")
	}
	for _, v := range restored.History() {
		if v.IP == "192.0.2.1" && (v.Visits != 1 || v.Downloads != 1 || v.Bytes != 123) {
			t.Fatalf("bad history: %+v", v)
		}
	}
	id, err := restored.NewSession("192.0.2.1")
	if err != nil {
		t.Fatal(err)
	}
	d, err := restored.Access(id, "192.0.2.1", "Browser", "", "page secret", true)
	if err != nil || d.Status != "pending" {
		t.Fatalf("password was not restored: %+v %v", d, err)
	}
}

func TestPendingRequestNameUpdatesReuseIDAndDoNotRenameHostHistory(t *testing.T) {
	m := manager(t)
	if err := m.UpdateSettings(SettingsPatch{RequireApproval: value(true)}); err != nil {
		t.Fatal(err)
	}
	if err := m.SetName("192.0.2.1", "Nombre del propietario"); err != nil {
		t.Fatal(err)
	}
	id, _ := m.NewSession("192.0.2.1")
	first, err := m.Access(id, "192.0.2.1", "Browser", "Primer nombre", "", true)
	if err != nil {
		t.Fatal(err)
	}
	second, err := m.Access(id, "192.0.2.1", "Browser", "Nombre actualizado", "", true)
	if err != nil {
		t.Fatal(err)
	}
	requests := m.Requests()
	if first.RequestID != second.RequestID || len(requests) != 1 || requests[0].Name != "Nombre actualizado" {
		t.Fatalf("request not updated in place: %+v", requests)
	}
	if m.Name("192.0.2.1") != "Nombre del propietario" {
		t.Fatal("untrusted request overwrote assigned name")
	}
}

func TestExpiredPendingSessionsCannotFillRequestQueueForever(t *testing.T) {
	m := manager(t)
	if err := m.UpdateSettings(SettingsPatch{RequireApproval: value(true)}); err != nil {
		t.Fatal(err)
	}
	id, _ := m.NewSession("192.0.2.1")
	_, err := m.Access(id, "192.0.2.1", "Browser", "", "", false)
	if err != nil {
		t.Fatal(err)
	}
	m.mu.Lock()
	m.sessions[id].Expires = time.Now().Add(-time.Second)
	m.mu.Unlock()
	if len(m.Requests()) != 0 {
		t.Fatal("expired pending request retained")
	}
	if _, err := m.NewSession("192.0.2.1"); err != nil {
		t.Fatal(err)
	}
}

func TestApprovalCookieBindingAndPolicyRevocation(t *testing.T) {
	m := manager(t)
	if err := m.UpdateSettings(SettingsPatch{PagePassword: value("secret"), RequireApproval: value(true)}); err != nil {
		t.Fatal(err)
	}
	id, _ := m.NewSession("192.0.2.10")
	if got := m.Authorize(id, "192.0.2.10").Status; got != "password" {
		t.Fatal(got)
	}
	if d, err := m.Access(id, "192.0.2.10", "Browser", "Ana", "wrong", true); err != ErrPassword || d.Status != "password" {
		t.Fatalf("wrong password accepted %+v %v", d, err)
	}
	d, err := m.Access(id, "192.0.2.10", "Browser", "Ana", "secret", true)
	if err != nil || d.Status != "pending" || d.RequestID == "" {
		t.Fatalf("no pending request %+v %v", d, err)
	}
	if err := m.Respond(d.RequestID, true); err != nil {
		t.Fatal(err)
	}
	if m.Authorize(id, "192.0.2.10").Status != "allowed" || m.Authorize(id, "192.0.2.11").Status == "allowed" {
		t.Fatal("cookie/IP binding failed")
	}
	if err := m.SetBlocked("192.0.2.10", true); err != nil {
		t.Fatal(err)
	}
	if got := m.Authorize(id, "192.0.2.10").Status; got != "blocked" {
		t.Fatal(got)
	}
	if err := m.SetBlocked("192.0.2.10", false); err != nil {
		t.Fatal(err)
	}
	if got := m.Authorize(id, "192.0.2.10").Status; got != "password" {
		t.Fatalf("old grants returned after unblock: %s", got)
	}
	if err := m.UpdateSettings(SettingsPatch{PagePassword: value("")}); err != nil {
		t.Fatal(err)
	}
	if got := m.Authorize(id, "192.0.2.10").Status; got != "pending" {
		t.Fatal(got)
	}
}

func TestPasswordRateLimitAndItemGrantRevocation(t *testing.T) {
	m := manager(t)
	if err := m.SetItemPassword("item", "first"); err != nil {
		t.Fatal(err)
	}
	id, _ := m.NewSession("192.0.2.1")
	if m.ItemAllowed(id, "192.0.2.1", "item") {
		t.Fatal("locked item allowed")
	}
	if err := m.Unlock(id, "192.0.2.1", "item", "first"); err != nil {
		t.Fatal(err)
	}
	if !m.ItemAllowed(id, "192.0.2.1", "item") {
		t.Fatal("grant not applied")
	}
	if err := m.SetItemPassword("item", "second"); err != nil {
		t.Fatal(err)
	}
	if m.ItemAllowed(id, "192.0.2.1", "item") {
		t.Fatal("password change did not revoke grant")
	}
	id, _ = m.NewSession("192.0.2.1")
	for i := 0; i < 6; i++ {
		_ = m.Unlock(id, "192.0.2.1", "item", "wrong")
	}
	if err := m.Unlock(id, "192.0.2.1", "item", "second"); err != ErrRateLimited {
		t.Fatalf("rate limit missing: %v", err)
	}
}

func TestItemPasswordChangePreservesPageApprovalAndOtherGrants(t *testing.T) {
	m := manager(t)
	if err := m.UpdateSettings(SettingsPatch{PagePassword: value("page"), RequireApproval: value(true)}); err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{"first", "second"} {
		if err := m.SetItemPassword(id, "item"); err != nil {
			t.Fatal(err)
		}
	}
	id, _ := m.NewSession("192.0.2.1")
	decision, err := m.Access(id, "192.0.2.1", "Browser", "", "page", true)
	if err != nil {
		t.Fatal(err)
	}
	if err := m.Respond(decision.RequestID, true); err != nil {
		t.Fatal(err)
	}
	for _, item := range []string{"first", "second"} {
		if err := m.Unlock(id, "192.0.2.1", item, "item"); err != nil {
			t.Fatal(err)
		}
	}
	if err := m.SetItemPassword("first", "changed"); err != nil {
		t.Fatal(err)
	}
	if m.ItemAllowed(id, "192.0.2.1", "first") {
		t.Fatal("changed item's old grant survived")
	}
	if !m.ItemAllowed(id, "192.0.2.1", "second") || m.Authorize(id, "192.0.2.1").Status != "allowed" {
		t.Fatal("unrelated item/page approval was revoked")
	}
	if requests := m.Requests(); len(requests) != 1 || requests[0].ID != decision.RequestID || requests[0].Status != "approved" {
		t.Fatal("item password changed the approval request")
	}
	if err := m.Unlock(id, "192.0.2.1", "first", "changed"); err != nil {
		t.Fatal("existing approved session cannot unlock new password", err)
	}
	if err := m.UpdateSettings(SettingsPatch{PagePassword: value("new page")}); err != nil {
		t.Fatal(err)
	}
	if m.Authorize(id, "192.0.2.1").Status != "password" {
		t.Fatal("global password must still revoke the complete session")
	}
}

func TestFailedPersistenceRollsBackSecuritySettings(t *testing.T) {
	m := manager(t)
	if err := m.UpdateSettings(SettingsPatch{PagePassword: value("old")}); err != nil {
		t.Fatal(err)
	}
	blocked := filepath.Join(t.TempDir(), "directory")
	if err := os.Mkdir(blocked, 0700); err != nil {
		t.Fatal(err)
	}
	m.file = blocked
	if err := m.UpdateSettings(SettingsPatch{PagePassword: value("new"), UploadsEnabled: value(true)}); err == nil {
		t.Fatal("expected atomic rename failure")
	}
	if m.Settings().UploadsEnabled {
		t.Fatal("failed setting took effect")
	}
	id, _ := m.NewSession("192.0.2.1")
	d, err := m.Access(id, "192.0.2.1", "", "", "old", true)
	if err != nil || d.Status != "allowed" {
		t.Fatal("old password lost after write failure")
	}
	if err := m.SetBlocked("192.0.2.1", true); err == nil || m.IsBlocked("192.0.2.1") {
		t.Fatal("failed blocked setting took effect")
	}
}
