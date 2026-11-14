package app

import (
	"errors"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/access"
)

func (a *App) UpdateSettings(patch access.SettingsPatch) error {
	if err := a.Access.UpdateSettings(patch); err != nil {
		return err
	}
	a.mu.Lock()
	if a.settingsError != "" {
		a.settingsError = ""
		a.status, a.shareError = StatusIdle, ""
	}
	a.mu.Unlock()
	a.MarkDirty()
	return nil
}

func (a *App) SetItemPassword(id, password string) error {
	if _, ok := a.Store.ItemPath(id); !ok {
		return errors.New("ese archivo o carpeta ya no está en la lista")
	}
	return a.Access.SetItemPassword(id, password)
}

func (a *App) SetVisitorBlocked(ip string, blocked bool) error {
	if err := a.Access.SetBlocked(ip, blocked); err != nil {
		return err
	}
	if blocked {
		a.Tracker.CancelIP(ip)
	}
	a.MarkDirty()
	return nil
}

// ReceivePaths adds successfully saved uploads without starting another tunnel.
func (a *App) ReceivePaths(paths []string) error {
	added, err := a.Store.AddPaths(paths)
	if added > 0 {
		a.Tracker.Logf("info", "Recibidos %d archivos", added)
	}
	return err
}

func (a *App) PickUploadFolder() (string, error) {
	if a.native == nil {
		return "", errors.New("el selector de carpetas no está disponible")
	}
	if picker, ok := a.native.(interface{ PickUploadFolder() (string, error) }); ok {
		return picker.PickUploadFolder()
	}
	return a.native.PickFolder()
}

// Bring a hidden desktop window forward once for each new access request.
// The actual decision remains with the host through the request controls.
func (a *App) notifyAccessRequests(requests []access.Request) {
	if a.native == nil {
		return
	}
	show := false
	a.mu.Lock()
	pending := make(map[string]bool)
	for _, request := range requests {
		if request.Status == "pending" {
			pending[request.ID] = true
			if !a.notifiedRequests[request.ID] {
				show = true
			}
		}
	}
	a.notifiedRequests = pending
	a.mu.Unlock()
	if show {
		a.native.ShowWindow()
	}
}
