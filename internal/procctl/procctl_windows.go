//go:build windows

// Package procctl provides cross-platform detached process creation and process-group termination.
package procctl

import (
	"errors"
	"os"
	"os/exec"
	"time"

	"golang.org/x/sys/windows"
)

const stillActive = 259

func SetDetached(cmd *exec.Cmd) {
	cmd.SysProcAttr = &windows.SysProcAttr{
		CreationFlags: windows.DETACHED_PROCESS | windows.CREATE_NEW_PROCESS_GROUP,
	}
}

func SetProcessGroup(cmd *exec.Cmd) {
	cmd.SysProcAttr = &windows.SysProcAttr{
		CreationFlags: windows.CREATE_NEW_PROCESS_GROUP,
	}
}

func ProcessAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	h, err := windows.OpenProcess(windows.PROCESS_QUERY_LIMITED_INFORMATION, false, uint32(pid))
	if err != nil {
		return errors.Is(err, windows.ERROR_ACCESS_DENIED)
	}
	defer windows.CloseHandle(h)
	var code uint32
	if err := windows.GetExitCodeProcess(h, &code); err != nil {
		return false
	}
	return code == stillActive
}

func KillPID(pid int, _ bool) error {
	if pid <= 0 {
		return nil
	}
	p, err := os.FindProcess(pid)
	if err != nil {
		return nil
	}
	err = p.Kill()
	if errors.Is(err, os.ErrProcessDone) {
		return nil
	}
	return err
}

func KillProcessGroupOf(p *os.Process) {
	if p == nil {
		return
	}
	_ = p.Kill()
}

func SignalGroup(pid int, force bool) {
	_ = KillGroupErr(pid, force)
}

func KillGroupErr(pid int, _ bool) error {
	if pid <= 0 {
		return nil
	}
	p, err := os.FindProcess(pid)
	if err != nil {
		return err
	}
	return p.Kill()
}

func TerminateGroup(p *os.Process, _ time.Duration) {
	if p == nil {
		return
	}
	_ = p.Kill()
}
