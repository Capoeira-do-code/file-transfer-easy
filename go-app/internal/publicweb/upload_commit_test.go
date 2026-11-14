package publicweb

import (
	"bytes"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"testing"
)

type noLinksRoot struct{ *os.Root }

func (r noLinksRoot) Link(string, string) error { return errors.ErrUnsupported }

func TestUploadCommitCopiesOnFilesystemsWithoutHardLinks(t *testing.T) {
	dir := t.TempDir()
	root, err := os.OpenRoot(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()
	want := bytes.Repeat([]byte("bytes con ñ\x00\xff"), 100000)
	if err := root.WriteFile(".temporary", want, 0600); err != nil {
		t.Fatal(err)
	}
	if err := commitUploadFile(noLinksRoot{root}, ".temporary", "received.bin"); err != nil {
		t.Fatal(err)
	}
	got, err := root.ReadFile("received.bin")
	if err != nil || !bytes.Equal(got, want) {
		t.Fatal("fallback changed file contents", err)
	}
	if err := root.WriteFile(".temporary", []byte("replacement"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := commitUploadFile(noLinksRoot{root}, ".temporary", "received.bin"); !errors.Is(err, os.ErrExist) {
		t.Fatalf("existing destination accepted: %v", err)
	}
	got, err = root.ReadFile("received.bin")
	if err != nil || !bytes.Equal(got, want) {
		t.Fatal("fallback overwrote prior destination", err)
	}
}

func TestUploadCommitFallbackDoesNotFollowDestinationLinks(t *testing.T) {
	dir, outside := t.TempDir(), t.TempDir()
	link := filepath.Join(dir, "destination")
	sentinel := filepath.Join(outside, "sentinel.txt")
	if err := os.WriteFile(sentinel, []byte("keep"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, link); err != nil {
		if runtime.GOOS != "windows" {
			t.Skip("symlink unavailable", err)
		}
		if output, junctionErr := exec.Command("cmd.exe", "/c", "mklink", "/J", link, outside).CombinedOutput(); junctionErr != nil {
			t.Skip("test reparse point unavailable", junctionErr, string(output))
		}
	}
	root, err := os.OpenRoot(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()
	if err := root.WriteFile(".temporary", []byte("bad"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := commitUploadFile(noLinksRoot{root}, ".temporary", "destination"); err == nil {
		t.Fatal("fallback followed/replaced destination link")
	}
	got, err := os.ReadFile(sentinel)
	if err != nil || string(got) != "keep" {
		t.Fatal("outside destination changed", err)
	}
	entries, err := os.ReadDir(outside)
	if err != nil || len(entries) != 1 {
		t.Fatal("fallback escaped upload root", err)
	}
	if _, err := os.Readlink(link); err != nil {
		t.Fatal("destination link was removed", err)
	}
}

type brokenCopyRoot struct{ noLinksRoot }

func (r brokenCopyRoot) Open(name string) (*os.File, error) {
	f, err := r.Root.Open(name)
	if err == nil {
		_ = f.Close()
	}
	return f, err
}

func TestUploadCommitFailedFallbackRemovesOnlyItsNewDestination(t *testing.T) {
	root, err := os.OpenRoot(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()
	if err := root.WriteFile(".temporary", []byte("source"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := root.WriteFile("existing.txt", []byte("keep"), 0600); err != nil {
		t.Fatal(err)
	}
	broken := brokenCopyRoot{noLinksRoot{root}}
	if err := commitUploadFile(broken, ".temporary", "partial.bin"); err == nil {
		t.Fatal("expected failed read")
	}
	if _, err := root.Lstat("partial.bin"); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("partial destination remains: %v", err)
	}
	if err := commitUploadFile(broken, ".temporary", "existing.txt"); !errors.Is(err, os.ErrExist) {
		t.Fatal("existing destination was opened for replacement", err)
	}
	got, err := root.ReadFile("existing.txt")
	if err != nil || string(got) != "keep" {
		t.Fatal("rollback touched unrelated destination", err)
	}
}
