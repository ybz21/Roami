package agentexecution

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/agentlifecycle"
	"github.com/ybz21/Roami/internal/sessionstore"
	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

type SessionBinding struct {
	Name              string         `json:"name"`
	ID                string         `json:"id"`
	TmuxID            string         `json:"tmuxId"`
	Created           string         `json:"created"`
	Server            string         `json:"server"`
	Pane              string         `json:"pane"`
	PID               int            `json:"pid"`
	Directory         string         `json:"directory"`
	ProviderID        string         `json:"providerConversationId"`
	HostProof         string         `json:"hostProof,omitempty"`
	DirectoryProof    string         `json:"directoryProof,omitempty"`
	ProviderHome      string         `json:"providerHome,omitempty"`
	ProviderHomeProof string         `json:"providerHomeProof,omitempty"`
	Processes         map[int]string `json:"processes,omitempty"`
	Scope             string         `json:"scope,omitempty"`
	ForeignProcesses  map[int]string `json:"foreignProcesses,omitempty"`
}

type sessionLifecycle struct {
	Structured       bool                     `json:"structured,omitempty"`
	Model            string                   `json:"model,omitempty"`
	Permission       string                   `json:"permission,omitempty"`
	InitialLaunch    bool                     `json:"initialLaunch,omitempty"`
	Binding          SessionBinding           `json:"binding"`
	Executor         string                   `json:"executor"`
	State            string                   `json:"state"`
	UnknownReason    string                   `json:"unknownReason,omitempty"`
	ProviderConflict *sessionProviderConflict `json:"providerConflict,omitempty"`
	TurnID           string                   `json:"turnId"`
	PromptHash       string                   `json:"promptHash"`
	LaunchKey        string                   `json:"launchKey,omitempty"`
	Tools            map[string]bool          `json:"tools"`
	ClaudeStop       *claudeStop              `json:"claudeStop,omitempty"`
	UpdatedMS        int64                    `json:"updatedMs"`
	CompletedKey     string                   `json:"completedLaunchKey,omitempty"`
	EndedIdle        bool                     `json:"endedIdle,omitempty"`
	Workspace        *Workspace               `json:"workspace,omitempty"`
	Resuming         bool                     `json:"resuming,omitempty"`
}

// Record identities only; hook input and tool output can contain private content.
type sessionProviderConflict struct {
	Executor   string `json:"executor"`
	ProviderID string `json:"providerConversationId"`
	TurnID     string `json:"turnId"`
	Hook       string `json:"hook"`
	Type       string `json:"type"`
}

type SessionEvent struct {
	Source           string            `json:"source"`
	PromptID         string            `json:"prompt_id"`
	NotificationType string            `json:"notification_type"`
	StopAssistant    string            `json:"last_assistant_message"`
	BackgroundTasks  []json.RawMessage `json:"background_tasks"`
	SessionCrons     []json.RawMessage `json:"session_crons"`
	Type             string            `json:"type"`
	ThreadID         string            `json:"thread-id"`
	NotificationTurn string            `json:"turn-id"`
	Inputs           []string          `json:"input-messages"`
	LastAssistant    string            `json:"last-assistant-message"`
	Hook             string            `json:"hook_event_name"`
	ProviderID       string            `json:"session_id"`
	TurnID           string            `json:"turn_id"`
	Prompt           string            `json:"prompt"`
	ToolID           string            `json:"tool_use_id"`
	AgentID          string            `json:"agent_id"`
}

const paneIdentityFormat = "#{session_name}\t#{session_id}\t#{session_created}\t#{pid}\t#{pane_id}\t#{pane_pid}\t#{pane_current_path}"

func (s Service) paneBinding(target string, pane bool) (SessionBinding, error) {
	var output string
	var err error
	if pane {
		if !strings.HasPrefix(target, "%") {
			return SessionBinding{}, fmt.Errorf("SESSION_PANE_REQUIRED")
		}
		output, err = s.Runtime.TmuxOutput("display-message", "-p", "-t", target, paneIdentityFormat)
	} else {
		row, resolveErr := s.Runtime.ResolveStrict(target)
		if resolveErr != nil {
			return SessionBinding{}, resolveErr
		}
		output, err = s.Runtime.TmuxOutput("list-panes", "-s", "-t", "="+row.Name, "-F", paneIdentityFormat)
	}
	if err != nil {
		return SessionBinding{}, fmt.Errorf("SESSION_OBSERVATION_FAILED")
	}
	lines := strings.Split(strings.TrimRight(output, "\n"), "\n")
	if len(lines) != 1 {
		return SessionBinding{}, fmt.Errorf("SESSION_PANE_AMBIGUOUS")
	}
	fields := strings.SplitN(lines[0], "\t", 7)
	if len(fields) != 7 {
		return SessionBinding{}, fmt.Errorf("SESSION_OBSERVATION_FAILED")
	}
	pid, err := strconv.Atoi(fields[5])
	if err != nil || pid < 1 || !strings.HasPrefix(fields[4], "%") || !filepath.IsAbs(fields[6]) {
		return SessionBinding{}, fmt.Errorf("SESSION_OBSERVATION_FAILED")
	}
	directory, err := canonicalWorkspace(fields[6])
	if err != nil {
		return SessionBinding{}, err
	}
	created, err := strconv.ParseInt(fields[2], 10, 64)
	if err != nil || created <= 0 || fields[0] == "" || !strings.HasPrefix(fields[1], "$") || fields[3] == "" {
		return SessionBinding{}, fmt.Errorf("SESSION_OBSERVATION_FAILED")
	}
	row := runtime.SessionRow{Name: fields[0], TmuxID: fields[1], Created: created}
	return SessionBinding{Name: fields[0], ID: row.ID(), TmuxID: fields[1], Created: fields[2], Server: fields[3], Pane: fields[4], PID: pid, Directory: directory, HostProof: sessionHostProof(), DirectoryProof: sessionDirectoryProof(directory)}, nil
}

func (binding SessionBinding) resourceID() string {
	return agentlifecycle.SessionResourceID(binding.Name, binding.TmuxID, binding.Created, binding.Server, binding.Pane)
}

func (s Service) lifecycleFile(binding SessionBinding) (string, error) {
	dir := filepath.Join(s.Runtime.DataDir, "agents", "session-lifecycle", binding.resourceID())
	if err := os.MkdirAll(dir, 0700); err != nil {
		return "", err
	}
	return filepath.Join(dir, "state.json"), nil
}

func sessionPrompt(dir string, spec Spec) string {
	return "Roami delegated task [" + filepath.Base(dir) + "]. Complete this task in the current session and preserve unrelated work. Report evidence and remaining blockers in your final answer.\n\n" + spec.Prompt
}

// ObserveSessionEvent consumes trusted local lifecycle callbacks, never screen text.
func (s Service) ObserveSessionEvent(ctx context.Context, executor, pane string, event SessionEvent) error {
	if executor != "codex" && executor != "claude" {
		return fmt.Errorf("INVALID_EXECUTOR")
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	binding, err := s.paneBinding(pane, true)
	if err != nil {
		return err
	}
	return s.applySessionEvent(executor, binding, event)
}

func markSessionUnknown(state *sessionLifecycle, reason string) {
	state.EndedIdle = false
	if state.State != "unknown" || state.UnknownReason == "" {
		state.UnknownReason = reason
	}
	state.State = "unknown"
}

func (s Service) applySessionEvent(executor string, binding SessionBinding, event SessionEvent) error {
	if executor == "claude" {
		if event.AgentID != "" && event.Hook != "SubagentStart" && event.Hook != "SubagentStop" {
			return nil
		}
		event.TurnID = event.PromptID
		if event.Hook == "PostToolUseFailure" {
			event.Hook = "PostToolUse"
		}
	}
	completed := executor == "codex" && event.Type == "agent-turn-complete"
	if completed {
		event.ProviderID, event.TurnID = event.ThreadID, event.NotificationTurn
	}
	if event.ProviderID == "" || len(event.ProviderID) > 300 {
		return fmt.Errorf("INVALID_SESSION_EVENT")
	}
	path, err := s.lifecycleFile(binding)
	if err != nil {
		return err
	}
	unlock, err := lock(filepath.Join(filepath.Dir(path), "state.lock"))
	if err != nil {
		return err
	}
	defer unlock()
	state := sessionLifecycle{Binding: binding, Executor: executor, State: "unknown", Tools: map[string]bool{}}
	if err = readJSON(path, &state); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	if state.Tools == nil {
		state.Tools = map[string]bool{}
	}
	if executor == "codex" && state.Executor == "codex" && state.InitialLaunch && state.TurnID == "" && state.PromptHash == "" {
		// SessionStart can belong to an internal thread; only assigned input authenticates a root.
		if event.Hook != "UserPromptSubmit" {
			return nil
		}
		dir, _ := s.directory(state.LaunchKey)
		var spec Spec
		var receipt Receipt
		if readJSON(filepath.Join(dir, "spec.json"), &spec) != nil || spec.Executor != "codex" || !spec.Persistent || (spec.SessionID != "" && spec.ResumeFrom == "") || spec.Key != state.LaunchKey || readJSON(filepath.Join(dir, "receipt.json"), &receipt) != nil || receipt.Binding != nil || workspaceHash(event.Prompt) != workspaceHash(sessionPrompt(dir, spec)) || event.TurnID == "" {
			return nil
		}
		if state.Resuming {
			if spec.ResumeFrom == "" || state.Binding.ProviderID != spec.ResumeProvider || state.State != "submitting" {
				return nil
			}
		} else {
			state.Binding.ProviderID, state.State = "", "submitting"
		}
	}
	if event.Hook == "UserPromptSubmit" {
		state.CompletedKey, state.EndedIdle = "", false
	}
	if state.Binding.ProviderID != "" && (state.Binding.ProviderID != event.ProviderID || state.Executor != executor) {
		if state.ProviderConflict == nil {
			state.ProviderConflict = &sessionProviderConflict{Executor: executor, ProviderID: event.ProviderID, TurnID: truncate(event.TurnID, 300), Hook: truncate(event.Hook, 100), Type: truncate(event.Type, 100)}
		}
		// Internal Codex threads inherit notify; their completion says nothing about this turn.
		if !completed || state.Executor != executor {
			markSessionUnknown(&state, "SESSION_PROVIDER_CHANGED")
		}
		state.UpdatedMS = time.Now().UnixMilli()
		return writeJSON(path, state)
	}
	if (event.TurnID == "" && event.Hook != "SessionStart" && event.Hook != "SessionEnd") || len(event.TurnID) > 300 {
		markSessionUnknown(&state, "SESSION_EVENT_INVALID_TURN")
		state.ClaudeStop = nil
		state.UpdatedMS = time.Now().UnixMilli()
		if err := writeJSON(path, state); err != nil {
			return err
		}
		return fmt.Errorf("INVALID_SESSION_EVENT")
	}
	state.Binding.ProviderID, state.Executor = event.ProviderID, executor
	state.UpdatedMS = time.Now().UnixMilli()
	claudeHandled, claudeCompleted := false, false
	if executor == "claude" {
		claudeHandled, claudeCompleted = observeClaudeStop(&state, &event)
		completed = claudeCompleted
	}
	switch {
	case claudeHandled:
	case event.Hook == "SessionStart":
		// Compaction keeps the authenticated turn, but invalidates an earlier Stop candidate.
		if executor == "claude" && event.Source == "compact" && !state.InitialLaunch && (state.State == "busy" || state.State == "idle") && state.TurnID != "" && state.PromptHash != "" && (event.TurnID == "" || event.TurnID == state.TurnID) {
			break
		}
		if state.InitialLaunch {
			state.State = "submitting"
		} else {
			markSessionUnknown(&state, "SESSION_START_UNTRACKED")
		}
	case event.Hook == "UserPromptSubmit":
		promptHash := workspaceHash(event.Prompt)
		if state.State == "busy" && state.TurnID == event.TurnID && state.PromptHash == promptHash {
			return nil
		}
		if state.LaunchKey != "" {
			dir, _ := s.directory(state.LaunchKey)
			var spec Spec
			if readJSON(filepath.Join(dir, "spec.json"), &spec) != nil || promptHash != workspaceHash(sessionPrompt(dir, spec)) || state.State != "submitting" {
				markSessionUnknown(&state, "SESSION_PROMPT_MISMATCH")
				return writeJSON(path, state)
			}
			if state.InitialLaunch {
				if err := s.bindInitialSession(dir, &state, binding, event.ProviderID); err != nil {
					return err
				}
			}
		}
		state.CompletedKey, state.EndedIdle = "", false
		state.TurnID, state.PromptHash, state.State = event.TurnID, promptHash, "busy"
	case event.Hook == "PreToolUse" || event.Hook == "PostToolUse":
		if event.Hook == "PreToolUse" && state.LaunchKey != "" && state.TurnID == event.TurnID {
			dir, _ := s.directory(state.LaunchKey)
			if _, cancelErr := os.Stat(filepath.Join(dir, "cancel.json")); cancelErr == nil {
				return fmt.Errorf("SESSION_TASK_CANCEL_REQUESTED")
			}
		}
		if state.State != "busy" || state.TurnID != event.TurnID || event.ToolID == "" {
			markSessionUnknown(&state, "SESSION_TOOL_EVENT_MISMATCH")
		} else if event.Hook == "PreToolUse" {
			state.Tools[event.ToolID] = true
		} else {
			delete(state.Tools, event.ToolID)
		}
	case event.Hook == "SubagentStart":
		if event.AgentID == "" {
			markSessionUnknown(&state, "SESSION_SUBAGENT_ID_MISSING")
		} else {
			state.Tools["subagent:"+event.AgentID] = true
		}
	case event.Hook == "Interrupt" || event.Hook == "SessionEnd":
		endedIdle := event.Hook == "SessionEnd" && (state.State == "idle" || state.State == "unknown" && state.EndedIdle && state.UnknownReason == "SESSION_INTERRUPTED") && state.CompletedKey != "" && len(state.Tools) == 0
		markSessionUnknown(&state, "SESSION_INTERRUPTED")
		state.EndedIdle = endedIdle
	case completed:
		inputMatches := claudeCompleted
		for _, input := range event.Inputs {
			inputMatches = inputMatches || workspaceHash(input) == state.PromptHash
		}
		if state.TurnID != event.TurnID || !inputMatches || len(state.Tools) != 0 || state.State != "busy" {
			if state.State == "idle" && state.TurnID == event.TurnID {
				return nil
			}
			markSessionUnknown(&state, "SESSION_COMPLETION_MISMATCH")
		} else if state.LaunchKey != "" {
			dir, _ := s.directory(state.LaunchKey)
			var receipt Receipt
			if readJSON(filepath.Join(dir, "receipt.json"), &receipt) != nil || receipt.Binding == nil || !sessionProcessesStopped(*receipt.Binding) {
				markSessionUnknown(&state, "SESSION_STOP_UNCONFIRMED")
			} else {
				stopped := true
				result := Result{State: "succeeded", Summary: truncate(event.LastAssistant, 32000), FinishedMS: time.Now().UnixMilli(), InputStopped: &stopped, OutcomeKnown: &stopped}
				if _, cancelErr := os.Stat(filepath.Join(dir, "cancel.json")); cancelErr == nil {
					result.State, result.Summary = "cancelled", "Session task stopped after cancellation request"
				}
				if err = writeJSON(filepath.Join(dir, "result.json"), result); err != nil {
					return err
				}
				state.CompletedKey = state.LaunchKey
				state.LaunchKey, state.State = "", "idle"
			}
		} else {
			state.State = "idle"
		}
	}
	if state.State != "unknown" {
		state.UnknownReason = ""
	}
	if err := writeJSON(path, state); err != nil {
		return err
	}
	if executor == "codex" || executor == "claude" {
		meta := sessmeta.New(s.Runtime.HomeDir)
		meta.DataDir = s.Runtime.DataDir
		if row, ok := meta.Get(binding.Name); ok && row.AgentKind == executor {
			return meta.SetAgentSession(binding.Name, event.ProviderID)
		}
	}
	return nil
}

func (s Service) continueSession(ctx context.Context, spec Spec) (Status, error) {
	if (spec.Executor != "codex" && spec.Executor != "claude" && !structuredExecutor(spec.Executor)) || spec.Directory != "" || spec.ProjectID != "" || spec.WorkspaceID != "" || spec.Base != "" || spec.Remote != "" || spec.Model != "" || spec.Permission != "" || strings.TrimSpace(spec.Prompt) == "" || !validExecutionTimeout(spec.TimeoutSeconds) {
		return Status{}, fmt.Errorf("INVALID_SESSION_EXECUTION_SPEC")
	}
	dir, err := s.directory(spec.Key)
	if err != nil {
		return Status{}, err
	}
	if err = os.MkdirAll(dir, 0700); err != nil {
		return Status{}, err
	}
	unlock, err := lock(filepath.Join(dir, "launch.lock"))
	if err != nil {
		return Status{}, err
	}
	defer unlock()
	var previous Spec
	if err = readJSON(filepath.Join(dir, "spec.json"), &previous); err == nil {
		if previous != spec {
			return Status{}, fmt.Errorf("LAUNCH_KEY_CONFLICT")
		}
		return s.Status(spec.Key)
	} else if !errors.Is(err, os.ErrNotExist) {
		return Status{}, err
	}
	if spec.ResumeFrom != "" || spec.ResumeProvider != "" {
		return s.restoreProviderSession(ctx, dir, spec)
	}
	binding, err := s.paneBinding(spec.SessionID, false)
	if err != nil {
		return Status{}, err
	}
	path, err := s.lifecycleFile(binding)
	if err != nil {
		return Status{}, err
	}
	stateUnlock, err := lock(filepath.Join(filepath.Dir(path), "state.lock"))
	if err != nil {
		return Status{}, err
	}
	defer func() { stateUnlock() }()
	var state sessionLifecycle
	if readJSON(path, &state) != nil || state.Executor != spec.Executor || state.Binding.ProviderID == "" {
		return Status{}, fmt.Errorf("SESSION_LIFECYCLE_UNAVAILABLE")
	}
	if structuredExecutor(spec.Executor) && (!state.Structured || !sessionProcessesStopped(state.Binding)) {
		return Status{}, fmt.Errorf("SESSION_NOT_IDLE")
	}
	if err = s.reconcileDirectCodexCompletion(binding, &state, path); err != nil {
		return Status{}, err
	}
	if state.State != "idle" || state.LaunchKey != "" || len(state.Tools) != 0 {
		return Status{}, fmt.Errorf("SESSION_NOT_IDLE")
	}
	if state.Binding.Directory != binding.Directory {
		return Status{}, fmt.Errorf("SESSION_DIRECTORY_CHANGED")
	}
	snapshot, scope, scoped, err := paneProcessSnapshot(binding.PID)
	if err != nil {
		return Status{}, err
	}
	binding.Scope, binding.Processes = scope, scoped
	binding.ForeignProcesses = map[int]string{}
	descendants := descendantProcesses(snapshot, binding.PID)
	for pid, token := range scoped {
		if descendants[pid] == "" {
			binding.ForeignProcesses[pid] = token
		}
	}
	if binding.Processes[binding.PID] == "" {
		return Status{}, fmt.Errorf("SESSION_PROCESS_OBSERVATION_UNAVAILABLE")
	}
	binding.ProviderID = state.Binding.ProviderID
	binding.ProviderHome, binding.ProviderHomeProof = state.Binding.ProviderHome, state.Binding.ProviderHomeProof
	var workspace Workspace
	if state.Workspace != nil {
		workspace, err = s.recoveryWorkspace(ctx, *state.Workspace)
	} else {
		workspace, err = s.rememberWorkspace(Workspace{Directory: binding.Directory})
	}
	if err != nil {
		return Status{}, err
	}
	if err = ctx.Err(); err != nil {
		return Status{}, err
	}
	if err = writeJSON(filepath.Join(dir, "spec.json"), spec); err != nil {
		return Status{}, err
	}
	receipt := Receipt{State: "submitting", Session: binding.ID, Workspace: &workspace, Binding: &binding, DeadlineMS: executionDeadline(spec.TimeoutSeconds)}
	if err = writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
		return Status{}, err
	}
	lease, err := s.claimWorkspace(ctx, binding.Directory, spec.Key)
	if err != nil {
		if writeErr := writeJSON(filepath.Join(dir, "result.json"), workspaceClaimResult(err)); writeErr != nil {
			return Status{}, writeErr
		}
		return s.Status(spec.Key)
	}
	defer lease()
	state.Binding, state.LaunchKey, state.State, state.Workspace = binding, spec.Key, "submitting", &workspace
	if err = writeJSON(path, state); err != nil {
		return Status{}, err
	}
	if state.Structured {
		// The resident runner consumes this journal entry exactly once.
		lease()
		stateUnlock()
		stateUnlock = func() {}
		return s.Status(spec.Key)
	}
	rt := s.Runtime
	rt.Context = ctx
	if err = rt.SendPromptSubmit(binding.Pane, sessionPrompt(dir, spec)); err != nil {
		return Status{}, fmt.Errorf("SESSION_SUBMISSION_UNKNOWN")
	}
	// A hook can now advance the durable state; never overwrite it after sending.
	stateUnlock()
	stateUnlock = func() {}
	return s.Status(spec.Key)
}

func (s Service) sessionExecutionStatus(key string, status Status) (Status, error) {
	binding, err := s.paneBinding(status.Binding.Name, false)
	if err != nil || binding.resourceID() != status.Binding.resourceID() {
		original := status.Receipt
		status.State, status.ObservationErrorCode = "unknown", "SESSION_BINDING_UNAVAILABLE"
		return s.missingSessionStatus(key, status, original)
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
	dir, _ := s.directory(key)
	var completed Result
	if resultErr := readJSON(filepath.Join(dir, "result.json"), &completed); resultErr == nil {
		status.State, status.Result = completed.State, &completed
		return status, nil
	} else if !errors.Is(resultErr, os.ErrNotExist) {
		return status, resultErr
	}
	var state sessionLifecycle
	if readJSON(path, &state) != nil {
		status.State, status.ObservationErrorCode = "unknown", "SESSION_LIFECYCLE_UNAVAILABLE"
		return status, nil
	}
	if recovered, ok, problem := s.reconcileCodexCompletion(key, status, &state, path); ok || problem != nil {
		return recovered, problem
	}
	if recovered, ok, problem := s.reconcileClaudeRejection(key, status, &state, path); ok || problem != nil {
		return recovered, problem
	}
	if state.LaunchKey == key && state.Executor == "claude" && state.Binding.ProviderID == status.Binding.ProviderID && state.Binding.resourceID() == binding.resourceID() {
		status.Progress = claudeReportedProgress(state.Binding, state.TurnID, state.PromptHash, dir)
	}
	if state.LaunchKey != key || (state.State != "busy" && !(state.Structured && state.State == "submitting")) {
		status.State, status.ObservationErrorCode = "unknown", state.UnknownReason
		if status.ObservationErrorCode == "" {
			status.ObservationErrorCode = "SESSION_LIFECYCLE_UNKNOWN"
		}
		if state.LaunchKey != key {
			status.ObservationErrorCode = "SESSION_LAUNCH_MISMATCH"
		}
		return status, nil
	}
	status.State = "running"
	if _, err := os.Stat(filepath.Join(dir, "cancel.json")); err == nil {
		status.State = "cancelling"
	}
	if status.State != "cancelling" && status.DeadlineMS != 0 && time.Now().UnixMilli() >= status.DeadlineMS {
		status.State, status.ObservationErrorCode = "unknown", "EXECUTION_DEADLINE"
	}
	return status, nil
}

// HookConfiguration only prints configuration; it never rewrites the user's hooks.
func HookConfiguration(executable, executor string) (map[string]any, error) {
	return agentlifecycle.HookConfiguration(executable, executor)
}

func DecodeSessionEvent(content []byte) (SessionEvent, error) {
	return ReadSessionEvent(bytes.NewReader(content))
}

// Tool responses are not lifecycle evidence and can be much larger than the event metadata.
func ReadSessionEvent(input io.Reader) (SessionEvent, error) {
	var event SessionEvent
	bounded := &io.LimitedReader{R: input, N: (64 << 20) + 1}
	decoder := json.NewDecoder(bounded)
	if err := decoder.Decode(&event); err != nil {
		return SessionEvent{}, fmt.Errorf("INVALID_SESSION_EVENT")
	}
	if decoder.Decode(new(any)) != io.EOF || bounded.N == 0 {
		return SessionEvent{}, fmt.Errorf("INVALID_SESSION_EVENT")
	}
	metadata, err := json.Marshal(event)
	if err != nil || len(metadata) > 100000 {
		return SessionEvent{}, fmt.Errorf("INVALID_SESSION_EVENT")
	}
	return event, nil
}
