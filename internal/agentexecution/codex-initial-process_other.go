//go:build !linux

package agentexecution

func initialCodexProcesses(binding SessionBinding, _ string, _ int64, _ string) (SessionBinding, bool) {
	return binding, false
}
