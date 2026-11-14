package publicweb

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/activity"
)

type receivedFile struct {
	Name      string `json:"name"`
	Size      int64  `json:"size"`
	temporary string
	final     string
	transfer  *activity.Transfer
	release   func()
}

type uploadFileSystem interface {
	Link(string, string) error
	Open(string) (*os.File, error)
	OpenFile(string, int, os.FileMode) (*os.File, error)
	Remove(string) error
}

// Prefer the atomic, no-replacement hard-link commit. FAT/exFAT and other
// filesystems without links fall back to an exclusive destination copy. The
// destination remains excluded from the shared Store until the whole batch
// succeeds; an interrupted copy removes only the destination created here.
func commitUploadFile(root uploadFileSystem, temporary, destination string) error {
	if err := root.Link(temporary, destination); err == nil || errors.Is(err, os.ErrExist) {
		return err
	}
	source, err := root.Open(temporary)
	if err != nil {
		return err
	}
	defer source.Close()
	output, err := root.OpenFile(destination, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	_, err = io.Copy(output, source)
	if err == nil {
		err = output.Sync()
	}
	closeErr := output.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		_ = root.Remove(destination)
	}
	return err
}

func randomUploadID() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	return hex.EncodeToString(b[:]), nil
}

func safeUploadName(name string) bool {
	if name == "" || len(name) > 200 || name == "." || name == ".." || strings.HasPrefix(name, ".fte-upload-") || strings.HasSuffix(name, ".") || strings.HasSuffix(name, " ") {
		return false
	}
	if strings.ContainsAny(name, "/\\:<>\"|?*") {
		return false
	}
	for _, r := range name {
		if r < 32 || r == 127 {
			return false
		}
	}
	base := strings.ToUpper(strings.SplitN(name, ".", 2)[0])
	switch base {
	case "CON", "PRN", "AUX", "NUL":
		return false
	}
	if len(base) == 4 && (strings.HasPrefix(base, "COM") || strings.HasPrefix(base, "LPT")) && base[3] >= '1' && base[3] <= '9' {
		return false
	}
	return true
}

// Reject symbolic-link components before creating a directory, then pin the
// directory with os.Root so concurrent path changes cannot escape confinement.
func openUploadRoot(dir string) (*os.Root, error) {
	dir = filepath.Clean(dir)
	if !filepath.IsAbs(dir) {
		return nil, errors.New("carpeta de subidas no válida")
	}
	var paths []string
	for p := dir; ; p = filepath.Dir(p) {
		paths = append(paths, p)
		if filepath.Dir(p) == p {
			break
		}
	}
	for i := len(paths) - 1; i >= 0; i-- {
		info, err := os.Lstat(paths[i])
		if errors.Is(err, os.ErrNotExist) {
			continue
		}
		if err != nil {
			return nil, err
		}
		if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
			return nil, errors.New("la carpeta de subidas no puede contener enlaces simbólicos")
		}
	}
	if err := os.MkdirAll(dir, 0700); err != nil {
		return nil, err
	}
	return os.OpenRoot(dir)
}

func (s *Server) uploadAllowed(r *http.Request, dir string, received int64) bool {
	code, _ := s.uploadProblem(r, dir, received)
	return code == 0
}
func (s *Server) uploadProblem(r *http.Request, dir string, received int64) (int, string) {
	settings := s.publicSettings()
	if !settings.UploadsEnabled {
		return http.StatusForbidden, "El propietario ha desactivado las subidas"
	}
	if settings.UploadDir != dir {
		return http.StatusConflict, "El propietario ha cambiado la carpeta de destino; vuelve a subir el archivo"
	}
	if received > settings.MaxUploadMB*(1<<20) {
		return http.StatusRequestEntityTooLarge, fmt.Sprintf("La subida supera el límite de %d MB", settings.MaxUploadMB)
	}
	if decision := s.decision(r); decision.Status != "allowed" {
		return gateCode(decision.Status), decision.Message
	}
	return 0, ""
}

func (s *Server) handleUpload(w http.ResponseWriter, r *http.Request) {
	if !sameOrigin(r) {
		writeJSON(w, http.StatusForbidden, map[string]any{"ok": false, "error": "Origen no permitido"})
		return
	}
	if !s.requireAccess(w, r) {
		return
	}
	settings := s.publicSettings()
	if !settings.UploadsEnabled {
		writeJSON(w, http.StatusForbidden, map[string]any{"ok": false, "error": "El propietario ha desactivado las subidas"})
		return
	}
	limit := settings.MaxUploadMB * (1 << 20)
	r.Body = http.MaxBytesReader(w, r.Body, limit+(1<<20))
	reader, err := r.MultipartReader()
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"ok": false, "error": "La subida debe contener archivos multipart"})
		return
	}
	root, err := openUploadRoot(settings.UploadDir)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"ok": false, "error": "No se pudo abrir la carpeta de subidas"})
		return
	}
	defer root.Close()
	var files []receivedFile
	committed := false
	defer func() {
		for _, file := range files {
			if file.temporary != "" {
				_ = root.Remove(file.temporary)
			}
			if !committed {
				if file.final != "" {
					_ = root.Remove(file.final)
				}
				if file.transfer != nil {
					s.tracker.FinishTransfer(file.transfer, "cancelled")
				}
			}
		}
		for _, file := range files {
			if file.release != nil {
				file.release()
			}
		}
		if len(files) > 0 {
			s.store.Rescan(true)
		}
	}()
	var total int64
	parts := 0
	fail := func(code int, message string) { writeJSON(w, code, map[string]any{"ok": false, "error": message}) }
	for {
		part, readErr := reader.NextPart()
		if errors.Is(readErr, io.EOF) {
			break
		}
		if readErr != nil {
			var maxError *http.MaxBytesError
			if errors.As(readErr, &maxError) {
				fail(http.StatusRequestEntityTooLarge, fmt.Sprintf("La subida supera el límite de %d MB", settings.MaxUploadMB))
			} else {
				fail(http.StatusBadRequest, "La subida está incompleta o el formulario no es válido")
			}
			return
		}
		parts++
		if parts > 128 {
			fail(http.StatusBadRequest, "La subida contiene demasiadas partes de formulario")
			return
		}
		_, params, parseErr := mime.ParseMediaType(part.Header.Get("Content-Disposition"))
		name, hasFilename := params["filename"]
		if parseErr != nil {
			fail(http.StatusBadRequest, "Nombre de archivo no válido")
			return
		}
		if !hasFilename {
			n, err := io.Copy(io.Discard, io.LimitReader(part, 16385))
			if err != nil || n > 16384 {
				fail(http.StatusBadRequest, "Campo de formulario no válido")
				return
			}
			part.Close()
			continue
		}
		if part.FormName() != "files" && part.FormName() != "file" {
			fail(http.StatusBadRequest, "Campo de archivo no válido")
			return
		}
		if !safeUploadName(name) || len(files) >= 64 {
			fail(http.StatusBadRequest, "Nombre de archivo no válido o demasiados archivos")
			return
		}
		if !s.uploadAllowed(r, settings.UploadDir, total) {
			code, message := s.uploadProblem(r, settings.UploadDir, total)
			fail(code, message)
			return
		}
		temporary := ".fte-upload-" + strconv.FormatInt(int64(os.Getpid()), 16) + "-" + strconv.FormatInt(int64(len(files)), 16) + "-"
		// A random temporary name and O_EXCL prevent following an existing link.
		var out *os.File
		for attempt := 0; attempt < 10; attempt++ {
			suffix, e := randomUploadID()
			if e != nil {
				err = e
				break
			}
			temporaryName := temporary + suffix
			out, err = root.OpenFile(temporaryName, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
			if err == nil {
				temporary = temporaryName
				break
			}
			if !errors.Is(err, os.ErrExist) {
				break
			}
		}
		if err != nil || out == nil {
			fail(http.StatusInternalServerError, "No se pudo guardar el archivo")
			return
		}
		files = append(files, receivedFile{Name: name, temporary: temporary})
		index := len(files) - 1
		transfer := s.tracker.StartTransfer("upload", name, clientIP(r), 0)
		files[index].transfer = transfer
		status := "done"
		failureCode, failureMessage := http.StatusInternalServerError, "No se pudo guardar el archivo en la carpeta de destino"
		buffer := make([]byte, copyBuffer)
		done := make(chan struct{})
		go func(t *activity.Transfer) {
			select {
			case <-t.Cancelled():
				r.Body.Close()
			case <-r.Context().Done():
				r.Body.Close()
			case <-done:
			}
		}(transfer)
		for {
			if !s.uploadAllowed(r, settings.UploadDir, total) {
				failureCode, failureMessage = s.uploadProblem(r, settings.UploadDir, total)
				status = "cancelled"
				break
			}
			select {
			case <-transfer.Cancelled():
				status = "cancelled"
				failureCode, failureMessage = http.StatusForbidden, "El propietario ha cancelado la subida"
			default:
			}
			if status != "done" {
				break
			}
			n, readErr := part.Read(buffer)
			if n > 0 {
				if !s.uploadAllowed(r, settings.UploadDir, total+int64(n)) {
					failureCode, failureMessage = s.uploadProblem(r, settings.UploadDir, total+int64(n))
					status = "cancelled"
					break
				}
				written, writeErr := out.Write(buffer[:n])
				total += int64(written)
				files[index].Size += int64(written)
				s.tracker.Progress(transfer, files[index].Size)
				if writeErr != nil || written != n {
					status = "error"
					break
				}
			}
			if errors.Is(readErr, io.EOF) {
				break
			}
			if readErr != nil {
				status = "error"
				failureCode, failureMessage = http.StatusBadRequest, "La conexión se interrumpió antes de recibir el archivo completo"
				var maxError *http.MaxBytesError
				if errors.As(readErr, &maxError) {
					failureCode, failureMessage = http.StatusRequestEntityTooLarge, fmt.Sprintf("La subida supera el límite de %d MB", settings.MaxUploadMB)
				}
				break
			}
		}
		close(done)
		if status == "done" {
			if err = out.Sync(); err != nil {
				status = "error"
			}
		}
		if err = out.Close(); err != nil {
			status = "error"
		}
		if status != "done" {
			s.tracker.FinishTransfer(transfer, status)
			files[index].transfer = nil
			fail(failureCode, failureMessage)
			return
		}
		part.Close()
	}
	if len(files) == 0 {
		fail(http.StatusBadRequest, "Selecciona al menos un archivo")
		return
	}
	if !s.uploadAllowed(r, settings.UploadDir, total) {
		code, message := s.uploadProblem(r, settings.UploadDir, total)
		fail(code, message)
		return
	}
	paths := make([]string, 0, len(files))
	for i := range files {
		name := files[i].Name
		for number := 0; number < 1000; number++ {
			candidate := name
			if number > 0 {
				ext := filepath.Ext(name)
				candidate = strings.TrimSuffix(name, ext) + fmt.Sprintf(" (%d)", number+1) + ext
			}
			release := s.store.ExcludePath(filepath.Join(settings.UploadDir, candidate))
			err = commitUploadFile(root, files[i].temporary, candidate)
			if errors.Is(err, os.ErrExist) {
				release()
				continue
			}
			if err != nil {
				release()
				fail(http.StatusInternalServerError, "No se pudo finalizar la subida sin sobrescribir archivos")
				return
			}
			files[i].final = candidate
			files[i].release = release
			files[i].Name = candidate
			paths = append(paths, filepath.Join(settings.UploadDir, candidate))
			break
		}
		if files[i].final == "" {
			fail(http.StatusConflict, "Hay demasiados archivos con este nombre")
			return
		}
	}
	if !s.uploadAllowed(r, settings.UploadDir, total) {
		code, message := s.uploadProblem(r, settings.UploadDir, total)
		fail(code, message)
		return
	}
	if s.onUpload != nil {
		if err := s.onUpload(paths); err != nil {
			fail(http.StatusInternalServerError, "No se pudieron añadir los archivos recibidos")
			return
		}
	}
	committed = true
	for _, file := range files {
		s.tracker.FinishTransfer(file.transfer, "done")
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "files": files})
}
