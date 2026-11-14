package access

// RevokeSessions retires browser permissions with their sharing session. Cookie
// paths alone cannot prevent a client replaying an old approval on a new link.
// Host settings, password hashes, names and visitor history remain unchanged.
func (m *Manager) RevokeSessions() {
	m.mu.Lock()
	m.revokeLocked()
	m.requests = make(map[string]Request)
	m.mu.Unlock()
	m.changed()
}
