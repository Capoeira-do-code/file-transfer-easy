package app

import "encoding/json"

// encodeState marshals a snapshot for the SSE stream. Newlines would break the
// `data:` framing, and json.Marshal escapes them inside strings, so the result
// is always safe to write as a single SSE data line.
func encodeState(state State) ([]byte, error) {
	return json.Marshal(state)
}
