package agentexecution

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
)

// NativeExecutionContext is an observation, never a grant to publish or change a task.
type NativeExecutionContext struct {
	SessionID              string `json:"sessionId"`
	Executor               string `json:"executor"`
	ProviderConversationID string `json:"providerConversationId"`
	ProviderTurnID         string `json:"providerTurnId"`
	LaunchKey              string `json:"launchKey"`
	ProjectID              string `json:"projectId,omitempty"`
	WorkspaceID            string `json:"workspaceId"`
	ObservationSHA256      string `json:"observationSha256"`
	ObservationOnly        bool   `json:"observationOnly"`
	PublicationAuthorized  bool   `json:"publicationAuthorized"`
}

func nativeCallerToken(snapshot map[int]paneProcess, binding SessionBinding, caller int) (string, error) {
	root, exists := snapshot[binding.PID]
	if !exists || root.Token == "" || binding.Processes[binding.PID] != root.Token || snapshot[caller].Token == "" {
		return "", fmt.Errorf("SESSION_PROCESS_IDENTITY_CHANGED")
	}
	seen := map[int]bool{}
	for pid := caller; pid > 0 && !seen[pid]; pid = snapshot[pid].Parent {
		seen[pid] = true
		process, exists := snapshot[pid]
		if !exists || process.Token == "" || binding.ForeignProcesses[pid] == process.Token {
			break
		}
		if pid == binding.PID {
			return snapshot[caller].Token, nil
		}
	}
	return "", fmt.Errorf("NATIVE_CALLER_SESSION_MISMATCH")
}

// The pane is a lookup hint; the actual caller must descend from its verified process.
func (s Service) CurrentNativeContext(pane string, caller int) (NativeExecutionContext, error) {
	var empty NativeExecutionContext
	binding, err := s.paneBinding(pane, true)
	if err != nil {
		return empty, err
	}
	if binding.Pane != pane {
		return empty, fmt.Errorf("NATIVE_CALLER_SESSION_MISMATCH")
	}
	path := filepath.Join(s.Runtime.DataDir, "agents", "session-lifecycle", binding.resourceID(), "state.json")
	raw, err := os.ReadFile(path)
	var state sessionLifecycle
	if err != nil || json.Unmarshal(raw, &state) != nil {
		return empty, fmt.Errorf("SESSION_LIFECYCLE_UNAVAILABLE")
	}
	if state.Executor != "codex" && state.Executor != "claude" {
		return empty, fmt.Errorf("NATIVE_CONTEXT_PROVIDER_UNSUPPORTED")
	}
	if state.State != "busy" || state.EndedIdle || state.LaunchKey == "" || state.TurnID == "" || state.Binding.ProviderID == "" {
		return empty, fmt.Errorf("NATIVE_EXECUTION_CONTEXT_REQUIRED")
	}
	if state.Binding.resourceID() != binding.resourceID() || state.Binding.PID != binding.PID || state.Binding.Directory != binding.Directory || state.Binding.HostProof != binding.HostProof || state.Binding.DirectoryProof != binding.DirectoryProof {
		return empty, fmt.Errorf("SESSION_PROVIDER_IDENTITY_CHANGED")
	}
	snapshot, scope, _, err := paneProcessSnapshot(binding.PID)
	if err != nil || scope != state.Binding.Scope {
		return empty, fmt.Errorf("SESSION_PROCESS_OBSERVATION_UNAVAILABLE")
	}
	token, err := nativeCallerToken(snapshot, state.Binding, caller)
	if err != nil {
		return empty, err
	}
	dir, err := s.directory(state.LaunchKey)
	if err != nil {
		return empty, err
	}
	specPath, receiptPath := filepath.Join(dir, "spec.json"), filepath.Join(dir, "receipt.json")
	specRaw, err := os.ReadFile(specPath)
	var spec Spec
	if err != nil || json.Unmarshal(specRaw, &spec) != nil {
		return empty, fmt.Errorf("NATIVE_EXECUTION_CONTEXT_UNAVAILABLE")
	}
	receiptRaw, err := os.ReadFile(receiptPath)
	var receipt Receipt
	if err != nil || json.Unmarshal(receiptRaw, &receipt) != nil || receipt.Binding == nil || receipt.Workspace == nil || (receipt.State != "running" && receipt.State != "submitting") || spec.Key != state.LaunchKey || spec.Executor != state.Executor || receipt.Session != binding.ID || receipt.Binding.resourceID() != binding.resourceID() || receipt.Binding.PID != binding.PID || receipt.Binding.ProviderID != state.Binding.ProviderID || receipt.Workspace.Directory != binding.Directory || state.PromptHash != workspaceHash(sessionPrompt(dir, spec)) {
		return empty, fmt.Errorf("NATIVE_EXECUTION_CONTEXT_CHANGED")
	}
	if _, err := os.Stat(filepath.Join(dir, "result.json")); !errors.Is(err, os.ErrNotExist) {
		return empty, fmt.Errorf("NATIVE_EXECUTION_CONTEXT_ENDED")
	}
	again, err := s.paneBinding(pane, true)
	if err != nil || !reflect.DeepEqual(again, binding) {
		return empty, fmt.Errorf("SESSION_PROVIDER_IDENTITY_CHANGED")
	}
	latest, latestScope, _, err := paneProcessSnapshot(binding.PID)
	if err != nil || latestScope != scope {
		return empty, fmt.Errorf("SESSION_PROCESS_OBSERVATION_UNAVAILABLE")
	}
	if current, err := nativeCallerToken(latest, state.Binding, caller); err != nil || current != token {
		return empty, fmt.Errorf("SESSION_PROCESS_IDENTITY_CHANGED")
	}
	for name, before := range map[string][]byte{path: raw, specPath: specRaw, receiptPath: receiptRaw} {
		after, err := os.ReadFile(name)
		if err != nil || !bytes.Equal(before, after) {
			return empty, fmt.Errorf("NATIVE_EXECUTION_CONTEXT_CHANGED")
		}
	}
	digest := sha256.New()
	for _, data := range [][]byte{raw, specRaw, receiptRaw, []byte(token)} {
		digest.Write(data)
		digest.Write([]byte{0})
	}
	return NativeExecutionContext{SessionID: binding.ID, Executor: state.Executor, ProviderConversationID: state.Binding.ProviderID, ProviderTurnID: state.TurnID, LaunchKey: state.LaunchKey, ProjectID: spec.ProjectID, WorkspaceID: receipt.Workspace.ID, ObservationSHA256: hex.EncodeToString(digest.Sum(nil)), ObservationOnly: true}, nil
}
