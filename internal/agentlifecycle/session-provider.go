package agentlifecycle

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

func SessionResourceID(name, tmuxID, created, server, pane string) string {
	return identityHash(strings.Join([]string{name, tmuxID, created, server, pane}, "\x00"))
}

type providerBinding struct {
	Name           string         `json:"name"`
	TmuxID         string         `json:"tmuxId"`
	Created        string         `json:"created"`
	Server         string         `json:"server"`
	Pane           string         `json:"pane"`
	PID            int            `json:"pid"`
	Directory      string         `json:"directory"`
	ProviderID     string         `json:"providerConversationId"`
	HostProof      string         `json:"hostProof"`
	DirectoryProof string         `json:"directoryProof"`
	Processes      map[int]string `json:"processes"`
}

// SessionProvider projects the existing lifecycle record; it never creates or updates one.
func SessionProvider(rt runtime.Runtime, name, executor string) (string, bool, error) {
	return sessionProvider(rt, name, executor, true)
}

// SessionTranscriptProvider reads an identity-verified binding even when execution
// is uncertain. Reading history must not admit or resume a managed run.
func SessionTranscriptProvider(rt runtime.Runtime, name, executor string) (string, bool, error) {
	return sessionProvider(rt, name, executor, false)
}

func sessionProvider(rt runtime.Runtime, name, executor string, requireReady bool) (string, bool, error) {
	row, err := rt.ResolveStrict(name)
	if err != nil {
		return "", true, err
	}
	output, err := rt.TmuxOutput("list-panes", "-s", "-t", "="+row.Name, "-F", "#{session_name}\t#{session_id}\t#{session_created}\t#{pid}\t#{pane_id}\t#{pane_pid}\t#{pane_current_path}")
	if err != nil {
		return "", true, err
	}
	lines := strings.Split(strings.TrimSpace(output), "\n")
	if len(lines) != 1 {
		return "", true, fmt.Errorf("SESSION_PANE_AMBIGUOUS")
	}
	fields := strings.SplitN(lines[0], "\t", 7)
	if len(fields) != 7 || fields[0] != row.Name || fields[1] != row.TmuxID || fields[2] != strconv.FormatInt(row.Created, 10) {
		return "", true, fmt.Errorf("SESSION_IDENTITY_CHANGED")
	}
	pid, err := strconv.Atoi(fields[5])
	if err != nil || pid < 1 || !filepath.IsAbs(fields[6]) {
		return "", true, fmt.Errorf("SESSION_PROCESS_OBSERVATION_UNAVAILABLE")
	}
	directory, err := filepath.EvalSymlinks(fields[6])
	if err != nil {
		return "", true, err
	}
	directory = filepath.Clean(directory)
	key := SessionResourceID(fields[0], fields[1], fields[2], fields[3], fields[4])
	data, err := os.ReadFile(filepath.Join(rt.DataDir, "agents", "session-lifecycle", key, "state.json"))
	if errors.Is(err, os.ErrNotExist) {
		return "", false, nil
	}
	if err != nil {
		return "", true, err
	}
	var state struct {
		Executor string          `json:"executor"`
		State    string          `json:"state"`
		Binding  providerBinding `json:"binding"`
	}
	if err := json.Unmarshal(data, &state); err != nil {
		return "", true, err
	}
	b := state.Binding
	if state.Executor != executor || b.ProviderID == "" || SessionResourceID(b.Name, b.TmuxID, b.Created, b.Server, b.Pane) != key || b.PID != pid || b.Directory != directory || (b.HostProof == "" || b.HostProof != HostProof()) || (b.DirectoryProof == "" || b.DirectoryProof != DirectoryProof(directory)) {
		return "", true, fmt.Errorf("SESSION_PROVIDER_IDENTITY_CHANGED")
	}
	if requireReady && state.State != "idle" && state.State != "busy" && state.State != "submitting" {
		return "", true, fmt.Errorf("SESSION_PROVIDER_UNAVAILABLE")
	}
	expected := b.Processes[pid]
	if expected == "" {
		return "", true, fmt.Errorf("SESSION_PROCESS_OBSERVATION_UNAVAILABLE")
	}
	{
		stat, err := os.ReadFile(filepath.Join("/proc", strconv.Itoa(pid), "stat"))
		if err != nil {
			return "", true, err
		}
		end := strings.LastIndexByte(string(stat), ')')
		if end < 0 {
			return "", true, fmt.Errorf("SESSION_PROCESS_IDENTITY_CHANGED")
		}
		values := strings.Fields(string(stat[end+1:]))
		if len(values) < 20 || values[19] != expected {
			return "", true, fmt.Errorf("SESSION_PROCESS_IDENTITY_CHANGED")
		}
	}
	return b.ProviderID, true, nil
}
