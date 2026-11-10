package memguard

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

type PaneStopProof struct {
	Scopes []string `json:"scopes"`
}

func CapturePaneStopProof(pids []int) (PaneStopProof, error) {
	proof := PaneStopProof{Scopes: []string{}}
	if len(pids) == 0 {
		return proof, fmt.Errorf("SESSION_PROCESS_OBSERVATION_UNAVAILABLE")
	}
	seen := map[string]bool{}
	for _, pid := range pids {
		if _, err := memoryScope(pid); err != nil {
			return proof, err
		}
		scope, _, err := ScopeProcesses(pid)
		if err != nil {
			return proof, err
		}
		if !seen[scope] {
			proof.Scopes = append(proof.Scopes, scope)
			seen[scope] = true
		}
	}
	return proof, nil
}

// Stop only dedicated pane scopes. An unknown observation never releases a writer.
func StopPaneScopes(ctx context.Context, proof PaneStopProof) error {
	if len(proof.Scopes) == 0 {
		return fmt.Errorf("SESSION_PROCESS_OBSERVATION_UNAVAILABLE")
	}
	for _, scope := range proof.Scopes {
		pids, err := RecordedScopeProcesses(scope)
		if err != nil {
			return err
		}
		if len(pids) == 0 {
			continue
		}
		if frozen, e := os.ReadFile(filepath.Join(scope, "cgroup.freeze")); e == nil && strings.TrimSpace(string(frozen)) == "1" {
			if e = os.WriteFile(filepath.Join(scope, "cgroup.freeze"), []byte("0"), 0); e != nil {
				return e
			}
		}
		if out, err := exec.CommandContext(ctx, "systemctl", "--user", "kill", "--kill-whom=all", "--signal=SIGKILL", "--", filepath.Base(scope)).CombinedOutput(); err != nil {
			if current, e := RecordedScopeProcesses(scope); e == nil && len(current) == 0 {
				continue
			}
			return fmt.Errorf("SESSION_STOP_UNCONFIRMED: %s", out)
		}
		deadline := time.NewTimer(3 * time.Second)
		ticker := time.NewTicker(20 * time.Millisecond)
		for {
			pids, err = RecordedScopeProcesses(scope)
			if err != nil {
				deadline.Stop()
				ticker.Stop()
				return err
			}
			if len(pids) == 0 {
				break
			}
			select {
			case <-ctx.Done():
				deadline.Stop()
				ticker.Stop()
				return ctx.Err()
			case <-deadline.C:
				ticker.Stop()
				return fmt.Errorf("SESSION_STOP_UNCONFIRMED")
			case <-ticker.C:
			}
		}
		deadline.Stop()
		ticker.Stop()
	}
	return nil
}
