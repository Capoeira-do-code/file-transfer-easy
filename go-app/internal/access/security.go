package access

import (
	"crypto/pbkdf2"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"errors"
	"sort"
	"strings"
	"time"
)

const passwordRounds = 600000
const sessionLifetime = 12 * time.Hour

var ErrPassword = errors.New("contraseña incorrecta")
var ErrRateLimited = errors.New("demasiados intentos; espera un minuto")

type passwordHash struct {
	Salt   string `json:"salt,omitempty"`
	Hash   string `json:"hash,omitempty"`
	Rounds int    `json:"rounds,omitempty"`
}

func (p passwordHash) empty() bool { return p.Hash == "" && p.Salt == "" && p.Rounds == 0 }
func (p passwordHash) valid() bool {
	if p.empty() {
		return true
	}
	salt, e := base64.RawStdEncoding.DecodeString(p.Salt)
	hash, e2 := base64.RawStdEncoding.DecodeString(p.Hash)
	return e == nil && e2 == nil && len(salt) == 16 && len(hash) == 32 && p.Rounds >= 100000 && p.Rounds <= 2000000
}
func hashPassword(password string) (passwordHash, error) {
	if password == "" {
		return passwordHash{}, nil
	}
	if len(password) > 1024 {
		return passwordHash{}, errors.New("la contraseña no puede superar 1024 caracteres")
	}
	var salt [16]byte
	if _, err := rand.Read(salt[:]); err != nil {
		return passwordHash{}, err
	}
	key, err := pbkdf2.Key(sha256.New, password, salt[:], passwordRounds, 32)
	if err != nil {
		return passwordHash{}, err
	}
	return passwordHash{Salt: base64.RawStdEncoding.EncodeToString(salt[:]), Hash: base64.RawStdEncoding.EncodeToString(key), Rounds: passwordRounds}, nil
}
func (p passwordHash) matches(password string) bool {
	if p.empty() {
		return true
	}
	if len(password) > 1024 || !p.valid() {
		return false
	}
	salt, _ := base64.RawStdEncoding.DecodeString(p.Salt)
	want, _ := base64.RawStdEncoding.DecodeString(p.Hash)
	key, err := pbkdf2.Key(sha256.New, password, salt, p.Rounds, 32)
	return err == nil && subtle.ConstantTimeCompare(key, want) == 1
}

type Decision struct {
	Status         string `json:"status"`
	Message        string `json:"message"`
	Theme          string `json:"theme"`
	Title          string `json:"title"`
	UploadsEnabled bool   `json:"uploadsEnabled"`
	MaxUploadMB    int64  `json:"maxUploadMB"`
	RequestID      string `json:"requestId,omitempty"`
}

func (m *Manager) decisionLocked(status string) Decision {
	message := map[string]string{"password": "Introduce la contraseña para abrir esta página.", "pending": "Tu solicitud está pendiente de aprobación.", "denied": "El propietario ha rechazado el acceso.", "blocked": "El acceso desde esta dirección está bloqueado."}[status]
	return Decision{Status: status, Message: message, Theme: m.settings.Theme, Title: m.settings.PageTitle, UploadsEnabled: m.settings.UploadsEnabled, MaxUploadMB: m.settings.MaxUploadMB}
}
func (m *Manager) revokeLocked() {
	m.sessions = map[string]*session{}
	for id, r := range m.requests {
		if r.Status == "pending" {
			r.Status = "denied"
			m.requests[id] = r
		}
	}
}

func (m *Manager) NewSession(ip string) (string, error) {
	ip = normalIP(ip)
	if ip == "" {
		return "", errors.New("IP no válida")
	}
	id, err := randomID()
	if err != nil {
		return "", err
	}
	m.mu.Lock()
	now := time.Now()
	m.pruneSessionsLocked(now)
	if len(m.sessions) >= 4096 {
		m.mu.Unlock()
		return "", errors.New("hay demasiadas sesiones; vuelve a intentarlo más tarde")
	}
	m.sessions[id] = &session{IP: ip, Expires: now.Add(sessionLifetime), Grants: map[string]bool{}}
	m.mu.Unlock()
	return id, nil
}

func (m *Manager) pruneSessionsLocked(now time.Time) {
	for key, s := range m.sessions {
		if !now.Before(s.Expires) {
			if request, ok := m.requests[s.RequestID]; ok && request.Status == "pending" {
				delete(m.requests, s.RequestID)
			}
			delete(m.sessions, key)
		}
	}
}
func (m *Manager) ValidSession(id, ip string) bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	s := m.sessions[id]
	return s != nil && s.IP == normalIP(ip) && time.Now().Before(s.Expires)
}

func (m *Manager) authorizeLocked(id, ip string) Decision {
	if m.history[ip].Blocked {
		return m.decisionLocked("blocked")
	}
	s := m.sessions[id]
	valid := s != nil && s.IP == ip && time.Now().Before(s.Expires)
	if !m.pagePassword.empty() && (!valid || !s.PageGranted) {
		return m.decisionLocked("password")
	}
	if m.settings.RequireApproval {
		if valid && s.RequestID != "" {
			r := m.requests[s.RequestID]
			d := m.decisionLocked(r.Status)
			d.RequestID = r.ID
			if r.Status == "approved" {
				d.Status = "allowed"
				d.Message = ""
			}
			return d
		}
		return m.decisionLocked("pending")
	}
	return m.decisionLocked("allowed")
}

// Authorize never creates requests or grants. It is safe to call for every
// chunk of an active transfer to enforce policy changes immediately.
func (m *Manager) Authorize(id, ip string) Decision {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.authorizeLocked(id, normalIP(ip))
}

func (m *Manager) allowAttemptLocked(key string) bool {
	now := time.Now()
	window := m.attempts[key]
	if now.Sub(window.Started) >= time.Minute {
		window = attemptWindow{Started: now}
	}
	if len(m.attempts) >= 8192 {
		for k, v := range m.attempts {
			if now.Sub(v.Started) >= time.Minute {
				delete(m.attempts, k)
			}
		}
	}
	if _, exists := m.attempts[key]; !exists && len(m.attempts) >= 8192 {
		return false
	}
	if window.Count >= 6 {
		return false
	}
	window.Count++
	m.attempts[key] = window
	return true
}

// Access optionally verifies a page password, then creates an approval request
// once. Names supplied by visitors label their request, not trusted host names.
func (m *Manager) Access(id, ip, label, name, password string, submit bool) (Decision, error) {
	ip = normalIP(ip)
	name = strings.TrimSpace(name)
	if len(name) > 80 {
		return Decision{}, errors.New("el nombre no puede superar 80 caracteres")
	}
	m.mu.Lock()
	if m.history[ip].Blocked {
		d := m.decisionLocked("blocked")
		m.mu.Unlock()
		return d, nil
	}
	s := m.sessions[id]
	if s == nil || s.IP != ip || time.Now().After(s.Expires) {
		d := m.authorizeLocked("", ip)
		m.mu.Unlock()
		return d, errors.New("la sesión ha caducado; recarga la página")
	}
	if !m.pagePassword.empty() && !s.PageGranted {
		if !submit {
			d := m.decisionLocked("password")
			m.mu.Unlock()
			return d, nil
		}
		if !m.allowAttemptLocked("page:" + ip) {
			d := m.decisionLocked("password")
			m.mu.Unlock()
			return d, ErrRateLimited
		}
		// Keep the policy lock during verification so changing the password
		// cannot authorize a result against a newer policy revision.
		if !m.pagePassword.matches(password) {
			d := m.decisionLocked("password")
			m.mu.Unlock()
			return d, ErrPassword
		}
		s.PageGranted = true
	}
	changed := false
	if submit && name != "" && s.RequestID != "" {
		request, ok := m.requests[s.RequestID]
		if ok && request.Status == "pending" && request.Name != name {
			request.Name = name
			m.requests[s.RequestID] = request
			changed = true
		}
	}
	if m.settings.RequireApproval && s.RequestID == "" {
		if !m.allowAttemptLocked("request:" + ip) {
			d := m.decisionLocked("pending")
			m.mu.Unlock()
			return d, ErrRateLimited
		}
		requestID, err := randomID()
		if err != nil {
			m.mu.Unlock()
			return Decision{}, err
		}
		if len(m.requests) >= 4096 {
			for key, request := range m.requests {
				if request.Status != "pending" {
					delete(m.requests, key)
				}
			}
		}
		if len(m.requests) >= 4096 {
			m.mu.Unlock()
			return Decision{}, errors.New("hay demasiadas solicitudes pendientes")
		}
		m.requests[requestID] = Request{ID: requestID, IP: ip, Name: name, Label: label, CreatedAt: time.Now().UTC(), Status: "pending"}
		s.RequestID = requestID
		changed = true
	}
	d := m.authorizeLocked(id, ip)
	m.mu.Unlock()
	if changed {
		m.changed()
	}
	return d, nil
}
func (m *Manager) Requests() []Request {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.pruneSessionsLocked(time.Now())
	out := make([]Request, 0, len(m.requests))
	for _, r := range m.requests {
		out = append(out, r)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].CreatedAt.After(out[j].CreatedAt) })
	return out
}
func (m *Manager) Respond(id string, accept bool) error {
	m.mu.Lock()
	r, ok := m.requests[id]
	if !ok || r.Status != "pending" {
		m.mu.Unlock()
		return errors.New("la solicitud ya no está pendiente")
	}
	if accept && m.history[r.IP].Blocked {
		m.mu.Unlock()
		return errors.New("esta IP está bloqueada")
	}
	if accept {
		r.Status = "approved"
	} else {
		r.Status = "denied"
	}
	m.requests[id] = r
	m.mu.Unlock()
	m.changed()
	return nil
}
func (m *Manager) SetItemPassword(id, password string) error {
	if strings.TrimSpace(id) == "" {
		return errors.New("archivo no válido")
	}
	hash, err := hashPassword(password)
	if err != nil {
		return err
	}
	m.mu.Lock()
	old, existed := m.itemPasswords[id]
	if hash.empty() {
		delete(m.itemPasswords, id)
	} else {
		m.itemPasswords[id] = hash
	}
	if err = m.saveLocked(); err != nil {
		if existed {
			m.itemPasswords[id] = old
		} else {
			delete(m.itemPasswords, id)
		}
		m.mu.Unlock()
		return err
	}
	// A file/folder password only revokes that owner's grants. Page access,
	// approval and grants for unrelated files remain valid.
	for _, s := range m.sessions {
		delete(s.Grants, id)
	}
	m.mu.Unlock()
	m.changed()
	return nil
}
func (m *Manager) ItemProtected(id string) bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	hash, ok := m.itemPasswords[id]
	return ok && !hash.empty()
}
func (m *Manager) ItemAllowed(sessionID, ip, id string) bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	ip = normalIP(ip)
	if m.authorizeLocked(sessionID, ip).Status != "allowed" {
		return false
	}
	hash := m.itemPasswords[id]
	if hash.empty() {
		return true
	}
	s := m.sessions[sessionID]
	return s != nil && s.IP == ip && time.Now().Before(s.Expires) && s.Grants[id]
}
func (m *Manager) Unlock(sessionID, ip, id, password string) error {
	m.mu.Lock()
	ip = normalIP(ip)
	if m.authorizeLocked(sessionID, ip).Status != "allowed" {
		m.mu.Unlock()
		return errors.New("el acceso a la página no está autorizado")
	}
	s := m.sessions[sessionID]
	if s == nil || s.IP != ip || time.Now().After(s.Expires) {
		m.mu.Unlock()
		return errors.New("recarga la página para iniciar una sesión")
	}
	hash := m.itemPasswords[id]
	if hash.empty() {
		m.mu.Unlock()
		return nil
	}
	if !m.allowAttemptLocked("item:" + ip) {
		m.mu.Unlock()
		return ErrRateLimited
	}
	if !hash.matches(password) {
		m.mu.Unlock()
		return ErrPassword
	}
	s.Grants[id] = true
	m.mu.Unlock()
	return nil
}
