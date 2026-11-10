package memguard

import (
	"fmt"
	"golang.org/x/sys/unix"
)

func signalProcess(pid int, start string, force bool, scopes map[string]bool) error {
	// pidfd pins the identity before rechecking membership and the snapshot token.
	fd, err := unix.PidfdOpen(pid, 0)
	if err != nil {
		return fmt.Errorf("SESSION_PROCESS_STALE: %w", err)
	}
	defer unix.Close(fd)
	p, err := readProcess(pid)
	if err != nil || start == "" || p.Start != start || !inProcessScopes(pid, scopes) {
		return fmt.Errorf("SESSION_PROCESS_STALE")
	}
	sig := unix.SIGTERM
	if force {
		sig = unix.SIGKILL
	}
	if err := unix.PidfdSendSignal(fd, sig, nil, 0); err != nil {
		return fmt.Errorf("SESSION_PROCESS_STOP_FAILED: %w", err)
	}
	return nil
}
