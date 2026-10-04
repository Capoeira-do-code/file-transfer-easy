package app

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/tunnel"
)

type fakeTunnel struct {
	mu      sync.Mutex
	running bool
	start   func(context.Context) (string, error)
	exit    func(error)
	stops   int
}

func (f *fakeTunnel) Start(ctx context.Context, _ int, exit func(error)) (string, error) {
	f.mu.Lock()
	f.exit = exit
	f.mu.Unlock()
	if f.start != nil {
		if _, err := f.start(ctx); err != nil {
			return "", err
		}
	}
	f.mu.Lock()
	f.running = true
	f.mu.Unlock()
	return "https://fixture.trycloudflare.com", nil
}
func (f *fakeTunnel) Stop()         { f.mu.Lock(); f.running = false; f.stops++; f.mu.Unlock() }
func (f *fakeTunnel) Running() bool { f.mu.Lock(); defer f.mu.Unlock(); return f.running }
func (f *fakeTunnel) die() {
	f.mu.Lock()
	f.running = false
	exit := f.exit
	f.mu.Unlock()
	exit(errors.New("fixture exit"))
}

func lifecycleFixture(t *testing.T) (*App, *fakeTunnel) {
	t.Helper()
	a := New(t.TempDir(), &noopNative{}, testAssets())
	f := &fakeTunnel{}
	a.tunnel = f
	a.waitDNS = func(context.Context, string, tunnel.Logf) bool { return true }
	p := filepath.Join(t.TempDir(), "hello.txt")
	if err := os.WriteFile(p, []byte("hello"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := a.Store.AddPaths([]string{p}); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(a.Close)
	return a, f
}

func await(t *testing.T, c <-chan struct{}) {
	t.Helper()
	select {
	case <-c:
	case <-time.After(2 * time.Second):
		t.Fatal("operation did not finish promptly")
	}
}

func TestStopInterruptsPreparation(t *testing.T) {
	for _, phase := range []string{"tunnel", "dns"} {
		t.Run(phase, func(t *testing.T) {
			a, f := lifecycleFixture(t)
			entered := make(chan struct{})
			if phase == "tunnel" {
				f.start = func(ctx context.Context) (string, error) { close(entered); <-ctx.Done(); return "", ctx.Err() }
			} else {
				a.waitDNS = func(ctx context.Context, _ string, _ tunnel.Logf) bool { close(entered); <-ctx.Done(); return false }
			}
			finished := make(chan struct{})
			go func() { defer close(finished); a.StartShare() }()
			await(t, entered)
			stopped := make(chan struct{})
			go func() { defer close(stopped); a.StopShare() }()
			await(t, stopped)
			await(t, finished)
			s := a.Snapshot().Share
			if s.Status != "stopped" || s.URL != "" || s.LanURL != "" || f.Running() {
				t.Fatalf("incomplete shutdown: %+v", s)
			}
		})
	}
}

func TestDNSFailureDoesNotPublishAndRetryClosesOldServer(t *testing.T) {
	a, f := lifecycleFixture(t)
	a.waitDNS = func(context.Context, string, tunnel.Logf) bool { return false }
	if err := a.StartShare(); err == nil {
		t.Fatal("expected DNS failure")
	}
	if a.PublicURL() != "" || a.Status() != StatusError || f.Running() {
		t.Fatal("unverified link published")
	}
	if err := a.CopyLink(); err == nil {
		t.Fatal("copied an unverified link")
	}
	a.mu.RLock()
	port, token := a.publicPort, a.shareToken
	a.mu.RUnlock()
	old := fmt.Sprintf("http://127.0.0.1:%d/s/%s/", port, token)
	client := &http.Client{Timeout: time.Second}
	res, err := client.Get(old)
	if err != nil {
		t.Fatalf("LAN fallback unavailable: %v", err)
	}
	res.Body.Close()
	a.waitDNS = func(context.Context, string, tunnel.Logf) bool { return true }
	if err := a.StartShare(); err != nil {
		t.Fatal(err)
	}
	if a.Status() != StatusLive || a.PublicURL() == "" {
		t.Fatal("retry did not start")
	}
	if res, err := client.Get(old); err == nil {
		res.Body.Close()
		t.Fatal("old listener survived retry")
	}
}

func TestTunnelDeathClearsReadyLink(t *testing.T) {
	a, f := lifecycleFixture(t)
	if err := a.StartShare(); err != nil {
		t.Fatal(err)
	}
	if err := a.CopyLink(); err != nil {
		t.Fatal(err)
	}
	f.die()
	if a.Status() != StatusError || a.PublicURL() != "" {
		t.Fatal("dead tunnel still advertised")
	}
	if err := a.CopyLink(); err == nil {
		t.Fatal("dead link copied")
	}
}

func TestTunnelDeathDuringDNSCannotBecomeLive(t *testing.T) {
	a, f := lifecycleFixture(t)
	a.waitDNS = func(ctx context.Context, _ string, _ tunnel.Logf) bool { f.die(); return ctx.Err() == nil }
	a.StartShare()
	if a.Status() != StatusError || a.PublicURL() != "" {
		t.Fatal("dead startup became live")
	}
}

func TestClosingPreventsLaterStartup(t *testing.T) {
	a, f := lifecycleFixture(t)
	a.Close()
	if err := a.StartShare(); err == nil {
		t.Fatal("closed app restarted")
	}
	if f.Running() {
		t.Fatal("tunnel running after quit")
	}
}
