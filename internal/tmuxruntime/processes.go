package runtime

import (
	"fmt"
	"strconv"
	"strings"

	"github.com/ybz21/Roami/internal/memguard"
)

func (r Runtime) processPanes(name string) ([]int, error) {
	row, err := r.ResolveStrict(name)
	if err != nil {
		return nil, err
	}
	pids := r.PanePIDs(row.Name)
	if len(pids) == 0 {
		return nil, fmt.Errorf("SESSION_PROCESS_UNAVAILABLE")
	}
	owners, err := r.TmuxOutput("list-panes", "-a", "-F", "#{session_name}\t#{pane_pid}")
	if err != nil {
		return nil, err
	}
	for _, line := range strings.Split(strings.TrimSpace(owners), "\n") {
		owner, value, ok := strings.Cut(line, "\t")
		if !ok || owner == row.Name {
			continue
		}
		pid, _ := strconv.Atoi(value)
		for _, target := range pids {
			scope := memguard.ScopeOf(target)
			if target == pid || (scope != "" && scope == memguard.ScopeOf(pid)) {
				return nil, fmt.Errorf("SESSION_PROCESS_SHARED_PANE")
			}
		}
	}
	return pids, nil
}

func (r Runtime) SessionProcesses(name string) ([]memguard.Process, error) {
	pids, err := r.processPanes(name)
	if err != nil {
		return nil, err
	}
	return memguard.Processes(pids)
}

func (r Runtime) StopSessionProcess(name string, pid int, start string, force bool) error {
	pids, err := r.processPanes(name)
	if err != nil {
		return err
	}
	return memguard.StopProcess(pids, pid, start, force)
}
