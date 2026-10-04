//go:build !darwin

package main

import (
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/app"
	"github.com/wailsapp/wails/v3/pkg/application"
)

func buildNativeTray(*application.App, *app.App, *desktopBridge) bool { return false }
