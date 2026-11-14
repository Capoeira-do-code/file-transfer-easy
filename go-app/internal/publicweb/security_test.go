package publicweb

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"net/textproto"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/access"
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/activity"
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/core"
)

func pointer[T any](v T) *T { return &v }

type secureFixture struct {
	handler  http.Handler
	store    *core.Store
	tracker  *activity.Tracker
	policy   *access.Manager
	dir      string
	cookies  []*http.Cookie
	ip       string
	onUpload func([]string) error
}

func secureServer(t *testing.T) *secureFixture {
	t.Helper()
	_, store, tracker, dir := newFixture(t)
	policy, err := access.New(t.TempDir(), nil)
	if err != nil {
		t.Fatal(err)
	}
	f := &secureFixture{store: store, tracker: tracker, policy: policy, dir: dir, ip: "192.0.2.40"}
	f.handler = New(testAssets(), store, tracker, testToken, Options{Access: policy, OnUpload: func(paths []string) error {
		if f.onUpload != nil {
			return f.onUpload(paths)
		}
		return nil
	}})
	return f
}
func (f *secureFixture) request(t *testing.T, method, path, body string) *httptest.ResponseRecorder {
	t.Helper()
	r := httptest.NewRequest(method, "/s/"+testToken+path, strings.NewReader(body))
	r.RemoteAddr = f.ip + ":40000"
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("User-Agent", "Test Browser")
	for _, c := range f.cookies {
		r.AddCookie(c)
	}
	w := httptest.NewRecorder()
	f.handler.ServeHTTP(w, r)
	if cs := w.Result().Cookies(); len(cs) > 0 {
		f.cookies = cs
	}
	return w
}
func (f *secureFixture) open(t *testing.T) {
	t.Helper()
	w := f.request(t, http.MethodGet, "/api/access", "")
	if w.Code != http.StatusOK {
		t.Fatalf("open access: %d %s", w.Code, w.Body)
	}
}
func payload(t *testing.T, w *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	var p map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &p); err != nil {
		t.Fatal(err, w.Body.String())
	}
	return p
}

func TestPublicPasswordApprovalItemAndZIPCannotBeBypassed(t *testing.T) {
	f := secureServer(t)
	folder := f.store.Items()[1].ID
	if err := f.policy.SetItemPassword(folder, "folder secret"); err != nil {
		t.Fatal(err)
	}
	if err := f.policy.UpdateSettings(access.SettingsPatch{PagePassword: pointer("page secret"), RequireApproval: pointer(true)}); err != nil {
		t.Fatal(err)
	}
	entries := f.store.Entries()
	folderFile := entries[1].ID
	if w := f.request(t, http.MethodGet, "/download/"+entries[0].ID+"?password=page%20secret", ""); w.Code != http.StatusUnauthorized {
		t.Fatal("password in URL bypassed cookie session")
	}
	for _, path := range []string{"/api/manifest", "/download/" + entries[0].ID, "/zip", "/ping", "/api/download/" + entries[0].ID, "/api/zip"} {
		method := http.MethodGet
		if path == "/ping" {
			method = http.MethodPost
		}
		if w := f.request(t, method, path, "{}"); w.Code != http.StatusUnauthorized {
			t.Fatalf("page gate bypass %s %d %s", path, w.Code, w.Body)
		}
	}
	w := f.request(t, http.MethodPost, "/api/access", `{"password":"wrong"}`)
	if w.Code != http.StatusUnauthorized {
		t.Fatal(w.Code)
	}
	w = f.request(t, http.MethodPost, "/api/access", `{"password":"page secret","name":"Ana"}`)
	p := payload(t, w)
	if w.Code != http.StatusOK || p["status"] != "pending" {
		t.Fatalf("expected pending: %d %v", w.Code, p)
	}
	if w = f.request(t, http.MethodGet, "/api/manifest", ""); w.Code != http.StatusForbidden {
		t.Fatal("pending visitor read manifest")
	}
	if err := f.policy.Respond(p["requestId"].(string), true); err != nil {
		t.Fatal(err)
	}
	w = f.request(t, http.MethodGet, "/api/manifest", "")
	if w.Code != http.StatusOK {
		t.Fatal(w.Code, w.Body)
	}
	var m manifest
	if err := json.Unmarshal(w.Body.Bytes(), &m); err != nil {
		t.Fatal(err)
	}
	if !m.Files[1].Locked || !m.Files[1].Protected || m.Files[1].OwnerID != folder {
		t.Fatalf("folder policy not inherited %+v", m.Files[1])
	}
	for _, path := range []string{"/download/" + folderFile, "/api/download/" + folderFile} {
		if w := f.request(t, http.MethodGet, path, ""); w.Code != http.StatusForbidden {
			t.Fatalf("item gate bypass %s %d", path, w.Code)
		}
	}
	w = f.request(t, http.MethodGet, "/zip", "")
	zr, err := zip.NewReader(bytes.NewReader(w.Body.Bytes()), int64(w.Body.Len()))
	if err != nil {
		t.Fatal(err)
	}
	if len(zr.File) != 1 {
		t.Fatalf("ZIP leaked protected folder: %d entries", len(zr.File))
	}
	w = f.request(t, http.MethodPost, "/api/unlock", fmt.Sprintf(`{"id":%q,"password":"folder secret"}`, folderFile))
	if w.Code != http.StatusOK {
		t.Fatal(w.Code, w.Body)
	}
	if w = f.request(t, http.MethodGet, "/download/"+entries[2].ID, ""); w.Code != http.StatusOK {
		t.Fatal("folder grant did not cover sibling", w.Code)
	}
	w = f.request(t, http.MethodGet, "/zip", "")
	zr, err = zip.NewReader(bytes.NewReader(w.Body.Bytes()), int64(w.Body.Len()))
	if err != nil || len(zr.File) != 3 {
		t.Fatalf("unlocked ZIP %v", err)
	}
	if err := f.policy.SetItemPassword(folder, "changed"); err != nil {
		t.Fatal(err)
	}
	if w = f.request(t, http.MethodGet, "/download/"+folderFile, ""); w.Code != http.StatusForbidden {
		t.Fatalf("item password change did not revoke the folder grant %d", w.Code)
	}
	if w = f.request(t, http.MethodGet, "/api/manifest", ""); w.Code != http.StatusOK {
		t.Fatal("item password change revoked page approval", w.Code)
	}
}

func TestBlockedIPOverridesCookieAndCannotSpoofProxyHeaders(t *testing.T) {
	f := secureServer(t)
	f.open(t)
	if err := f.policy.SetBlocked(f.ip, true); err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRequest(http.MethodGet, "/s/"+testToken+"/api/manifest", nil)
	r.RemoteAddr = f.ip + ":40000"
	r.Header.Set("CF-Connecting-IP", "203.0.113.1")
	r.Header.Set("X-Forwarded-For", "203.0.113.1")
	for _, c := range f.cookies {
		r.AddCookie(c)
	}
	w := httptest.NewRecorder()
	f.handler.ServeHTTP(w, r)
	if w.Code != http.StatusForbidden || payload(t, w)["status"] != "blocked" {
		t.Fatalf("spoof bypassed block: %d %s", w.Code, w.Body)
	}
}

func uploadRequest(t *testing.T, f *secureFixture, name string, data []byte) *http.Request {
	t.Helper()
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	header := textproto.MIMEHeader{}
	header.Set("Content-Disposition", fmt.Sprintf(`form-data; name="files"; filename=%q`, name))
	header.Set("Content-Type", "application/octet-stream")
	part, err := writer.CreatePart(header)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := part.Write(data); err != nil {
		t.Fatal(err)
	}
	writer.Close()
	r := httptest.NewRequest(http.MethodPost, "/s/"+testToken+"/upload", &body)
	r.RemoteAddr = f.ip + ":40000"
	r.Header.Set("Content-Type", writer.FormDataContentType())
	for _, c := range f.cookies {
		r.AddCookie(c)
	}
	return r
}
func (f *secureFixture) upload(t *testing.T, name string, data []byte) *httptest.ResponseRecorder {
	t.Helper()
	w := httptest.NewRecorder()
	f.handler.ServeHTTP(w, uploadRequest(t, f, name, data))
	return w
}

func TestUploadsDisabledTraversalLimitAndNoOverwrite(t *testing.T) {
	f := secureServer(t)
	f.open(t)
	if w := f.upload(t, "note.txt", []byte("content")); w.Code != http.StatusForbidden {
		t.Fatal("disabled upload accepted")
	}
	dir := filepath.Join(t.TempDir(), "received")
	if err := f.policy.UpdateSettings(access.SettingsPatch{UploadsEnabled: pointer(true), UploadDir: &dir, MaxUploadMB: pointer(int64(1))}); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"../escape.txt", `..\escape.txt`, "C:escape.txt", "CON.txt", "note.txt ", "nul", ".fte-upload-secret"} {
		w := f.upload(t, name, []byte("bad"))
		if w.Code != http.StatusBadRequest {
			t.Fatalf("unsafe name accepted %q %d %s", name, w.Code, w.Body)
		}
	}
	var imported []string
	f.onUpload = func(paths []string) error { imported = append(imported, paths...); return nil }
	for _, content := range []string{"first", "second"} {
		if w := f.upload(t, "nota con ñ.txt", []byte(content)); w.Code != http.StatusOK {
			t.Fatalf("upload %d %s", w.Code, w.Body)
		} else if strings.Contains(w.Body.String(), dir) {
			t.Fatal("disk path leaked")
		}
	}
	if len(imported) != 2 || imported[0] == imported[1] {
		t.Fatalf("callback paths wrong: %v", imported)
	}
	for i, path := range imported {
		got, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if string(got) != []string{"first", "second"}[i] {
			t.Fatal("existing file overwritten")
		}
	}
	w := f.upload(t, "large.bin", bytes.Repeat([]byte("x"), (1<<20)+1))
	if w.Code == http.StatusOK {
		t.Fatal("oversized upload accepted")
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 2 {
		t.Fatalf("partial upload retained: %v", entries)
	}
	_, transfers, stats, _ := f.tracker.Snapshot()
	if len(transfers) < 2 || transfers[0].Kind != "upload" || stats.Downloads != 0 {
		t.Fatal("upload progress/statistics not tracked correctly")
	}
}

type policyReader struct {
	reader io.Reader
	once   bool
	change func()
}

func (r *policyReader) Read(p []byte) (int, error) {
	n, e := r.reader.Read(p)
	if !r.once && n > 0 {
		r.once = true
		r.change()
	}
	return n, e
}
func TestDisablingUploadsDuringReceiptRollsBackPartialFile(t *testing.T) {
	f := secureServer(t)
	f.open(t)
	if err := f.policy.UpdateSettings(access.SettingsPatch{UploadsEnabled: pointer(true)}); err != nil {
		t.Fatal(err)
	}
	r := uploadRequest(t, f, "partial.bin", bytes.Repeat([]byte("x"), copyBuffer*2))
	original := r.Body
	r.Body = io.NopCloser(&policyReader{reader: original, change: func() { _ = f.policy.UpdateSettings(access.SettingsPatch{UploadsEnabled: pointer(false)}) }})
	w := httptest.NewRecorder()
	f.handler.ServeHTTP(w, r)
	if w.Code != http.StatusForbidden {
		t.Fatalf("disable during upload accepted %d %s", w.Code, w.Body)
	}
	entries, err := os.ReadDir(f.policy.Settings().UploadDir)
	if err != nil && !os.IsNotExist(err) {
		t.Fatal(err)
	}
	if len(entries) != 0 {
		t.Fatal("partial file survived disable")
	}
}

func TestUploadSymlinkRootRejected(t *testing.T) {
	f := secureServer(t)
	f.open(t)
	outside := t.TempDir()
	link := filepath.Join(t.TempDir(), "link")
	if err := os.Symlink(outside, link); err != nil {
		// Windows permits directory junctions without the symbolic-link
		// privilege. They must be rejected by the same reparse-point check.
		if runtime.GOOS != "windows" {
			t.Skip("symlink creation not permitted", err)
		}
		if output, junctionErr := exec.Command("cmd.exe", "/c", "mklink", "/J", link, outside).CombinedOutput(); junctionErr != nil {
			t.Skip("test reparse point unavailable", junctionErr, string(output))
		}
	}
	if err := f.policy.UpdateSettings(access.SettingsPatch{UploadsEnabled: pointer(true), UploadDir: &link}); err != nil {
		t.Fatal(err)
	}
	if w := f.upload(t, "outside.txt", []byte("bad")); w.Code == http.StatusOK {
		t.Fatal("symlink upload root accepted")
	}
	entries, _ := os.ReadDir(outside)
	if len(entries) != 0 {
		t.Fatal("upload escaped root")
	}
}

type revokeWriter struct {
	*httptest.ResponseRecorder
	change  func()
	changed bool
}

func (w *revokeWriter) Write(p []byte) (int, error) {
	n, e := w.ResponseRecorder.Write(p)
	if !w.changed {
		w.changed = true
		w.change()
	}
	return n, e
}
func TestBlockingIPCutsAnActiveDownload(t *testing.T) {
	f := secureServer(t)
	f.open(t)
	big := filepath.Join(f.dir, "big.bin")
	if err := os.WriteFile(big, bytes.Repeat([]byte("x"), copyBuffer*3), 0600); err != nil {
		t.Fatal(err)
	}
	f.store.AddPaths([]string{big})
	id := f.store.Items()[2].ID
	r := httptest.NewRequest(http.MethodGet, "/s/"+testToken+"/download/"+id, nil)
	r.RemoteAddr = f.ip + ":40000"
	for _, c := range f.cookies {
		r.AddCookie(c)
	}
	w := &revokeWriter{ResponseRecorder: httptest.NewRecorder(), change: func() {
		if err := f.policy.SetBlocked(f.ip, true); err != nil {
			t.Fatal(err)
		}
	}}
	f.handler.ServeHTTP(w, r)
	if w.Body.Len() >= copyBuffer*3 {
		t.Fatal("blocked transfer continued")
	}
	_, transfers, _, _ := f.tracker.Snapshot()
	if len(transfers) != 1 || transfers[0].Status != "cancelled" {
		t.Fatalf("transfer not cancelled %+v", transfers)
	}
}

func TestPreflightConcreteMissingFileErrorAndNoPathLeak(t *testing.T) {
	f := secureServer(t)
	f.open(t)
	entry := f.store.Entries()[0]
	if err := os.Remove(entry.Path); err != nil {
		t.Fatal(err)
	}
	w := f.request(t, http.MethodGet, "/api/download/"+entry.ID, "")
	p := payload(t, w)
	if w.Code != http.StatusNotFound || !strings.Contains(p["error"].(string), "ya no existe") {
		t.Fatalf("missing reason %d %v", w.Code, p)
	}
	if strings.Contains(w.Body.String(), f.dir) {
		t.Fatal("filesystem path leaked")
	}
}

func TestCustomMessageDoesNotHideActualAccessFailure(t *testing.T) {
	f := secureServer(t)
	if err := f.policy.UpdateSettings(access.SettingsPatch{PagePassword: pointer("secret"), ErrorMessage: pointer("generic message")}); err != nil {
		t.Fatal(err)
	}
	w := f.request(t, http.MethodGet, "/api/access", "")
	p := payload(t, w)
	if p["status"] != "password" || !strings.Contains(p["message"].(string), "contraseña") {
		t.Fatalf("actual reason hidden: %v", p)
	}
	w = f.request(t, http.MethodPost, "/api/access", `{"password":"wrong"}`)
	if !strings.Contains(payload(t, w)["error"].(string), "incorrecta") {
		t.Fatal("wrong-password reason hidden")
	}
}
