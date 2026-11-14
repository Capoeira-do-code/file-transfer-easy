// Package uiserver exposes the desktop window's API over loopback.
//
// The Wails webview loads this server rather than Wails' own asset server, so
// the frontend is plain HTML talking plain HTTP: no generated bindings, no
// runtime JS, and the whole UI can be opened in a normal browser while
// developing. Every route is guarded by a per-run token, so nothing else on the
// machine can drive the app.
package uiserver

import (
	"crypto/subtle"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"mime"
	"net"
	"net/http"
	"path"
	"strconv"
	"strings"
	"time"

	"github.com/skip2/go-qrcode"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/app"
)

// Server is the loopback API behind the desktop window.
type Server struct {
	core   *app.App
	assets fs.FS
	token  string
	mux    *http.ServeMux

	listener net.Listener
	http     *http.Server
}

// New builds the UI server. assets is the embedded frontend bundle.
func New(core *app.App, assets fs.FS, token string) *Server {
	s := &Server{core: core, assets: assets, token: token}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /{$}", s.handleIndex)
	// index.html links its assets by bare relative path, so they are served
	// from the root. This pattern is less specific than every /api/... route,
	// so the mux still prefers those.
	mux.HandleFunc("GET /{name}", s.handleAsset)
	mux.HandleFunc("GET /api/state", s.guard(s.handleState))
	mux.HandleFunc("GET /api/events", s.handleEvents)
	mux.HandleFunc("GET /api/qr.png", s.guard(s.handleQR))

	mux.HandleFunc("POST /api/items/add-files", s.action(func(*http.Request) error {
		return core.AddFilesDialog()
	}))
	mux.HandleFunc("POST /api/items/add-folder", s.action(func(*http.Request) error {
		return core.AddFolderDialog()
	}))
	mux.HandleFunc("POST /api/items/remove", s.action(func(r *http.Request) error {
		var body struct {
			IDs []string `json:"ids"`
		}
		if err := decode(r, &body); err != nil {
			return err
		}
		return core.RemoveItems(body.IDs)
	}))
	mux.HandleFunc("POST /api/items/clear", s.action(func(*http.Request) error {
		return core.ClearItems()
	}))
	mux.HandleFunc("POST /api/items/reveal", s.action(func(r *http.Request) error {
		var body struct {
			ID string `json:"id"`
		}
		if err := decode(r, &body); err != nil {
			return err
		}
		return core.RevealItem(body.ID)
	}))
	mux.HandleFunc("POST /api/share/start", s.action(func(*http.Request) error {
		return core.StartShare()
	}))
	mux.HandleFunc("POST /api/share/stop", s.action(func(*http.Request) error {
		return core.StopShare()
	}))
	mux.HandleFunc("POST /api/share/copy", s.action(func(*http.Request) error {
		return core.CopyLink()
	}))
	mux.HandleFunc("POST /api/share/open", s.action(func(*http.Request) error {
		return core.OpenPublicPage()
	}))
	mux.HandleFunc("POST /api/transfers/cancel", s.action(func(r *http.Request) error {
		var body struct {
			ID string `json:"id"`
		}
		if err := decode(r, &body); err != nil {
			return err
		}
		return core.CancelTransfer(body.ID)
	}))
	mux.HandleFunc("POST /api/visitors/forget", s.action(func(r *http.Request) error {
		var body struct {
			ID string `json:"id"`
		}
		if err := decode(r, &body); err != nil {
			return err
		}
		return core.ForgetVisitor(body.ID)
	}))
	mux.HandleFunc("POST /api/window/minimise", s.action(func(*http.Request) error {
		core.MinimiseWindow()
		return nil
	}))
	mux.HandleFunc("POST /api/window/hide", s.action(func(*http.Request) error {
		core.HideWindow()
		return nil
	}))
	s.registerSettingsRoutes(mux)

	s.mux = mux
	return s
}

// Start binds the server to a random loopback port and returns the URL the
// window should load.
func (s *Server) Start() (string, error) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return "", fmt.Errorf("no se pudo abrir el puerto de la interfaz: %w", err)
	}
	s.listener = listener
	s.http = &http.Server{
		Handler:           s,
		ReadHeaderTimeout: 10 * time.Second,
	}

	go s.http.Serve(listener)

	port := listener.Addr().(*net.TCPAddr).Port
	return fmt.Sprintf("http://127.0.0.1:%d/", port), nil
}

// Close shuts the server down.
func (s *Server) Close() {
	if s.http != nil {
		s.http.Close()
	}
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Body != nil && strings.HasPrefix(r.URL.Path, "/api/") {
		r.Body = http.MaxBytesReader(w, r.Body, 64<<10)
	}
	s.mux.ServeHTTP(w, r)
}

// authorised accepts the token from the header, or from the query string for
// EventSource, which cannot set headers.
func (s *Server) authorised(r *http.Request) bool {
	given := r.Header.Get("X-FTE-Token")
	if given == "" {
		given = r.URL.Query().Get("t")
	}
	return subtle.ConstantTimeCompare([]byte(given), []byte(s.token)) == 1
}

// guard rejects unauthorised callers.
func (s *Server) guard(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !s.authorised(r) {
			http.Error(w, "No autorizado", http.StatusUnauthorized)
			return
		}
		next(w, r)
	}
}

// action wraps a mutating endpoint into the {"ok":…} envelope the UI expects.
func (s *Server) action(run func(*http.Request) error) http.HandlerFunc {
	return s.guard(func(w http.ResponseWriter, r *http.Request) {
		if err := run(r); err != nil {
			writeJSON(w, http.StatusOK, map[string]any{"ok": false, "error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"ok": true})
	})
}

// ------------------------------------------------------------------ endpoints

func (s *Server) handleIndex(w http.ResponseWriter, r *http.Request) {
	page, err := fs.ReadFile(s.assets, "index.html")
	if err != nil {
		http.Error(w, "No se pudo cargar la interfaz", http.StatusInternalServerError)
		return
	}
	// Only the quoted placeholder is replaced, never the bare identifier: the
	// page declares `window.__FTE_TOKEN__="__FTE_TOKEN__"`, and a blind
	// ReplaceAll would rewrite the variable name too. strconv.Quote also
	// escapes the value, so an odd token cannot break out of the string.
	body := strings.ReplaceAll(string(page), `"__FTE_TOKEN__"`, strconv.Quote(s.token))

	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write([]byte(body))
}

func (s *Server) handleAsset(w http.ResponseWriter, r *http.Request) {
	name := path.Base(r.PathValue("name"))
	data, err := fs.ReadFile(s.assets, name)
	if err != nil {
		http.Error(w, "No encontrado", http.StatusNotFound)
		return
	}

	// These are application assets, not user files. In particular, Windows
	// file associations can override mime.TypeByExtension with a type that
	// WebView2 refuses to execute or apply, preventing the UI from loading.
	var contentType string
	switch path.Ext(name) {
	case ".js":
		contentType = "text/javascript; charset=utf-8"
	case ".css":
		contentType = "text/css; charset=utf-8"
	default:
		contentType = mime.TypeByExtension(path.Ext(name))
		if contentType == "" {
			contentType = "application/octet-stream"
		}
	}
	w.Header().Set("Content-Type", contentType)
	w.Write(data)
}

func (s *Server) handleState(w http.ResponseWriter, r *http.Request) {
	s.core.Store.Rescan(false)
	writeJSON(w, http.StatusOK, s.core.Snapshot())
}

func (s *Server) handleQR(w http.ResponseWriter, r *http.Request) {
	url := s.core.PublicURL()
	if url == "" {
		http.Error(w, "Todavía no hay enlace", http.StatusNotFound)
		return
	}

	// Medium recovery keeps the code readable at small sizes without making the
	// modules too dense for a phone camera.
	png, err := qrcode.Encode(url, qrcode.Medium, 512)
	if err != nil {
		http.Error(w, "No se pudo generar el código QR", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "image/png")
	w.Write(png)
}

// handleEvents streams application state to the window over SSE.
func (s *Server) handleEvents(w http.ResponseWriter, r *http.Request) {
	if !s.authorised(r) {
		http.Error(w, "No autorizado", http.StatusUnauthorized)
		return
	}
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "Streaming no soportado", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)

	updates, unsubscribe := s.core.Subscribe()
	defer unsubscribe()

	// Send the current state immediately so the page never renders empty while
	// waiting for the first change.
	if payload, err := json.Marshal(s.core.Snapshot()); err == nil {
		writeEvent(w, payload)
		flusher.Flush()
	}

	// A comment line every 20s keeps intermediaries from closing an idle stream.
	keepalive := time.NewTicker(20 * time.Second)
	defer keepalive.Stop()

	for {
		select {
		case <-r.Context().Done():
			return

		case payload, open := <-updates:
			if !open {
				return
			}
			writeEvent(w, payload)
			flusher.Flush()

		case <-keepalive.C:
			fmt.Fprint(w, ": keepalive\n\n")
			flusher.Flush()
		}
	}
}

func writeEvent(w http.ResponseWriter, payload []byte) {
	fmt.Fprint(w, "event: state\ndata: ")
	w.Write(payload)
	fmt.Fprint(w, "\n\n")
}

// --------------------------------------------------------------------- helpers

func decode(r *http.Request, target any) error {
	defer r.Body.Close()
	decoder := json.NewDecoder(r.Body)
	if err := decoder.Decode(target); err != nil {
		return fmt.Errorf("petición mal formada: %w", err)
	}
	if err := decoder.Decode(new(any)); err != io.EOF {
		return fmt.Errorf("la petición debe contener un único objeto JSON")
	}
	return nil
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(payload)
}
