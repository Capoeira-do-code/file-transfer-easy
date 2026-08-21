// Command file-transfer-easy is a desktop app for sharing files from your own
// machine: drop files or folders on the window, get a public link, and watch
// live who opens it and what they download.
//
// The window is a Wails v3 webview pointed at a loopback HTTP server, so the
// whole UI is plain HTML talking plain HTTP. Sharing happens over a Cloudflare
// quick tunnel run by the bundled cloudflared.
package main

import (
	"embed"
	"io/fs"
	"log"
	"os"
	"path/filepath"
	"strings"

	"github.com/wailsapp/wails/v3/pkg/application"
	"github.com/wailsapp/wails/v3/pkg/events"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/app"
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/uiserver"
)

//go:embed all:frontend
var frontendFS embed.FS

//go:embed all:public
var publicFS embed.FS

//go:embed build/icons
var iconFS embed.FS

const appName = "File Transfer Easy"

// version is stamped at build time with -ldflags "-X main.version=…".
var version = "dev"

func main() {
	if err := run(); err != nil {
		log.Fatalf("%s no pudo arrancar: %v", appName, err)
	}
}

func run() error {
	frontend, err := fs.Sub(frontendFS, "frontend")
	if err != nil {
		return err
	}
	public, err := fs.Sub(publicFS, "public")
	if err != nil {
		return err
	}

	dataDir, err := ensureDataDir()
	if err != nil {
		return err
	}

	desktop := &desktopBridge{}
	core := app.New(dataDir, desktop, public)
	defer core.Close()

	ui := uiserver.New(core, frontend, newUIToken())
	uiURL, err := ui.Start()
	if err != nil {
		return err
	}
	defer ui.Close()

	wails := application.New(application.Options{
		Name:        appName,
		Description: "Envía archivos entre dispositivos que no están en la misma red · " + version,
		Icon:        icon("appicon.png"),
		Mac: application.MacOptions{
			ActivationPolicy: application.ActivationPolicyRegular,
			// Closing the window hides it to the tray, so the app must survive
			// having no windows on screen.
			ApplicationShouldTerminateAfterLastWindowClosed: false,
		},
		SingleInstance: &application.SingleInstanceOptions{
			UniqueID: "com.filetransfereasy.desktop",
			OnSecondInstanceLaunch: func(data application.SecondInstanceData) {
				// On Windows, dropping files on the executable or a shortcut
				// launches a second instance with them as arguments.
				if paths := existingPaths(data.Args); len(paths) > 0 {
					core.AddPaths(paths)
				}
				desktop.ShowWindow()
			},
		},
		OnShutdown: func() {
			core.Close()
			ui.Close()
		},
	})

	window := wails.Window.NewWithOptions(application.WebviewWindowOptions{
		Name:      "main",
		Title:     appName,
		URL:       uiURL,
		Width:     1040,
		Height:    720,
		MinWidth:  820,
		MinHeight: 560,
		// Native file drop is handled entirely in Go: the paths never reach the
		// page, which is what lets the UI stay a plain sandboxed web page.
		EnableFileDrop:             true,
		DefaultContextMenuDisabled: true,
		BackgroundColour:           application.NewRGB(15, 22, 24),
		InitialPosition:            application.WindowCentered,
		Mac: application.MacWindow{
			// The inset title bar gives the traffic lights room while letting
			// the page paint the whole window.
			TitleBar:                application.MacTitleBarHiddenInset,
			InvisibleTitleBarHeight: 28,
			Backdrop:                application.MacBackdropNormal,
		},
	})

	desktop.attach(wails, window, core)

	window.OnWindowEvent(events.Common.WindowFilesDropped, func(event *application.WindowEvent) {
		paths := event.Context().DroppedFiles()
		if len(paths) == 0 {
			return
		}
		if err := core.AddPaths(paths); err != nil {
			core.Tracker.Logf("warn", "%s", err.Error())
		}
	})

	// Closing the window keeps the app alive in the tray, which is what a
	// background sharing tool should do.
	window.RegisterHook(events.Common.WindowClosing, func(event *application.WindowEvent) {
		event.Cancel()
		window.Hide()
	})

	// SystemTray.Run() is a no-op until the application is running, so the tray
	// has to be built from the started event rather than before Run().
	wails.Event.OnApplicationEvent(events.Common.ApplicationStarted, func(*application.ApplicationEvent) {
		buildTray(wails, core, desktop)
	})

	// Files dropped on the Dock icon (macOS) or opened with the app (Windows)
	// are added straight away, which is what makes adding things possible while
	// the window is hidden. The system tray icon itself cannot accept drops:
	// neither Wails nor the platforms expose that.
	wails.Event.OnApplicationEvent(events.Common.ApplicationOpenedWithFile, func(event *application.ApplicationEvent) {
		path := event.Context().Filename()
		if path == "" {
			return
		}
		if err := core.AddPaths([]string{path}); err != nil {
			core.Tracker.Logf("warn", "%s", err.Error())
		}
	})

	return wails.Run()
}

// ensureDataDir returns the per-user directory where cloudflared is cached.
func ensureDataDir() (string, error) {
	base, err := os.UserConfigDir()
	if err != nil {
		home, homeErr := os.UserHomeDir()
		if homeErr != nil {
			return "", err
		}
		base = home
	}
	dir := filepath.Join(base, "FileTransferEasy")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	return dir, nil
}

// existingPaths keeps only the arguments that name something on disk, so that
// flags and stray arguments are never mistaken for files to share.
func existingPaths(args []string) []string {
	var paths []string
	for _, arg := range args {
		if arg == "" || strings.HasPrefix(arg, "-") {
			continue
		}
		if _, err := os.Stat(arg); err == nil {
			paths = append(paths, arg)
		}
	}
	return paths
}

func icon(name string) []byte {
	data, err := iconFS.ReadFile("build/icons/" + name)
	if err != nil {
		return nil
	}
	return data
}
