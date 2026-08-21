package format

import (
	"testing"
	"time"
)

func TestBytes(t *testing.T) {
	cases := []struct {
		in   int64
		want string
	}{
		{0, "0 B"},
		{-5, "0 B"},
		{999, "999 B"},
		{1024, "1 KB"},
		{1536, "2 KB"},
		{1024 * 1024, "1,0 MB"},
		{1024*1024*3 + 512*1024, "3,5 MB"},
		{1024 * 1024 * 1024, "1,0 GB"},
	}
	for _, testCase := range cases {
		if got := Bytes(testCase.in); got != testCase.want {
			t.Errorf("Bytes(%d) = %q, esperaba %q", testCase.in, got, testCase.want)
		}
	}
}

func TestSpeed(t *testing.T) {
	if got := Speed(0); got != "—" {
		t.Errorf("una velocidad nula debería mostrarse como guion, dio %q", got)
	}
	if got := Speed(1024 * 1024); got != "1,0 MB/s" {
		t.Errorf("Speed = %q", got)
	}
}

func TestETA(t *testing.T) {
	cases := []struct {
		remaining int64
		speed     float64
		want      string
	}{
		{0, 1000, "—"},      // nothing left
		{1000, 0, "—"},      // stalled, cannot estimate
		{1000, 1000, "1 s"}, // one second's worth
		{90 * 1000, 1000, "1 min 30 s"},
		{7200 * 1000, 1000, "2 h"},
	}
	for _, testCase := range cases {
		if got := ETA(testCase.remaining, testCase.speed); got != testCase.want {
			t.Errorf("ETA(%d, %v) = %q, esperaba %q",
				testCase.remaining, testCase.speed, got, testCase.want)
		}
	}
}

func TestDuration(t *testing.T) {
	cases := []struct {
		in   time.Duration
		want string
	}{
		{500 * time.Millisecond, "1 s"},
		{45 * time.Second, "45 s"},
		{2 * time.Minute, "2 min"},
		{time.Hour + 30*time.Minute, "1 h 30 min"},
	}
	for _, testCase := range cases {
		if got := Duration(testCase.in); got != testCase.want {
			t.Errorf("Duration(%v) = %q, esperaba %q", testCase.in, got, testCase.want)
		}
	}
}

func TestDate(t *testing.T) {
	moment := time.Date(2026, time.August, 21, 10, 15, 0, 0, time.UTC)
	if got := Date(moment); got != "21 ago 2026" {
		t.Errorf("Date = %q", got)
	}
	if got := Date(time.Time{}); got != "" {
		t.Errorf("una fecha vacía debería dar cadena vacía, dio %q", got)
	}
}
