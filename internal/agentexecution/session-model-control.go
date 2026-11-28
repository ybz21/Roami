package agentexecution

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"time"

	"github.com/ybz21/Roami/internal/fsguard"
)

type ModelSelectionSpec struct {
	Key           string `json:"key"`
	PreparedFrom  string `json:"preparedFrom"`
	ExpectedModel string `json:"expectedModel"`
	Model         string `json:"model"`
	AllowMetered  bool   `json:"allowMetered,omitempty"`
}

type ClaudeModelSelection struct {
	ModelSelectionSpec
	SessionID  string           `json:"sessionId"`
	ProviderID string           `json:"providerConversationId"`
	Proof      claudeModelProof `json:"proof"`
	SelectedMS int64            `json:"selectedMs"`
	NativeID   string           `json:"nativeModelId"`
}

type claudeModelSelection struct {
	Spec         ModelSelectionSpec `json:"spec"`
	Target       claudePickerModel  `json:"target"`
	Anchor       claudeModelAnchor  `json:"anchor"`
	SettingsHash string             `json:"settingsSha256"`
	CompletedKey string             `json:"completedLaunchKey"`
	TurnID       string             `json:"turnId"`
}

type claudeModelRejection struct {
	Spec         ModelSelectionSpec `json:"spec"`
	CommandID    string             `json:"commandId"`
	SourceDigest string             `json:"sourceSha256"`
}

var claudePickerTargetUnconfirmed = errors.New("SESSION_MODEL_SELECTION_TARGET_UNCONFIRMED")

func (state sessionLifecycle) configuredModel() string {
	if state.SelectedModel != nil {
		return state.SelectedModel.Model
	}
	return state.Model
}

func (state sessionLifecycle) claudeTranscriptModel() string {
	if state.SelectedModel != nil {
		return state.SelectedModel.NativeID
	}
	return state.Model
}

// SelectClaudeModel sends a local control command once. A retry reconciles the saved evidence.
func (s Service) SelectClaudeModel(ctx context.Context, spec ModelSelectionSpec) (ClaudeModelSelection, error) {
	if spec.Key == "" || len(spec.Key) > 200 || spec.PreparedFrom == "" || spec.ExpectedModel == "" || spec.ExpectedModel == spec.Model {
		return ClaudeModelSelection{}, fmt.Errorf("INVALID_SESSION_MODEL_SELECTION")
	}
	dir, err := s.directory("model-selection:" + spec.Key)
	if err != nil {
		return ClaudeModelSelection{}, err
	}
	if err = os.MkdirAll(dir, 0700); err != nil {
		return ClaudeModelSelection{}, err
	}
	unlock, err := lock(filepath.Join(dir, "selection.lock"))
	if err != nil {
		return ClaudeModelSelection{}, err
	}
	defer unlock()
	receiptPath := filepath.Join(dir, "receipt.json")
	var prior ClaudeModelSelection
	if err = readJSON(receiptPath, &prior); err == nil {
		if prior.ModelSelectionSpec != spec {
			return ClaudeModelSelection{}, fmt.Errorf("SESSION_MODEL_SELECTION_KEY_CONFLICT")
		}
		return prior, nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return ClaudeModelSelection{}, err
	}
	rejectionPath := filepath.Join(dir, "unchanged.json")
	var rejection claudeModelRejection
	if err = readJSON(rejectionPath, &rejection); err == nil {
		if rejection.Spec != spec {
			return ClaudeModelSelection{}, fmt.Errorf("SESSION_MODEL_SELECTION_KEY_CONFLICT")
		}
		if !codexThreadID.MatchString(rejection.CommandID) || !claudeRequestSHA.MatchString(rejection.SourceDigest) {
			return ClaudeModelSelection{}, claudePickerUnavailable
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return ClaudeModelSelection{}, err
	}

	launchDir, err := s.directory(spec.PreparedFrom)
	if err != nil {
		return ClaudeModelSelection{}, err
	}
	var original Receipt
	if readJSON(filepath.Join(launchDir, "receipt.json"), &original) != nil || original.Binding == nil {
		return ClaudeModelSelection{}, fmt.Errorf("SESSION_MODEL_SELECTION_ORIGIN_UNCONFIRMED")
	}
	binding, err := s.paneBinding(original.Session, false)
	if err != nil || binding.resourceID() != original.Binding.resourceID() {
		return ClaudeModelSelection{}, fmt.Errorf("SESSION_BINDING_UNAVAILABLE")
	}
	statePath, err := s.lifecycleFile(binding)
	if err != nil {
		return ClaudeModelSelection{}, err
	}

	// Read the existing origin proof before the state reservation. The reservation rechecks its scope.
	prepared, prepareErr := s.PreparedSession(spec.PreparedFrom)
	stateLockPath := filepath.Join(filepath.Dir(statePath), "state.lock")
	stateUnlock, err := lock(stateLockPath)
	if err != nil {
		return ClaudeModelSelection{}, err
	}
	var state sessionLifecycle
	if readJSON(statePath, &state) != nil || !claudeModelSelectionReady(binding, state) {
		stateUnlock()
		return ClaudeModelSelection{}, fmt.Errorf("SESSION_MODEL_SELECTION_ORIGIN_UNCONFIRMED")
	}
	if rejection.Spec == spec {
		defer stateUnlock()
		return ClaudeModelSelection{}, clearUnchangedModelSelection(statePath, state, spec)
	}
	if prior := state.SelectedModel; prior != nil && prior.Key == spec.Key {
		stateUnlock()
		if prior.ModelSelectionSpec != spec {
			return ClaudeModelSelection{}, fmt.Errorf("SESSION_MODEL_SELECTION_KEY_CONFLICT")
		}
		return *prior, writeJSON(receiptPath, prior)
	}
	start := state.ModelSelection == nil
	if start {
		if prepareErr != nil || prepared.Executor != "claude" || prepared.ConfiguredModel != spec.ExpectedModel ||
			state.configuredModel() != spec.ExpectedModel || state.CompletedKey != prepared.completedKey || !reflect.DeepEqual(prepared.Binding, state.Binding) {
			stateUnlock()
			return ClaudeModelSelection{}, fmt.Errorf("SESSION_MODEL_SELECTION_ORIGIN_UNCONFIRMED")
		}
		anchor, anchorOK := claudeModelCheckpoint(state.Binding)
		settings := readClaudeModelSettings(state.Binding)
		target, resolveErr := s.claudePickerTarget(ctx, spec.Model, settings, spec.AllowMetered)
		if resolveErr != nil || !anchorOK || settings == nil {
			stateUnlock()
			return ClaudeModelSelection{}, claudePickerTargetUnconfirmed
		}
		state.ModelSelection = &claudeModelSelection{Spec: spec, Target: target, Anchor: anchor, SettingsHash: claudeSettingsHash(settings), CompletedKey: state.CompletedKey, TurnID: state.TurnID}
		if err = writeJSON(statePath, state); err != nil {
			stateUnlock()
			return ClaudeModelSelection{}, err
		}
	} else if state.ModelSelection.Spec != spec {
		stateUnlock()
		return ClaudeModelSelection{}, fmt.Errorf("SESSION_MODEL_SELECTION_PENDING")
	}
	intent := *state.ModelSelection
	knownBinding := state.Binding
	stateUnlock()

	var resume *claudeModelAnchor
	if !start {
		resume = &intent.Anchor
	}
	actionErr := s.operateClaudePicker(ctx, knownBinding, intent.Target, resume)
	if actionErr == nil {
		wait, cancel := context.WithTimeout(ctx, 2*time.Second)
		defer cancel()
		waitForClaudeModelProof(wait, knownBinding, intent)
	}
	stateUnlock, err = lock(stateLockPath)
	if err != nil {
		return ClaudeModelSelection{}, err
	}
	defer stateUnlock()
	actual, err := s.paneBinding(binding.ID, false)
	if err != nil || readJSON(statePath, &state) != nil || state.ModelSelection == nil || *state.ModelSelection != intent ||
		!reflect.DeepEqual(knownBinding, state.Binding) || !claudeModelSelectionReady(actual, state) ||
		state.CompletedKey != intent.CompletedKey || state.TurnID != intent.TurnID {
		return ClaudeModelSelection{}, fmt.Errorf("SESSION_MODEL_SELECTION_UNCONFIRMED")
	}
	if errors.Is(actionErr, claudePickerNotOpened) {
		state.ModelSelection = nil
		if err = writeJSON(statePath, state); err != nil {
			return ClaudeModelSelection{}, err
		}
		return ClaudeModelSelection{}, claudePickerNotOpened
	}
	if settings := readClaudeModelSettings(state.Binding); settings == nil || claudeSettingsHash(settings) != intent.SettingsHash {
		return ClaudeModelSelection{}, fmt.Errorf("SESSION_MODEL_SELECTION_UNCONFIRMED")
	}
	proof, proven := claudeSessionModelProof(state.Binding, intent.Anchor, []string{intent.Target.Display, intent.Target.NativeID})
	if !proven {
		appendix := claudeModelAppend(state.Binding, intent.Anchor)
		command, unchanged := claudeUnchangedModelProof(appendix, state.Binding, state.configuredModel())
		if !unchanged {
			return ClaudeModelSelection{}, fmt.Errorf("SESSION_MODEL_SELECTION_UNCONFIRMED")
		}
		digest := sha256.Sum256(appendix)
		rejection := claudeModelRejection{Spec: spec, CommandID: command, SourceDigest: hex.EncodeToString(digest[:])}
		if err := writeJSON(rejectionPath, rejection); err != nil {
			return ClaudeModelSelection{}, err
		}
		return ClaudeModelSelection{}, clearUnchangedModelSelection(statePath, state, spec)
	}
	if err = ctx.Err(); err != nil {
		return ClaudeModelSelection{}, err
	}
	prior = ClaudeModelSelection{ModelSelectionSpec: spec, SessionID: binding.ID, ProviderID: state.Binding.ProviderID, Proof: proof, SelectedMS: time.Now().UnixMilli(), NativeID: intent.Target.NativeID}
	state.SelectedModel, state.ModelSelection = &prior, nil
	if err = writeJSON(statePath, state); err != nil {
		return ClaudeModelSelection{}, err
	}
	return prior, writeJSON(receiptPath, prior)
}

func clearUnchangedModelSelection(path string, state sessionLifecycle, spec ModelSelectionSpec) error {
	if state.ModelSelection != nil && state.ModelSelection.Spec == spec {
		state.ModelSelection = nil
		if err := writeJSON(path, state); err != nil {
			return err
		}
	}
	return claudePickerTargetUnconfirmed
}

func waitForClaudeModelProof(ctx context.Context, binding SessionBinding, intent claudeModelSelection) {
	tick := time.NewTicker(80 * time.Millisecond)
	defer tick.Stop()
	for {
		if _, ok := claudeSessionModelProof(binding, intent.Anchor, []string{intent.Target.Display, intent.Target.NativeID}); ok && sessionProcessesStopped(binding) {
			return
		}
		select {
		case <-ctx.Done():
			return
		case <-tick.C:
		}
	}
}

func claudeModelSelectionReady(pane SessionBinding, state sessionLifecycle) bool {
	binding := state.Binding
	return state.Executor == "claude" && state.State == "idle" && state.CompletedKey != "" && state.LaunchKey == "" &&
		state.ProviderConflict == nil && state.UnknownReason == "" && !state.EndedIdle && len(state.Tools) == 0 &&
		pane.resourceID() == binding.resourceID() && pane.PID == binding.PID && pane.Directory == binding.Directory &&
		pane.HostProof == binding.HostProof && pane.DirectoryProof == binding.DirectoryProof && claudeCapabilityProcess(binding) &&
		binding.ProviderHomeProof != "" && binding.ProviderHomeProof == sessionDirectoryProof(binding.ProviderHome) && sessionProcessesStopped(binding)
}

func readClaudeModelSettings(binding SessionBinding) []byte {
	file, err := fsguard.OpenReadNoFollow(filepath.Join(binding.ProviderHome, "settings.json"))
	if err != nil {
		return nil
	}
	defer file.Close()
	const limit = 1 << 20
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() || !fsguard.OwnedByCurrentUser(info) || info.Mode().Perm()&0022 != 0 || info.Size() > limit {
		return nil
	}
	data, err := io.ReadAll(io.LimitReader(file, limit+1))
	if err != nil || int64(len(data)) != info.Size() {
		return nil
	}
	if after, err := os.Lstat(file.Name()); err != nil || !sameClaudeInputFile(info, after) {
		return nil
	}
	return data
}

func claudeSettingsHash(data []byte) string {
	digest := sha256.Sum256(data)
	return hex.EncodeToString(digest[:])
}
