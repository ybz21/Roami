package agentexecution

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// Code mode starts lazily and keeps its bundled host alive between turns.
func codexCodeModeHost(binding SessionBinding, snapshot map[int]paneProcess, pid int) bool {
	child, ok := snapshot[pid]
	parent, parentOK := snapshot[child.Parent]
	if !ok || !parentOK || binding.Processes[child.Parent] != parent.Token {
		return false
	}
	seen, owned := map[int]bool{}, false
	for current := child.Parent; current > 0 && !seen[current]; current = snapshot[current].Parent {
		seen[current] = true
		if current == binding.PID {
			owned = true
			break
		}
	}
	if !owned {
		return false
	}
	providerPath, err := os.Readlink(filepath.Join("/proc", strconv.Itoa(child.Parent), "exe"))
	if err != nil || filepath.Base(providerPath) != "codex" {
		return false
	}
	provider, err := os.Stat(providerPath)
	if err != nil {
		return false
	}
	runningProvider, err := os.Stat(filepath.Join("/proc", strconv.Itoa(child.Parent), "exe"))
	if err != nil || !os.SameFile(provider, runningProvider) {
		return false
	}
	expected, err := os.Stat(filepath.Join(filepath.Dir(providerPath), "codex-code-mode-host"))
	if err != nil {
		return false
	}
	actual, err := os.Stat(filepath.Join("/proc", strconv.Itoa(pid), "exe"))
	return err == nil && os.SameFile(expected, actual) &&
		observedProcessToken(pid) == child.Token && observedProcessToken(child.Parent) == parent.Token
}

func observedProcessToken(pid int) string {
	data, err := os.ReadFile(filepath.Join("/proc", strconv.Itoa(pid), "stat"))
	if err != nil {
		return ""
	}
	end := strings.LastIndexByte(string(data), ')')
	if end < 0 {
		return ""
	}
	fields := strings.Fields(string(data[end+1:]))
	if len(fields) < 20 {
		return ""
	}
	return fields[19]
}
