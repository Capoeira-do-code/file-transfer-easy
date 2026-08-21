// Package app wires the shared store, the activity tracker, the public web
// server and the cloudflared tunnel into the single object the UI drives.
package app

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"fmt"
	"io/fs"
	"net"
	"net/http"
	"sync"
	"time"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/activity"
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/core"
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/publicweb"
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/tunnel"
)

// Native is the set of desktop capabilities the app needs from the windowing
// layer. main.go implements it against Wails; tests can stub it.
type Native interface {
	PickFiles() ([]string, error)
	PickFolder() (string, error)
	Reveal(path string) error
	SetClipboard(text string) bool
	MinimiseWindow()
	HideWindow()
	ShowWindow()
	OpenInBrowser(url string) error

	// StateChanged is called whenever anything the tray shows has changed.
	StateChanged(Summary)
}

// Summary is the condensed view of the app that the tray menu displays, so a
// user can tell what is going on without opening the window.
type Summary struct {
	Status     ShareStatus
	StatusText string
	URL        string
	Items      int
	Files      int
	BytesText  string
	Online     int // visitors currently viewing the link
	Active     int // downloads in flight
}

// App is the application core.
type App struct {
	Store   *core.Store
	Tracker *activity.Tracker

	dataDir      string
	native       Native
	tunnel       *tunnel.Runner
	publicAssets fs.FS

	mu         sync.RWMutex
	status     ShareStatus
	publicURL  string
	lanURL     string
	shareError string
	liveSince  time.Time
	shareToken string
	publicPort int
	publicSrv  *http.Server

	// shareMu serialises start/stop so two clicks cannot race.
	shareMu sync.Mutex

	// Broadcast plumbing for the SSE stream.
	busMu    sync.Mutex
	clients  map[chan []byte]struct{}
	dirty    chan struct{}
	shutdown chan struct{}
	once     sync.Once
}

// New builds the application core. dataDir is where cloudflared is cached, and
// publicAssets is the embedded bundle for the share page.
func New(dataDir string, native Native, publicAssets fs.FS) *App {
	a := &App{
		dataDir:      dataDir,
		native:       native,
		publicAssets: publicAssets,
		status:       StatusIdle,
		clients:      make(map[chan []byte]struct{}),
		dirty:        make(chan struct{}, 1),
		shutdown:     make(chan struct{}),
	}

	a.Store = core.NewStore(a.MarkDirty)
	a.Tracker = activity.New(a.MarkDirty)
	a.tunnel = tunnel.NewRunner(dataDir, a.Tracker.Logf)

	go a.broadcastLoop()
	return a
}

// Close tears everything down on quit.
func (a *App) Close() {
	a.once.Do(func() {
		close(a.shutdown)
		a.StopShare()
	})
}

func newToken() string {
	buf := make([]byte, 18)
	if _, err := rand.Read(buf); err != nil {
		// crypto/rand only fails catastrophically; fall back to a time seed so
		// the app still runs rather than dying on a share click.
		return base64.RawURLEncoding.EncodeToString([]byte(time.Now().Format(time.RFC3339Nano)))
	}
	return base64.RawURLEncoding.EncodeToString(buf)
}

// ---------------------------------------------------------------- broadcasting

// MarkDirty schedules a state broadcast. It never blocks.
func (a *App) MarkDirty() {
	select {
	case a.dirty <- struct{}{}:
	default:
	}
}

// Subscribe registers an SSE client. The returned function unregisters it.
func (a *App) Subscribe() (<-chan []byte, func()) {
	// A small buffer lets a briefly-stalled client catch up instead of
	// dropping frames; a full buffer means the client is gone.
	channel := make(chan []byte, 4)

	a.busMu.Lock()
	a.clients[channel] = struct{}{}
	a.busMu.Unlock()

	return channel, func() {
		a.busMu.Lock()
		if _, ok := a.clients[channel]; ok {
			delete(a.clients, channel)
			close(channel)
		}
		a.busMu.Unlock()
	}
}

// broadcastLoop coalesces state changes so a burst of updates becomes one
// frame, and keeps ticking while transfers are running so progress animates.
func (a *App) broadcastLoop() {
	const (
		coalesce = 120 * time.Millisecond
		progress = 400 * time.Millisecond
	)

	ticker := time.NewTicker(progress)
	defer ticker.Stop()

	var pending bool
	settle := time.NewTimer(time.Hour)
	settle.Stop()
	defer settle.Stop()

	for {
		select {
		case <-a.shutdown:
			return

		case <-a.dirty:
			if !pending {
				pending = true
				settle.Reset(coalesce)
			}

		case <-settle.C:
			pending = false
			a.publish()

		case <-ticker.C:
			// Only spin while something is actually moving.
			if a.Tracker.HasActive() {
				a.publish()
			}
		}
	}
}

func (a *App) publish() {
	state := a.Snapshot()

	if a.native != nil {
		a.native.StateChanged(summaryOf(state))
	}

	payload, err := encodeState(state)
	if err != nil {
		return
	}

	a.busMu.Lock()
	for channel := range a.clients {
		select {
		case channel <- payload:
		default:
			// Client is not keeping up; it will get the next frame.
		}
	}
	a.busMu.Unlock()
}

// ---------------------------------------------------------------------- items

// AddPaths shares the given files and folders, starting the tunnel the first
// time something is added.
func (a *App) AddPaths(paths []string) error {
	if len(paths) == 0 {
		return nil
	}
	wasEmpty := a.Store.IsEmpty()

	added, err := a.Store.AddPaths(paths)
	if added > 0 {
		a.Tracker.Logf("info", "Añadidos %d elementos", added)
	}
	if wasEmpty && added > 0 {
		go a.autoStart()
	}
	return err
}

// autoStart brings the link up on its own after the first item is added, which
// is the whole point of the drag-and-drop flow.
func (a *App) autoStart() {
	a.mu.RLock()
	status := a.status
	a.mu.RUnlock()

	switch status {
	case StatusIdle, StatusStopped, StatusError:
		if err := a.StartShare(); err != nil {
			a.Tracker.Logf("error", "%s", err.Error())
		}
	}
}

// AddFilesDialog opens the native multi-file picker.
func (a *App) AddFilesDialog() error {
	paths, err := a.native.PickFiles()
	if err != nil {
		return err
	}
	return a.AddPaths(paths)
}

// AddFolderDialog opens the native folder picker.
func (a *App) AddFolderDialog() error {
	path, err := a.native.PickFolder()
	if err != nil {
		return err
	}
	if path == "" {
		return nil
	}
	return a.AddPaths([]string{path})
}

// RemoveItems drops shared items, stopping the share when nothing is left.
func (a *App) RemoveItems(ids []string) error {
	if a.Store.Remove(ids) == 0 {
		return nil
	}
	if a.Store.IsEmpty() {
		go a.StopShare()
	}
	return nil
}

// ClearItems removes everything and stops sharing.
func (a *App) ClearItems() error {
	a.Store.Clear()
	go a.StopShare()
	return nil
}

// RevealItem shows an item in the system file manager.
func (a *App) RevealItem(id string) error {
	path, ok := a.Store.ItemPath(id)
	if !ok {
		return errors.New("ese elemento ya no está en la lista")
	}
	return a.native.Reveal(path)
}

// ---------------------------------------------------------------------- share

// ShareToken is the secret path segment of the public link.
func (a *App) ShareToken() string {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.shareToken
}

// PublicURL returns the current public link, empty when not sharing.
func (a *App) PublicURL() string {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.publicURL
}

// Status returns the current share status.
func (a *App) Status() ShareStatus {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.status
}

func (a *App) setStatus(status ShareStatus, shareErr string) {
	a.mu.Lock()
	a.status = status
	a.shareError = shareErr
	if status == StatusLive {
		a.liveSince = time.Now()
	}
	if status != StatusLive {
		a.publicURL = ""
	}
	a.mu.Unlock()

	a.MarkDirty()
}

// StartShare brings up the public server and the cloudflared tunnel.
func (a *App) StartShare() error {
	a.shareMu.Lock()
	defer a.shareMu.Unlock()

	if a.Status() == StatusLive {
		return nil
	}
	if a.Store.IsEmpty() {
		return errors.New("añade algún archivo antes de compartir")
	}

	a.setStatus(StatusPreparing, "")

	token := newToken()
	port, err := a.startPublicServer(token)
	if err != nil {
		a.setStatus(StatusError, err.Error())
		return err
	}

	a.mu.Lock()
	a.shareToken = token
	a.publicPort = port
	a.lanURL = ""
	if ip := lanIP(); ip != "" {
		a.lanURL = fmt.Sprintf("http://%s:%d/s/%s", ip, port, token)
	}
	a.mu.Unlock()

	if tunnel.Locate(a.dataDir) == "" {
		a.setStatus(StatusInstalling, "")
	} else {
		a.setStatus(StatusStarting, "")
	}

	base, err := a.tunnel.Start(port, a.onTunnelDied)
	if err != nil {
		a.Tracker.Logf("error", "%s", err.Error())
		// The LAN link still works, so leave the public server running and
		// surface the failure instead of tearing everything down.
		a.setStatus(StatusError, err.Error())
		return err
	}

	// cloudflared announces the URL before Cloudflare publishes its DNS record,
	// and trycloudflare.com caches NXDOMAIN for 30 minutes. Handing the link
	// over now would give the first person to open it a link that stays broken
	// for half an hour, so wait for the name to actually resolve first.
	waitCtx, cancelWait := context.WithTimeout(context.Background(), 2*time.Minute)
	tunnel.WaitUntilResolvable(waitCtx, base, a.Tracker.Logf)
	cancelWait()

	// The user may have stopped sharing while we waited.
	if a.Status() != StatusStarting && a.Status() != StatusInstalling {
		return nil
	}

	a.mu.Lock()
	a.publicURL = base + "/s/" + token
	url := a.publicURL
	a.mu.Unlock()

	a.setStatus(StatusLive, "")
	a.Tracker.Logf("info", "Enlace listo: %s", url)
	return nil
}

// onTunnelDied handles cloudflared exiting without being asked to.
func (a *App) onTunnelDied(err error) {
	if a.Status() != StatusLive {
		return
	}
	message := "el túnel se cerró de forma inesperada"
	if err != nil {
		message = "el túnel se cerró: " + err.Error()
	}
	a.Tracker.Logf("error", "%s", message)
	a.setStatus(StatusError, message)
}

// StopShare tears down the tunnel and the public server.
func (a *App) StopShare() error {
	a.shareMu.Lock()
	defer a.shareMu.Unlock()

	if a.Status() == StatusIdle {
		return nil
	}
	a.setStatus(StatusStopping, "")

	a.Tracker.CancelAll()
	a.tunnel.Stop()
	a.stopPublicServer()
	a.Tracker.Reset()

	a.mu.Lock()
	a.publicURL = ""
	a.lanURL = ""
	a.shareToken = ""
	a.publicPort = 0
	a.liveSince = time.Time{}
	a.mu.Unlock()

	a.setStatus(StatusStopped, "")
	a.Tracker.Logf("info", "Has dejado de compartir")
	return nil
}

// OpenPublicPage opens the share link in the user's real browser, so they can
// see exactly what a recipient sees.
func (a *App) OpenPublicPage() error {
	a.mu.RLock()
	url := a.publicURL
	if url == "" {
		url = a.lanURL
	}
	a.mu.RUnlock()

	if url == "" {
		return errors.New("todavía no hay ninguna página que abrir")
	}
	return a.native.OpenInBrowser(url)
}

// CopyLink puts the public link on the clipboard.
func (a *App) CopyLink() error {
	a.mu.RLock()
	url := a.publicURL
	if url == "" {
		url = a.lanURL
	}
	a.mu.RUnlock()

	if url == "" {
		return errors.New("todavía no hay ningún enlace que copiar")
	}
	if !a.native.SetClipboard(url) {
		return errors.New("no se pudo copiar al portapapeles")
	}
	return nil
}

// CancelTransfer aborts a download in progress.
func (a *App) CancelTransfer(id string) error {
	if !a.Tracker.Cancel(id) {
		return errors.New("esa descarga ya había terminado")
	}
	return nil
}

// ForgetVisitor removes a visitor from the list.
func (a *App) ForgetVisitor(id string) error {
	if !a.Tracker.Forget(id) {
		return errors.New("ese visitante ya no está en la lista")
	}
	return nil
}

// MinimiseWindow, HideWindow and ShowWindow forward to the native layer.
func (a *App) MinimiseWindow() { a.native.MinimiseWindow() }
func (a *App) HideWindow()     { a.native.HideWindow() }
func (a *App) ShowWindow()     { a.native.ShowWindow() }

// ------------------------------------------------------------- public server

func (a *App) startPublicServer(token string) (int, error) {
	// Bind every interface so the LAN link is a genuine fallback when
	// cloudflared cannot be reached. The token in the path is what guards it.
	listener, err := net.Listen("tcp", "0.0.0.0:0")
	if err != nil {
		return 0, fmt.Errorf("no se pudo abrir un puerto local: %w", err)
	}

	handler := publicweb.New(a.publicAssets, a.Store, a.Tracker, token)
	server := &http.Server{
		Handler:           handler,
		ReadHeaderTimeout: 15 * time.Second,
		// No WriteTimeout: downloads of large files must be able to run long.
		IdleTimeout: 60 * time.Second,
	}

	a.mu.Lock()
	a.publicSrv = server
	a.mu.Unlock()

	go func() {
		if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
			a.Tracker.Logf("error", "El servidor local falló: %s", err.Error())
		}
	}()

	return listener.Addr().(*net.TCPAddr).Port, nil
}

func (a *App) stopPublicServer() {
	a.mu.Lock()
	server := a.publicSrv
	a.publicSrv = nil
	a.mu.Unlock()

	if server == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	// Cancelled transfers make Shutdown return early; Close finishes the job.
	if err := server.Shutdown(ctx); err != nil {
		server.Close()
	}
}

// lanIP finds the address other machines on the network can reach us at. The
// UDP socket is never used to send anything; it just resolves the route.
func lanIP() string {
	conn, err := net.Dial("udp", "8.8.8.8:80")
	if err != nil {
		return ""
	}
	defer conn.Close()

	addr, ok := conn.LocalAddr().(*net.UDPAddr)
	if !ok || addr.IP.IsLoopback() {
		return ""
	}
	return addr.IP.String()
}
