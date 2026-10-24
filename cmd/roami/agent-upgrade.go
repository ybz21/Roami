package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"github.com/ybz21/Roami/internal/agentruntime"
	metadb "github.com/ybz21/Roami/internal/storage"
	"golang.org/x/sys/unix"
)

func runAgentUpgrade(args []string) int {
	if len(args) != 1 {
		return 2
	}
	paths, err := agentruntime.Resolve("", "")
	if err != nil {
		p, pathErr := metadb.ResolvePaths("", "")
		if pathErr == nil && os.IsNotExist(err) {
			if _, lockErr := os.Stat(filepath.Join(p.Data, "locks", "agent-runtime.lock")); os.IsNotExist(lockErr) {
				return 0
			}
		}
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	if !agentReady(paths.Socket) {
		// An unreachable but locked writer is unknown, never safe to replace.
		lock, err := os.OpenFile(filepath.Join(paths.Storage.Data, "locks", "agent-runtime.lock"), os.O_RDWR, 0)
		if os.IsNotExist(err) {
			return 0
		}
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		defer lock.Close()
		if err := unix.Flock(int(lock.Fd()), unix.LOCK_EX|unix.LOCK_NB); err != nil {
			fmt.Fprintln(os.Stderr, "AGENT_UPGRADE_RUNTIME_UNKNOWN")
			return 1
		}
		defer unix.Flock(int(lock.Fd()), unix.LOCK_UN)
		return 0
	}
	raw, err := agentRequest(paths.Socket, "GET", "/v1/status", nil)
	var status struct {
		Data struct {
			Managed bool `json:"managed"`
		} `json:"data"`
	}
	if err != nil || json.Unmarshal(raw, &status) != nil || !status.Data.Managed {
		fmt.Fprintln(os.Stderr, "AGENT_UPGRADE_UNMANAGED_RUNTIME: stop the manually started runtime first")
		return 1
	}
	_, err = agentRequest(paths.Socket, "POST", "/internal/installation/quiesce", map[string]bool{"resume": args[0] == "resume-upgrade"})
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return 0
}
