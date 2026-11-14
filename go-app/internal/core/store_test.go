package core

import (
	"os"
	"path/filepath"
	"testing"
)

// tempTree builds a small directory tree and returns its root.
func tempTree(t *testing.T) string {
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

	write("loose.txt", "hola")
	write("carpeta/uno.txt", "uno")
	write("carpeta/dos.txt", "dos!!")
	write("carpeta/sub/tres.txt", "tres")
	write("carpeta/.oculto", "no debería aparecer")

	return root
}

func TestAddFileAndFolder(t *testing.T) {
	root := tempTree(t)
	store := NewStore(nil)

	if _, err := store.AddPaths([]string{
		filepath.Join(root, "loose.txt"),
		filepath.Join(root, "carpeta"),
	}); err != nil {
		t.Fatalf("AddPaths: %v", err)
	}

	items := store.Items()
	if len(items) != 2 {
		t.Fatalf("esperaba 2 elementos, hay %d", len(items))
	}
	if items[0].Kind != KindFile || items[1].Kind != KindFolder {
		t.Fatalf("tipos incorrectos: %s, %s", items[0].Kind, items[1].Kind)
	}

	// The folder holds three files; the dotfile must be skipped.
	if items[1].FileCount != 3 {
		t.Errorf("esperaba 3 archivos en la carpeta, hay %d", items[1].FileCount)
	}

	totals := store.Totals()
	if totals.Files != 4 {
		t.Errorf("esperaba 4 archivos en total, hay %d", totals.Files)
	}
	// "hola"=4, "uno"=3, "dos!!"=5, "tres"=4
	if totals.Bytes != 16 {
		t.Errorf("esperaba 16 bytes, hay %d", totals.Bytes)
	}
}

func TestAddIsIdempotent(t *testing.T) {
	root := tempTree(t)
	store := NewStore(nil)
	path := filepath.Join(root, "loose.txt")

	added, _ := store.AddPaths([]string{path})
	if added != 1 {
		t.Fatalf("primera adición: esperaba 1, hubo %d", added)
	}
	added, _ = store.AddPaths([]string{path})
	if added != 0 {
		t.Errorf("adición repetida: esperaba 0, hubo %d", added)
	}
	if len(store.Items()) != 1 {
		t.Errorf("el elemento se duplicó")
	}
}

func TestEntriesAndLookup(t *testing.T) {
	root := tempTree(t)
	store := NewStore(nil)
	store.AddPaths([]string{filepath.Join(root, "carpeta")})

	entries := store.Entries()
	if len(entries) != 3 {
		t.Fatalf("esperaba 3 entradas, hay %d", len(entries))
	}

	for _, entry := range entries {
		found, ok := store.Entry(entry.ID)
		if !ok {
			t.Fatalf("no se pudo resolver la entrada %s", entry.ID)
		}
		if found.Path != entry.Path {
			t.Errorf("la entrada %s resolvió a otra ruta", entry.ID)
		}
		if entry.Folder != "carpeta" {
			t.Errorf("esperaba carpeta propietaria, hay %q", entry.Folder)
		}
	}

	// Nested files keep their relative path inside the zip.
	var nested bool
	for _, entry := range entries {
		if entry.ZipPath == "carpeta/sub/tres.txt" {
			nested = true
		}
	}
	if !nested {
		t.Error("la ruta dentro del zip no conserva la jerarquía")
	}

	if _, ok := store.Entry("no-existe"); ok {
		t.Error("una id inventada no debería resolver")
	}
}

func TestEntryIDsAreStableAcrossRescan(t *testing.T) {
	root := tempTree(t)
	store := NewStore(nil)
	store.AddPaths([]string{filepath.Join(root, "carpeta")})

	before := make(map[string]bool)
	for _, entry := range store.Entries() {
		before[entry.ID] = true
	}

	store.Rescan(true)

	for _, entry := range store.Entries() {
		if !before[entry.ID] {
			// A changing id would break links already open in a browser.
			t.Fatalf("la id %s cambió tras reescanear", entry.ID)
		}
	}
}

func TestRescanPicksUpNewFiles(t *testing.T) {
	root := tempTree(t)
	store := NewStore(nil)
	store.AddPaths([]string{filepath.Join(root, "carpeta")})

	if got := len(store.Entries()); got != 3 {
		t.Fatalf("esperaba 3 entradas, hay %d", got)
	}

	if err := os.WriteFile(filepath.Join(root, "carpeta", "cuatro.txt"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	store.Rescan(true)

	if got := len(store.Entries()); got != 4 {
		t.Errorf("tras reescanear esperaba 4 entradas, hay %d", got)
	}
}

func TestRescanFlagsMissingItems(t *testing.T) {
	root := tempTree(t)
	store := NewStore(nil)
	path := filepath.Join(root, "loose.txt")
	store.AddPaths([]string{path})

	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	store.Rescan(true)

	items := store.Items()
	if !items[0].Missing {
		t.Error("un archivo borrado debería marcarse como ausente")
	}
	// Missing items must not be offered for download.
	if len(store.Entries()) != 0 {
		t.Error("un archivo ausente no debería seguir descargable")
	}
}

func TestRemoveAndClear(t *testing.T) {
	root := tempTree(t)
	store := NewStore(nil)
	store.AddPaths([]string{
		filepath.Join(root, "loose.txt"),
		filepath.Join(root, "carpeta"),
	})

	items := store.Items()
	if removed := store.Remove([]string{items[0].ID}); removed != 1 {
		t.Fatalf("esperaba quitar 1, quitó %d", removed)
	}
	if len(store.Items()) != 1 {
		t.Fatalf("debería quedar 1 elemento")
	}
	if removed := store.Remove([]string{"inventada"}); removed != 0 {
		t.Errorf("una id inexistente no debería quitar nada")
	}

	store.Clear()
	if !store.IsEmpty() {
		t.Error("Clear debería vaciar la lista")
	}
}

func TestOnChangeFires(t *testing.T) {
	root := tempTree(t)
	var calls int
	store := NewStore(func() { calls++ })

	store.AddPaths([]string{filepath.Join(root, "loose.txt")})
	if calls == 0 {
		t.Fatal("añadir debería notificar")
	}

	before := calls
	store.AddPaths([]string{filepath.Join(root, "loose.txt")})
	if calls != before {
		t.Error("una adición duplicada no debería notificar")
	}
}

func TestReceivingPathIsHiddenFromSharedFolderRescans(t *testing.T) {
	dir := t.TempDir()
	file := filepath.Join(dir, "incoming.txt")
	if err := os.WriteFile(file, []byte("partial"), 0600); err != nil {
		t.Fatal(err)
	}
	store := NewStore(nil)
	if _, err := store.AddPaths([]string{dir}); err != nil {
		t.Fatal(err)
	}
	entry := store.Entries()[0]
	release := store.ExcludePath(file)
	store.Rescan(true)
	if _, ok := store.Entry(entry.ID); ok {
		t.Fatal("receiving file downloadable by ID")
	}
	if len(store.Entries()) != 0 || store.Totals().Files != 0 || store.Folders()[0].FileCount != 0 || store.Items()[0].FileCount != 0 {
		t.Fatal("receiving file exposed through a shared folder snapshot")
	}
	if err := os.WriteFile(file, []byte("complete contents"), 0600); err != nil {
		t.Fatal(err)
	}
	release()
	release()
	store.Rescan(true)
	entries := store.Entries()
	if len(entries) != 1 || entries[0].Size != 17 || store.Totals().Files != 1 {
		t.Fatalf("completed file did not become available: %+v", entries)
	}
}
