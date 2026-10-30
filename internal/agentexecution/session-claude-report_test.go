package agentexecution

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

const reportProviderID = "92fde746-24a1-4990-a8f8-f5f786fddbdd"

func reportFixture(t *testing.T) (SessionBinding, string, string, string) {
	t.Helper()
	root := t.TempDir()
	t.Setenv("CLAUDE_CONFIG_DIR", root)
	directory := filepath.Join(root, "workspace")
	if err := os.MkdirAll(filepath.Join(directory, "page"), 0700); err != nil {
		t.Fatal(err)
	}
	projects := filepath.Join(root, "projects", "workspace")
	if err := os.MkdirAll(projects, 0700); err != nil {
		t.Fatal(err)
	}
	launch := filepath.Join(root, "launch")
	if err := os.Mkdir(launch, 0700); err != nil {
		t.Fatal(err)
	}
	return SessionBinding{ProviderID: reportProviderID, Directory: directory}, filepath.Join(projects, reportProviderID+".jsonl"), launch, "Create a research page with retained files"
}

func writeReportRecords(t *testing.T, path string, records []map[string]any) {
	t.Helper()
	file, err := os.OpenFile(path, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	for _, record := range records {
		if err = json.NewEncoder(file).Encode(record); err != nil {
			t.Fatal(err)
		}
	}
}

func reportRecords(binding SessionBinding, prompt string) []map[string]any {
	return []map[string]any{
		{"type": "user", "sessionId": binding.ProviderID, "promptId": "prompt", "cwd": binding.Directory, "message": map[string]any{"content": prompt}},
		{"type": "assistant", "sessionId": binding.ProviderID, "cwd": filepath.Join(binding.Directory, "page"), "message": map[string]any{"stop_reason": "end_turn", "content": []any{map[string]string{"type": "thinking", "thinking": "must not become a report"}, map[string]string{"type": "text", "text": "[Page](index.html) and `shot.png`"}}}},
	}
}

func TestClaudeReportedFilesRemainProgressWithoutCompletionEvidence(t *testing.T) {
	binding, path, launch, prompt := reportFixture(t)
	records := reportRecords(binding, prompt)
	records = append(records, map[string]any{"type": "user", "sessionId": binding.ProviderID, "promptId": "prompt", "isCompactSummary": true, "message": map[string]string{"content": "internal compacted history"}})
	writeReportRecords(t, path, records)
	progress := claudeReportedProgress(binding, "prompt", workspaceHash(prompt), launch)
	if progress == nil || progress.Summary != "[Page](index.html) and `shot.png`" || progress.Directory != filepath.Join(binding.Directory, "page") || progress.SourceDigest == "" {
		t.Fatalf("bound report missing: %+v", progress)
	}
	cached := claudeReportedProgress(binding, "prompt", workspaceHash(prompt), launch)
	if cached == nil || *cached != *progress {
		t.Fatal("stable transcript progress was not retained")
	}
	if _, err := os.Stat(filepath.Join(launch, "result.json")); !os.IsNotExist(err) {
		t.Fatal("report created completion evidence")
	}
}

func TestClaudeReportedProgressRejectsForeignOrAmbiguousEvidence(t *testing.T) {
	for _, mode := range []string{"foreign provider", "wrong prompt", "later user", "outside directory", "sidechain", "no final response", "malformed", "writable transcript"} {
		t.Run(mode, func(t *testing.T) {
			binding, path, launch, prompt := reportFixture(t)
			records := reportRecords(binding, prompt)
			switch mode {
			case "foreign provider":
				records[1]["sessionId"] = "another-provider"
			case "wrong prompt":
				records[0]["promptId"] = "other"
			case "later user":
				records = append(records, map[string]any{"type": "user", "sessionId": binding.ProviderID, "promptId": "new", "message": map[string]string{"content": "A separate request"}})
			case "outside directory":
				records[1]["cwd"] = t.TempDir()
			case "sidechain":
				records[1]["isSidechain"] = true
			case "no final response":
				records[1]["message"].(map[string]any)["stop_reason"] = "tool_use"
			}
			writeReportRecords(t, path, records)
			if mode == "malformed" {
				if err := os.WriteFile(path, []byte("{"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			if mode == "writable transcript" {
				if err := os.Chmod(path, 0666); err != nil {
					t.Fatal(err)
				}
			}
			if got := claudeReportedProgress(binding, "prompt", workspaceHash(prompt), launch); got != nil {
				t.Fatalf("unsafe report: %+v", got)
			}
		})
	}
}

func TestClaudeReportCacheIsInvalidatedByNewUserInput(t *testing.T) {
	binding, path, launch, prompt := reportFixture(t)
	records := reportRecords(binding, prompt)
	writeReportRecords(t, path, records)
	if claudeReportedProgress(binding, "prompt", workspaceHash(prompt), launch) == nil {
		t.Fatal("initial report missing")
	}
	records = append(records, map[string]any{"type": "user", "sessionId": binding.ProviderID, "promptId": "new", "message": map[string]string{"content": "Independent work"}})
	writeReportRecords(t, path, records)
	if claudeReportedProgress(binding, "prompt", workspaceHash(prompt), launch) != nil {
		t.Fatal("cached report leaked into a later user request")
	}
}
