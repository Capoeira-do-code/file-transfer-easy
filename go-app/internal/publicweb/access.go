package publicweb

import (
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/access"
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/activity"
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/core"
)

const sessionCookie = "fte_session"

func (s *Server) publicSettings() access.SettingsView {
	if s.access != nil {
		return s.access.Settings()
	}
	return access.SettingsView{Theme: "light", MaxUploadMB: 1024, PageTitle: "Archivos compartidos"}
}
func (s *Server) sessionID(r *http.Request) string {
	cookie, err := r.Cookie(sessionCookie)
	if err != nil {
		return ""
	}
	return cookie.Value
}
func secureRequest(r *http.Request) bool {
	if r.TLS != nil {
		return true
	}
	host, _, _ := net.SplitHostPort(r.RemoteAddr)
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback() && strings.EqualFold(r.Header.Get("X-Forwarded-Proto"), "https")
}
func (s *Server) ensureSession(w http.ResponseWriter, r *http.Request) (string, error) {
	if s.access == nil {
		return "", nil
	}
	if s.access.IsBlocked(clientIP(r)) {
		return "", nil
	}
	id := s.sessionID(r)
	ip := clientIP(r)
	if s.access.ValidSession(id, ip) {
		return id, nil
	}
	id, err := s.access.NewSession(ip)
	if err != nil {
		return "", err
	}
	// The random credential never appears in a URL, manifest or page script.
	cookie := &http.Cookie{Name: sessionCookie, Value: id, Path: "/s/" + s.token + "/", HttpOnly: true, Secure: secureRequest(r), SameSite: http.SameSiteStrictMode, MaxAge: 12 * 60 * 60}
	http.SetCookie(w, cookie)
	// Remove an expired credential before adding the replacement, so handlers
	// processing this same request read the new session rather than the old one.
	var kept []string
	for _, c := range r.Cookies() {
		if c.Name != sessionCookie {
			kept = append(kept, c.String())
		}
	}
	r.Header.Del("Cookie")
	if len(kept) > 0 {
		r.Header.Set("Cookie", strings.Join(kept, "; "))
	}
	r.AddCookie(cookie)
	return id, nil
}
func (s *Server) observe(r *http.Request, page bool) {
	ip := clientIP(r)
	if page {
		s.tracker.Visit(ip, r.UserAgent())
	} else {
		s.tracker.Seen(ip, r.UserAgent())
	}
	if s.access != nil {
		if err := s.access.Observe(ip, activity.DescribeUserAgent(r.UserAgent()), page); err != nil {
			s.tracker.Logf("warn", "No se pudo guardar la visita: %s", err)
		}
	}
}
func (s *Server) decision(r *http.Request) access.Decision {
	if s.access != nil {
		return s.access.Authorize(s.sessionID(r), clientIP(r))
	}
	c := s.publicSettings()
	return access.Decision{Status: "allowed", Theme: c.Theme, Title: c.PageTitle, UploadsEnabled: c.UploadsEnabled, MaxUploadMB: c.MaxUploadMB}
}
func gateCode(status string) int {
	if status == "password" {
		return http.StatusUnauthorized
	}
	return http.StatusForbidden
}
func (s *Server) requireAccess(w http.ResponseWriter, r *http.Request) bool {
	if !s.authorised(r) {
		writeJSON(w, http.StatusGone, map[string]any{"ok": false, "expired": true, "error": "Este enlace ya no está disponible"})
		return false
	}
	s.observe(r, false)
	if _, err := s.ensureSession(w, r); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{"ok": false, "error": "No se pudo iniciar la sesión"})
		return false
	}
	d := s.decision(r)
	if d.Status != "allowed" {
		writeJSON(w, gateCode(d.Status), map[string]any{"ok": false, "status": d.Status, "error": d.Message})
		return false
	}
	return true
}
func sameOrigin(r *http.Request) bool {
	value := r.Header.Get("Origin")
	if value == "" {
		return true
	}
	origin, err := url.Parse(value)
	return err == nil && (origin.Scheme == "http" || origin.Scheme == "https") && strings.EqualFold(origin.Host, r.Host)
}
func decodeBody(w http.ResponseWriter, r *http.Request, target any) error {
	if !strings.HasPrefix(strings.ToLower(r.Header.Get("Content-Type")), "application/json") {
		return errors.New("usa una petición JSON")
	}
	r.Body = http.MaxBytesReader(w, r.Body, 16<<10)
	decoder := json.NewDecoder(r.Body)
	if err := decoder.Decode(target); err != nil {
		return errors.New("petición no válida")
	}
	if decoder.Decode(new(any)) != io.EOF {
		return errors.New("petición no válida")
	}
	return nil
}
func (s *Server) handleAccess(w http.ResponseWriter, r *http.Request) {
	if !s.authorised(r) {
		writeJSON(w, http.StatusGone, map[string]any{"ok": false, "expired": true, "error": "Este enlace ya no está disponible"})
		return
	}
	if !sameOrigin(r) {
		writeJSON(w, http.StatusForbidden, map[string]any{"ok": false, "error": "Origen no permitido"})
		return
	}
	s.observe(r, false)
	id, err := s.ensureSession(w, r)
	if err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{"ok": false, "error": "No se pudo iniciar la sesión"})
		return
	}
	var body struct {
		Password string `json:"password"`
		Name     string `json:"name"`
	}
	if r.Method == http.MethodPost {
		if err := decodeBody(w, r, &body); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]any{"ok": false, "error": err.Error()})
			return
		}
	}
	if s.access == nil {
		writeJSON(w, http.StatusOK, s.decision(r))
		return
	}
	d, err := s.access.Access(id, clientIP(r), activity.DescribeUserAgent(r.UserAgent()), body.Name, body.Password, r.Method == http.MethodPost)
	if err != nil {
		code := http.StatusBadRequest
		if errors.Is(err, access.ErrPassword) {
			code = http.StatusUnauthorized
		}
		if errors.Is(err, access.ErrRateLimited) {
			code = http.StatusTooManyRequests
			w.Header().Set("Retry-After", "60")
		}
		writeJSON(w, code, map[string]any{"ok": false, "error": err.Error(), "status": d.Status, "message": err.Error(), "theme": d.Theme, "title": d.Title, "uploadsEnabled": d.UploadsEnabled, "maxUploadMB": d.MaxUploadMB, "requestId": d.RequestID})
		return
	}
	writeJSON(w, http.StatusOK, d)
}
func (s *Server) ownerID(entry core.Entry) string {
	if entry.OwnerID != "" {
		return entry.OwnerID
	}
	return entry.ID
}

func (s *Server) effectiveProtection(r *http.Request, entry core.Entry) (ownerID, name, kind string, protected, allowed bool) {
	if s.store.Excluded(entry.Path) {
		return s.ownerID(entry), "", "", false, false
	}
	if s.access == nil {
		return s.ownerID(entry), "", "", false, true
	}
	owners := s.store.ProtectionOwners(entry.ID)
	ids := make([]string, len(owners))
	for i, owner := range owners {
		ids[i] = owner.ID
	}
	ownerID, protected, allowed = s.access.EffectiveItemAccess(s.sessionID(r), clientIP(r), entry.ID, ids)
	if !protected {
		return s.ownerID(entry), "", "", false, allowed
	}
	if ownerID == entry.ID {
		return ownerID, entry.Name, "file", true, allowed
	}
	for _, owner := range owners {
		if owner.ID == ownerID {
			return ownerID, owner.Name, "folder", true, allowed
		}
	}
	return ownerID, entry.Name, "file", true, allowed
}
func (s *Server) itemAllowed(r *http.Request, entry core.Entry) bool {
	_, _, _, _, allowed := s.effectiveProtection(r, entry)
	return allowed
}
func (s *Server) handleUnlock(w http.ResponseWriter, r *http.Request) {
	if !sameOrigin(r) {
		writeJSON(w, http.StatusForbidden, map[string]any{"ok": false, "error": "Origen no permitido"})
		return
	}
	if !s.requireAccess(w, r) {
		return
	}
	var body struct {
		ID       string `json:"id"`
		Password string `json:"password"`
	}
	if err := decodeBody(w, r, &body); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	entry, ok := s.store.Entry(body.ID)
	owner := body.ID
	if !ok {
		found := false
		for _, item := range s.store.Items() {
			if item.ID == body.ID {
				found = true
				break
			}
		}
		if !found {
			writeJSON(w, http.StatusNotFound, map[string]any{"ok": false, "error": "Ese archivo ya no está compartido"})
			return
		}
	}
	if s.access != nil {
		var err error
		if ok {
			owners := s.store.ProtectionOwners(entry.ID)
			ids := make([]string, len(owners))
			for i, candidate := range owners {
				ids[i] = candidate.ID
			}
			owner, err = s.access.UnlockEffective(s.sessionID(r), clientIP(r), entry.ID, ids, body.Password)
		} else {
			err = s.access.Unlock(s.sessionID(r), clientIP(r), owner, body.Password)
		}
		if err != nil {
			code := http.StatusUnauthorized
			if errors.Is(err, access.ErrRateLimited) {
				code = http.StatusTooManyRequests
				w.Header().Set("Retry-After", "60")
			}
			writeJSON(w, code, map[string]any{"ok": false, "error": err.Error()})
			return
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "ownerId": owner})
}
func (s *Server) transferAllowed(r *http.Request) bool {
	return s.access == nil || s.access.Authorize(s.sessionID(r), clientIP(r)).Status == "allowed"
}
func (s *Server) downloaded(ip string, bytes int64) {
	if s.access != nil {
		if err := s.access.RecordDownload(ip, bytes); err != nil {
			s.tracker.Logf("warn", "No se pudo guardar el historial: %s", err)
		}
	}
}
