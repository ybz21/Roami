//go:build !linux

package memguard

import "fmt"

func signalProcess(pid int, start string, force bool, scopes map[string]bool) error {
	return fmt.Errorf("SESSION_PROCESS_UNAVAILABLE")
}
