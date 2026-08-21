// Package core holds the set of files and folders the user is currently sharing.
//
// The store is the single source of truth for both HTTP servers: the local UI
// server renders it as application state, and the public server resolves
// download requests against it.
package core

import (
	"crypto/sha1"
	"encoding/hex"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Kind distinguishes the two things a user can add.
type Kind string

const (
	KindFile   Kind = "file"
	KindFolder Kind = "folder"
)

// maxFolderEntries caps a single folder scan so that adding a huge directory
// tree by accident cannot lock the app up.
const maxFolderEntries = 20000

// rescanInterval is the minimum gap between two folder rescans.
const rescanInterval = 4 * time.Second

// Entry is one concrete file a recipient can download.
type Entry struct {
	ID      string
	Name    string // filename shown and used for the download
	ZipPath string // path this entry takes inside the "download all" zip
	Path    string // absolute path on disk
	Size    int64
	ModTime time.Time
	Folder  string // name of the owning folder item, "" for loose files
	Ext     string
}

// Item is one element the user added: a single file or a whole folder.
type Item struct {
	ID        string
	Kind      Kind
	Name      string
	Path      string
	Ext       string
	Size      int64
	FileCount int
	Missing   bool
	AddedAt   time.Time

	entries []Entry
}

// Totals summarises everything currently shared.
type Totals struct {
	Items int
	Files int
	Bytes int64
}

// Store is a concurrency-safe collection of shared items.
type Store struct {
	mu       sync.RWMutex
	items    []*Item
	lastScan time.Time

	onChange func()
}

// NewStore returns an empty store. onChange, if non-nil, is called after every
// mutation so the caller can broadcast fresh state.
func NewStore(onChange func()) *Store {
	return &Store{onChange: onChange}
}

func (s *Store) notify() {
	if s.onChange != nil {
		s.onChange()
	}
}

// hashID derives a stable identifier from a path, so links stay valid across
// rescans and dedupe is a simple lookup.
func hashID(path string) string {
	sum := sha1.Sum([]byte(path))
	return hex.EncodeToString(sum[:])[:12]
}

func extOf(name string) string {
	ext := strings.TrimPrefix(strings.ToLower(filepath.Ext(name)), ".")
	if len(ext) > 8 {
		return ""
	}
	return ext
}

// isHidden reports whether a directory entry should be skipped during a scan.
// Dotfiles and the macOS/Windows metadata files add noise recipients never want.
func isHidden(name string) bool {
	if strings.HasPrefix(name, ".") {
		return true
	}
	switch strings.ToLower(name) {
	case "thumbs.db", "desktop.ini", "$recycle.bin", "system volume information":
		return true
	}
	return false
}

// AddPaths adds every path that is not already shared and returns how many were
// new. Unreadable paths are reported through the error, but the readable ones
// are still added.
func (s *Store) AddPaths(paths []string) (int, error) {
	s.mu.Lock()

	existing := make(map[string]bool, len(s.items))
	for _, item := range s.items {
		existing[item.Path] = true
	}

	var added int
	var failures []string
	for _, raw := range paths {
		abs, err := filepath.Abs(raw)
		if err != nil {
			failures = append(failures, filepath.Base(raw))
			continue
		}
		if resolved, err := filepath.EvalSymlinks(abs); err == nil {
			abs = resolved
		}
		if existing[abs] {
			continue
		}
		info, err := os.Stat(abs)
		if err != nil {
			failures = append(failures, filepath.Base(abs))
			continue
		}
		item := buildItem(abs, info)
		s.items = append(s.items, item)
		existing[abs] = true
		added++
	}
	s.mu.Unlock()

	if added > 0 {
		s.notify()
	}
	if len(failures) > 0 {
		return added, errors.New("no se pudieron añadir: " + strings.Join(failures, ", "))
	}
	return added, nil
}

func buildItem(abs string, info os.FileInfo) *Item {
	item := &Item{
		ID:      hashID(abs),
		Name:    filepath.Base(abs),
		Path:    abs,
		AddedAt: time.Now(),
	}
	if info.IsDir() {
		item.Kind = KindFolder
		item.scanFolder()
		return item
	}
	item.Kind = KindFile
	item.Ext = extOf(info.Name())
	item.Size = info.Size()
	item.FileCount = 1
	item.entries = []Entry{{
		ID:      hashID(abs),
		Name:    info.Name(),
		ZipPath: info.Name(),
		Path:    abs,
		Size:    info.Size(),
		ModTime: info.ModTime(),
		Ext:     item.Ext,
	}}
	return item
}

// scanFolder walks a folder item and rebuilds its entry list. It must be called
// with the item not shared across goroutines, or under the store lock.
func (it *Item) scanFolder() {
	entries := make([]Entry, 0, 64)
	var total int64

	root := it.Path
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			// An unreadable subtree should not abort the whole scan.
			if d != nil && d.IsDir() {
				return fs.SkipDir
			}
			return nil
		}
		name := d.Name()
		if path != root && isHidden(name) {
			if d.IsDir() {
				return fs.SkipDir
			}
			return nil
		}
		if d.IsDir() {
			return nil
		}
		if !d.Type().IsRegular() {
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return nil
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			rel = name
		}
		entries = append(entries, Entry{
			ID:      hashID(path),
			Name:    name,
			ZipPath: filepath.ToSlash(filepath.Join(it.Name, rel)),
			Path:    path,
			Size:    info.Size(),
			ModTime: info.ModTime(),
			Folder:  it.Name,
			Ext:     extOf(name),
		})
		total += info.Size()
		if len(entries) >= maxFolderEntries {
			return fs.SkipAll
		}
		return nil
	})

	sort.Slice(entries, func(a, b int) bool { return entries[a].ZipPath < entries[b].ZipPath })

	it.entries = entries
	it.FileCount = len(entries)
	it.Size = total
	it.Missing = err != nil && !os.IsPermission(err)
}

// Rescan refreshes folder contents and the missing flag on every item. It is
// throttled, so callers may invoke it on every request; pass force to bypass.
func (s *Store) Rescan(force bool) {
	s.mu.Lock()
	if !force && time.Since(s.lastScan) < rescanInterval {
		s.mu.Unlock()
		return
	}
	s.lastScan = time.Now()

	changed := false
	for _, item := range s.items {
		info, err := os.Stat(item.Path)
		if err != nil {
			if !item.Missing {
				item.Missing = true
				changed = true
			}
			continue
		}
		if item.Missing {
			item.Missing = false
			changed = true
		}
		if item.Kind == KindFolder {
			before := folderSignature(item)
			item.scanFolder()
			if folderSignature(item) != before {
				changed = true
			}
			continue
		}
		if info.Size() != item.Size {
			item.Size = info.Size()
			if len(item.entries) == 1 {
				item.entries[0].Size = info.Size()
				item.entries[0].ModTime = info.ModTime()
			}
			changed = true
		}
	}
	s.mu.Unlock()

	if changed {
		s.notify()
	}
}

// folderSignature is a cheap fingerprint used to detect that a rescan actually
// changed a folder's contents.
func folderSignature(item *Item) string {
	return strconv.Itoa(item.FileCount) + ":" + strconv.FormatInt(item.Size, 10)
}

// Remove drops the given item ids and reports how many were removed.
func (s *Store) Remove(ids []string) int {
	wanted := make(map[string]bool, len(ids))
	for _, id := range ids {
		wanted[id] = true
	}

	s.mu.Lock()
	kept := s.items[:0]
	removed := 0
	for _, item := range s.items {
		if wanted[item.ID] {
			removed++
			continue
		}
		kept = append(kept, item)
	}
	s.items = kept
	s.mu.Unlock()

	if removed > 0 {
		s.notify()
	}
	return removed
}

// Clear removes every shared item.
func (s *Store) Clear() {
	s.mu.Lock()
	had := len(s.items) > 0
	s.items = nil
	s.mu.Unlock()
	if had {
		s.notify()
	}
}

// IsEmpty reports whether nothing is shared.
func (s *Store) IsEmpty() bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.items) == 0
}

// Items returns a snapshot copy of the shared items, newest last.
func (s *Store) Items() []Item {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]Item, 0, len(s.items))
	for _, item := range s.items {
		copied := *item
		copied.entries = nil
		out = append(out, copied)
	}
	return out
}

// ItemPath resolves an item id to its path on disk.
func (s *Store) ItemPath(id string) (string, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, item := range s.items {
		if item.ID == id {
			return item.Path, true
		}
	}
	return "", false
}

// Entries returns every downloadable file across all shared items, with loose
// files first and folder contents after, each in a stable order.
func (s *Store) Entries() []Entry {
	s.mu.RLock()
	defer s.mu.RUnlock()

	var loose, grouped []Entry
	for _, item := range s.items {
		if item.Missing {
			continue
		}
		if item.Kind == KindFile {
			loose = append(loose, item.entries...)
			continue
		}
		grouped = append(grouped, item.entries...)
	}
	return append(loose, grouped...)
}

// Entry resolves a download id to a single file.
func (s *Store) Entry(id string) (Entry, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, item := range s.items {
		if item.Missing {
			continue
		}
		for _, entry := range item.entries {
			if entry.ID == id {
				return entry, true
			}
		}
	}
	return Entry{}, false
}

// Folders lists the folder items, for the grouped view on the public page.
func (s *Store) Folders() []Item {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var out []Item
	for _, item := range s.items {
		if item.Kind == KindFolder && !item.Missing {
			copied := *item
			copied.entries = nil
			out = append(out, copied)
		}
	}
	return out
}

// Totals summarises the shared set.
func (s *Store) Totals() Totals {
	s.mu.RLock()
	defer s.mu.RUnlock()
	totals := Totals{Items: len(s.items)}
	for _, item := range s.items {
		if item.Missing {
			continue
		}
		totals.Files += item.FileCount
		totals.Bytes += item.Size
	}
	return totals
}
