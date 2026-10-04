package app

import (
	"fmt"
	"strings"
)

// summaryOf condenses a full snapshot into what the tray menu shows.
func summaryOf(state State) Summary {
	summary := Summary{
		Status:     ShareStatus(state.Share.Status),
		StatusText: state.Share.StatusText,
		URL:        state.Share.URL,
		LANURL:     state.Share.LanURL,
		Items:      state.Totals.Items,
		Files:      state.Totals.Files,
		BytesText:  state.Totals.BytesText,
	}
	for _, visitor := range state.Visitors {
		if visitor.Online {
			summary.Online++
		}
	}
	for _, transfer := range state.Transfers {
		if transfer.Status == "active" {
			summary.Active++
		}
	}
	return summary
}

// ContentLine describes what is being shared, e.g. "3 elementos · 12 archivos · 80 MB".
func (s Summary) ContentLine() string {
	if s.Items == 0 {
		return "Nada compartido todavía"
	}

	parts := []string{plural(s.Items, "elemento", "elementos")}
	// The file count only adds information once a folder is involved.
	if s.Files != s.Items {
		parts = append(parts, plural(s.Files, "archivo", "archivos"))
	}
	parts = append(parts, s.BytesText)
	return strings.Join(parts, " · ")
}

// ActivityLine describes the share status and who is on the other end.
func (s Summary) ActivityLine() string {
	if s.Status != StatusLive {
		return s.StatusText
	}

	parts := []string{"Compartiendo"}
	if s.Online > 0 {
		parts = append(parts, fmt.Sprintf("%d viendo", s.Online))
	}
	if s.Active > 0 {
		parts = append(parts, plural(s.Active, "descarga", "descargas"))
	}
	if len(parts) == 1 {
		return "Compartiendo · nadie conectado"
	}
	return strings.Join(parts, " · ")
}

// Tooltip is the hover text for the tray icon.
func (s Summary) Tooltip() string {
	if s.Status != StatusLive {
		return "File Transfer Easy · " + s.StatusText
	}
	return "File Transfer Easy · " + s.ActivityLine()
}

func plural(count int, one, many string) string {
	if count == 1 {
		return fmt.Sprintf("%d %s", count, one)
	}
	return fmt.Sprintf("%d %s", count, many)
}
