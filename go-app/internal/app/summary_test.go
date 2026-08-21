package app

import "testing"

func TestSummaryOfCountsOnlyLiveActivity(t *testing.T) {
	state := State{
		Totals: TotalsView{Items: 2, Files: 9, BytesText: "80 MB"},
		Share:  ShareView{Status: string(StatusLive), StatusText: "Compartiendo"},
		Visitors: []VisitorView{
			{Online: true}, {Online: false}, {Online: true},
		},
		Transfers: []TransferView{
			{Status: "active"}, {Status: "done"}, {Status: "cancelled"},
		},
	}

	summary := summaryOf(state)
	if summary.Online != 2 {
		t.Errorf("visitantes en línea: esperaba 2, hay %d", summary.Online)
	}
	if summary.Active != 1 {
		t.Errorf("descargas activas: esperaba 1, hay %d", summary.Active)
	}
	if summary.Files != 9 || summary.BytesText != "80 MB" {
		t.Errorf("totales mal copiados: %+v", summary)
	}
}

func TestContentLine(t *testing.T) {
	cases := []struct {
		name    string
		summary Summary
		want    string
	}{
		{"vacío", Summary{}, "Nada compartido todavía"},
		{
			// One loose file: repeating the file count would add nothing.
			"un archivo suelto",
			Summary{Items: 1, Files: 1, BytesText: "180 KB"},
			"1 elemento · 180 KB",
		},
		{
			// A folder makes the file count meaningful.
			"carpeta con varios archivos",
			Summary{Items: 2, Files: 12, BytesText: "80 MB"},
			"2 elementos · 12 archivos · 80 MB",
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := testCase.summary.ContentLine(); got != testCase.want {
				t.Errorf("esperaba %q, hubo %q", testCase.want, got)
			}
		})
	}
}

func TestActivityLine(t *testing.T) {
	cases := []struct {
		name    string
		summary Summary
		want    string
	}{
		{
			"aún no comparte",
			Summary{Status: StatusStarting, StatusText: "Creando el enlace…"},
			"Creando el enlace…",
		},
		{
			"compartiendo sin nadie",
			Summary{Status: StatusLive},
			"Compartiendo · nadie conectado",
		},
		{
			"con visitantes",
			Summary{Status: StatusLive, Online: 3},
			"Compartiendo · 3 viendo",
		},
		{
			"con visitantes y descargas",
			Summary{Status: StatusLive, Online: 2, Active: 1},
			"Compartiendo · 2 viendo · 1 descarga",
		},
		{
			"varias descargas",
			Summary{Status: StatusLive, Online: 2, Active: 4},
			"Compartiendo · 2 viendo · 4 descargas",
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := testCase.summary.ActivityLine(); got != testCase.want {
				t.Errorf("esperaba %q, hubo %q", testCase.want, got)
			}
		})
	}
}

func TestTooltipFallsBackToStatus(t *testing.T) {
	idle := Summary{Status: StatusIdle, StatusText: "Listo"}
	if got := idle.Tooltip(); got != "File Transfer Easy · Listo" {
		t.Errorf("tooltip inesperado: %q", got)
	}

	live := Summary{Status: StatusLive, Online: 1}
	if got := live.Tooltip(); got != "File Transfer Easy · Compartiendo · 1 viendo" {
		t.Errorf("tooltip inesperado: %q", got)
	}
}
