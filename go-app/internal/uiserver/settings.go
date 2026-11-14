package uiserver

import (
	"net/http"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/access"
)

func (s *Server) registerSettingsRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/settings", s.guard(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, s.core.Access.Settings())
	}))
	mux.HandleFunc("POST /api/settings", s.action(func(r *http.Request) error {
		var patch access.SettingsPatch
		if err := decode(r, &patch); err != nil {
			return err
		}
		return s.core.UpdateSettings(patch)
	}))
	mux.HandleFunc("POST /api/settings/upload-folder", s.guard(func(w http.ResponseWriter, r *http.Request) {
		path, err := s.core.PickUploadFolder()
		if err != nil {
			writeJSON(w, http.StatusOK, map[string]any{"ok": false, "error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"ok": true, "path": path})
	}))
	mux.HandleFunc("POST /api/items/password", s.action(func(r *http.Request) error {
		var body struct {
			ID       string `json:"id"`
			Password string `json:"password"`
		}
		if err := decode(r, &body); err != nil {
			return err
		}
		return s.core.SetItemPassword(body.ID, body.Password)
	}))
	mux.HandleFunc("POST /api/visitors/block", s.action(func(r *http.Request) error {
		var body struct {
			IP      string `json:"ip"`
			Blocked bool   `json:"blocked"`
		}
		if err := decode(r, &body); err != nil {
			return err
		}
		return s.core.SetVisitorBlocked(body.IP, body.Blocked)
	}))
	mux.HandleFunc("POST /api/visitors/name", s.action(func(r *http.Request) error {
		var body struct {
			IP   string `json:"ip"`
			Name string `json:"name"`
		}
		if err := decode(r, &body); err != nil {
			return err
		}
		return s.core.Access.SetName(body.IP, body.Name)
	}))
	mux.HandleFunc("POST /api/history/delete", s.action(func(r *http.Request) error {
		var body struct {
			IP string `json:"ip"`
		}
		if err := decode(r, &body); err != nil {
			return err
		}
		return s.core.Access.DeleteHistory(body.IP)
	}))
	mux.HandleFunc("POST /api/requests/respond", s.action(func(r *http.Request) error {
		var body struct {
			ID     string `json:"id"`
			Accept bool   `json:"accept"`
		}
		if err := decode(r, &body); err != nil {
			return err
		}
		return s.core.Access.Respond(body.ID, body.Accept)
	}))
}
