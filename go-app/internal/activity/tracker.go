// Package activity tracks who is looking at the share link and what they are
// downloading, so the desktop window can show it live.
package activity

import (
	"crypto/sha1"
	"encoding/hex"
	"fmt"
	"sort"
	"sync"
	"time"
)

const (
	// onlineWindow is how long after its last heartbeat a visitor still counts
	// as present. The public page pings every 10s.
	onlineWindow = 25 * time.Second
	// visitorTTL drops visitors that have been gone for a long while.
	visitorTTL = 90 * time.Minute
	// maxVisitors caps the list shown in the UI.
	maxVisitors = 50
	// finishedKept is how many completed transfers stay on screen.
	finishedKept = 20
	// maxLog caps the activity log.
	maxLog = 200
)

// Visitor is one person who opened the share link, identified by IP.
type Visitor struct {
	ID        string
	IP        string
	Label     string
	FirstSeen time.Time
	LastSeen  time.Time
	Downloads int
	Bytes     int64
}

// Online reports whether the visitor has pinged recently.
func (v Visitor) Online() bool { return time.Since(v.LastSeen) <= onlineWindow }

// Transfer is a single download in flight, or one that recently finished.
type Transfer struct {
	ID       string
	Name     string
	IP       string
	Kind     string // "file", "zip" or "upload"
	Status   string // active, done, cancelled, error
	Bytes    int64
	Total    int64
	Speed    float64
	Started  time.Time
	Updated  time.Time
	Finished time.Time

	cancel     chan struct{}
	cancelOnce sync.Once
	sampleAt   time.Time
	sampleByte int64
}

// Cancelled exposes the channel a streaming handler selects on to abort.
func (t *Transfer) Cancelled() <-chan struct{} { return t.cancel }

// TransferSnapshot is a copyable view of a Transfer. Transfer itself carries a
// sync.Once for cancellation and must never be copied, so the UI gets this.
type TransferSnapshot struct {
	ID       string
	Name     string
	IP       string
	Kind     string
	Status   string
	Bytes    int64
	Total    int64
	Speed    float64
	Started  time.Time
	Updated  time.Time
	Finished time.Time
}

// Stats are the cumulative counters shown in the window.
type Stats struct {
	Downloads     int
	Bytes         int64
	Visitors      int
	Uploads       int
	ReceivedBytes int64
}

// LogEntry is one line of the activity log.
type LogEntry struct {
	Time  time.Time
	Level string // info, warn, error
	Text  string
}

// Tracker owns all live activity state.
type Tracker struct {
	mu         sync.RWMutex
	visitors   map[string]*Visitor
	suppressed map[string]bool
	transfers  []*Transfer
	stats      Stats
	log        []LogEntry

	onChange func()
}

// New returns a tracker. onChange, if non-nil, is called whenever something
// worth re-rendering happened.
func New(onChange func()) *Tracker {
	return &Tracker{
		visitors:   make(map[string]*Visitor),
		suppressed: make(map[string]bool),
		onChange:   onChange,
	}
}

func (t *Tracker) notify() {
	if t.onChange != nil {
		t.onChange()
	}
}

func idFor(value string) string {
	sum := sha1.Sum([]byte(value))
	return hex.EncodeToString(sum[:])[:12]
}

// Seen records a visitor heartbeat or page view, creating the visitor if new.
func (t *Tracker) Seen(ip, userAgent string) {
	if ip == "" {
		return
	}
	now := time.Now()

	t.mu.Lock()
	if t.suppressed[ip] {
		t.mu.Unlock()
		return
	}
	visitor, ok := t.visitors[ip]
	fresh := !ok
	if !ok {
		visitor = &Visitor{
			ID:        idFor(ip),
			IP:        ip,
			Label:     DescribeUserAgent(userAgent),
			FirstSeen: now,
		}
		t.visitors[ip] = visitor
		t.stats.Visitors++
	}
	wasOffline := now.Sub(visitor.LastSeen) > onlineWindow
	visitor.LastSeen = now
	if userAgent != "" {
		visitor.Label = DescribeUserAgent(userAgent)
	}
	t.pruneVisitorsLocked(now)
	t.mu.Unlock()

	if fresh {
		t.Logf("info", "Nueva visita desde %s", ip)
	}
	if fresh || wasOffline {
		t.notify()
	}
}

// Visit marks an actual page opening, unlike a background heartbeat. A person
// removed from the live list can appear again after deliberately reopening it.
func (t *Tracker) Visit(ip, userAgent string) {
	t.mu.Lock()
	delete(t.suppressed, ip)
	t.mu.Unlock()
	t.Seen(ip, userAgent)
}

func (t *Tracker) pruneVisitorsLocked(now time.Time) {
	if len(t.visitors) <= maxVisitors {
		for ip, visitor := range t.visitors {
			if now.Sub(visitor.LastSeen) > visitorTTL {
				delete(t.visitors, ip)
			}
		}
		return
	}
	// Over the cap: drop the least recently seen first.
	all := make([]*Visitor, 0, len(t.visitors))
	for _, visitor := range t.visitors {
		all = append(all, visitor)
	}
	sort.Slice(all, func(a, b int) bool { return all[a].LastSeen.After(all[b].LastSeen) })
	for _, visitor := range all[maxVisitors:] {
		delete(t.visitors, visitor.IP)
	}
}

// Forget drops a visitor from the list by id.
func (t *Tracker) Forget(id string) bool {
	t.mu.Lock()
	var found bool
	for ip, visitor := range t.visitors {
		if visitor.ID == id {
			delete(t.visitors, ip)
			t.suppressed[ip] = true
			found = true
			break
		}
	}
	t.mu.Unlock()
	if found {
		t.notify()
	}
	return found
}

// StartTransfer registers a download that is about to begin streaming.
func (t *Tracker) StartTransfer(kind, name, ip string, total int64) *Transfer {
	now := time.Now()
	transfer := &Transfer{
		ID:       idFor(name + ip + now.Format(time.RFC3339Nano)),
		Name:     name,
		IP:       ip,
		Kind:     kind,
		Status:   "active",
		Total:    total,
		Started:  now,
		Updated:  now,
		cancel:   make(chan struct{}),
		sampleAt: now,
	}

	t.mu.Lock()
	t.transfers = append(t.transfers, transfer)
	t.pruneTransfersLocked()
	t.mu.Unlock()

	if kind == "upload" {
		t.Logf("info", "%s empieza a enviar %s", ip, name)
	} else {
		t.Logf("info", "%s empieza a descargar %s", ip, name)
	}
	t.notify()
	return transfer
}

// Progress updates the byte counter and the smoothed speed of a transfer.
// It does not notify: the SSE loop ticks while transfers are active, which
// keeps per-chunk overhead off the hot path.
func (t *Tracker) Progress(transfer *Transfer, sent int64) {
	now := time.Now()

	t.mu.Lock()
	transfer.Bytes = sent
	transfer.Updated = now
	if elapsed := now.Sub(transfer.sampleAt); elapsed >= 400*time.Millisecond {
		instant := float64(sent-transfer.sampleByte) / elapsed.Seconds()
		if transfer.Speed == 0 {
			transfer.Speed = instant
		} else {
			// Exponential moving average keeps the readout from jittering.
			transfer.Speed = transfer.Speed*0.65 + instant*0.35
		}
		transfer.sampleAt = now
		transfer.sampleByte = sent
	}
	t.mu.Unlock()
}

// FinishTransfer closes out a transfer with a final status.
func (t *Tracker) FinishTransfer(transfer *Transfer, status string) {
	now := time.Now()

	t.mu.Lock()
	transfer.Status = status
	transfer.Finished = now
	transfer.Updated = now
	if status == "done" {
		if transfer.Total > 0 {
			transfer.Bytes = transfer.Total
		}
		if transfer.Kind == "upload" {
			t.stats.Uploads++
			t.stats.ReceivedBytes += transfer.Bytes
		} else {
			t.stats.Downloads++
			t.stats.Bytes += transfer.Bytes
			if visitor, ok := t.visitors[transfer.IP]; ok {
				visitor.Downloads++
				visitor.Bytes += transfer.Bytes
				visitor.LastSeen = now
			}
		}
	}
	t.pruneTransfersLocked()
	t.mu.Unlock()

	switch status {
	case "done":
		t.Logf("info", "%s completó %s", transfer.IP, transfer.Name)
	case "cancelled":
		t.Logf("warn", "Transferencia cancelada: %s", transfer.Name)
	case "error":
		t.Logf("error", "Fallo en la transferencia de %s", transfer.Name)
	}
	t.notify()
}

func (t *Tracker) pruneTransfersLocked() {
	var finished int
	for _, transfer := range t.transfers {
		if transfer.Status != "active" {
			finished++
		}
	}
	if finished <= finishedKept {
		return
	}
	drop := finished - finishedKept
	kept := make([]*Transfer, 0, len(t.transfers)-drop)
	for _, transfer := range t.transfers {
		if drop > 0 && transfer.Status != "active" {
			drop--
			continue
		}
		kept = append(kept, transfer)
	}
	t.transfers = kept
}

// Cancel aborts an in-flight transfer by id.
func (t *Tracker) Cancel(id string) bool {
	t.mu.RLock()
	var target *Transfer
	for _, transfer := range t.transfers {
		if transfer.ID == id && transfer.Status == "active" {
			target = transfer
			break
		}
	}
	t.mu.RUnlock()

	if target == nil {
		return false
	}
	target.cancelOnce.Do(func() { close(target.cancel) })
	return true
}

// CancelIP aborts active transfers belonging to a blocked visitor.
func (t *Tracker) CancelIP(ip string) {
	t.mu.RLock()
	var active []*Transfer
	for _, transfer := range t.transfers {
		if transfer.IP == ip && transfer.Status == "active" {
			active = append(active, transfer)
		}
	}
	t.mu.RUnlock()
	for _, transfer := range active {
		transfer.cancelOnce.Do(func() { close(transfer.cancel) })
	}
}

// CancelAll aborts every in-flight transfer, used when sharing stops.
func (t *Tracker) CancelAll() {
	t.mu.RLock()
	active := make([]*Transfer, 0, len(t.transfers))
	for _, transfer := range t.transfers {
		if transfer.Status == "active" {
			active = append(active, transfer)
		}
	}
	t.mu.RUnlock()

	for _, transfer := range active {
		transfer.cancelOnce.Do(func() { close(transfer.cancel) })
	}
}

// HasActive reports whether any transfer is streaming right now, which the SSE
// loop uses to decide whether to keep ticking.
func (t *Tracker) HasActive() bool {
	t.mu.RLock()
	defer t.mu.RUnlock()
	for _, transfer := range t.transfers {
		if transfer.Status == "active" {
			return true
		}
	}
	return false
}

// Logf appends a line to the activity log.
func (t *Tracker) Logf(level, format string, args ...any) {
	text := format
	if len(args) > 0 {
		text = fmt.Sprintf(format, args...)
	}
	t.mu.Lock()
	t.log = append(t.log, LogEntry{Time: time.Now(), Level: level, Text: text})
	if len(t.log) > maxLog {
		t.log = append(t.log[:0], t.log[len(t.log)-maxLog:]...)
	}
	t.mu.Unlock()
	t.notify()
}

// Snapshot returns copies of everything the UI renders.
func (t *Tracker) Snapshot() ([]Visitor, []TransferSnapshot, Stats, []LogEntry) {
	t.mu.RLock()
	defer t.mu.RUnlock()

	visitors := make([]Visitor, 0, len(t.visitors))
	for _, visitor := range t.visitors {
		visitors = append(visitors, *visitor)
	}
	sort.Slice(visitors, func(a, b int) bool {
		if visitors[a].Online() != visitors[b].Online() {
			return visitors[a].Online()
		}
		return visitors[a].LastSeen.After(visitors[b].LastSeen)
	})

	transfers := make([]TransferSnapshot, 0, len(t.transfers))
	for _, transfer := range t.transfers {
		transfers = append(transfers, TransferSnapshot{
			ID:       transfer.ID,
			Name:     transfer.Name,
			IP:       transfer.IP,
			Kind:     transfer.Kind,
			Status:   transfer.Status,
			Bytes:    transfer.Bytes,
			Total:    transfer.Total,
			Speed:    transfer.Speed,
			Started:  transfer.Started,
			Updated:  transfer.Updated,
			Finished: transfer.Finished,
		})
	}
	sort.Slice(transfers, func(a, b int) bool {
		if (transfers[a].Status == "active") != (transfers[b].Status == "active") {
			return transfers[a].Status == "active"
		}
		return transfers[a].Started.After(transfers[b].Started)
	})

	logs := make([]LogEntry, len(t.log))
	copy(logs, t.log)

	// stats.Visitors is the cumulative count of distinct visitors seen, which
	// is more useful than the currently-listed count the UI can already see.
	return visitors, transfers, t.stats, logs
}

// Reset clears live state when the user stops sharing, keeping the log.
func (t *Tracker) Reset() {
	t.mu.Lock()
	t.visitors = make(map[string]*Visitor)
	t.suppressed = make(map[string]bool)
	t.transfers = nil
	t.mu.Unlock()
	t.notify()
}
