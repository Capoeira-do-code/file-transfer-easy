// Package access owns durable host settings and recipient access decisions.
// Passwords are salted hashes; browser sessions and approvals are deliberately
// ephemeral so restarting the host revokes previous browser permissions.
package access

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

type SettingsView struct {
	Theme           string `json:"theme"`
	UploadsEnabled  bool   `json:"uploadsEnabled"`
	UploadDir       string `json:"uploadDir"`
	MaxUploadMB     int64  `json:"maxUploadMB"`
	RequireApproval bool   `json:"requireApproval"`
	PagePasswordSet bool   `json:"pagePasswordSet"`
	ErrorMessage    string `json:"errorMessage"`
	PageTitle       string `json:"pageTitle"`
}

type SettingsPatch struct {
	Theme           *string `json:"theme"`
	UploadsEnabled  *bool   `json:"uploadsEnabled"`
	UploadDir       *string `json:"uploadDir"`
	MaxUploadMB     *int64  `json:"maxUploadMB"`
	RequireApproval *bool   `json:"requireApproval"`
	PagePassword    *string `json:"pagePassword"`
	ErrorMessage    *string `json:"errorMessage"`
	PageTitle       *string `json:"pageTitle"`
}

type Visitor struct {
	ID        string    `json:"id"`
	IP        string    `json:"ip"`
	Name      string    `json:"name"`
	Label     string    `json:"label"`
	FirstSeen time.Time `json:"firstSeen"`
	LastSeen  time.Time `json:"lastSeen"`
	Visits    int       `json:"visits"`
	Downloads int       `json:"downloads"`
	Bytes     int64     `json:"bytes"`
	Blocked   bool      `json:"blocked"`
}

type Request struct {
	ID        string    `json:"id"`
	IP        string    `json:"ip"`
	Name      string    `json:"name"`
	Label     string    `json:"label"`
	CreatedAt time.Time `json:"createdAt"`
	Status    string    `json:"status"`
}

type diskState struct {
	Version       int                     `json:"version"`
	Settings      SettingsView            `json:"settings"`
	PagePassword  passwordHash            `json:"pagePasswordHash,omitempty"`
	ItemPasswords map[string]passwordHash `json:"itemPasswordHashes,omitempty"`
	History       []Visitor               `json:"history"`
}

type session struct {
	IP          string
	Expires     time.Time
	PageGranted bool
	RequestID   string
	Grants      map[string]bool
}

type attemptWindow struct {
	Started time.Time
	Count   int
}

type Manager struct {
	mu            sync.RWMutex
	file          string
	settings      SettingsView
	pagePassword  passwordHash
	itemPasswords map[string]passwordHash
	history       map[string]Visitor
	sessions      map[string]*session
	requests      map[string]Request
	attempts      map[string]attemptWindow
	onChange      func()
}

// New returns a usable manager even when the stored file could not be read.
// The caller should surface the error; defaults remain in effect in that case.
func New(dataDir string, onChange func()) (*Manager, error) {
	abs, err := filepath.Abs(dataDir)
	if err != nil {
		return nil, err
	}
	m := &Manager{file: filepath.Join(abs, "access.json"), onChange: onChange,
		settings:      SettingsView{Theme: "light", UploadDir: filepath.Join(abs, "Uploads"), MaxUploadMB: 1024, PageTitle: "Archivos compartidos"},
		itemPasswords: map[string]passwordHash{}, history: map[string]Visitor{}, sessions: map[string]*session{}, requests: map[string]Request{}, attempts: map[string]attemptWindow{}}
	f, err := os.Open(m.file)
	if errors.Is(err, os.ErrNotExist) {
		return m, nil
	}
	if err != nil {
		return m, fmt.Errorf("no se pudo leer la configuración: %w", err)
	}
	defer f.Close()
	var saved diskState
	decoder := json.NewDecoder(io.LimitReader(f, 64<<20))
	if err := decoder.Decode(&saved); err != nil {
		return m, fmt.Errorf("configuración guardada no válida: %w", err)
	}
	if err := decoder.Decode(new(any)); err != io.EOF {
		return m, errors.New("configuración guardada contiene datos adicionales")
	}
	if saved.Version != 1 {
		return m, errors.New("versión de configuración no compatible")
	}
	if err := validateSettings(saved.Settings); err != nil {
		return m, err
	}
	if !saved.PagePassword.valid() {
		return m, errors.New("hash de contraseña guardado no válido")
	}
	for id, hash := range saved.ItemPasswords {
		if id == "" || !hash.valid() {
			return m, errors.New("contraseña de archivo guardada no válida")
		}
	}
	m.settings = saved.Settings
	m.pagePassword = saved.PagePassword
	m.settings.PagePasswordSet = !m.pagePassword.empty()
	for id, hash := range saved.ItemPasswords {
		m.itemPasswords[id] = hash
	}
	for _, v := range saved.History {
		if ip := normalIP(v.IP); ip != "" {
			v.IP = ip
			v.ID = visitorID(ip)
			m.history[ip] = v
		}
	}
	return m, nil
}

func validateSettings(s SettingsView) error {
	if s.Theme != "light" && s.Theme != "dark" {
		return errors.New("el tema debe ser light o dark")
	}
	if s.MaxUploadMB < 1 || s.MaxUploadMB > 102400 {
		return errors.New("el límite de subida debe estar entre 1 y 102400 MB")
	}
	if s.UploadDir == "" || !filepath.IsAbs(s.UploadDir) {
		return errors.New("elige una carpeta de subidas absoluta")
	}
	if len(s.PageTitle) > 160 || strings.TrimSpace(s.PageTitle) == "" {
		return errors.New("el título debe tener entre 1 y 160 caracteres")
	}
	if len(s.ErrorMessage) > 1000 {
		return errors.New("el mensaje no puede superar 1000 caracteres")
	}
	return nil
}

func (m *Manager) Settings() SettingsView { m.mu.RLock(); defer m.mu.RUnlock(); return m.settings }

func (m *Manager) UpdateSettings(p SettingsPatch) error {
	var hash passwordHash
	var err error
	if p.PagePassword != nil {
		hash, err = hashPassword(*p.PagePassword)
		if err != nil {
			return err
		}
	}
	m.mu.Lock()
	previous, oldHash := m.settings, m.pagePassword
	next := previous
	if p.Theme != nil {
		next.Theme = *p.Theme
	}
	if p.UploadsEnabled != nil {
		next.UploadsEnabled = *p.UploadsEnabled
	}
	if p.UploadDir != nil {
		next.UploadDir = filepath.Clean(strings.TrimSpace(*p.UploadDir))
	}
	if p.MaxUploadMB != nil {
		next.MaxUploadMB = *p.MaxUploadMB
	}
	if p.RequireApproval != nil {
		next.RequireApproval = *p.RequireApproval
	}
	if p.ErrorMessage != nil {
		next.ErrorMessage = strings.TrimSpace(*p.ErrorMessage)
	}
	if p.PageTitle != nil {
		next.PageTitle = strings.TrimSpace(*p.PageTitle)
	}
	if err := validateSettings(next); err != nil {
		m.mu.Unlock()
		return err
	}
	if p.PagePassword != nil {
		m.pagePassword = hash
	}
	next.PagePasswordSet = !m.pagePassword.empty()
	m.settings = next
	if err = m.saveLocked(); err != nil {
		m.settings = previous
		m.pagePassword = oldHash
		m.mu.Unlock()
		return err
	}
	if p.PagePassword != nil || next.RequireApproval != previous.RequireApproval {
		m.revokeLocked()
	}
	m.mu.Unlock()
	m.changed()
	return nil
}

func (m *Manager) saveLocked() error {
	if err := os.MkdirAll(filepath.Dir(m.file), 0700); err != nil {
		return err
	}
	history := make([]Visitor, 0, len(m.history))
	for _, v := range m.history {
		history = append(history, v)
	}
	sort.Slice(history, func(i, j int) bool { return history[i].IP < history[j].IP })
	state := diskState{Version: 1, Settings: m.settings, PagePassword: m.pagePassword, ItemPasswords: m.itemPasswords, History: history}
	f, err := os.CreateTemp(filepath.Dir(m.file), ".access-*.json")
	if err != nil {
		return err
	}
	name := f.Name()
	defer os.Remove(name)
	if err = f.Chmod(0600); err == nil {
		err = json.NewEncoder(f).Encode(state)
	}
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	return os.Rename(name, m.file)
}

func (m *Manager) changed() {
	if m.onChange != nil {
		m.onChange()
	}
}

func normalIP(value string) string {
	ip := net.ParseIP(strings.TrimSpace(value))
	if ip == nil {
		return ""
	}
	return ip.String()
}
func visitorID(ip string) string {
	sum := sha256.Sum256([]byte(ip))
	return hex.EncodeToString(sum[:])[:16]
}
func randomID() (string, error) {
	var b [32]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	return hex.EncodeToString(b[:]), nil
}

func (m *Manager) History() []Visitor {
	m.mu.RLock()
	defer m.mu.RUnlock()
	out := make([]Visitor, 0, len(m.history))
	for _, v := range m.history {
		out = append(out, v)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].LastSeen.After(out[j].LastSeen) })
	return out
}
func (m *Manager) Name(ip string) string {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.history[normalIP(ip)].Name
}
func (m *Manager) IsBlocked(ip string) bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.history[normalIP(ip)].Blocked
}

// Observe keeps all IPs, including blocked and denied visitors. pageView is
// false for heartbeat/API calls, which must not inflate the visit counter.
func (m *Manager) Observe(ip, label string, pageView bool) error {
	ip = normalIP(ip)
	if ip == "" {
		return nil
	}
	now := time.Now().UTC()
	m.mu.Lock()
	v, exists := m.history[ip]
	if exists && !pageView && v.Label == label && now.Sub(v.LastSeen) < 5*time.Second {
		m.mu.Unlock()
		return nil
	}
	if !exists {
		v = Visitor{ID: visitorID(ip), IP: ip, FirstSeen: now}
	}
	v.LastSeen = now
	if label != "" {
		v.Label = label
	}
	if pageView {
		v.Visits++
	}
	m.history[ip] = v
	err := m.saveLocked()
	m.mu.Unlock()
	if !exists || pageView {
		m.changed()
	}
	return err
}
func (m *Manager) RecordDownload(ip string, bytes int64) error {
	ip = normalIP(ip)
	if ip == "" {
		return nil
	}
	m.mu.Lock()
	v := m.history[ip]
	now := time.Now().UTC()
	if v.ID == "" {
		v = Visitor{ID: visitorID(ip), IP: ip, FirstSeen: now}
	}
	v.LastSeen = now
	v.Downloads++
	if bytes > 0 {
		v.Bytes += bytes
	}
	m.history[ip] = v
	err := m.saveLocked()
	m.mu.Unlock()
	m.changed()
	return err
}
func (m *Manager) SetName(ip, name string) error {
	ip = normalIP(ip)
	name = strings.TrimSpace(name)
	if ip == "" {
		return errors.New("IP no válida")
	}
	if len(name) > 80 {
		return errors.New("el nombre no puede superar 80 caracteres")
	}
	m.mu.Lock()
	previous, existed := m.history[ip]
	v := previous
	if v.ID == "" {
		now := time.Now().UTC()
		v = Visitor{ID: visitorID(ip), IP: ip, FirstSeen: now, LastSeen: now}
	}
	v.Name = name
	m.history[ip] = v
	err := m.saveLocked()
	if err != nil {
		if existed {
			m.history[ip] = previous
		} else {
			delete(m.history, ip)
		}
		m.mu.Unlock()
		return err
	}
	m.mu.Unlock()
	m.changed()
	return err
}
func (m *Manager) SetBlocked(ip string, blocked bool) error {
	ip = normalIP(ip)
	if ip == "" {
		return errors.New("IP no válida")
	}
	m.mu.Lock()
	previous, existed := m.history[ip]
	v := previous
	if v.ID == "" {
		now := time.Now().UTC()
		v = Visitor{ID: visitorID(ip), IP: ip, FirstSeen: now, LastSeen: now}
	}
	v.Blocked = blocked
	m.history[ip] = v
	err := m.saveLocked()
	if err != nil {
		if existed {
			m.history[ip] = previous
		} else {
			delete(m.history, ip)
		}
		m.mu.Unlock()
		return err
	}
	for id, s := range m.sessions {
		if s.IP == ip {
			delete(m.sessions, id)
		}
	}
	for id, r := range m.requests {
		if r.IP == ip && r.Status == "pending" {
			r.Status = "denied"
			m.requests[id] = r
		}
	}
	m.mu.Unlock()
	m.changed()
	return err
}
func (m *Manager) DeleteHistory(ip string) error {
	ip = normalIP(ip)
	if ip == "" {
		return errors.New("IP no válida")
	}
	m.mu.Lock()
	// Removing a log entry must not silently unblock the address.
	v, ok := m.history[ip]
	if ok && v.Blocked {
		m.mu.Unlock()
		return errors.New("desbloquea esta IP antes de borrar su historial")
	}
	delete(m.history, ip)
	err := m.saveLocked()
	if err != nil {
		if ok {
			m.history[ip] = v
		}
		m.mu.Unlock()
		return err
	}
	m.mu.Unlock()
	m.changed()
	return err
}
