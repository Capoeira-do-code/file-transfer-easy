//go:build !windows

package tunnel

import (
	"os/exec"
	"syscall"
)

// hideConsoleWindow is a no-op outside Windows: cloudflared inherits our
// stdio and never opens a window of its own.
func hideConsoleWindow(*exec.Cmd) {}

// terminate asks cloudflared to shut down cleanly so it can tear the tunnel
// down on Cloudflare's side before exiting.
func terminate(cmd *exec.Cmd) error {
	return cmd.Process.Signal(syscall.SIGTERM)
}
