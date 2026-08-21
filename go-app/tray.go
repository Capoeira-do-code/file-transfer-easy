package main

import (
	"runtime"

	"github.com/wailsapp/wails/v3/pkg/application"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/app"
)

// buildTray puts the app in the macOS menu bar or the Windows notification
// area. The top of the menu is a live summary, so the user can see what is
// being shared and who is on it without opening the window at all.
func buildTray(wails *application.App, core *app.App, desktop *desktopBridge) {
	tray := wails.SystemTray.New()

	if runtime.GOOS == "darwin" {
		// A template icon adapts to light and dark menu bars automatically.
		if data := icon("tray-template.png"); data != nil {
			tray.SetTemplateIcon(data)
		}
	} else if data := icon("tray.png"); data != nil {
		tray.SetIcon(data)
	}

	menu := application.NewMenu()

	// Two read-only lines at the top: what is shared, and what is happening.
	// They are disabled because they are information, not actions.
	content := menu.Add("Nada compartido todavía")
	content.SetEnabled(false)
	activity := menu.Add("Listo")
	activity.SetEnabled(false)

	menu.AddSeparator()

	menu.Add("Abrir la ventana").OnClick(func(*application.Context) {
		desktop.ShowWindow()
	})

	openPage := menu.Add("Ver la página pública")
	openPage.OnClick(func(*application.Context) {
		if err := core.OpenPublicPage(); err != nil {
			core.Tracker.Logf("warn", "%s", err.Error())
		}
	})

	copyLink := menu.Add("Copiar enlace")
	copyLink.OnClick(func(*application.Context) {
		if err := core.CopyLink(); err != nil {
			core.Tracker.Logf("warn", "%s", err.Error())
		}
	})

	menu.AddSeparator()

	// Adding from the tray matters because the window is often hidden.
	menu.Add("Añadir archivos…").OnClick(func(*application.Context) {
		desktop.ShowWindow()
		go func() {
			if err := core.AddFilesDialog(); err != nil {
				core.Tracker.Logf("warn", "%s", err.Error())
			}
		}()
	})
	menu.Add("Añadir carpeta…").OnClick(func(*application.Context) {
		desktop.ShowWindow()
		go func() {
			if err := core.AddFolderDialog(); err != nil {
				core.Tracker.Logf("warn", "%s", err.Error())
			}
		}()
	})

	menu.AddSeparator()

	stop := menu.Add("Dejar de compartir")
	stop.OnClick(func(*application.Context) { go core.StopShare() })

	menu.Add("Salir").OnClick(func(*application.Context) {
		core.Close()
		wails.Quit()
	})

	tray.SetMenu(menu)
	tray.OnClick(func() { desktop.ShowWindow() })

	desktop.adoptTray(&trayHandles{
		tray:     tray,
		content:  content,
		activity: activity,
		copyLink: copyLink,
		openPage: openPage,
		stop:     stop,
	})

	tray.Run()
}

// trayHandles are the menu items the bridge keeps up to date.
type trayHandles struct {
	tray     *application.SystemTray
	content  *application.MenuItem
	activity *application.MenuItem
	copyLink *application.MenuItem
	openPage *application.MenuItem
	stop     *application.MenuItem
}

// refresh rewrites the summary lines and enables only the actions that can
// actually do something right now.
func (h *trayHandles) refresh(summary app.Summary) {
	if h == nil {
		return
	}

	h.content.SetLabel(summary.ContentLine())
	h.activity.SetLabel(summary.ActivityLine())

	live := summary.Status == app.StatusLive && summary.URL != ""
	h.copyLink.SetEnabled(live)
	h.openPage.SetEnabled(live)
	h.stop.SetEnabled(summary.Status != app.StatusIdle && summary.Status != app.StatusStopped)

	h.tray.SetTooltip(summary.Tooltip())
}
