package runtime

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/ybz21/Roami/internal/memguard"
	"github.com/ybz21/Roami/internal/memrelief"
)

const MemoryReclaimEnv = "ROAM_MEMORY_RECLAIM"
const MemoryCompactEnv = "ROAM_MEMORY_COMPACT"

func (r Runtime) MemoryRecoveryEnabled(key string) bool {
	v := strings.ToLower(strings.TrimSpace(r.EnvValue(key)))
	return v != "off" && v != "0" && v != "false"
}

func (r Runtime) memoryStatePath(name string) string {
	return filepath.Join(r.DataDir, "session-memory", fmt.Sprintf("%x.json", sha256.Sum256([]byte(name))))
}

func (r Runtime) MemoryReliefState(name string) memrelief.State {
	var s memrelief.State
	b, err := os.ReadFile(r.memoryStatePath(name))
	if err == nil {
		_ = json.Unmarshal(b, &s)
	}
	return s
}

func (r Runtime) saveMemoryRelief(name string, s memrelief.State) error {
	path := r.memoryStatePath(name)
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	b, err := json.Marshal(s)
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".memory-")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err = f.Write(b); err != nil {
		_ = f.Close()
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	return os.Rename(f.Name(), path)
}

// Shared with pause/resume so competing CLI processes cannot repeat recovery.
func (r Runtime) LockSessionMemory(name string) (func(), error) {
	dir := filepath.Join(r.DataDir, "locks")
	if err := os.MkdirAll(dir, 0700); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(filepath.Join(dir, fmt.Sprintf("session-pause-%x.lock", sha256.Sum256([]byte(name)))), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err = syscall.Flock(int(f.Fd()), syscall.LOCK_EX); err != nil {
		_ = f.Close()
		return nil, err
	}
	return func() { _ = syscall.Flock(int(f.Fd()), syscall.LOCK_UN); _ = f.Close() }, nil
}

func (r Runtime) ReclaimSession(name string, automatic bool) (memrelief.State, error) {
	row, err := r.ResolveStrict(name)
	if err != nil {
		return memrelief.State{}, err
	}
	name = row.Name
	unlock, err := r.LockSessionMemory(name)
	if err != nil {
		return memrelief.State{}, err
	}
	defer unlock()
	s := r.MemoryReliefState(name)
	if automatic && (!r.MemoryRecoveryEnabled(MemoryReclaimEnv) || r.MemoryResumeGrace(name) || r.Now().Unix()-s.ReclaimAt < int64(memrelief.ReclaimCooldown/time.Second)) {
		return s, nil
	}
	s.ReclaimAt = r.Now().Unix()
	s.Reclaimed = 0
	s.SwapDelta = 0
	seen := map[string]bool{}
	pids := []int{}
	var before, swapBefore int64
	for _, pid := range r.PanePIDs(name) {
		scope := memguard.ScopeOf(pid)
		if scope == "" || seen[scope] {
			continue
		}
		seen[scope] = true
		cur, _, ok := memguard.Current(pid)
		if !ok {
			continue
		}
		sw, _ := memguard.SwapOf(pid)
		before += cur
		swapBefore += sw
		pids = append(pids, pid)
	}
	s.ReclaimStatus = "unavailable"
	n := memrelief.Bytes(before, memguard.SwapFree())
	if len(pids) > 0 && n == 0 {
		s.ReclaimStatus = "no-swap"
	}
	if len(pids) > 0 && n > 0 {
		s.ReclaimStatus = "failed"
		deadline := time.Now().Add(time.Second)
		for _, pid := range pids {
			if time.Now().After(deadline) {
				break
			}
			_ = memguard.Reclaim(pid, n/int64(len(pids)))
		}
		var after, swapAfter int64
		for _, pid := range pids {
			cur, _, ok := memguard.Current(pid)
			if ok {
				after += cur
			}
			sw, _ := memguard.SwapOf(pid)
			swapAfter += sw
		}
		if swapAfter > swapBefore {
			s.SwapDelta = swapAfter - swapBefore
		}
		// Report only the observed reduction, never the requested byte count.
		if after < before && s.SwapDelta > 0 {
			s.Reclaimed = before - after
			s.ReclaimStatus = "done"
		}
	}
	if err := r.saveMemoryRelief(name, s); err != nil {
		return s, err
	}
	return s, nil
}

func (r Runtime) compactProbe(name string, automatic bool) (string, error) {
	out, err := r.TmuxOutput("list-panes", "-s", "-t", "="+name, "-F", "#{pane_id}\t#{pane_current_command}\t#{cursor_y}\t#{session_attached}\t#{pane_pid}")
	if err != nil {
		return "", err
	}
	lines := strings.Split(strings.TrimSpace(out), "\n")
	if len(lines) != 1 {
		return "", fmt.Errorf("MEMORY_COMPACT_DEFERRED")
	}
	f := strings.Split(lines[0], "\t")
	if len(f) != 5 {
		return "", fmt.Errorf("MEMORY_COMPACT_UNSUPPORTED")
	}
	pid, _ := strconv.Atoi(f[4])
	kind := foregroundCompactKind(pid)
	if kind == "" {
		return "", fmt.Errorf("MEMORY_COMPACT_UNSUPPORTED")
	}
	if automatic && f[3] != "0" {
		return "", fmt.Errorf("MEMORY_COMPACT_DEFERRED")
	}
	y, err := strconv.Atoi(f[2])
	if err != nil {
		return "", err
	}
	screen, err := r.TmuxOutput("capture-pane", "-t", f[0], "-p")
	if err != nil {
		return "", err
	}
	if !memrelief.EmptyPrompt(kind, screen, y) {
		return "", fmt.Errorf("MEMORY_COMPACT_DEFERRED")
	}
	for _, pid := range r.PanePIDs(name) {
		frozen, err := memguard.FreezeState(pid)
		if err != nil || frozen {
			return "", fmt.Errorf("MEMORY_COMPACT_DEFERRED")
		}
	}
	return out + "\n" + screen, nil
}

func (r Runtime) CompactSession(name string, automatic bool) (memrelief.State, error) {
	row, err := r.ResolveStrict(name)
	if err != nil {
		return memrelief.State{}, err
	}
	name = row.Name
	unlock, err := r.LockSessionMemory(name)
	if err != nil {
		return memrelief.State{}, err
	}
	defer unlock()
	s := r.MemoryReliefState(name)
	previous := s
	if automatic && (!r.MemoryRecoveryEnabled(MemoryCompactEnv) || r.MemoryResumeGrace(name) || r.Now().Unix()-s.CompactAt < int64(memrelief.CompactCooldown/time.Second)) {
		return s, nil
	}
	probe, err := r.compactProbe(name, automatic)
	if err == nil {
		time.Sleep(100 * time.Millisecond)
		again, e := r.compactProbe(name, automatic)
		if e != nil || again != probe {
			err = fmt.Errorf("MEMORY_COMPACT_DEFERRED")
		}
	}
	s.CompactStatus = "deferred"
	if err != nil && strings.Contains(err.Error(), "UNSUPPORTED") {
		s.CompactStatus = "unsupported"
	}
	if err == nil {
		// Persist before sending: an unknown delivery must not be retried automatically.
		s.CompactAt = r.Now().Unix()
		s.CompactStatus = "requested"
		if e := r.saveMemoryRelief(name, s); e != nil {
			return s, e
		}
		err = r.SendPromptSubmit("="+name+":", "/compact")
		if err != nil {
			s.CompactStatus = "unknown"
		}
	}
	if s == previous {
		return s, err
	}
	if e := r.saveMemoryRelief(name, s); e != nil {
		return s, e
	}
	if automatic {
		return s, nil
	}
	return s, err
}
