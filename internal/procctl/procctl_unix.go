//go:build !windows

// Package procctl provides cross-platform detached process creation and process-group termination.
package procctl

import (
	"errors"
	"os"
	"os/exec"
	"syscall"
	"time"
)

func SetDetached(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
}

func SetProcessGroup(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
}

func ProcessAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	p, err := os.FindProcess(pid)
	if err != nil {
		return false
	}
	return p.Signal(syscall.Signal(0)) == nil
}

func KillPID(pid int, force bool) error {
	if pid <= 0 {
		return nil
	}
	sig := syscall.SIGTERM
	if force {
		sig = syscall.SIGKILL
	}
	err := syscall.Kill(pid, sig)
	if errors.Is(err, syscall.ESRCH) {
		return nil
	}
	return err
}

func KillProcessGroupOf(p *os.Process) {
	if p == nil {
		return
	}
	if pgid, err := syscall.Getpgid(p.Pid); err == nil {
		_ = syscall.Kill(-pgid, syscall.SIGKILL)
	} else {
		_ = p.Kill()
	}
}

func SignalGroup(pid int, force bool) {
	_ = KillGroupErr(pid, force)
}

func KillGroupErr(pid int, force bool) error {
	if pid <= 0 {
		return nil
	}
	sig := syscall.SIGTERM
	if force {
		sig = syscall.SIGKILL
	}
	return syscall.Kill(-pid, sig)
}

func TerminateGroup(p *os.Process, grace time.Duration) {
	if p == nil {
		return
	}
	_ = syscall.Kill(-p.Pid, syscall.SIGTERM)
	if grace > 0 {
		time.Sleep(grace)
	}
	_ = syscall.Kill(-p.Pid, syscall.SIGKILL)
}
