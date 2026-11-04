//go:build !linux

package agentexecution

import "fmt"

func signalCapturedSessionTools(_ SessionBinding, captured map[int]string) error {
	if len(captured) != 0 {
		return fmt.Errorf("SESSION_TOOL_INTERRUPT_UNKNOWN")
	}
	return nil
}
