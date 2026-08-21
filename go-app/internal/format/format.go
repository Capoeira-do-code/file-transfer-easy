// Package format renders sizes, speeds and durations the way the UI shows them.
package format

import (
	"fmt"
	"math"
	"strings"
	"time"
)

var sizeUnits = []string{"B", "KB", "MB", "GB", "TB", "PB"}

// Bytes renders a byte count with one decimal from MB upwards, e.g. "180 KB", "1,4 GB".
func Bytes(n int64) string {
	if n < 0 {
		n = 0
	}
	value := float64(n)
	unit := 0
	for value >= 1024 && unit < len(sizeUnits)-1 {
		value /= 1024
		unit++
	}
	if unit <= 1 {
		return fmt.Sprintf("%d %s", int64(math.Round(value)), sizeUnits[unit])
	}
	return strings.Replace(fmt.Sprintf("%.1f %s", value, sizeUnits[unit]), ".", ",", 1)
}

// Speed renders a transfer rate in bytes per second.
func Speed(bytesPerSecond float64) string {
	if bytesPerSecond <= 0 || math.IsInf(bytesPerSecond, 0) || math.IsNaN(bytesPerSecond) {
		return "—"
	}
	return Bytes(int64(bytesPerSecond)) + "/s"
}

// ETA renders the time left for a transfer, or "—" when it cannot be estimated.
func ETA(remaining int64, bytesPerSecond float64) string {
	if remaining <= 0 {
		return "—"
	}
	if bytesPerSecond < 1 || math.IsInf(bytesPerSecond, 0) || math.IsNaN(bytesPerSecond) {
		return "—"
	}
	return Duration(time.Duration(float64(remaining)/bytesPerSecond) * time.Second)
}

// Duration renders a short, human duration such as "12 s" or "3 min 4 s".
func Duration(d time.Duration) string {
	if d < time.Second {
		return "1 s"
	}
	total := int(d.Seconds())
	switch {
	case total < 60:
		return fmt.Sprintf("%d s", total)
	case total < 3600:
		if total%60 == 0 {
			return fmt.Sprintf("%d min", total/60)
		}
		return fmt.Sprintf("%d min %d s", total/60, total%60)
	default:
		hours := total / 3600
		minutes := (total % 3600) / 60
		if minutes == 0 {
			return fmt.Sprintf("%d h", hours)
		}
		return fmt.Sprintf("%d h %d min", hours, minutes)
	}
}

var spanishMonths = [...]string{
	"ene", "feb", "mar", "abr", "may", "jun",
	"jul", "ago", "sep", "oct", "nov", "dic",
}

// Date renders a date as "21 ago 2026".
func Date(t time.Time) string {
	if t.IsZero() {
		return ""
	}
	return fmt.Sprintf("%d %s %d", t.Day(), spanishMonths[int(t.Month())-1], t.Year())
}

// Clock renders a wall-clock time as "10:15:02", used by the activity log.
func Clock(t time.Time) string {
	return t.Format("15:04:05")
}
