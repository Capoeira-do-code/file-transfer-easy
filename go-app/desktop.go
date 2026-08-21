package main

import (
	"crypto/rand"
	"encoding/base64"
	"os/exec"
	"path/filepath"
	"runtime"
	"sync"

	"github.com/wailsapp/wails/v3/pkg/application"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/app"
)

// desktopBridge implements app.Native against Wails. It is created before the
// Wails application exists so it can be handed to the core, then wired up with
// attach once the window is built.
type desktopBridge struct {
	mu     sync.RWMutex
	wails  *application.App
	window *application.WebviewWindow
	core   *app.App

	tray *trayHandles
}

// adoptTray hands the bridge the menu items it keeps in sync.
func (d *desktopBridge) adoptTray(handles *trayHandles) {
	d.mu.Lock()
	d.tray = handles
	d.mu.Unlock()
}

func (d *desktopBridge) attach(wails *application.App, window *application.WebviewWindow, core *app.App) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.wails = wails
	d.window = window
	d.core = core
}

func (d *desktopBridge) parts() (*application.App, *application.WebviewWindow) {
	d.mu.RLock()
	defer d.mu.RUnlock()
	return d.wails, d.window
}

// PickFiles opens the native multi-file picker.
func (d *desktopBridge) PickFiles() ([]string, error) {
	wails, window := d.parts()
	if wails == nil {
		return nil, nil
	}

	dialog := wails.Dialog.OpenFile().
		CanChooseFiles(true).
		CanChooseDirectories(false).
		SetTitle("Elige los archivos que quieres compartir")
	if window != nil {
		dialog.AttachToWindow(window)
	}

	paths, err := dialog.PromptForMultipleSelection()
	if err != nil {
		return nil, err
	}
	return paths, nil
}

// PickFolder opens the native folder picker.
func (d *desktopBridge) PickFolder() (string, error) {
	wails, window := d.parts()
	if wails == nil {
		return "", nil
	}

	dialog := wails.Dialog.OpenFile().
		CanChooseFiles(false).
		CanChooseDirectories(true).
		SetTitle("Elige la carpeta que quieres compartir")
	if window != nil {
		dialog.AttachToWindow(window)
	}

	return dialog.PromptForSingleSelection()
}

// SetClipboard copies text to the system clipboard.
func (d *desktopBridge) SetClipboard(text string) bool {
	wails, _ := d.parts()
	if wails == nil {
		return false
	}
	return wails.Clipboard.SetText(text)
}

// MinimiseWindow minimises the window.
func (d *desktopBridge) MinimiseWindow() {
	if _, window := d.parts(); window != nil {
		window.Minimise()
	}
}

// HideWindow hides the window, leaving the app in the tray.
func (d *desktopBridge) HideWindow() {
	if _, window := d.parts(); window != nil {
		window.Hide()
	}
}

// ShowWindow brings the window back to the front from the tray.
func (d *desktopBridge) ShowWindow() {
	wails, window := d.parts()
	if window == nil {
		return
	}
	window.Show()
	window.Restore()
	window.Focus()
	if wails != nil {
		wails.Show()
	}
}

// StateChanged keeps the tray summary in step with the app.
//
// It arrives on the broadcast goroutine, but updating a menu item reaches
// straight into AppKit/Win32 with no marshalling of its own, so the work has to
// be handed to the main thread explicitly. The dispatch is asynchronous on
// purpose: a modal file dialog owns the main thread while it is open, and
// waiting for it would stall the whole event stream behind it.
func (d *desktopBridge) StateChanged(summary app.Summary) {
	d.mu.RLock()
	tray := d.tray
	d.mu.RUnlock()

	if tray == nil {
		return
	}
	application.InvokeAsync(func() { tray.refresh(summary) })
}

// OpenInBrowser opens a URL in the user's default browser.
func (d *desktopBridge) OpenInBrowser(url string) error {
	wails, _ := d.parts()
	if wails == nil {
		return nil
	}
	return wails.Browser.OpenURL(url)
}

// Reveal shows a file or folder in the system file manager.
func (d *desktopBridge) Reveal(path string) error {
	switch runtime.GOOS {
	case "darwin":
		return exec.Command("open", "-R", path).Start()
	case "windows":
		// explorer always exits non-zero here, so the error is not meaningful.
		exec.Command("explorer", "/select,"+filepath.Clean(path)).Start()
		return nil
	default:
		return exec.Command("xdg-open", filepath.Dir(path)).Start()
	}
}

// newUIToken mints the secret that guards the loopback UI server for this run.
func newUIToken() string {
	buf := make([]byte, 24)
	if _, err := rand.Read(buf); err != nil {
		// Without randomness the UI server would be unguarded, so refuse to run.
		panic("no se pudo generar el token de la interfaz: " + err.Error())
	}
	return base64.RawURLEncoding.EncodeToString(buf)
}
