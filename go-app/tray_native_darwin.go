package main

/*
#cgo CFLAGS: -mmacosx-version-min=13.0
#cgo LDFLAGS: -framework Cocoa
#include <stdlib.h>
#include "tray_native_darwin.h"
*/
import "C"

import (
	"encoding/json"
	"unsafe"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/app"
	"github.com/wailsapp/wails/v3/pkg/application"
)

// These handlers are installed before the status item is created, then remain
// immutable. Native callbacks queue work so drag tracking never waits on Go.
var nativeTrayAction func(int)
var nativeTrayDrop func([]string)

//export fteTrayAction
func fteTrayAction(action C.int) {
	if nativeTrayAction != nil {
		go nativeTrayAction(int(action))
	}
}

//export fteTrayDrop
func fteTrayDrop(payload *C.char) {
	var paths []string
	if json.Unmarshal([]byte(C.GoString(payload)), &paths) == nil && len(paths) > 0 && nativeTrayDrop != nil {
		go nativeTrayDrop(paths)
	}
}

func buildNativeTray(wails *application.App, core *app.App, desktop *desktopBridge) bool {
	data := icon("tray-template.png")
	if len(data) == 0 {
		return false
	}
	nativeTrayDrop = desktop.AddDroppedPaths
	nativeTrayAction = func(action int) {
		var err error
		switch action {
		case 1:
			desktop.ShowWindow()
		case 2:
			err = core.OpenPublicPage()
		case 3:
			err = core.CopyLink()
		case 4:
			desktop.ShowWindow()
			err = core.AddFilesDialog()
		case 5:
			desktop.ShowWindow()
			err = core.AddFolderDialog()
		case 6:
			err = core.StopShare()
		case 7:
			core.Close()
			wails.Quit()
		}
		if err != nil {
			core.Tracker.Logf("warn", "%s", err.Error())
		}
	}
	application.InvokeSync(func() {
		C.fteTrayCreate(unsafe.Pointer(&data[0]), C.size_t(len(data)))
	})
	desktop.adoptTray(&trayHandles{refreshNative: func(summary app.Summary) {
		content, activity := C.CString(summary.ContentLine()), C.CString(summary.ActivityLine())
		defer C.free(unsafe.Pointer(content))
		defer C.free(unsafe.Pointer(activity))
		live := summary.Status == app.StatusLive && summary.URL != ""
		C.fteTrayUpdate(content, activity, C.bool(live), C.bool(live || summary.LANURL != ""),
			C.bool(summary.Status != app.StatusIdle && summary.Status != app.StatusStopped))
	}})
	core.MarkDirty()
	return true
}
