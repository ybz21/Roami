//go:build windows

package sessionipc

import (
	"os"
	"os/exec"

	"golang.org/x/sys/windows"
)

// SpawnDetached launches roami-sessiond detached from the caller's console/process group.
func SpawnDetached(binary string, args ...string) (int, error) {
	cmd := exec.Command(binary, args...)
	cmd.Stdin = nil
	cmd.Stdout = nil
	cmd.Stderr = nil
	cmd.Env = os.Environ()
	cmd.SysProcAttr = &windows.SysProcAttr{
		CreationFlags: windows.DETACHED_PROCESS | windows.CREATE_NEW_PROCESS_GROUP,
	}
	if err := cmd.Start(); err != nil {
		return 0, err
	}
	pid := cmd.Process.Pid
	_ = cmd.Process.Release()
	return pid, nil
}
