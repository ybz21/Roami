package session

import (
	"encoding/json"
	"fmt"
	"io"
	"strconv"

	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func Processes(rt runtime.Runtime, args []string, stop bool, w io.Writer) error {
	if len(args) == 0 {
		return fmt.Errorf("usage: roami session processes <session> --json")
	}
	if !stop {
		processes, err := rt.SessionProcesses(args[0])
		if err != nil {
			return err
		}
		return json.NewEncoder(w).Encode(map[string]any{"processes": processes})
	}
	if len(args) < 3 {
		return fmt.Errorf("usage: roami session process-stop <session> <pid> <start> [--force]")
	}
	pid, err := strconv.Atoi(args[1])
	if err != nil {
		return fmt.Errorf("SESSION_PROCESS_STALE")
	}
	force := false
	for _, arg := range args[3:] {
		if arg == "--force" {
			force = true
		} else if arg != "--json" {
			return fmt.Errorf("invalid process-stop argument")
		}
	}
	if err := rt.StopSessionProcess(args[0], pid, args[2], force); err != nil {
		return err
	}
	return json.NewEncoder(w).Encode(map[string]bool{"signalled": true})
}
