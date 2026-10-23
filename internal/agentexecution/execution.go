// Package agentexecution runs registry-backed coding tasks in observable tmux sessions.
package agentexecution

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/ybz21/Roami/internal/agent"
	"github.com/ybz21/Roami/internal/application"
	"github.com/ybz21/Roami/internal/gitcontext"
	sessmeta "github.com/ybz21/Roami/internal/sessionstore"
	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

type Spec struct {
	Persistent     bool   `json:"persistent,omitempty"`
	Key            string `json:"key"`
	Executor       string `json:"executor"`
	Directory      string `json:"directory,omitempty"`
	ProjectID      string `json:"projectId,omitempty"`
	WorkspaceID    string `json:"workspaceId,omitempty"`
	SessionID      string `json:"sessionId,omitempty"`
	Base           string `json:"base,omitempty"`
	Remote         string `json:"remote,omitempty"`
	Prompt         string `json:"prompt"`
	Model          string `json:"model,omitempty"`
	Permission     string `json:"permission,omitempty"`
	TimeoutSeconds int    `json:"timeoutSeconds"`
}

type Receipt struct {
	Session    string          `json:"session,omitempty"`
	State      string          `json:"state"`
	Workspace  *Workspace      `json:"workspace,omitempty"`
	DeadlineMS int64           `json:"deadlineMs,omitempty"`
	Binding    *SessionBinding `json:"sessionBinding,omitempty"`
}

type Result struct {
	InputStopped *bool  `json:"inputStopped,omitempty"`
	OutcomeKnown *bool  `json:"outcomeKnown,omitempty"`
	StopEvidence string `json:"stopEvidenceSha256,omitempty"`
	State        string `json:"state"`
	Summary      string `json:"summary"`
	ExitCode     int    `json:"exitCode"`
	Stderr       string `json:"stderr,omitempty"`
	Output       string `json:"output,omitempty"`
	FinishedMS   int64  `json:"finishedMs"`
}

type Status struct {
	Receipt
	Result *Result `json:"result,omitempty"`
}

type Service struct {
	Runtime    runtime.Runtime
	Executable string
}

func (s Service) directory(key string) (string, error) {
	if key == "" || len(key) > 300 {
		return "", fmt.Errorf("INVALID_LAUNCH_KEY")
	}
	hash := sha256.Sum256([]byte(key))
	return filepath.Join(s.Runtime.DataDir, "agents", "executions", hex.EncodeToString(hash[:])), nil
}

func lock(path string) (func(), error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err = syscall.Flock(int(f.Fd()), syscall.LOCK_EX); err != nil {
		f.Close()
		return nil, err
	}
	return func() { _ = syscall.Flock(int(f.Fd()), syscall.LOCK_UN); _ = f.Close() }, nil
}

func writeJSON(path string, value any) error {
	data, err := json.Marshal(value)
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".receipt-")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if err = f.Chmod(0600); err == nil {
		_, err = f.Write(data)
	}
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	if err = os.Rename(f.Name(), path); err != nil {
		return err
	}
	d, err := os.Open(filepath.Dir(path))
	if err != nil {
		return err
	}
	defer d.Close()
	return d.Sync()
}

func readJSON(path string, value any) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	return json.Unmarshal(data, value)
}

// Launch journals intent before starting tmux. An uncertain launch is reconciled, never replayed.
func (s Service) Launch(ctx context.Context, spec Spec) (Status, error) {
	if spec.SessionID != "" {
		return s.continueSession(ctx, spec)
	}
	dir, err := s.directory(spec.Key)
	if err != nil {
		return Status{}, err
	}
	if a := agent.Get(spec.Executor); a == nil || a.Kind() != spec.Executor {
		return Status{}, fmt.Errorf("INVALID_EXECUTOR")
	}
	invalidTarget := (spec.ProjectID == "" && !filepath.IsAbs(spec.Directory)) ||
		(spec.ProjectID != "" && spec.Directory != "") ||
		(spec.ProjectID == "" && (spec.Base != "" || spec.Remote != "" || spec.WorkspaceID != "")) ||
		(spec.WorkspaceID != "" && (spec.Base != "" || spec.Remote != ""))
	if invalidTarget || strings.TrimSpace(spec.Prompt) == "" || !validExecutionTimeout(spec.TimeoutSeconds) {
		return Status{}, fmt.Errorf("INVALID_EXECUTION_SPEC")
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
	if _, err = agent.ResolveBinary(spec.Executor); err != nil {
		return Status{}, err
	}
	if err = ctx.Err(); err != nil {
		return Status{}, err
	}
	if err = writeJSON(filepath.Join(dir, "spec.json"), spec); err != nil {
		return Status{}, err
	}
	receipt := Receipt{State: "preparing", DeadlineMS: executionDeadline(spec.TimeoutSeconds)}
	if err = writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
		return Status{}, err
	}
	hash := filepath.Base(dir)
	prepareCtx, cancel := executionContext(ctx, receipt.DeadlineMS)
	workspace, prepErr := s.prepareWorkspace(prepareCtx, spec, hash)
	cancel()
	if prepErr != nil {
		result := Result{State: "failed", Summary: preparationCode(prepErr), ExitCode: -1, FinishedMS: time.Now().UnixMilli()}
		if err = writeJSON(filepath.Join(dir, "result.json"), result); err != nil {
			return Status{}, err
		}
		return s.Status(spec.Key)
	}
	receipt.Workspace = &workspace
	receipt.State = "starting"
	if err = writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
		return Status{}, err
	}
	command := "exec " + quote(s.Executable) + " agent execution run --key " + quote(spec.Key)
	opt := runtime.CreateOpts{Label: spec.Executor + ": " + truncate(strings.Join(strings.Fields(spec.Prompt), " "), 60), Dir: workspace.Directory, Extra: []string{
		"-e", "ROAMI_HOME=" + s.Runtime.HomeDir, "-e", "ROAMI_DATA=" + s.Runtime.DataDir,
		"-e", "TMUX_BIN=" + s.Runtime.TmuxBin, "-e", "PATH=" + os.Getenv("PATH"),
		"-e", "ROAMI_AGENT_LAUNCH=" + hash, command,
	}}
	meta := sessmeta.New(s.Runtime.HomeDir)
	meta.DataDir = s.Runtime.DataDir
	created, err := application.NewSessions(s.Runtime, meta, nil).Create(ctx, opt, false)
	if err != nil {
		// tmux may have accepted the command even if its response was lost.
		return Status{}, fmt.Errorf("EXECUTION_LAUNCH_UNCERTAIN: %w", err)
	}
	_ = meta.SetAgentKind(created.Session, spec.Executor)
	if workspace.ProjectID != "" {
		s.bindWorkspace(ctx, created.Session, workspace)
	}
	receipt.Session, receipt.State = created.Session, "launched"
	if err = writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
		return Status{}, err
	}
	return s.Status(spec.Key)
}

func (s Service) Status(key string) (status Status, err error) {
	// A controller identity is not a confirmed native conversation binding.
	defer func() {
		if status.Binding != nil && status.Binding.ProviderID == "" {
			status.Binding = nil
		}
	}()
	dir, err := s.directory(key)
	if err != nil {
		return Status{}, err
	}
	if err = readJSON(filepath.Join(dir, "receipt.json"), &status.Receipt); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			if _, specErr := os.Stat(filepath.Join(dir, "spec.json")); errors.Is(specErr, os.ErrNotExist) {
				return Status{Receipt: Receipt{State: "not_started"}}, nil
			}
			return Status{Receipt: Receipt{State: "unknown"}}, nil
		}
		return status, err
	}
	var result Result
	if err = readJSON(filepath.Join(dir, "result.json"), &result); err == nil {
		status.State = result.State
		status.Result = &result
		return status, nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return status, err
	}
	if status.Binding != nil {
		return s.sessionExecutionStatus(key, status)
	}
	// Query success matters: a transport failure is not proof that an agent stopped.
	out, err := s.Runtime.TmuxOutput("list-sessions", "-F", "#{session_name}\t#{ROAMI_AGENT_LAUNCH}")
	if err != nil {
		// The runner can persist its result and exit while tmux is being queried.
		if resultErr := readJSON(filepath.Join(dir, "result.json"), &result); resultErr == nil {
			status.State, status.Result = result.State, &result
			return status, nil
		} else if !errors.Is(resultErr, os.ErrNotExist) {
			return status, resultErr
		}
		if !runtime.NoServer(out) {
			return status, fmt.Errorf("EXECUTION_OBSERVATION_FAILED: %w", err)
		}
	}
	for _, line := range strings.Split(out, "\n") {
		name, hash, ok := strings.Cut(line, "\t")
		if ok && hash == filepath.Base(dir) {
			status.Session = name
			status.State = "running"
			return status, nil
		}
	}
	status.State = "unknown"
	return status, nil
}

// Cancel asks only this execution's runner to stop; it never kills a reused session.
func (s Service) Cancel(key string) (Status, error) {
	status, err := s.Status(key)
	if err != nil || status.Result != nil {
		return status, err
	}
	if status.Binding != nil {
		dir, _ := s.directory(key)
		if err = writeJSON(filepath.Join(dir, "cancel.json"), map[string]bool{"cancel": true}); err != nil {
			return status, err
		}
		if status.State == "running" {
			status.State = "cancelling"
		}
		return status, nil
	}
	if status.State != "running" {
		return status, fmt.Errorf("EXECUTION_STATE_UNKNOWN")
	}
	dir, _ := s.directory(key)
	if err = writeJSON(filepath.Join(dir, "cancel.json"), map[string]bool{"cancel": true}); err != nil {
		return status, err
	}
	status.State = "cancelling"
	return status, nil
}

// Run is re-executed inside tmux and writes a durable terminal result before exiting.
func (s Service) Run(ctx context.Context, key string, stdout, stderr io.Writer) error {
	dir, err := s.directory(key)
	if err != nil {
		return err
	}
	// Wait for the creator to finish the session identity and metadata receipt.
	launchUnlock, err := lock(filepath.Join(dir, "launch.lock"))
	if err != nil {
		return err
	}
	launchUnlock()
	unlock, err := lock(filepath.Join(dir, "run.lock"))
	if err != nil {
		return err
	}
	defer unlock()
	var prior Result
	if err = readJSON(filepath.Join(dir, "result.json"), &prior); err == nil {
		return nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	// A second runner must not repeat writes after the first runner crashed.
	marker, err := os.OpenFile(filepath.Join(dir, "started"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return fmt.Errorf("EXECUTION_ALREADY_STARTED: %w", err)
	}
	if err = marker.Sync(); err != nil {
		marker.Close()
		return err
	}
	marker.Close()
	var spec Spec
	if err = readJSON(filepath.Join(dir, "spec.json"), &spec); err != nil {
		return err
	}
	if spec.SessionID != "" {
		return fmt.Errorf("SESSION_RUNNER_UNSUPPORTED")
	}
	if spec.Persistent {
		if structuredExecutor(spec.Executor) {
			return s.runStructuredSession(ctx, dir, spec, stdout, stderr)
		}
		return s.runPersistent(ctx, dir, spec)
	}
	if structuredExecutor(spec.Executor) {
		return s.runStructuredOnce(ctx, dir, spec, stdout, stderr)
	}
	a := agent.Get(spec.Executor)
	if a == nil {
		return fmt.Errorf("INVALID_EXECUTOR")
	}
	args := a.OneShotArgs(agent.StartOpts{Model: spec.Model, Permission: spec.Permission, MaxTurns: ""})
	if promptArg, ok := a.(interface{ OneShotPromptArg() bool }); ok && promptArg.OneShotPromptArg() {
		args = append(args, spec.Prompt)
	}
	var receipt Receipt
	if err = readJSON(filepath.Join(dir, "receipt.json"), &receipt); err != nil {
		return err
	}
	directory := spec.Directory
	if receipt.Workspace != nil {
		directory = receipt.Workspace.Directory
	}
	if spec.ProjectID != "" && (receipt.Workspace == nil || receipt.Workspace.ProjectID == "") {
		return fmt.Errorf("PROJECT_WORKSPACE_NOT_PREPARED")
	}
	workspaceUnlock, err := s.claimWorkspace(ctx, directory, key)
	if err != nil {
		return writeJSON(filepath.Join(dir, "result.json"), Result{State: "failed", Summary: workspaceLeaseCode(err), ExitCode: -1, FinishedMS: time.Now().UnixMilli()})
	}
	defer workspaceUnlock()
	deadline := receipt.DeadlineMS
	if deadline == 0 {
		deadline = executionDeadline(spec.TimeoutSeconds)
	}
	runCtx, cancel := executionContext(ctx, deadline)
	defer cancel()
	cmd := exec.CommandContext(runCtx, a.Bin(), args...)
	cmd.Dir = directory
	cmd.Env = gitcontext.ForDirectory(os.Environ())
	cmd.Stdin = strings.NewReader(spec.Prompt)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		if cmd.Process == nil {
			return nil
		}
		return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
	cmd.WaitDelay = 2 * time.Second
	output, diagnostics := &tail{limit: 32000}, &tail{limit: 8000}
	cmd.Stdout = io.MultiWriter(stdout, output)
	cmd.Stderr = io.MultiWriter(stderr, diagnostics)
	done := make(chan struct{})
	go func() {
		timer := time.NewTicker(100 * time.Millisecond)
		defer timer.Stop()
		for {
			select {
			case <-done:
				return
			case <-runCtx.Done():
				return
			case <-timer.C:
				if _, e := os.Stat(filepath.Join(dir, "cancel.json")); e == nil {
					cancel()
					return
				}
			}
		}
	}()
	err = cmd.Run()
	close(done)
	// Descendants may survive their original wrapper even after a clean exit.
	if cmd.Process != nil {
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
	result := Result{State: "succeeded", Summary: output.String(), Stderr: diagnostics.String(), ExitCode: 0, FinishedMS: time.Now().UnixMilli()}
	if err != nil {
		result.State = "failed"
		result.ExitCode = -1
		if exit, ok := err.(*exec.ExitError); ok {
			result.ExitCode = exit.ExitCode()
		}
		if result.Summary == "" {
			result.Summary = "EXECUTION_FAILED"
		}
	}
	if runCtx.Err() != nil {
		result.State = "failed"
		result.Output = output.String()
		result.Summary = "EXECUTION_DEADLINE_OR_INTERRUPTION"
		if _, e := os.Stat(filepath.Join(dir, "cancel.json")); e == nil {
			result.State = "cancelled"
			result.Summary = "Execution cancelled"
		}
	}
	return writeJSON(filepath.Join(dir, "result.json"), result)
}

type tail struct {
	mu    sync.Mutex
	data  []byte
	limit int
}

func (b *tail) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.data = append(b.data, p...)
	if len(b.data) > b.limit {
		b.data = bytes.Clone(b.data[len(b.data)-b.limit:])
	}
	return len(p), nil
}
func (b *tail) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return strings.ToValidUTF8(string(b.data), "�")
}
func quote(s string) string { return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'" }
func truncate(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		return string(r[:n])
	}
	return s
}

// Zero denotes no task-wide deadline; cancellation remains owned by the caller.
func validExecutionTimeout(seconds int) bool {
	return seconds >= 0 && int64(seconds) <= math.MaxInt64/int64(time.Second)
}

func executionDeadline(seconds int) int64 {
	if seconds == 0 {
		return 0
	}
	return time.Now().Add(time.Duration(seconds) * time.Second).UnixMilli()
}
func executionContext(ctx context.Context, deadline int64) (context.Context, context.CancelFunc) {
	if deadline == 0 {
		return context.WithCancel(ctx)
	}
	return context.WithDeadline(ctx, time.UnixMilli(deadline))
}
