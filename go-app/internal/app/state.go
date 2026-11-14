package app

import (
	"time"

	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/access"
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/activity"
	"github.com/Capoeira-do-code/file-transfer-easy/go-app/internal/format"
)

// ShareStatus is the lifecycle of the public link.
type ShareStatus string

const (
	StatusIdle       ShareStatus = "idle"
	StatusPreparing  ShareStatus = "preparing"
	StatusInstalling ShareStatus = "installing"
	StatusStarting   ShareStatus = "starting"
	StatusLive       ShareStatus = "live"
	StatusStopping   ShareStatus = "stopping"
	StatusStopped    ShareStatus = "stopped"
	StatusError      ShareStatus = "error"
)

// statusText maps a status to the already-localised label the UI displays.
var statusText = map[ShareStatus]string{
	StatusIdle:       "Listo",
	StatusPreparing:  "Preparando…",
	StatusInstalling: "Instalando cloudflared…",
	StatusStarting:   "Creando el enlace…",
	StatusLive:       "Compartiendo",
	StatusStopping:   "Deteniendo…",
	StatusStopped:    "Detenido",
	StatusError:      "Error",
}

// State is the payload the desktop UI renders. Field names match the contract
// the frontend was written against, so changes here are breaking changes.
type State struct {
	Items     []ItemView          `json:"items"`
	Totals    TotalsView          `json:"totals"`
	Share     ShareView           `json:"share"`
	Visitors  []VisitorView       `json:"visitors"`
	Transfers []TransferView      `json:"transfers"`
	Stats     StatsView           `json:"stats"`
	Log       []LogView           `json:"log"`
	Settings  access.SettingsView `json:"settings"`
	History   []HistoryView       `json:"history"`
	Requests  []access.Request    `json:"requests"`
}

type ItemView struct {
	ID        string `json:"id"`
	Kind      string `json:"kind"`
	Name      string `json:"name"`
	Path      string `json:"path"`
	Ext       string `json:"ext"`
	Size      int64  `json:"size"`
	SizeText  string `json:"sizeText"`
	FileCount int    `json:"fileCount"`
	Missing   bool   `json:"missing"`
	AddedAt   string `json:"addedAt"`
	Protected bool   `json:"protected"`
}

type TotalsView struct {
	Items     int    `json:"items"`
	Files     int    `json:"files"`
	Bytes     int64  `json:"bytes"`
	BytesText string `json:"bytesText"`
}

type HistoryView struct {
	access.Visitor
	BytesText string `json:"bytesText"`
}

type ShareView struct {
	Status     string `json:"status"`
	StatusText string `json:"statusText"`
	URL        string `json:"url"`
	LanURL     string `json:"lanUrl"`
	Error      string `json:"error"`
	Since      string `json:"since"`
}

type VisitorView struct {
	ID        string `json:"id"`
	IP        string `json:"ip"`
	Label     string `json:"label"`
	Online    bool   `json:"online"`
	FirstSeen string `json:"firstSeen"`
	LastSeen  string `json:"lastSeen"`
	Downloads int    `json:"downloads"`
	Bytes     int64  `json:"bytes"`
	BytesText string `json:"bytesText"`
	Name      string `json:"name"`
	Blocked   bool   `json:"blocked"`
}

type TransferView struct {
	ID        string  `json:"id"`
	Name      string  `json:"name"`
	IP        string  `json:"ip"`
	Kind      string  `json:"kind"`
	Status    string  `json:"status"`
	Bytes     int64   `json:"bytes"`
	Total     int64   `json:"total"`
	Percent   float64 `json:"percent"`
	Speed     float64 `json:"speed"`
	SpeedText string  `json:"speedText"`
	ETAText   string  `json:"etaText"`
}

type StatsView struct {
	Downloads         int    `json:"downloads"`
	Bytes             int64  `json:"bytes"`
	BytesText         string `json:"bytesText"`
	Visitors          int    `json:"visitors"`
	Uploads           int    `json:"uploads"`
	ReceivedBytes     int64  `json:"receivedBytes"`
	ReceivedBytesText string `json:"receivedBytesText"`
}

type LogView struct {
	Time  string `json:"time"`
	Level string `json:"level"`
	Text  string `json:"text"`
}

// Snapshot builds the current state for the UI.
func (a *App) Snapshot() State {
	items := a.Store.Items()
	totals := a.Store.Totals()
	visitors, transfers, stats, logs := a.Tracker.Snapshot()
	requests := a.Access.Requests()
	for i := range requests {
		if name := a.Access.Name(requests[i].IP); name != "" {
			requests[i].Name = name
		}
	}

	state := State{
		Items:     make([]ItemView, 0, len(items)),
		Visitors:  make([]VisitorView, 0, len(visitors)),
		Transfers: make([]TransferView, 0, len(transfers)),
		Log:       make([]LogView, 0, len(logs)),
		Totals: TotalsView{
			Items:     totals.Items,
			Files:     totals.Files,
			Bytes:     totals.Bytes,
			BytesText: format.Bytes(totals.Bytes),
		},
		Stats: StatsView{
			Downloads:         stats.Downloads,
			Bytes:             stats.Bytes,
			BytesText:         format.Bytes(stats.Bytes),
			Visitors:          stats.Visitors,
			Uploads:           stats.Uploads,
			ReceivedBytes:     stats.ReceivedBytes,
			ReceivedBytesText: format.Bytes(stats.ReceivedBytes),
		},
		Share:    a.shareView(),
		Settings: a.Access.Settings(),
		History:  make([]HistoryView, 0),
		Requests: requests,
	}

	for _, item := range items {
		state.Items = append(state.Items, ItemView{
			ID:        item.ID,
			Kind:      string(item.Kind),
			Name:      item.Name,
			Path:      item.Path,
			Ext:       item.Ext,
			Size:      item.Size,
			SizeText:  format.Bytes(item.Size),
			FileCount: item.FileCount,
			Missing:   item.Missing,
			AddedAt:   item.AddedAt.UTC().Format(time.RFC3339),
			Protected: a.Access.ItemProtected(item.ID),
		})
	}

	for _, visitor := range visitors {
		state.Visitors = append(state.Visitors, VisitorView{
			ID:        visitor.ID,
			IP:        visitor.IP,
			Label:     visitor.Label,
			Online:    visitor.Online(),
			FirstSeen: visitor.FirstSeen.UTC().Format(time.RFC3339),
			LastSeen:  visitor.LastSeen.UTC().Format(time.RFC3339),
			Downloads: visitor.Downloads,
			Bytes:     visitor.Bytes,
			BytesText: format.Bytes(visitor.Bytes),
			Name:      a.Access.Name(visitor.IP),
			Blocked:   a.Access.IsBlocked(visitor.IP),
		})
	}
	for _, visitor := range a.Access.History() {
		state.History = append(state.History, HistoryView{Visitor: visitor, BytesText: format.Bytes(visitor.Bytes)})
	}

	for _, transfer := range transfers {
		state.Transfers = append(state.Transfers, transferView(transfer))
	}

	for _, entry := range logs {
		state.Log = append(state.Log, LogView{
			Time:  format.Clock(entry.Time),
			Level: entry.Level,
			Text:  entry.Text,
		})
	}

	return state
}

func transferView(transfer activity.TransferSnapshot) TransferView {
	view := TransferView{
		ID:     transfer.ID,
		Name:   transfer.Name,
		IP:     transfer.IP,
		Kind:   transfer.Kind,
		Status: transfer.Status,
		Bytes:  transfer.Bytes,
		Total:  transfer.Total,
		Speed:  transfer.Speed,
	}

	switch {
	case transfer.Total > 0:
		view.Percent = float64(transfer.Bytes) / float64(transfer.Total) * 100
		if view.Percent > 100 {
			view.Percent = 100
		}
	case transfer.Status == "done":
		// A zip has no known total until it is finished.
		view.Percent = 100
	}

	if transfer.Status == "active" {
		view.SpeedText = format.Speed(transfer.Speed)
		view.ETAText = format.ETA(transfer.Total-transfer.Bytes, transfer.Speed)
	} else {
		view.SpeedText = "—"
		view.ETAText = "—"
		if transfer.Status == "done" {
			// Show the average rate achieved rather than a stale instant value.
			if elapsed := transfer.Finished.Sub(transfer.Started).Seconds(); elapsed > 0 {
				view.SpeedText = format.Speed(float64(transfer.Bytes) / elapsed)
			}
		}
	}

	return view
}

func (a *App) shareView() ShareView {
	a.mu.RLock()
	defer a.mu.RUnlock()

	view := ShareView{
		Status:     string(a.status),
		StatusText: statusText[a.status],
		URL:        a.publicURL,
		LanURL:     a.lanURL,
		Error:      a.shareError,
	}
	if !a.liveSince.IsZero() {
		view.Since = a.liveSince.UTC().Format(time.RFC3339)
	}
	return view
}
