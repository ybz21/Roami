package agentexecution

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

type sessionInterrupt struct {
	ResourceID           string         `json:"resourceId"`
	ProviderID           string         `json:"providerConversationId"`
	TurnID               string         `json:"turnId"`
	PromptHash           string         `json:"promptHash"`
	Delivered            bool           `json:"delivered"`
	CreatedMS            int64          `json:"createdMs"`
	Tools                map[int]string `json:"tools,omitempty"`
	ToolSignalsDelivered bool           `json:"toolSignalsDelivered,omitempty"`
}

func (s Service) cancelSession(key string, status Status) (Status, error) {
	dir, _ := s.directory(key)
	if err := writeJSON(filepath.Join(dir, "cancel.json"), map[string]bool{"cancel": true}); err != nil {
		return status, err
	}
	if status.State == "unknown" {
		if cancelled, handled, err := s.cancelRejectedClaude(key, status); handled || err != nil {
			return cancelled, err
		}
	}
	// An elapsed observation deadline does not make the still-bound turn uninterruptible.
	expired := status.State == "unknown" && status.ObservationErrorCode == "EXECUTION_DEADLINE"
	if status.State != "running" && status.State != "cancelling" && !expired {
		return status, nil
	}
	status.State, status.ObservationErrorCode = "cancelling", ""
	binding, err := s.paneBinding(status.Binding.Name, false)
	if err != nil || binding.resourceID() != status.Binding.resourceID() || binding.PID != status.Binding.PID || binding.Directory != status.Binding.Directory {
		status.State, status.ObservationErrorCode = "unknown", "SESSION_BINDING_UNAVAILABLE"
		return status, nil
	}
	path, err := s.lifecycleFile(binding)
	if err != nil {
		return status, err
	}
	unlock, err := lock(filepath.Join(filepath.Dir(path), "state.lock"))
	if err != nil {
		return status, err
	}
	defer unlock()
	var state sessionLifecycle
	var spec Spec
	if readJSON(path, &state) != nil || readJSON(filepath.Join(dir, "spec.json"), &spec) != nil {
		status.State, status.ObservationErrorCode = "unknown", "SESSION_LIFECYCLE_UNAVAILABLE"
		return status, nil
	}
	if state.Structured {
		return status, nil
	}
	if spec.Executor != "codex" && spec.Executor != "claude" {
		return status, nil
	}
	if state.LaunchKey != key || state.State != "busy" || state.TurnID == "" || state.Executor != spec.Executor || state.Binding.ProviderID != status.Binding.ProviderID || state.Binding.resourceID() != binding.resourceID() || state.Binding.PID != binding.PID || state.Binding.Directory != binding.Directory || workspaceHash(sessionPrompt(dir, spec)) != state.PromptHash {
		status.State, status.ObservationErrorCode = "unknown", "SESSION_BINDING_CONFLICT"
		return status, nil
	}
	processes, scope, scoped, err := paneProcessSnapshot(binding.PID)
	if err != nil || scope != state.Binding.Scope || state.Binding.Processes[binding.PID] == "" || processes[binding.PID].Token != state.Binding.Processes[binding.PID] {
		status.State, status.ObservationErrorCode = "unknown", "SESSION_PROCESS_OBSERVATION_UNAVAILABLE"
		return status, nil
	}
	current, err := s.paneBinding(binding.Name, false)
	if err != nil || current.resourceID() != binding.resourceID() || current.PID != binding.PID || current.Directory != binding.Directory {
		status.State, status.ObservationErrorCode = "unknown", "SESSION_BINDING_UNAVAILABLE"
		return status, nil
	}
	intent := sessionInterrupt{ResourceID: binding.resourceID(), ProviderID: state.Binding.ProviderID, TurnID: state.TurnID, PromptHash: state.PromptHash, CreatedMS: time.Now().UnixMilli()}
	interruptPath := filepath.Join(dir, "interrupt-request.json")
	var previous sessionInterrupt
	if err = readJSON(interruptPath, &previous); err == nil {
		if previous.ResourceID != intent.ResourceID || previous.ProviderID != intent.ProviderID || previous.TurnID != intent.TurnID || previous.PromptHash != intent.PromptHash {
			return status, fmt.Errorf("SESSION_INTERRUPT_CONFLICT")
		}
		if !previous.Delivered {
			status.ObservationErrorCode = "SESSION_INTERRUPT_UNKNOWN"
		} else if len(previous.Tools) > 0 && !previous.ToolSignalsDelivered {
			status.ObservationErrorCode = "SESSION_TOOL_INTERRUPT_UNKNOWN"
		}
		return status, nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return status, err
	}
	intent.Tools = capturedSessionTools(*status.Binding, processes, scoped)
	// Journal before input: an uncertain delivery must never hit a later reused turn.
	if err = writeJSON(interruptPath, intent); err != nil {
		return status, err
	}
	if err = s.Runtime.Tmux("send-keys", "-t", binding.Pane, "Escape"); err != nil {
		status.ObservationErrorCode = "SESSION_INTERRUPT_UNKNOWN"
		return status, nil
	}
	intent.Delivered = true
	if err = writeJSON(interruptPath, intent); err != nil {
		return status, err
	}
	if err = signalCapturedSessionTools(*status.Binding, intent.Tools); err != nil {
		status.ObservationErrorCode = "SESSION_TOOL_INTERRUPT_UNKNOWN"
		return status, nil
	}
	intent.ToolSignalsDelivered = true
	if err = writeJSON(interruptPath, intent); err != nil {
		return status, err
	}
	return status, nil
}
