//go:build linux || darwin

package sessionipc

import (
	"os"
	"os/exec"
	"syscall"
)

// SpawnDetached launches roami-sessiond in its own session so parent exit never kills PTYs.
func SpawnDetached(binary string, args ...string) (int, error) {
	cmd := exec.Command(binary, args...)
	cmd.Stdin = nil
	cmd.Stdout = nil
	cmd.Stderr = nil
	cmd.Env = os.Environ()
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if err := cmd.Start(); err != nil {
		return 0, err
	}
	pid := cmd.Process.Pid
	_ = cmd.Process.Release()
	return pid, nil
}
