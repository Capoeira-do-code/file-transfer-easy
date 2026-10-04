package tunnel

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestDownloadCancellation(t *testing.T) {
	entered := make(chan struct{})
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { close(entered); <-r.Context().Done() }))
	defer s.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	result := make(chan error, 1)
	target := filepath.Join(t.TempDir(), "binary")
	go func() { result <- download(ctx, s.URL, target, false) }()
	select {
	case <-entered:
	case <-time.After(time.Second):
		t.Fatal("request did not start")
	}
	cancel()
	select {
	case err := <-result:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("unexpected error: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("download ignored cancellation")
	}
}

func TestCancelledDNSReturnsImmediately(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	done := make(chan bool, 1)
	go func() { done <- WaitUntilResolvable(ctx, "https://fixture.trycloudflare.com", nil) }()
	select {
	case ok := <-done:
		if ok {
			t.Fatal("cancelled DNS reported ready")
		}
	case <-time.After(time.Second):
		t.Fatal("DNS ignored cancellation")
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestCancelledInstallLeavesNoCachedBinary(t *testing.T) {
	t.Setenv("PATH", t.TempDir())
	dir := t.TempDir()
	entered := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.(http.Flusher).Flush()
		close(entered)
		<-r.Context().Done()
	}))
	defer server.Close()
	local, err := url.Parse(server.URL)
	if err != nil {
		t.Fatal(err)
	}
	// Keep the production installer and HTTP cancellation path, while serving
	// the archive locally so the regression test does not depend on GitHub.
	original := http.DefaultTransport
	http.DefaultTransport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
		copy := r.Clone(r.Context())
		copy.URL = local
		return original.RoundTrip(copy)
	})
	defer func() { http.DefaultTransport = original }()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	result := make(chan error, 1)
	go func() { _, err := Ensure(ctx, dir, nil); result <- err }()
	select {
	case <-entered:
	case <-time.After(time.Second):
		t.Fatal("install download did not start")
	}
	cancel()
	select {
	case err := <-result:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("cancelled install returned %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("install ignored cancellation")
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 0 {
		t.Fatalf("cancelled install left cache files: %v", entries)
	}
}
