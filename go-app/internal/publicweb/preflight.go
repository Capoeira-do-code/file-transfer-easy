package publicweb

import (
	"errors"
	"net/http"
	"net/url"
	"os"
)

func fileError(err error) (int, string) {
	if errors.Is(err, os.ErrNotExist) {
		return http.StatusNotFound, "El archivo ya no existe en el equipo del propietario"
	}
	if errors.Is(err, os.ErrPermission) {
		return http.StatusForbidden, "El propietario no tiene permiso para leer este archivo"
	}
	return http.StatusConflict, "El archivo está ocupado o no se puede leer en este momento"
}
func (s *Server) handleDownloadCheck(w http.ResponseWriter, r *http.Request) {
	if !s.requireAccess(w, r) {
		return
	}
	entry, ok := s.store.Entry(r.PathValue("id"))
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]any{"ok": false, "error": "Ese archivo ya no está compartido"})
		return
	}
	if !s.itemAllowed(r, entry) {
		writeJSON(w, http.StatusForbidden, map[string]any{"ok": false, "locked": true, "error": "Introduce la contraseña de este archivo o carpeta"})
		return
	}
	f, err := os.Open(entry.Path)
	if err != nil {
		code, message := fileError(err)
		writeJSON(w, code, map[string]any{"ok": false, "error": message})
		return
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		code, message := fileError(err)
		writeJSON(w, code, map[string]any{"ok": false, "error": message})
		return
	}
	if !info.Mode().IsRegular() {
		writeJSON(w, http.StatusConflict, map[string]any{"ok": false, "error": "Este elemento ya no es un archivo descargable"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "url": "/s/" + s.token + "/download/" + url.PathEscape(entry.ID)})
}
func (s *Server) handleZipCheck(w http.ResponseWriter, r *http.Request) {
	if !s.requireAccess(w, r) {
		return
	}
	count, skipped := 0, 0
	for _, entry := range s.store.Entries() {
		if !s.itemAllowed(r, entry) {
			skipped++
			continue
		}
		f, err := os.Open(entry.Path)
		if err != nil {
			code, message := fileError(err)
			writeJSON(w, code, map[string]any{"ok": false, "error": message})
			return
		}
		info, err := f.Stat()
		f.Close()
		if err != nil {
			code, message := fileError(err)
			writeJSON(w, code, map[string]any{"ok": false, "error": message})
			return
		}
		if info.Mode().IsRegular() {
			count++
		}
	}
	if count == 0 {
		code, message := http.StatusNotFound, "No hay archivos para descargar"
		if skipped > 0 {
			code, message = http.StatusForbidden, "Desbloquea algún archivo antes de descargar el ZIP"
		}
		writeJSON(w, code, map[string]any{"ok": false, "error": message})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "url": "/s/" + s.token + "/zip", "files": count, "skippedLocked": skipped})
}
