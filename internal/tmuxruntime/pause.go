package runtime

import (
	"crypto/sha256"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"

	"github.com/ybz21/Roami/internal/memguard"
)

const pauseOption = "@roam_pause_reason"
const resumeOption = "@roam_memory_resume_until"

func (r Runtime) PauseReason(name string) string {
	out, _ := r.TmuxOutput("show-options", "-qv", "-t", r.SessionRow(name).TmuxID, pauseOption)
	return strings.TrimSpace(out)
}

func (r Runtime) MemoryResumeGrace(name string) bool {
	out, _ := r.TmuxOutput("show-options", "-qv", "-t", r.SessionRow(name).TmuxID, resumeOption)
	until, _ := strconv.ParseInt(strings.TrimSpace(out), 10, 64)
	return r.Now().Unix() < until
}

// SetPaused serializes CLI and watcher actions across processes.
func (r Runtime) SetPaused(name string, pause bool, reason string) error {
	row, err := r.ResolveStrict(name)
	if err != nil {
		return err
	}
	name = row.Name
	dir := filepath.Join(r.DataDir, "locks")
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	lock, err := os.OpenFile(filepath.Join(dir, fmt.Sprintf("session-pause-%x.lock", sha256.Sum256([]byte(name)))), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return err
	}
	defer lock.Close()
	if err := syscall.Flock(int(lock.Fd()), syscall.LOCK_EX); err != nil {
		return err
	}
	defer syscall.Flock(int(lock.Fd()), syscall.LOCK_UN)
	if pause && reason != "manual" && r.MemoryResumeGrace(name) {
		return nil
	}
	pids := r.PanePIDs(name)
	if len(pids) == 0 {
		return fmt.Errorf("SESSION_PAUSE_UNAVAILABLE")
	}
	owners, err := r.TmuxOutput("list-panes", "-a", "-F", "#{session_name}\t#{pane_pid}")
	if err != nil {
		return err
	}
	for _, line := range strings.Split(strings.TrimSpace(owners), "\n") {
		owner, value, ok := strings.Cut(line, "\t")
		if !ok || owner == name {
			continue
		}
		pid, _ := strconv.Atoi(value)
		for _, target := range pids {
			if target == pid {
				return fmt.Errorf("SESSION_PAUSE_SHARED_PANE")
			}
		}
	}
	before := make(map[int]bool, len(pids))
	for _, pid := range pids {
		frozen, err := memguard.FreezeState(pid)
		if err != nil {
			return fmt.Errorf("SESSION_PAUSE_UNAVAILABLE: %w", err)
		}
		before[pid] = frozen
	}
	changed := []int{}
	rollback := func(cause error) error {
		for _, pid := range changed {
			if err := memguard.Freeze(pid, before[pid]); err != nil {
				cause = errors.Join(cause, err)
			}
		}
		return fmt.Errorf("SESSION_PAUSE_FAILED: %w", cause)
	}
	for _, pid := range pids {
		if before[pid] == pause {
			continue
		}
		changed = append(changed, pid)
		if err := memguard.Freeze(pid, pause); err != nil {
			return rollback(err)
		}
	}
	if !pause {
		// Explicit resume grants time to finish or release memory before another pause.
		if err := r.Tmux("set-option", "-t", row.TmuxID, resumeOption, strconv.FormatInt(r.Now().Unix()+30, 10)); err != nil {
			return rollback(err)
		}
		reason = ""
	}
	if err := r.Tmux("set-option", "-t", row.TmuxID, pauseOption, reason); err != nil {
		return rollback(err)
	}
	return nil
}
