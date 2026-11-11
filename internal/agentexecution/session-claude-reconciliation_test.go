package agentexecution

import (
	"context"
	"os/exec"
	"testing"
	"time"
)

func claudeChangedFailureRecords(binding SessionBinding, prompt, turn string, modelCommand bool) []map[string]any {
	records := claudeFailureRecords(binding, prompt, turn)
	stamp, _ := time.Parse(time.RFC3339Nano, records[2]["timestamp"].(string))
	if modelCommand {
		parent := "first-end"
		for i, text := range []string{"<local-command-caveat>Local CLI command context</local-command-caveat>", "<command-name>/model</command-name>\n<command-message>model</command-message>\n<command-args></command-args>", "<local-command-stdout>Model unchanged</local-command-stdout>"} {
			uuid := []string{"model-caveat", "model-command", "model-output"}[i]
			records = append(records, map[string]any{"type": "user", "uuid": uuid, "parentUuid": parent, "sessionId": binding.ProviderID, "promptId": "model-selection", "cwd": binding.Directory, "timestamp": stamp.Add(time.Duration(i+1) * time.Millisecond).Format(time.RFC3339Nano), "isMeta": i == 0, "message": map[string]any{"content": text}})
			parent = uuid
		}
	}
	next := claudeFailureRecords(binding, "Continue", "followup")
	next[0]["uuid"] = "next-user"
	next[1]["uuid"] = "next-error"
	next[2]["parentUuid"] = "next-error"
	for i := range next {
		next[i]["timestamp"] = stamp.Add(time.Duration(i+5) * time.Millisecond).Format(time.RFC3339Nano)
	}
	return append(records, next...)
}

func TestClaudeChangedInputRequiresExplicitRejectedWindowProof(t *testing.T) {
	for _, modelCommand := range []bool{false, true} {
		t.Run(map[bool]string{false: "continue", true: "model then continue"}[modelCommand], func(t *testing.T) {
			binding, path, _, prompt := reportFixture(t)
			records := claudeChangedFailureRecords(binding, prompt, "prompt", modelCommand)
			records = append(records[:3], append([]map[string]any{{"type": "file-history-snapshot"}}, records[3:]...)...)
			writeReportRecords(t, path, records)
			if result, _ := claudeRejectedResponse(binding, "prompt", workspaceHash(prompt)); result != nil {
				t.Fatal("automatic status accepted changed input")
			}
			if result, digest := claudeRejectedWindow(binding, "prompt", workspaceHash(prompt), true); result == nil || len(digest) != 64 {
				t.Fatal("complete rejected window not proved")
			}
		})
	}
}

func TestClaudeChangedInputRejectsIncompleteOrUncertainWindow(t *testing.T) {
	for _, mode := range []string{"no changed input", "no end", "pending request", "normal assistant", "tool block", "server error", "wrong provider", "sidechain", "wrong model command", "wrong model parent", "wrong model prompt", "missing model caveat", "incomplete model command", "later user"} {
		t.Run(mode, func(t *testing.T) {
			binding, path, _, prompt := reportFixture(t)
			records := claudeChangedFailureRecords(binding, prompt, "prompt", true)
			switch mode {
			case "no changed input":
				records = records[:3]
			case "no end":
				records = records[:len(records)-1]
			case "pending request":
				records = append(records[:6], records[6], map[string]any{"type": "api-request"})
			case "normal assistant":
				records[7]["message"].(map[string]any)["model"] = "real-model"
			case "tool block":
				records[7]["message"].(map[string]any)["content"] = []any{map[string]any{"type": "tool_use"}}
			case "server error":
				records[7]["apiErrorStatus"] = 500
			case "wrong provider":
				records[6]["sessionId"] = "foreign"
			case "sidechain":
				records[6]["isSidechain"] = true
			case "wrong model command":
				records[4]["message"].(map[string]any)["content"] = "<command-name>/clear</command-name>"
			case "wrong model parent":
				records[4]["parentUuid"] = "foreign"
			case "wrong model prompt":
				records[5]["promptId"] = "foreign"
			case "missing model caveat":
				records[3]["isMeta"] = false
			case "incomplete model command":
				records = records[:5]
			case "later user":
				records = append(records, map[string]any{"type": "user", "promptId": "later", "uuid": "later-user", "message": map[string]any{"content": "A separate request"}})
			}
			writeReportRecords(t, path, records)
			if result, _ := claudeRejectedWindow(binding, "prompt", workspaceHash(prompt), true); result != nil {
				t.Fatalf("%s accepted", mode)
			}
		})
	}
}

func TestClaudeExplicitReconciliationPreservesOriginalSession(t *testing.T) {
	s, binding, spec, path, _ := rejectedClaudeTask(t)
	dir, _ := s.directory(spec.Key)
	event := claudeEvent("UserPromptSubmit", "followup")
	event.ProviderID = reportProviderID
	event.Prompt = "Continue"
	if err := s.applySessionEvent("claude", binding, event); err != nil {
		t.Fatal(err)
	}
	records := claudeChangedFailureRecords(binding, sessionPrompt(dir, spec), "prompt", true)
	writeReportRecords(t, path, records)
	before, err := s.Status(spec.Key)
	if err != nil || before.State != "unknown" || before.Result != nil {
		t.Fatalf("changed input settled automatically: %+v %v", before, err)
	}
	status, err := s.ReconcileSession(context.Background(), spec.Key)
	if err != nil || status.State != "failed" || status.Result == nil || status.Result.Summary != "SESSION_SCOPE_CHANGED_STOPPED" || status.Result.InputStopped == nil || !*status.Result.InputStopped || status.Result.OutcomeKnown == nil || !*status.Result.OutcomeKnown || len(status.Result.StopEvidence) != 64 || status.Binding.ProviderID != reportProviderID {
		t.Fatalf("reconcile %+v %v", status, err)
	}
	again, err := s.ReconcileSession(context.Background(), spec.Key)
	if err != nil || again.Result.FinishedMS != status.Result.FinishedMS {
		t.Fatal("repeated reconcile changed receipt")
	}
	spec.Key = "claude-recovered"
	spec.Prompt = "Read current evidence"
	next, err := s.Launch(context.Background(), spec)
	if err != nil || next.Session != binding.ID || next.Binding.ProviderID != reportProviderID {
		t.Fatalf("original provider not reusable: %+v %v", next, err)
	}
}

func TestClaudeExplicitReconciliationRejectsLiveProcess(t *testing.T) {
	s, binding, spec, path, _ := rejectedClaudeTask(t)
	dir, _ := s.directory(spec.Key)
	event := claudeEvent("UserPromptSubmit", "followup")
	event.ProviderID = reportProviderID
	event.Prompt = "Continue"
	if err := s.applySessionEvent("claude", binding, event); err != nil {
		t.Fatal(err)
	}
	writeReportRecords(t, path, claudeChangedFailureRecords(binding, sessionPrompt(dir, spec), "prompt", false))
	process := exec.Command("sleep", "30")
	if err := process.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = process.Process.Kill(); _ = process.Wait() }()
	if status, err := s.ReconcileSession(context.Background(), spec.Key); err == nil || status.Result != nil {
		t.Fatalf("live work reconciled: %+v %v", status, err)
	}
}
