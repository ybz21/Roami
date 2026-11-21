package agentexecution

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"strings"
	"syscall"
)

var (
	claudeCapabilityName    = regexp.MustCompile("^[A-Za-z][A-Za-z0-9_-]{0,127}$")
	claudeCapabilityRequest = regexp.MustCompile("^[A-Za-z0-9_-]{1,100}$")
)

// Read only the active, already-bound Main launch. No provider data is returned verbatim.
func (s Service) ClaudeCapabilityInput(key, capability, request string) (*ClaudeModelInputEvidence, error) {
	unavailable := fmt.Errorf("NATIVE_CAPABILITY_INPUT_UNCONFIRMED")
	if !strings.HasPrefix(key, "project-main:") || !claudeCapabilityName.MatchString(capability) || !claudeCapabilityRequest.MatchString(request) {
		return nil, unavailable
	}
	dir, err := s.directory(key)
	if err != nil {
		return nil, unavailable
	}
	specPath, receiptPath, resultPath := filepath.Join(dir, "spec.json"), filepath.Join(dir, "receipt.json"), filepath.Join(dir, "result.json")
	specRaw, specErr := os.ReadFile(specPath)
	receiptRaw, receiptErr := os.ReadFile(receiptPath)
	var spec Spec
	var receipt Receipt
	if specErr != nil || receiptErr != nil || json.Unmarshal(specRaw, &spec) != nil || json.Unmarshal(receiptRaw, &receipt) != nil ||
		spec.Key != key || spec.Executor != "claude" || !spec.Persistent || spec.SessionID == "" || spec.SessionID != receipt.Session ||
		receipt.Binding == nil || receipt.Workspace == nil || receipt.State != "running" && receipt.State != "submitting" {
		return nil, unavailable
	}
	pane, err := s.paneBinding(receipt.Session, false)
	if err != nil || pane.resourceID() != receipt.Binding.resourceID() || pane.Directory != receipt.Workspace.Directory {
		return nil, unavailable
	}
	statePath := filepath.Join(s.Runtime.DataDir, "agents", "session-lifecycle", pane.resourceID(), "state.json")
	stateRaw, err := os.ReadFile(statePath)
	var state sessionLifecycle
	if err != nil || json.Unmarshal(stateRaw, &state) != nil || !claudeCapabilityActive(key, dir, spec, receipt, state, pane) ||
		s.preparedContinuation(spec, state) != nil || !claudeCapabilityProcess(state.Binding) {
		return nil, unavailable
	}
	if _, err = os.Lstat(resultPath); !errors.Is(err, os.ErrNotExist) {
		return nil, unavailable
	}
	input := readClaudeCapabilityInput(state.Binding, state.TurnID, state.PromptHash, capability, request)
	if input == nil {
		return nil, unavailable
	}
	after, err := s.paneBinding(receipt.Session, false)
	if err != nil || !reflect.DeepEqual(pane, after) || !claudeCapabilityProcess(state.Binding) {
		return nil, unavailable
	}
	for path, before := range map[string][]byte{statePath: stateRaw, specPath: specRaw, receiptPath: receiptRaw} {
		raw, err := os.ReadFile(path)
		if err != nil || !bytes.Equal(before, raw) {
			return nil, unavailable
		}
	}
	if _, err = os.Lstat(resultPath); !errors.Is(err, os.ErrNotExist) {
		return nil, unavailable
	}
	return input, nil
}

func claudeCapabilityActive(key, dir string, spec Spec, receipt Receipt, state sessionLifecycle, pane SessionBinding) bool {
	binding := state.Binding
	return state.State == "busy" && state.Executor == "claude" && !state.EndedIdle && !state.InitialLaunch && !state.Structured &&
		state.ProviderConflict == nil && state.UnknownReason == "" && state.TurnID != "" && state.LaunchKey == key &&
		state.PromptHash == workspaceHash(sessionPrompt(dir, spec)) && samePreparedProvider(*receipt.Binding, binding) &&
		pane.resourceID() == binding.resourceID() && pane.PID == binding.PID && pane.Directory == binding.Directory &&
		pane.HostProof == binding.HostProof && pane.DirectoryProof == binding.DirectoryProof &&
		binding.ProviderHomeProof != "" && binding.ProviderHomeProof == sessionDirectoryProof(binding.ProviderHome)
}

func claudeCapabilityProcess(binding SessionBinding) bool {
	snapshot, scope, _, err := paneProcessSnapshot(binding.PID)
	return err == nil && scope != "" && scope == binding.Scope && snapshot[binding.PID].Token != "" &&
		snapshot[binding.PID].Token == binding.Processes[binding.PID]
}

func readClaudeCapabilityInput(binding SessionBinding, turn, hash, capability, request string) *ClaudeModelInputEvidence {
	path, info := claudeTranscriptPath(binding)
	if info == nil {
		return nil
	}
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil
	}
	file := os.NewFile(uintptr(fd), path)
	defer file.Close()
	if opened, err := file.Stat(); err != nil || !sameClaudeInputFile(info, opened) {
		return nil
	}
	result := claudeModelInput(io.NewSectionReader(file, 0, info.Size()), binding, turn, hash, capability, request)
	if after, err := os.Lstat(path); err != nil || !sameClaudeInputFile(info, after) {
		return nil
	}
	return result
}

func sameClaudeInputFile(before, after os.FileInfo) bool {
	return os.SameFile(before, after) && before.Mode() == after.Mode() && before.Size() == after.Size() &&
		before.ModTime().Equal(after.ModTime())
}
