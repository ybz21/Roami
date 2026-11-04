package agentexecution

import (
	"errors"
	"fmt"
	"sort"

	"golang.org/x/sys/unix"
)

func signalCapturedSessionTools(binding SessionBinding, captured map[int]string) error {
	if len(captured) == 0 {
		return nil
	}
	snapshot, err := processSnapshot()
	if err != nil {
		return err
	}
	depth := map[int]int{}
	order := make([]int, 0, len(captured))
	for pid := range captured {
		order = append(order, pid)
		seen := map[int]bool{}
		for current := pid; current > 0 && !seen[current]; current = snapshot[current].Parent {
			seen[current] = true
			depth[pid]++
		}
	}
	// Stop leaves first, while their original parent chain can still be verified.
	sort.Slice(order, func(i, j int) bool { return depth[order[i]] > depth[order[j]] })
	for _, pid := range order {
		token := captured[pid]
		fd, err := unix.PidfdOpen(pid, 0)
		if errors.Is(err, unix.ESRCH) {
			continue
		}
		if err != nil {
			return fmt.Errorf("SESSION_TOOL_INTERRUPT_UNKNOWN")
		}
		// A pidfd pins the task; recheck ownership after opening, before signalling.
		snapshot, scope, scoped, err := paneProcessSnapshot(binding.PID)
		if err != nil || scope != binding.Scope || snapshot[binding.PID].Token != binding.Processes[binding.PID] {
			_ = unix.Close(fd)
			return fmt.Errorf("SESSION_TOOL_INTERRUPT_UNKNOWN")
		}
		if snapshot[pid].Token != token {
			_ = unix.Close(fd)
			continue
		}
		if capturedSessionTools(binding, snapshot, scoped)[pid] != token {
			_ = unix.Close(fd)
			return fmt.Errorf("SESSION_TOOL_INTERRUPT_UNKNOWN")
		}
		err = unix.PidfdSendSignal(fd, unix.SIGTERM, nil, 0)
		_ = unix.Close(fd)
		if err != nil && !errors.Is(err, unix.ESRCH) {
			return fmt.Errorf("SESSION_TOOL_INTERRUPT_UNKNOWN")
		}
	}
	return nil
}
