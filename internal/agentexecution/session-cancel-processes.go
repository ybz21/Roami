package agentexecution

import (
	"os"
	"path/filepath"
	"strconv"
)

func capturedSessionTools(binding SessionBinding, snapshot map[int]paneProcess, scoped map[int]string) map[int]string {
	owned := descendantProcesses(snapshot, binding.PID)
	tools := map[int]string{}
	for pid, token := range scoped {
		if token == "" || owned[pid] != token || binding.Processes[pid] == token || binding.ForeignProcesses[pid] == token || pid == binding.PID {
			continue
		}
		executable, err := os.Readlink(filepath.Join("/proc", strconv.Itoa(pid), "exe"))
		if err != nil || filepath.Base(executable) == "codex" || codexCodeModeHost(binding, snapshot, pid) {
			continue
		}
		foreign := false
		seen := map[int]bool{}
		for parent := snapshot[pid].Parent; parent > 0 && parent != binding.PID && !seen[parent]; parent = snapshot[parent].Parent {
			seen[parent] = true
			if binding.ForeignProcesses[parent] == snapshot[parent].Token && snapshot[parent].Token != "" {
				foreign = true
				break
			}
		}
		if !foreign {
			tools[pid] = token
		}
	}
	return tools
}
