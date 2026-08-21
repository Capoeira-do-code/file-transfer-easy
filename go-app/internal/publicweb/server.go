// Package publicweb serves the share page and the downloads that recipients
// reach through the cloudflared tunnel.
//
// Every route lives under /s/<token>. Nothing here can mutate the shared set:
// the admin surface is on a separate server bound to loopback, so a leaked
// tunnel URL only ever exposes what the host chose to share.
package publicweb

import (
	"crypto/subtle"
	"encoding/json"
	"io/fs"
	"net"
	"net/http"
	"strings"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/activity"
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/core"
)

// Server answers public requests for one share session.
type Server struct {
	assets  fs.FS
	store   *core.Store
	tracker *activity.Tracker
	token   string
	mux     *http.ServeMux
}

// New builds a handler for a share session identified by token. assets is the
// embedded page bundle (index.html, style.css, app.js), injected so the embed
// directive can live next to the files themselves.
func New(assets fs.FS, store *core.Store, tracker *activity.Tracker, token string) http.Handler {
	s := &Server{assets: assets, store: store, tracker: tracker, token: token}

	mux := http.NewServeMux()
	// The page lives at the trailing-slash form so that the relative asset
	// paths inside it resolve under /s/<token>/ rather than /s/.
	mux.HandleFunc("GET /s/{token}/{$}", s.handlePage)
	mux.HandleFunc("GET /s/{token}", s.redirectToPage)
	mux.HandleFunc("GET /s/{token}/assets/{name}", s.handleAsset)
	mux.HandleFunc("GET /s/{token}/api/manifest", s.handleManifest)
	mux.HandleFunc("GET /s/{token}/download/{id}", s.handleDownload)
	mux.HandleFunc("GET /s/{token}/zip", s.handleZip)
	mux.HandleFunc("POST /s/{token}/ping", s.handlePing)
	mux.HandleFunc("/", s.handleNotFound)
	s.mux = mux

	return s
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// The page must never be cached: the host adds and removes files live.
	w.Header().Set("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Referrer-Policy", "no-referrer")
	s.mux.ServeHTTP(w, r)
}

// authorised compares the request token in constant time.
func (s *Server) authorised(r *http.Request) bool {
	given := r.PathValue("token")
	return subtle.ConstantTimeCompare([]byte(given), []byte(s.token)) == 1
}

// redirectToPage sends the bare share link to its canonical trailing-slash form.
func (s *Server) redirectToPage(w http.ResponseWriter, r *http.Request) {
	http.Redirect(w, r, r.URL.EscapedPath()+"/", http.StatusFound)
}

func (s *Server) handleNotFound(w http.ResponseWriter, r *http.Request) {
	http.Error(w, "No encontrado", http.StatusNotFound)
}

// clientIP resolves the caller's address, trusting the header cloudflared sets
// ahead of the generic proxy headers.
func clientIP(r *http.Request) string {
	if value := strings.TrimSpace(r.Header.Get("CF-Connecting-IP")); value != "" {
		return value
	}
	if value := r.Header.Get("X-Forwarded-For"); value != "" {
		if first, _, found := strings.Cut(value, ","); found {
			return strings.TrimSpace(first)
		}
		return strings.TrimSpace(value)
	}
	if value := strings.TrimSpace(r.Header.Get("X-Real-IP")); value != "" {
		return value
	}
	if host, _, err := net.SplitHostPort(r.RemoteAddr); err == nil {
		return host
	}
	return r.RemoteAddr
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(payload)
}
