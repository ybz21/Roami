package agentexecution

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/ybz21/Roami/internal/memguard"
)

type paneProcess struct {
	Parent int
	Token  string
}

// Start times distinguish a surviving process from a recycled PID.
func processSnapshot() (map[int]paneProcess, error) {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return nil, fmt.Errorf("SESSION_PROCESS_OBSERVATION_UNAVAILABLE")
	}
	result := map[int]paneProcess{}
	for _, entry := range entries {
		pid, err := strconv.Atoi(entry.Name())
		if err != nil {
			continue
		}
		data, err := os.ReadFile(filepath.Join("/proc", entry.Name(), "stat"))
		if errors.Is(err, os.ErrNotExist) {
			continue
		}
		if err != nil {
			return nil, fmt.Errorf("SESSION_PROCESS_OBSERVATION_UNAVAILABLE")
		}
		end := strings.LastIndexByte(string(data), ')')
		if end < 0 {
			return nil, fmt.Errorf("SESSION_PROCESS_OBSERVATION_UNAVAILABLE")
		}
		fields := strings.Fields(string(data[end+1:]))
		if len(fields) < 20 {
			return nil, fmt.Errorf("SESSION_PROCESS_OBSERVATION_UNAVAILABLE")
		}
		parent, err := strconv.Atoi(fields[1])
		if err != nil {
			return nil, fmt.Errorf("SESSION_PROCESS_OBSERVATION_UNAVAILABLE")
		}
		result[pid] = paneProcess{Parent: parent, Token: fields[19]}
	}
	return result, nil
}

func descendantProcesses(snapshot map[int]paneProcess, root int) map[int]string {
	result := map[int]string{}
	for pid, process := range snapshot {
		seen := map[int]bool{}
		for current := pid; current > 0 && !seen[current]; current = snapshot[current].Parent {
			seen[current] = true
			if current == root {
				result[pid] = process.Token
				break
			}
		}
	}
	return result
}

func paneProcessSnapshot(pid int) (map[int]paneProcess, string, map[int]string, error) {
	scope, pids, err := memguard.ScopeProcesses(pid)
	if err != nil {
		return nil, "", nil, fmt.Errorf("SESSION_PROCESS_OBSERVATION_UNAVAILABLE")
	}
	snapshot, err := processSnapshot()
	if err != nil {
		return nil, "", nil, err
	}
	scoped := map[int]string{}
	for _, pid := range pids {
		if process, exists := snapshot[pid]; exists {
			scoped[pid] = process.Token
		}
	}
	return snapshot, scope, scoped, nil
}

func sessionProcessesStopped(binding SessionBinding) bool {
	snapshot, scope, scoped, err := paneProcessSnapshot(binding.PID)
	if err != nil || scope != binding.Scope || snapshot[binding.PID].Token != binding.Processes[binding.PID] {
		return false
	}
	ancestors := map[int]bool{}
	for pid := os.Getpid(); pid > 0 && !ancestors[pid]; pid = snapshot[pid].Parent {
		ancestors[pid] = true
	}
	for pid, token := range scoped {
		if !ancestors[pid] && binding.Processes[pid] != token {
			if codexCodeModeHost(binding, snapshot, pid) {
				continue
			}
			foreign := false
			seen := map[int]bool{}
			for current := pid; current > 0 && !seen[current]; current = snapshot[current].Parent {
				seen[current] = true
				if current == binding.PID {
					break
				}
				if snapshot[current].Token != "" && binding.ForeignProcesses[current] == snapshot[current].Token {
					foreign = true
					break
				}
			}
			if !foreign {
				return false
			}
		}
	}
	return true
}
