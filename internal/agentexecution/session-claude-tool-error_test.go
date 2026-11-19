package agentexecution

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

const classifierFailure = "roami-claude/free is temporarily unavailable (timed out), so auto mode cannot determine the safety of Bash right now. Wait a moment and then try this action again. If it keeps failing, continue with other tasks that don't require this action and come back to it later."

func classifierRecords(binding SessionBinding, prompt string) []map[string]any {
	return []map[string]any{
		{"type": "user", "sessionId": binding.ProviderID, "promptId": "prompt", "cwd": binding.Directory, "message": map[string]any{"content": prompt}},
		{"type": "assistant", "sessionId": binding.ProviderID, "cwd": binding.Directory, "message": map[string]any{"stop_reason": "tool_use", "content": []any{map[string]any{"type": "tool_use", "id": "bash-1", "name": "Bash"}}}},
		{"type": "user", "sessionId": binding.ProviderID, "promptId": "prompt", "cwd": binding.Directory, "timestamp": "2026-11-19T04:57:48.936Z", "message": map[string]any{"content": []any{map[string]any{"type": "tool_result", "tool_use_id": "bash-1", "is_error": true, "content": classifierFailure}}}},
	}
}

func TestClaudeToolPreflightFailureIsBoundReportedEvidence(t *testing.T) {
	for _, wrapped := range []bool{false, true} {
		t.Run(fmt.Sprint(wrapped), func(t *testing.T) {
			binding, path, launch, prompt := reportFixture(t)
			records := classifierRecords(binding, prompt)
			if wrapped {
				records[0]["message"].(map[string]any)["content"] = "\n\n<pasted_content id=\"fixture\">\n" + prompt + "\n</pasted_content id=\"fixture\">\n"
			}
			writeReportRecords(t, path, records)
			progress, report := claudeReportedState(binding, "prompt", workspaceHash(prompt), launch)
			if progress != nil || report == nil || report.Code != "CLAUDE_AUTO_CLASSIFIER_UNAVAILABLE" || report.Tool != "Bash" || report.ToolUseID != "bash-1" || report.ProviderID != binding.ProviderID || report.PromptID != "prompt" || len(report.SourceDigest) != 64 || report.ObservedMS != 1795064268936 {
				t.Fatalf("missing bound diagnostic: %+v %+v", progress, report)
			}
			_, cached := claudeReportedState(binding, "prompt", workspaceHash(prompt), launch)
			if cached == nil || *cached != *report {
				t.Fatal("unstable diagnostic cache")
			}
			if _, err := os.Stat(launch + "/result.json"); !os.IsNotExist(err) {
				t.Fatal("diagnostic created an execution result")
			}
		})
	}
}

func TestClaudeToolPreflightRejectsAmbiguousOrUnboundEvidence(t *testing.T) {
	for _, mode := range []string{"wrong prompt", "changed paste", "foreign provider", "later user", "changed same prompt", "outside directory", "sidechain", "unknown tool", "wrong tool", "not error", "quoted text", "ordinary failure", "missing time", "malformed", "writable"} {
		t.Run(mode, func(t *testing.T) {
			binding, path, launch, prompt := reportFixture(t)
			records := classifierRecords(binding, prompt)
			block := records[2]["message"].(map[string]any)["content"].([]any)[0].(map[string]any)
			switch mode {
			case "wrong prompt":
				records[0]["promptId"] = "other"
			case "changed paste":
				records[0]["message"].(map[string]any)["content"] = "\n\n<pasted_content id=\"fixture\">\nchanged\n</pasted_content id=\"fixture\">\n"
			case "foreign provider":
				records[2]["sessionId"] = "foreign"
			case "later user":
				records = append(records, map[string]any{"type": "user", "sessionId": binding.ProviderID, "promptId": "new", "cwd": binding.Directory, "message": map[string]any{"content": "new request"}})
			case "changed same prompt":
				records = append(records, map[string]any{"type": "user", "sessionId": binding.ProviderID, "promptId": "prompt", "cwd": binding.Directory, "message": map[string]any{"content": "different user input"}})
			case "outside directory":
				records[2]["cwd"] = t.TempDir()
			case "sidechain":
				records[2]["isSidechain"] = true
			case "unknown tool":
				block["tool_use_id"] = "foreign"
			case "wrong tool":
				records[1]["message"].(map[string]any)["content"].([]any)[0].(map[string]any)["name"] = "Read"
			case "not error":
				block["is_error"] = false
			case "quoted text":
				records[2]["message"].(map[string]any)["content"] = []any{map[string]any{"type": "text", "text": classifierFailure}}
			case "ordinary failure":
				block["content"] = "Exit code 1: " + classifierFailure
			case "missing time":
				delete(records[2], "timestamp")
			}
			writeReportRecords(t, path, records)
			if mode == "malformed" {
				if err := os.WriteFile(path, []byte("{"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			if mode == "writable" {
				if err := os.Chmod(path, 0666); err != nil {
					t.Fatal(err)
				}
			}
			_, report := claudeReportedState(binding, "prompt", workspaceHash(prompt), launch)
			if report != nil {
				t.Fatalf("unsafe %s: %+v", mode, report)
			}
		})
	}
}

func TestClaudeToolDiagnosticCacheDoesNotSurviveNewInput(t *testing.T) {
	binding, path, launch, prompt := reportFixture(t)
	records := classifierRecords(binding, prompt)
	writeReportRecords(t, path, records)
	_, first := claudeReportedState(binding, "prompt", workspaceHash(prompt), launch)
	if first == nil {
		t.Fatal("initial report missing")
	}
	records = append(records, map[string]any{"type": "user", "sessionId": binding.ProviderID, "promptId": "new", "cwd": binding.Directory, "message": map[string]any{"content": "new request"}})
	writeReportRecords(t, path, records)
	_, report := claudeReportedState(binding, "prompt", workspaceHash(prompt), launch)
	if report != nil {
		t.Fatal("diagnostic leaked into another input")
	}
}

func TestClaudeWrappedPromptRetainsReportedProgress(t *testing.T) {
	binding, path, launch, prompt := reportFixture(t)
	records := reportRecords(binding, prompt)
	records[0]["message"].(map[string]any)["content"] = "\n\n<pasted_content id=\"fixture\">\n" + prompt + "\n</pasted_content id=\"fixture\">\n"
	writeReportRecords(t, path, records)
	progress := claudeReportedProgress(binding, "prompt", workspaceHash(prompt), launch)
	if progress == nil || progress.PromptID != "prompt" {
		t.Fatal("paste wrapper discarded current report")
	}
}

func TestClaudeCurrentInputMayUseAProjectSubdirectory(t *testing.T) {
	binding, path, launch, prompt := reportFixture(t)
	records := classifierRecords(binding, prompt)
	for _, record := range records {
		record["cwd"] = filepath.Join(binding.Directory, "page")
	}
	writeReportRecords(t, path, records)
	_, report := claudeReportedState(binding, "prompt", workspaceHash(prompt), launch)
	if report == nil || report.Directory != filepath.Join(binding.Directory, "page") {
		t.Fatal("valid current-project subdirectory lost")
	}
}
