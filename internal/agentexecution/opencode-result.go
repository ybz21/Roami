package agentexecution

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/ybz21/Roami/internal/gitcontext"
)

type boundedExport struct{ bytes.Buffer }

func (b *boundedExport) Write(p []byte) (int, error) {
	if b.Len()+len(p) > 16*1024*1024 {
		return 0, fmt.Errorf("EXECUTOR_TRANSCRIPT_TOO_LARGE")
	}
	return b.Buffer.Write(p)
}

// OpenCode 2 can omit step_finish; its exact-session export is the completion authority.
func readOpenCodeResult(data []byte, provider, directory, prompt string, started int64) (string, error) {
	var transcript struct {
		Info struct {
			ID       string `json:"id"`
			Outcome  string `json:"outcome"`
			Location struct {
				Directory string `json:"directory"`
			} `json:"location"`
		} `json:"info"`
		Messages []struct {
			Type    string          `json:"type"`
			Text    string          `json:"text"`
			Finish  string          `json:"finish"`
			Outcome string          `json:"outcome"`
			Error   json.RawMessage `json:"error"`
			Time    struct {
				Created   int64 `json:"created"`
				Completed int64 `json:"completed"`
			} `json:"time"`
			Content []struct {
				Type  string `json:"type"`
				Text  string `json:"text"`
				State struct {
					Status string `json:"status"`
				} `json:"state"`
			} `json:"content"`
		} `json:"messages"`
	}
	if json.Unmarshal(data, &transcript) != nil || transcript.Info.ID != provider || transcript.Info.Outcome != "succeeded" {
		return "", fmt.Errorf("EXECUTOR_COMPLETION_UNCONFIRMED")
	}
	actual, err := filepath.EvalSymlinks(transcript.Info.Location.Directory)
	expected, e := filepath.EvalSymlinks(directory)
	if err != nil || e != nil || actual != expected {
		return "", fmt.Errorf("SESSION_DIRECTORY_CHANGED")
	}
	user := -1
	for i, m := range transcript.Messages {
		if m.Type == "user" {
			user = i
		}
	}
	if user < 0 || transcript.Messages[user].Text != prompt || transcript.Messages[user].Time.Created < started {
		return "", fmt.Errorf("EXECUTOR_PROMPT_BINDING_UNCONFIRMED")
	}
	var answer string
	completed, idle := false, false
	for _, m := range transcript.Messages[user+1:] {
		if m.Type == "idle" {
			idle = m.Outcome == "succeeded"
			continue
		}
		if m.Type != "assistant" {
			continue
		}
		if len(m.Error) != 0 && string(m.Error) != "null" {
			return "", fmt.Errorf("EXECUTOR_REPORTED_FAILURE")
		}
		var text strings.Builder
		for _, part := range m.Content {
			if part.Type == "tool" && (part.State.Status == "running" || part.State.Status == "streaming") {
				return "", fmt.Errorf("EXECUTOR_COMPLETION_UNCONFIRMED")
			}
			if part.Type == "text" {
				text.WriteString(part.Text)
				text.WriteByte('\n')
			}
		}
		answer = strings.TrimSpace(text.String())
		completed = m.Time.Completed >= started && (m.Finish == "stop" || m.Finish == "end_turn")
	}
	if !idle || !completed || answer == "" {
		return "", fmt.Errorf("EXECUTOR_COMPLETION_UNCONFIRMED")
	}
	return truncate(answer, 32000), nil
}
func exportOpenCodeResult(ctx context.Context, bin, provider, directory, prompt string, started int64) (string, error) {
	readCtx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	cmd := exec.CommandContext(readCtx, bin, "session", "export", "--standalone", provider)
	cmd.Dir = directory
	cmd.Env = gitcontext.ForDirectory(os.Environ())
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		if cmd.Process == nil {
			return nil
		}
		return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
	cmd.WaitDelay = 2 * time.Second
	output := &boundedExport{}
	cmd.Stdout = output
	cmd.Stderr = &tail{limit: 8000}
	err := cmd.Run()
	if cmd.Process != nil {
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
	if err != nil {
		return "", fmt.Errorf("EXECUTOR_TRANSCRIPT_UNAVAILABLE")
	}
	return readOpenCodeResult(output.Bytes(), provider, directory, prompt, started)
}
