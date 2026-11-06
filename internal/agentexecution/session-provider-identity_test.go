package agentexecution

import (
	"github.com/ybz21/Roami/internal/agentlifecycle"
	"os"
	"path/filepath"
	"testing"
)

func TestSessionProviderReadsExactLiveBindingWithoutCreatingState(t *testing.T) {
	s, original := sessionFixture(t)
	binding, err := s.paneBinding(original.Name, false)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(s.Runtime.DataDir, "agents", "session-lifecycle", binding.resourceID(), "state.json")
	if id, managed, err := agentlifecycle.SessionProvider(s.Runtime, original.Name, "codex"); err != nil || managed || id != "" {
		t.Fatalf("unmanaged: %q %v %v", id, managed, err)
	}
	if _, err := os.Stat(filepath.Dir(path)); !os.IsNotExist(err) {
		t.Fatalf("read created lifecycle directory: %v", err)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	binding.Processes = map[int]string{binding.PID: observedProcessToken(binding.PID)}
	binding.ProviderID = "11111111-1111-4111-8111-111111111111"
	state := sessionLifecycle{Binding: binding, Executor: "codex", State: "idle"}
	if err := writeJSON(path, state); err != nil {
		t.Fatal(err)
	}
	before, _ := os.ReadFile(path)
	if id, managed, err := agentlifecycle.SessionProvider(s.Runtime, original.Name, "codex"); err != nil || !managed || id != binding.ProviderID {
		t.Fatalf("bound: %q %v %v", id, managed, err)
	}
	after, _ := os.ReadFile(path)
	if string(before) != string(after) {
		t.Fatal("reader changed lifecycle")
	}
	for _, mismatch := range []string{"executor", "pid", "directory", "host", "process", "missing proof", "unknown"} {
		t.Run(mismatch, func(t *testing.T) {
			changed := state
			switch mismatch {
			case "executor":
				changed.Executor = "claude"
			case "pid":
				changed.Binding.PID++
			case "directory":
				changed.Binding.Directory = t.TempDir()
			case "host":
				changed.Binding.HostProof = "foreign"
			case "process":
				changed.Binding.Processes = map[int]string{binding.PID: "recycled"}
			case "missing proof":
				changed.Binding.HostProof = ""
			case "unknown":
				changed.State = "unknown"
			}
			if err := writeJSON(path, changed); err != nil {
				t.Fatal(err)
			}
			if id, managed, err := agentlifecycle.SessionProvider(s.Runtime, original.Name, "codex"); err == nil || !managed || id != "" {
				t.Fatalf("mismatch accepted: %q %v %v", id, managed, err)
			}
		})
	}
}
