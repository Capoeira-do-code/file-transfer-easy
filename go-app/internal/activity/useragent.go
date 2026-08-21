package activity

import "strings"

// DescribeUserAgent turns a User-Agent header into a short human label such as
// "Chrome · macOS". It is deliberately approximate: it only needs to help the
// host recognise who is on the other end, never to drive behaviour.
func DescribeUserAgent(userAgent string) string {
	if strings.TrimSpace(userAgent) == "" {
		return "Desconocido"
	}
	browser := detectBrowser(userAgent)
	system := detectSystem(userAgent)
	switch {
	case browser != "" && system != "":
		return browser + " · " + system
	case browser != "":
		return browser
	case system != "":
		return system
	default:
		return "Desconocido"
	}
}

// browserRules are checked in order, because most browsers impersonate the ones
// before them in the list (Edge claims Chrome, Chrome claims Safari, and so on).
var browserRules = []struct{ token, name string }{
	{"edg/", "Edge"},
	{"opr/", "Opera"},
	{"vivaldi", "Vivaldi"},
	{"brave", "Brave"},
	{"samsungbrowser", "Samsung Internet"},
	{"firefox/", "Firefox"},
	{"fxios/", "Firefox"},
	{"crios/", "Chrome"},
	{"chrome/", "Chrome"},
	{"chromium/", "Chromium"},
	{"safari/", "Safari"},
	{"curl/", "curl"},
	{"wget/", "wget"},
	{"python-requests", "Python"},
	{"postman", "Postman"},
}

func detectBrowser(userAgent string) string {
	lower := strings.ToLower(userAgent)
	for _, rule := range browserRules {
		if strings.Contains(lower, rule.token) {
			return rule.name
		}
	}
	return ""
}

func detectSystem(userAgent string) string {
	lower := strings.ToLower(userAgent)
	switch {
	case strings.Contains(lower, "iphone"):
		return "iPhone"
	case strings.Contains(lower, "ipad"):
		return "iPad"
	case strings.Contains(lower, "android"):
		return "Android"
	case strings.Contains(lower, "windows nt"):
		return "Windows"
	case strings.Contains(lower, "mac os x"), strings.Contains(lower, "macintosh"):
		return "macOS"
	case strings.Contains(lower, "cros"):
		return "ChromeOS"
	case strings.Contains(lower, "linux"):
		return "Linux"
	default:
		return ""
	}
}
