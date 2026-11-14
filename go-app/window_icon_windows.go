package main

import (
	"log"
	"sync"

	"github.com/wailsapp/wails/v3/pkg/application"
	"github.com/wailsapp/wails/v3/pkg/events"
	"github.com/wailsapp/wails/v3/pkg/w32"
)

// configureWindowIcon sets both sizes explicitly: Wails only assigns ICON_BIG,
// leaving the title bar and small taskbar icon dependent on a class fallback.
// Use the embedded ICO as well as the EXE resource so development builds have
// the same icon. The two handles stay alive with the application's window class.
func configureWindowIcon(window *application.WebviewWindow) {
	var once sync.Once
	window.OnWindowEvent(events.Windows.WebViewNavigationCompleted, func(*application.WindowEvent) {
		application.InvokeAsync(func() {
			if window.NativeWindow() == nil {
				return
			}
			once.Do(func() {
				large, err := w32.CreateLargeHIconFromImage(icon("icon.ico"))
				if err != nil {
					log.Printf("no se pudo cargar el icono de la ventana: %v", err)
					return
				}
				small, err := w32.CreateSmallHIconFromImage(icon("icon.ico"))
				if err != nil {
					w32.DestroyIcon(large)
					log.Printf("no se pudo cargar el icono pequeño: %v", err)
					return
				}
				hwnd := uintptr(window.NativeWindow())
				w32.SendMessage(hwnd, w32.WM_SETICON, w32.ICON_BIG, large)
				w32.SetWindowIcon(hwnd, small)
				w32.SetApplicationIcon(hwnd, large)
			})
		})
	})
}
