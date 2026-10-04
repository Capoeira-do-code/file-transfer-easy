package main

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestLaunchPathsDoesNotShareExecutableOnReopen(t *testing.T) {
	binary := filepath.Join(t.TempDir(), "file-transfer-easy")
	if err := os.WriteFile(binary, []byte("executable fixture"), 0600); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{nil, {}, {binary}, {binary, "--flag", ""}} {
		if paths := launchPaths(args, ""); len(paths) != 0 {
			t.Fatalf("reopening shared unexpected paths: %v", paths)
		}
	}
}

func TestLaunchPathsUsesLaunchingInstancesWorkingDirectory(t *testing.T) {
	dir := t.TempDir()
	file, folder := filepath.Join(dir, "nota con ñ.txt"), filepath.Join(dir, "Carpeta de prueba")
	if err := os.WriteFile(file, []byte("file fixture"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(folder, 0700); err != nil {
		t.Fatal(err)
	}
	want := []string{file, folder}
	args := []string{file, filepath.Base(file), filepath.Base(folder), "missing", "--flag"}
	if got := launchPaths(args, dir); !reflect.DeepEqual(got, want) {
		t.Fatalf("paths = %v; want %v", got, want)
	}
	if got := launchPaths([]string{file, folder}, ""); !reflect.DeepEqual(got, []string{folder}) {
		t.Fatalf("absolute paths = %v", got)
	}
}
