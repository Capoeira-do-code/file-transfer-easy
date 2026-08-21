//go:build windows

package tunnel

import (
	"os/exec"
	"syscall"
)

// createNoWindow keeps cloudflared from flashing a console window on screen.
const createNoWindow = 0x08000000

func hideConsoleWindow(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: createNoWindow,
	}
}

// terminate ends the process. Windows has no SIGTERM, so a kill is the only
// option; cloudflared holds no state that needs an orderly shutdown.
func terminate(cmd *exec.Cmd) error {
	return cmd.Process.Kill()
}
