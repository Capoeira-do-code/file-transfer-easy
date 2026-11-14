package publicweb

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/access"
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/activity"
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/core"
)

func decodeManifest(w *httptest.ResponseRecorder, m *manifest) error {
	return json.Unmarshal(w.Body.Bytes(), m)
}

func aliasServer(t *testing.T, looseFirst bool) (*secureFixture, string, string) {
	t.Helper()
	dir := t.TempDir()
	file := filepath.Join(dir, "private.txt")
	if err := os.WriteFile(file, []byte("private bytes"), 0600); err != nil {
		t.Fatal(err)
	}
	store := core.NewStore(nil)
	paths := []string{dir, file}
	if looseFirst {
		paths = []string{file, dir}
	}
	if _, err := store.AddPaths(paths); err != nil {
		t.Fatal(err)
	}
	policy, err := access.New(t.TempDir(), nil)
	if err != nil {
		t.Fatal(err)
	}
	tracker := activity.New(nil)
	f := &secureFixture{store: store, tracker: tracker, policy: policy, dir: dir, ip: "192.0.2.40"}
	f.handler = New(testAssets(), store, tracker, testToken, Options{Access: policy})
	f.open(t)
	var fileID, folderID string
	for _, item := range store.Items() {
		if item.Kind == core.KindFile {
			fileID = item.ID
		} else {
			folderID = item.ID
		}
	}
	return f, fileID, folderID
}

func assertAliasDenied(t *testing.T, f *secureFixture, id string) {
	t.Helper()
	for _, path := range []string{"/download/" + id, "/api/download/" + id, "/zip", "/api/zip"} {
		w := f.request(t, http.MethodGet, path, "")
		if w.Code != http.StatusForbidden {
			t.Fatalf("alias bypass %s: %d %s", path, w.Code, w.Body)
		}
		if bytes.Contains(w.Body.Bytes(), []byte("private bytes")) {
			t.Fatal("private bytes leaked")
		}
	}
}

func TestExplicitFilePasswordProtectsAllFolderAndLooseAliases(t *testing.T) {
	for _, looseFirst := range []bool{false, true} {
		t.Run(fmt.Sprintf("looseFirst=%v", looseFirst), func(t *testing.T) {
			f, id, folder := aliasServer(t, looseFirst)
			if err := f.policy.SetItemPassword(id, "file secret"); err != nil {
				t.Fatal(err)
			}
			assertAliasDenied(t, f, id)
			w := f.request(t, http.MethodGet, "/api/manifest", "")
			var m manifest
			if err := decodeManifest(w, &m); err != nil {
				t.Fatal(err)
			}
			if len(m.Files) != 2 {
				t.Fatalf("missing aliases: %+v", m.Files)
			}
			for _, file := range m.Files {
				if !file.Locked || !file.Protected || file.OwnerID != id || file.ProtectionKind != "file" || file.ProtectionName != "private.txt" {
					t.Fatalf("alias has wrong effective policy: %+v", file)
				}
			}
			// Unlocking the unprotected folder must not unlock its explicitly
			// protected child through a second alias.
			w = f.request(t, http.MethodPost, "/api/unlock", fmt.Sprintf(`{"id":%q,"password":""}`, folder))
			if w.Code != http.StatusOK {
				t.Fatal(w.Code, w.Body)
			}
			assertAliasDenied(t, f, id)
			w = f.request(t, http.MethodPost, "/api/unlock", fmt.Sprintf(`{"id":%q,"password":"file secret"}`, id))
			if w.Code != http.StatusOK {
				t.Fatal(w.Code, w.Body)
			}
			if w = f.request(t, http.MethodGet, "/download/"+id, ""); w.Code != http.StatusOK || w.Body.String() != "private bytes" {
				t.Fatal("effective file unlock failed", w.Code, w.Body)
			}
			w = f.request(t, http.MethodGet, "/zip", "")
			archive, err := zip.NewReader(bytes.NewReader(w.Body.Bytes()), int64(w.Body.Len()))
			if err != nil || len(archive.File) != 2 {
				t.Fatal("unlocked aliases not archived", err)
			}
		})
	}
}

func TestProtectedFolderCannotBeBypassedByUnprotectedLooseAlias(t *testing.T) {
	for _, looseFirst := range []bool{false, true} {
		t.Run(fmt.Sprintf("looseFirst=%v", looseFirst), func(t *testing.T) {
			f, id, folder := aliasServer(t, looseFirst)
			if err := f.policy.SetItemPassword(folder, "folder secret"); err != nil {
				t.Fatal(err)
			}
			assertAliasDenied(t, f, id)
			w := f.request(t, http.MethodGet, "/api/manifest", "")
			var m manifest
			if err := decodeManifest(w, &m); err != nil {
				t.Fatal(err)
			}
			for _, file := range m.Files {
				if file.OwnerID != folder || file.ProtectionKind != "folder" || !file.Locked {
					t.Fatalf("loose alias policy wrong %+v", file)
				}
			}
			w = f.request(t, http.MethodPost, "/api/unlock", fmt.Sprintf(`{"id":%q,"password":"folder secret"}`, id))
			if w.Code != http.StatusOK {
				t.Fatal(w.Code, w.Body)
			}
			if w = f.request(t, http.MethodGet, "/download/"+id, ""); w.Code != http.StatusOK {
				t.Fatal("folder password did not unlock loose alias", w.Code, w.Body)
			}
		})
	}
}

func TestNestedFolderUsesMostSpecificPolicyAndFileOverrideWins(t *testing.T) {
	for _, childFirst := range []bool{false, true} {
		t.Run(fmt.Sprintf("childFirst=%v", childFirst), func(t *testing.T) {
			f, id, parent := aliasServer(t, false)
			childPath := filepath.Join(f.dir, "nested")
			if err := os.Mkdir(childPath, 0700); err != nil {
				t.Fatal(err)
			}
			file := filepath.Join(childPath, "private.txt")
			if err := os.WriteFile(file, []byte("nested private"), 0600); err != nil {
				t.Fatal(err)
			}
			f.store.Clear()
			paths := []string{f.dir, childPath, file}
			if childFirst {
				paths = []string{childPath, file, f.dir}
			}
			if _, err := f.store.AddPaths(paths); err != nil {
				t.Fatal(err)
			}
			var child string
			for _, item := range f.store.Items() {
				if item.Path == childPath {
					child = item.ID
				}
				if item.Path == file {
					id = item.ID
				}
				if item.Path == f.dir {
					parent = item.ID
				}
			}
			if err := f.policy.SetItemPassword(parent, "parent"); err != nil {
				t.Fatal(err)
			}
			if err := f.policy.SetItemPassword(child, "child"); err != nil {
				t.Fatal(err)
			}
			w := f.request(t, http.MethodPost, "/api/unlock", fmt.Sprintf(`{"id":%q,"password":"parent"}`, id))
			if w.Code != http.StatusUnauthorized {
				t.Fatal("less specific password accepted", w.Code, w.Body)
			}
			w = f.request(t, http.MethodGet, "/api/manifest", "")
			var m manifest
			if err := decodeManifest(w, &m); err != nil {
				t.Fatal(err)
			}
			for _, entry := range m.Files {
				if entry.ID == id && (entry.OwnerID != child || entry.ProtectionName != "nested" || entry.ProtectionKind != "folder") {
					t.Fatalf("wrong specific owner %+v", entry)
				}
			}
			w = f.request(t, http.MethodPost, "/api/unlock", fmt.Sprintf(`{"id":%q,"password":"child"}`, id))
			if w.Code != http.StatusOK {
				t.Fatal(w.Code, w.Body)
			}
			if w = f.request(t, http.MethodGet, "/download/"+id, ""); w.Code != http.StatusOK {
				t.Fatal("most specific grant failed", w.Code)
			}
			if err := f.policy.SetItemPassword(id, "file"); err != nil {
				t.Fatal(err)
			}
			if w = f.request(t, http.MethodGet, "/download/"+id, ""); w.Code != http.StatusForbidden {
				t.Fatal("new explicit file policy did not override existing folder grant", w.Code)
			}
			w = f.request(t, http.MethodPost, "/api/unlock", fmt.Sprintf(`{"id":%q,"password":"file"}`, id))
			if w.Code != http.StatusOK {
				t.Fatal(w.Code, w.Body)
			}
		})
	}
}

func TestAliasPolicyIsReevaluatedDuringEveryDownloadChunk(t *testing.T) {
	f, id, folder := aliasServer(t, false)
	if err := os.WriteFile(filepath.Join(f.dir, "private.txt"), bytes.Repeat([]byte("x"), copyBuffer*3), 0600); err != nil {
		t.Fatal(err)
	}
	f.store.Rescan(true)
	r := httptest.NewRequest(http.MethodGet, "/s/"+testToken+"/download/"+id, nil)
	r.RemoteAddr = f.ip + ":40000"
	for _, c := range f.cookies {
		r.AddCookie(c)
	}
	w := &revokeWriter{ResponseRecorder: httptest.NewRecorder(), change: func() {
		if err := f.policy.SetItemPassword(folder, "added during transfer"); err != nil {
			t.Fatal(err)
		}
	}}
	f.handler.ServeHTTP(w, r)
	if w.Body.Len() >= copyBuffer*3 {
		t.Fatal("new folder protection did not stop loose alias stream")
	}
}

func TestCapturedEntryCannotStreamAnExcludedReceivingDestination(t *testing.T) {
	f := secureServer(t)
	f.open(t)
	entry := f.store.Entries()[0]
	server := f.handler.(*Server)
	r := httptest.NewRequest(http.MethodGet, "/s/"+testToken+"/download/"+entry.ID, nil)
	r.RemoteAddr = f.ip + ":40000"
	for _, c := range f.cookies {
		r.AddCookie(c)
	}
	if !server.itemAllowed(r, entry) {
		t.Fatal("fixture should initially allow the entry")
	}
	release := f.store.ExcludePath(entry.Path)
	defer release()
	if server.itemAllowed(r, entry) {
		t.Fatal("captured Entry bypassed receiving exclusion")
	}
	w := httptest.NewRecorder()
	transfer := f.tracker.StartTransfer("file", entry.Name, f.ip, 13)
	status := server.streamEntry(w, strings.NewReader("private bytes"), transfer, r, entry)
	if status != "cancelled" || w.Body.Len() != 0 {
		t.Fatalf("excluded captured entry leaked bytes: %s %q", status, w.Body.String())
	}
}

func TestNewLooseFileInProtectedFolderDoesNotWaitForFolderRescan(t *testing.T) {
	f, _, folder := aliasServer(t, false)
	if err := f.policy.SetItemPassword(folder, "folder"); err != nil {
		t.Fatal(err)
	}
	f.store.Rescan(true)
	file := filepath.Join(f.dir, "added-after-scan.txt")
	if err := os.WriteFile(file, []byte("new private bytes"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := f.store.AddPaths([]string{file}); err != nil {
		t.Fatal(err)
	}
	var id string
	for _, item := range f.store.Items() {
		if item.Path == file {
			id = item.ID
		}
	}
	for _, path := range []string{"/download/" + id, "/api/download/" + id} {
		if w := f.request(t, http.MethodGet, path, ""); w.Code != http.StatusForbidden {
			t.Fatalf("new alias bypassed protected ancestor: %s %d", path, w.Code)
		}
	}
	f.store.Remove([]string{folder})
	if w := f.request(t, http.MethodGet, "/download/"+id, ""); w.Code != http.StatusOK {
		t.Fatalf("removed folder policy remained in alias index: %d", w.Code)
	}
}
