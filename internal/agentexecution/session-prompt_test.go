package agentexecution

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSessionPromptPreservesLegacyBinding(t *testing.T) {
	var spec Spec
	if err := json.Unmarshal([]byte(`{"prompt":"Read the existing results"}`), &spec); err != nil {
		t.Fatal(err)
	}
	want := "Roami delegated task [launch-id]. Complete this task in the current session and preserve unrelated work. Report evidence and remaining blockers in your final answer.\n\nRead the existing results"
	if got := sessionPrompt("/executions/launch-id", spec); got != want {
		t.Fatalf("persisted launch prompt changed: %q", got)
	}
}

func TestShortExecutionLabelPreservesPreviouslyRenderedPrompts(t *testing.T) {
	id := "3db62d1583bf5e0bc2b2b0d25ac4b4c9fb07a9280ebbe0fd4b0a9dfd1ed36c67"
	dir := filepath.Join(t.TempDir(), id)
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	if err := writeJSON(filepath.Join(dir, "receipt.json"), Receipt{Session: "actual-session", State: "running"}); err != nil {
		t.Fatal(err)
	}
	spec := Spec{PromptFormat: "markdown-session", Prompt: "# 任务：\n\nContinue"}
	want := spec.Prompt + "\n\n# 执行上下文\n\n当前会话（稳定 ID）：`actual-session`。会话操作使用此 ID；改名只改变展示名。\n\n执行标识：`" + id + "`。仅用于本次任务绑定，无需写入交付内容。"
	if got := sessionPrompt(dir, spec); got != want {
		t.Fatal("previously persisted markdown-session prompt changed")
	}
	spec.ShortExecutionLabel = true
	got := sessionPrompt(dir, spec)
	if !strings.Contains(got, "执行标识（短 ID）：`3db62d15`") || strings.Contains(got, id) || !strings.Contains(got, "当前会话（稳定 ID）：`actual-session`") {
		t.Fatalf("wrong short display label or session target: %s", got)
	}
}

func TestSessionPromptUsesActualSessionAcrossReceiptUpdates(t *testing.T) {
	for _, original := range []string{"", "original-session"} {
		t.Run("source-"+original, func(t *testing.T) {
			dir := t.TempDir()
			spec := Spec{PromptFormat: "markdown-session", Prompt: "# 任务：\n\nContinue", SessionID: original}
			receipt := Receipt{State: "submitting", Session: "actual-session"}
			if err := writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
				t.Fatal(err)
			}
			prompt := sessionPrompt(dir, spec)
			if !strings.HasPrefix(prompt, spec.Prompt) || !strings.Contains(prompt, "当前会话（稳定 ID）：`actual-session`") || strings.Contains(prompt, "original-session") {
				t.Fatalf("wrong current session: %s", prompt)
			}
			receipt.State, receipt.Binding = "running", &SessionBinding{ID: "actual-session", ProviderID: "provider"}
			if err := writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
				t.Fatal(err)
			}
			if got := sessionPrompt(dir, spec); got != prompt {
				t.Fatal("receipt updates changed the prompt binding")
			}
		})
	}
}

func TestSessionMarkdownPromptLeadsWithTaskAndKeepsUniqueBinding(t *testing.T) {
	spec := Spec{PromptFormat: "markdown", Prompt: "# 任务：\n\n调研 wowtype\n\n# 开工准备\n\n保留已有工作。"}
	got := sessionPrompt("/executions/launch-id", spec)
	if !strings.HasPrefix(got, spec.Prompt+"\n\n# 执行上下文\n\n") || !strings.Contains(got, "`launch-id`") {
		t.Fatalf("task must come before execution identity: %q", got)
	}
	if workspaceHash(got) == workspaceHash(sessionPrompt("/executions/another-launch", spec)) {
		t.Fatal("identical tasks must retain distinct execution bindings")
	}
}
