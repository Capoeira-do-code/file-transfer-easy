package publicweb

import (
	"archive/zip"
	"errors"
	"io"
	"io/fs"
	"mime"
	"net/http"
	"net/url"
	"os"
	"path"
	"strconv"
	"strings"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/activity"
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/core"
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/format"
)

// copyBuffer is the chunk size used when streaming downloads. Big enough to
// keep syscalls cheap, small enough that cancelling feels immediate.
const copyBuffer = 256 * 1024

// ------------------------------------------------------------------- the page

func (s *Server) handlePage(w http.ResponseWriter, r *http.Request) {
	if !s.authorised(r) {
		s.expiredPage(w)
		return
	}
	s.observe(r, true)
	if id, err := s.ensureSession(w, r); err == nil && s.access != nil {
		_, _ = s.access.Access(id, clientIP(r), activity.DescribeUserAgent(r.UserAgent()), "", "", false)
	}

	page, err := fs.ReadFile(s.assets, "index.html")
	if err != nil {
		http.Error(w, "No se pudo cargar la página", http.StatusInternalServerError)
		return
	}
	// Replace only the quoted placeholder, so that the surrounding
	// `window.__FTE_BASE__=` identifier survives intact.
	body := strings.ReplaceAll(string(page), `"__FTE_BASE__"`, strconv.Quote("/s/"+s.token))

	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write([]byte(body))
}

// expiredPage answers a stale link with a minimal self-contained page, since
// the real bundle is keyed to a token that no longer exists.
func (s *Server) expiredPage(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(http.StatusGone)
	w.Write([]byte(expiredHTML))
}

func (s *Server) handleAsset(w http.ResponseWriter, r *http.Request) {
	if !s.authorised(r) {
		http.Error(w, "No encontrado", http.StatusNotFound)
		return
	}

	name := path.Base(r.PathValue("name"))
	data, err := fs.ReadFile(s.assets, name)
	if err != nil {
		http.Error(w, "No encontrado", http.StatusNotFound)
		return
	}

	contentType := mime.TypeByExtension(path.Ext(name))
	if path.Ext(name) == ".js" {
		contentType = "text/javascript; charset=utf-8"
	}
	if path.Ext(name) == ".css" {
		contentType = "text/css; charset=utf-8"
	}
	if contentType == "" {
		contentType = "application/octet-stream"
	}
	w.Header().Set("Content-Type", contentType)
	w.Write(data)
}

func (s *Server) handlePing(w http.ResponseWriter, r *http.Request) {
	if !s.authorised(r) {
		writeJSON(w, http.StatusGone, map[string]any{"expired": true})
		return
	}
	if !s.requireAccess(w, r) {
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}

// --------------------------------------------------------------- the manifest

type manifestFile struct {
	ProtectionName string `json:"protectionName"`
	ProtectionKind string `json:"protectionKind"`
	OwnerID        string `json:"ownerId"`
	Protected      bool   `json:"protected"`
	Locked         bool   `json:"locked"`
	ID             string `json:"id"`
	Name           string `json:"name"`
	Ext            string `json:"ext"`
	Size           int64  `json:"size"`
	SizeText       string `json:"sizeText"`
	Folder         string `json:"folder"`
	ModifiedText   string `json:"modifiedText"`
}

type manifestFolder struct {
	ID        string `json:"id"`
	Protected bool   `json:"protected"`
	Locked    bool   `json:"locked"`
	Name      string `json:"name"`
	FileCount int    `json:"fileCount"`
	SizeText  string `json:"sizeText"`
}

type manifestTotals struct {
	Files     int    `json:"files"`
	Bytes     int64  `json:"bytes"`
	BytesText string `json:"bytesText"`
}

type manifest struct {
	Theme                   string           `json:"theme"`
	UploadsEnabled          bool             `json:"uploadsEnabled"`
	MaxUploadMB             int64            `json:"maxUploadMB"`
	Settings                map[string]any   `json:"settings"`
	ZipIncludesUnlockedOnly bool             `json:"zipIncludesUnlockedOnly"`
	Title                   string           `json:"title"`
	Files                   []manifestFile   `json:"files"`
	Folders                 []manifestFolder `json:"folders"`
	Totals                  manifestTotals   `json:"totals"`
	Expired                 bool             `json:"expired"`
}

func (s *Server) handleManifest(w http.ResponseWriter, r *http.Request) {
	if !s.authorised(r) {
		writeJSON(w, http.StatusGone, manifest{Expired: true})
		return
	}
	if !s.requireAccess(w, r) {
		return
	}

	// Pick up files the host added or deleted since the last poll.
	s.store.Rescan(false)

	entries := s.store.Entries()
	payload := manifest{
		Title:   "File Transfer Easy",
		Files:   make([]manifestFile, 0, len(entries)),
		Folders: make([]manifestFolder, 0),
	}
	settings := s.publicSettings()
	payload.Title = settings.PageTitle
	payload.Theme = settings.Theme
	payload.UploadsEnabled = settings.UploadsEnabled
	payload.MaxUploadMB = settings.MaxUploadMB
	payload.ZipIncludesUnlockedOnly = true
	payload.Settings = map[string]any{"theme": settings.Theme, "uploadsEnabled": settings.UploadsEnabled, "maxUploadMB": settings.MaxUploadMB, "pageTitle": settings.PageTitle, "errorMessage": settings.ErrorMessage}

	var total int64
	for _, entry := range entries {
		owner, name, kind, protected, allowed := s.effectiveProtection(r, entry)
		payload.Files = append(payload.Files, manifestFile{
			OwnerID: owner, ProtectionName: name, ProtectionKind: kind, Protected: protected, Locked: !allowed,
			ID:           entry.ID,
			Name:         entry.Name,
			Ext:          entry.Ext,
			Size:         entry.Size,
			SizeText:     format.Bytes(entry.Size),
			Folder:       entry.Folder,
			ModifiedText: format.Date(entry.ModTime),
		})
		total += entry.Size
	}

	for _, folder := range s.store.Folders() {
		payload.Folders = append(payload.Folders, manifestFolder{
			ID: folder.ID, Protected: s.access != nil && s.access.ItemProtected(folder.ID), Locked: s.access != nil && !s.access.ItemAllowed(s.sessionID(r), clientIP(r), folder.ID),
			Name:      folder.Name,
			FileCount: folder.FileCount,
			SizeText:  format.Bytes(folder.Size),
		})
	}

	payload.Totals = manifestTotals{
		Files:     len(payload.Files),
		Bytes:     total,
		BytesText: format.Bytes(total),
	}
	writeJSON(w, http.StatusOK, payload)
}

// ---------------------------------------------------------------- downloading

func (s *Server) handleDownload(w http.ResponseWriter, r *http.Request) {
	if !s.authorised(r) {
		http.Error(w, "Este enlace ya no está disponible", http.StatusGone)
		return
	}
	if !s.requireAccess(w, r) {
		return
	}

	entry, ok := s.store.Entry(r.PathValue("id"))
	if !ok {
		http.Error(w, "Ese archivo ya no está compartido", http.StatusNotFound)
		return
	}
	if !s.itemAllowed(r, entry) {
		writeJSON(w, http.StatusForbidden, map[string]any{"ok": false, "locked": true, "error": "Introduce la contraseña de este archivo o carpeta"})
		return
	}
	file, err := os.Open(entry.Path)
	if err != nil {
		code, message := fileError(err)
		writeJSON(w, code, map[string]any{"ok": false, "error": message})
		return
	}
	defer file.Close()

	info, err := file.Stat()
	if err != nil {
		http.Error(w, "No se pudo leer el archivo", http.StatusInternalServerError)
		return
	}
	if !info.Mode().IsRegular() {
		writeJSON(w, http.StatusConflict, map[string]any{"ok": false, "error": "Este elemento ya no es un archivo descargable"})
		return
	}

	ip := clientIP(r)
	s.tracker.Seen(ip, r.Header.Get("User-Agent"))

	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Content-Length", strconv.FormatInt(info.Size(), 10))
	w.Header().Set("Content-Disposition", contentDisposition(entry.Name))

	transfer := s.tracker.StartTransfer("file", entry.Name, ip, info.Size())
	status := s.streamEntry(w, file, transfer, r, entry)
	s.tracker.FinishTransfer(transfer, status)
	if status == "done" {
		s.downloaded(ip, info.Size())
	}
}

func (s *Server) handleZip(w http.ResponseWriter, r *http.Request) {
	if !s.authorised(r) {
		http.Error(w, "Este enlace ya no está disponible", http.StatusGone)
		return
	}
	if !s.requireAccess(w, r) {
		return
	}

	entries := make([]core.Entry, 0)
	for _, entry := range s.store.Entries() {
		if s.itemAllowed(r, entry) {
			entries = append(entries, entry)
		}
	}
	if len(entries) == 0 {
		if len(s.store.Entries()) > 0 {
			writeJSON(w, http.StatusForbidden, map[string]any{"ok": false, "locked": true, "error": "Desbloquea algún archivo antes de descargar el ZIP"})
		} else {
			http.Error(w, "No hay nada que descargar", http.StatusNotFound)
		}
		return
	}

	ip := clientIP(r)
	s.tracker.Seen(ip, r.Header.Get("User-Agent"))

	// The compressed size is unknowable up front, so progress is tracked
	// against the total bytes read from disk instead of bytes on the wire.
	var total int64
	for _, entry := range entries {
		total += entry.Size
	}

	name := "file-transfer-easy.zip"
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", contentDisposition(name))

	transfer := s.tracker.StartTransfer("zip", name, ip, total)
	status := s.streamZip(w, entries, transfer, r)
	s.tracker.FinishTransfer(transfer, status)
	if status == "done" {
		s.downloaded(ip, total)
	}
}

// stream copies a file to the client, reporting progress and honouring both
// cancellation from the host and the client hanging up.
func (s *Server) stream(w http.ResponseWriter, src io.Reader, transfer *activity.Transfer, r *http.Request) string {
	return s.streamEntry(w, src, transfer, r, core.Entry{})
}
func (s *Server) streamEntry(w http.ResponseWriter, src io.Reader, transfer *activity.Transfer, r *http.Request, entry core.Entry) string {
	flusher, _ := w.(http.Flusher)
	buffer := make([]byte, copyBuffer)
	var sent int64

	for {
		if !s.transferAllowed(r) || (entry.ID != "" && !s.itemAllowed(r, entry)) {
			return "cancelled"
		}
		select {
		case <-transfer.Cancelled():
			return "cancelled"
		case <-r.Context().Done():
			return "cancelled"
		default:
		}

		read, readErr := src.Read(buffer)
		if read > 0 {
			written, writeErr := w.Write(buffer[:read])
			sent += int64(written)
			s.tracker.Progress(transfer, sent)
			if writeErr != nil {
				return "error"
			}
			if flusher != nil {
				flusher.Flush()
			}
		}
		if errors.Is(readErr, io.EOF) {
			return "done"
		}
		if readErr != nil {
			return "error"
		}
	}
}

// streamZip builds the archive straight onto the wire, so nothing is buffered
// to disk and the download starts immediately.
func (s *Server) streamZip(w http.ResponseWriter, entries []core.Entry, transfer *activity.Transfer, r *http.Request) string {
	archive := zip.NewWriter(w)
	buffer := make([]byte, copyBuffer)
	var read int64
	status := "done"

	used := make(map[string]int, len(entries))

entries:
	for _, entry := range entries {
		if !s.transferAllowed(r) || !s.itemAllowed(r, entry) {
			status = "cancelled"
			break entries
		}
		select {
		case <-transfer.Cancelled():
			status = "cancelled"
			break entries
		case <-r.Context().Done():
			status = "cancelled"
			break entries
		default:
		}

		file, err := os.Open(entry.Path)
		if err != nil {
			// A file that vanished mid-archive should not kill the download.
			continue
		}

		header := &zip.FileHeader{
			Name:     uniqueName(used, entry.ZipPath),
			Method:   zip.Deflate,
			Modified: entry.ModTime,
		}
		writer, err := archive.CreateHeader(header)
		if err != nil {
			file.Close()
			status = "error"
			break
		}

		for {
			if !s.transferAllowed(r) || !s.itemAllowed(r, entry) {
				file.Close()
				status = "cancelled"
				break entries
			}
			select {
			case <-transfer.Cancelled():
				file.Close()
				status = "cancelled"
				break entries
			case <-r.Context().Done():
				file.Close()
				status = "cancelled"
				break entries
			default:
			}

			n, readErr := file.Read(buffer)
			if n > 0 {
				if _, writeErr := writer.Write(buffer[:n]); writeErr != nil {
					file.Close()
					status = "error"
					break entries
				}
				read += int64(n)
				s.tracker.Progress(transfer, read)
			}
			if errors.Is(readErr, io.EOF) {
				break
			}
			if readErr != nil {
				file.Close()
				status = "error"
				break entries
			}
		}
		file.Close()
	}

	if err := archive.Close(); err != nil && status == "done" {
		status = "error"
	}
	return status
}

// uniqueName keeps two files with the same path inside the archive from
// colliding, which zip readers handle badly.
func uniqueName(used map[string]int, name string) string {
	count := used[name]
	used[name] = count + 1
	if count == 0 {
		return name
	}

	ext := path.Ext(name)
	return strings.TrimSuffix(name, ext) + " (" + strconv.Itoa(count+1) + ")" + ext
}

// contentDisposition builds a header that survives non-ASCII filenames on every
// browser, pairing an ASCII fallback with the RFC 5987 encoded form.
func contentDisposition(name string) string {
	ascii := make([]rune, 0, len(name))
	for _, r := range name {
		if r < 32 || r > 126 || r == '"' || r == '\\' {
			ascii = append(ascii, '_')
			continue
		}
		ascii = append(ascii, r)
	}
	fallback := strings.TrimSpace(string(ascii))
	if fallback == "" {
		fallback = "descarga"
	}
	return `attachment; filename="` + fallback + `"; filename*=UTF-8''` + url.PathEscape(name)
}

// expiredHTML is the standalone page shown for a link that no longer works.
var expiredHTML = `<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Enlace no disponible</title>
<style>
:root{color-scheme:light dark;--bg:#f4f7f8;--fg:#12212c;--muted:#4a5f66;--card:#fff;--line:#dae5e7}
@media(prefers-color-scheme:dark){:root{--bg:#0e1618;--fg:#e8f1f2;--muted:#a3b8bc;--card:#162226;--line:#24343a}}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:var(--bg);color:var(--fg);
font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
.card{max-width:420px;text-align:center;background:var(--card);border:1px solid var(--line);
border-radius:20px;padding:40px 32px;box-shadow:0 18px 48px rgba(16,38,48,.08)}
h1{margin:0 0 12px;font-size:22px;letter-spacing:-.01em}
p{margin:0;color:var(--muted)}
svg{margin-bottom:20px;color:var(--muted)}
</style></head><body>
<main class="card">
<svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"
 stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
<path d="M10.6 13.4a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.2 1.2"/>
<path d="M13.4 10.6a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.2-1.2"/>
</svg>
<h1>Este enlace ya no está disponible</h1>
<p>Quien te lo envió ha dejado de compartir estos archivos. Pídele un enlace nuevo si todavía los necesitas.</p>
</main></body></html>`
