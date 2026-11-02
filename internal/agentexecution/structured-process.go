package agentexecution

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/google/uuid"
	"github.com/ybz21/Roami/internal/agent"
	"github.com/ybz21/Roami/internal/gitcontext"
)

func structuredArgs(spec Spec, provider string) []string {
	var args []string
	if spec.Executor == "opencode" {
		args = agent.Get("opencode").OneShotArgs(agent.StartOpts{Model: spec.Model, Permission: spec.Permission})
		args = append(args, "--standalone", "--format", "json")
		if provider != "" {
			args = append(args, "--session", provider)
		}
		return args
	}
	args = []string{"--print", "--mode", "json", "--session-id", provider}
	if spec.Model != "" {
		args = append(args, "--model", spec.Model)
	}
	return append(args, "--", spec.Prompt)
}

func (s Service) structuredProcess(ctx context.Context, dir string, spec Spec, receipt Receipt, provider string, stdout, stderr io.Writer) (Result, string) {
	result := Result{State: "failed", ExitCode: -1, Summary: "EXECUTOR_START_FAILED"}
	if provider == "" && spec.Executor == "pi" {
		provider = uuid.NewString()
	}
	parsed := newStructuredOutput(spec.Executor, provider)
	output, diagnostics := &tail{limit: 32000}, &tail{limit: 8000}
	bin, err := agent.ResolveBinary(spec.Executor)
	if err != nil {
		result.Summary = "EXECUTOR_BINARY_UNAVAILABLE"
		result.FinishedMS = time.Now().UnixMilli()
		return result, provider
	}
	runCtx, cancel := executionContext(ctx, receipt.DeadlineMS)
	defer cancel()
	cmd := exec.CommandContext(runCtx, bin, structuredArgs(spec, provider)...)
	cmd.Dir = receipt.Workspace.Directory
	cmd.Env = gitcontext.ForDirectory(os.Environ())
	if spec.Executor == "opencode" {
		cmd.Stdin = strings.NewReader(spec.Prompt)
	}
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		if cmd.Process == nil {
			return nil
		}
		return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
	cmd.WaitDelay = 2 * time.Second
	// Keep structured evidence separate from the human handoff.
	cmd.Stdout = io.MultiWriter(stdout, output, parsed)
	cmd.Stderr = io.MultiWriter(stderr, diagnostics)
	done := make(chan struct{})
	go func() {
		ticker := time.NewTicker(100 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-done:
				return
			case <-runCtx.Done():
				return
			case <-ticker.C:
				if _, e := os.Stat(filepath.Join(dir, "cancel.json")); e == nil {
					cancel()
					return
				}
			}
		}
	}()
	if _, e := os.Stat(filepath.Join(dir, "cancel.json")); e == nil {
		cancel()
	}
	started := time.Now().UnixMilli()
	err = cmd.Run()
	close(done)
	if cmd.Process != nil {
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
	parsed.finish()
	result.Stderr = diagnostics.String()
	result.Output = output.String()
	result.FinishedMS = time.Now().UnixMilli()
	result.Summary = strings.TrimSpace(parsed.text.String())
	if err == nil && spec.Executor == "opencode" && !parsed.invalid && !parsed.failed && parsed.provider != "" {
		var answer string
		answer, err = exportOpenCodeResult(runCtx, bin, parsed.provider, cmd.Dir, spec.Prompt, started)
		if err == nil {
			result.Summary = answer
			parsed.complete = true
		}
	} else if err == nil {
		err = parsed.validate()
	}
	if err == nil {
		result.State = "succeeded"
		result.ExitCode = 0
	} else {
		if exit, ok := err.(*exec.ExitError); ok {
			result.ExitCode = exit.ExitCode()
		}
		if result.Summary == "" {
			result.Summary = "EXECUTOR_FAILED"
		}
		if _, ok := err.(*exec.ExitError); !ok {
			result.Summary = err.Error()
		}
	}
	if runCtx.Err() != nil {
		result.State = "failed"
		result.Summary = "EXECUTION_DEADLINE_OR_INTERRUPTION"
		if _, e := os.Stat(filepath.Join(dir, "cancel.json")); e == nil {
			result.State = "cancelled"
			result.Summary = "Execution cancelled"
		}
	}
	if parsed.invalid {
		return result, ""
	}
	return result, parsed.provider
}

func (s Service) runStructuredOnce(ctx context.Context, dir string, spec Spec, stdout, stderr io.Writer) error {
	var receipt Receipt
	if err := readJSON(filepath.Join(dir, "receipt.json"), &receipt); err != nil {
		return err
	}
	if receipt.Workspace == nil {
		receipt.Workspace = &Workspace{Directory: spec.Directory}
	}
	lease, err := s.claimWorkspace(ctx, receipt.Workspace.Directory, spec.Key)
	if err != nil {
		return s.failPersistent(dir, err)
	}
	defer lease()
	result, _ := s.structuredProcess(ctx, dir, spec, receipt, "", stdout, stderr)
	return writeJSON(filepath.Join(dir, "result.json"), result)
}

func markStructuredStarted(dir string) error {
	f, err := os.OpenFile(filepath.Join(dir, "started"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return fmt.Errorf("EXECUTION_ALREADY_STARTED: %w", err)
	}
	defer f.Close()
	return f.Sync()
}
