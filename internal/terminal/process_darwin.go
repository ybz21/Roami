//go:build darwin

package terminal

import (
	"fmt"

	"golang.org/x/sys/unix"
)

// ProcessIdentity returns a PID-reuse-safe start-time token using pure-Go sysctl (CGO_ENABLED=0).
func (UnixBackend) ProcessIdentity(pid int) (string, error) {
	if pid < 1 {
		return "", fmt.Errorf("terminal: invalid pid %d", pid)
	}
	kp, err := unix.SysctlKinfoProc("kern.proc.pid", pid)
	if err != nil {
		return "", err
	}
	tv := kp.Proc.P_starttime
	return fmt.Sprintf("darwin:%d:%d.%06d", pid, tv.Sec, tv.Usec), nil
}

// CurrentDir returns ErrUnsupported under CGO_ENABLED=0; hosts track OSC 7 and initial cwd.
func (UnixBackend) CurrentDir(_ int) (string, error) {
	return "", ErrUnsupported
}
