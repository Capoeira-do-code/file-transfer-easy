//go:build !windows

package tunnel

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func stubCloudflared(t *testing.T, body string) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "cloudflared"), []byte("#!/bin/sh\n"+body), 0755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir)
	return dir
}

func TestRunnerStartupCancellationKillsProcess(t *testing.T) {
	dir := stubCloudflared(t, "exec /bin/sleep 60\n")
	runner := NewRunner(dir, nil)
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	started := time.Now()
	if _, err := runner.Start(ctx, 1234, nil); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("unexpected result: %v", err)
	}
	if time.Since(started) > time.Second {
		t.Fatal("startup cancellation waited for process timeout")
	}
	if runner.Running() {
		t.Fatal("cancelled process still registered")
	}
}

func TestIntentionalStopDoesNotNotifyExit(t *testing.T) {
	dir := stubCloudflared(t, "echo https://fixture.trycloudflare.com >&2\nexec /bin/sleep 60\n")
	runner := NewRunner(dir, nil)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	exits := make(chan error, 1)
	url, err := runner.Start(ctx, 1234, func(err error) { exits <- err })
	if err != nil || url != "https://fixture.trycloudflare.com" {
		t.Fatalf("startup failed: %s %v", url, err)
	}
	runner.Stop()
	if runner.Running() {
		t.Fatal("stopped process still registered")
	}
	select {
	case err := <-exits:
		t.Fatalf("intentional shutdown notified failure: %v", err)
	case <-time.After(50 * time.Millisecond):
	}
}
