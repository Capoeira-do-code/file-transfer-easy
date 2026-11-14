// Package publicweb serves the share page and the downloads that recipients
// reach through the cloudflared tunnel.
//
// Every route lives under /s/<token>. Administrative controls remain on a
// separate loopback server. Recipients can read authorized files and, only
// when enabled by the host, send files to the configured upload directory.
package publicweb

import (
	"crypto/subtle"
	"encoding/json"
	"io/fs"
	"net"
	"net/http"
	"strings"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/access"
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/activity"
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/core"
)

// Server answers public requests for one share session.
type Server struct {
	assets   fs.FS
	store    *core.Store
	tracker  *activity.Tracker
	access   *access.Manager
	onUpload func([]string) error
	token    string
	mux      *http.ServeMux
}

// New builds a handler for a share session identified by token. assets is the
// embedded page bundle (index.html, style.css, app.js), injected so the embed
// directive can live next to the files themselves.
type Options struct {
	Access   *access.Manager
	OnUpload func([]string) error
}

func New(assets fs.FS, store *core.Store, tracker *activity.Tracker, token string, options ...Options) http.Handler {
	s := &Server{assets: assets, store: store, tracker: tracker, token: token}
	if len(options) > 0 {
		s.access = options[0].Access
		s.onUpload = options[0].OnUpload
	}

	mux := http.NewServeMux()
	// The page lives at the trailing-slash form so that the relative asset
	// paths inside it resolve under /s/<token>/ rather than /s/.
	mux.HandleFunc("GET /s/{token}/{$}", s.handlePage)
	mux.HandleFunc("GET /s/{token}", s.redirectToPage)
	mux.HandleFunc("GET /s/{token}/assets/{name}", s.handleAsset)
	mux.HandleFunc("GET /s/{token}/api/manifest", s.handleManifest)
	mux.HandleFunc("GET /s/{token}/api/access", s.handleAccess)
	mux.HandleFunc("POST /s/{token}/api/access", s.handleAccess)
	mux.HandleFunc("POST /s/{token}/api/unlock", s.handleUnlock)
	mux.HandleFunc("GET /s/{token}/api/download/{id}", s.handleDownloadCheck)
	mux.HandleFunc("GET /s/{token}/api/zip", s.handleZipCheck)
	mux.HandleFunc("POST /s/{token}/upload", s.handleUpload)
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
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host = r.RemoteAddr
	}
	remote := net.ParseIP(strings.TrimSpace(host))
	// Only the loopback tunnel transport can supply forwarded identities.
	// A direct LAN client must not bypass a blocked IP with a forged header.
	if remote != nil && remote.IsLoopback() {
		for _, header := range []string{"CF-Connecting-IP", "X-Forwarded-For", "X-Real-IP"} {
			value := strings.TrimSpace(strings.SplitN(r.Header.Get(header), ",", 2)[0])
			if ip := net.ParseIP(value); ip != nil {
				return ip.String()
			}
		}
	}
	if remote != nil {
		return remote.String()
	}
	return ""
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(payload)
}
