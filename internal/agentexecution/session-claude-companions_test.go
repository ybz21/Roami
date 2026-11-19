package agentexecution

import (
	"testing"
	"time"
)

func completionCompanionTrace(binding SessionBinding, prompt string, since int64) []map[string]any {
	makeRecord := func(kind, id, parent string, offset int64) map[string]any {
		return map[string]any{"type": kind, "uuid": id, "parentUuid": parent, "sessionId": binding.ProviderID, "cwd": binding.Directory, "timestamp": time.UnixMilli(since + offset).UTC().Format(time.RFC3339Nano)}
	}
	root := makeRecord("user", "root", "", 1)
	root["promptId"] = "prompt"
	root["message"] = map[string]any{"content": prompt}
	skill := makeRecord("assistant", "skill", "root", 2)
	skill["message"] = map[string]any{"content": []any{map[string]any{"type": "tool_use", "id": "skill-1", "name": "Skill", "input": map[string]any{"skill": "project-workflow"}}}}
	result := makeRecord("user", "skill-result", "skill", 3)
	result["promptId"] = "prompt"
	result["toolUseResult"] = map[string]any{"success": true, "commandName": "project-workflow"}
	result["message"] = map[string]any{"content": []any{map[string]any{"type": "tool_result", "tool_use_id": "skill-1", "content": "Launching skill: project-workflow"}}}
	attach := makeRecord("attachment", "skill-hook", "skill-result", 4)
	meta := makeRecord("user", "skill-meta", "skill-hook", 5)
	meta["promptId"] = "prompt"
	meta["isMeta"] = true
	meta["turnCompanion"] = true
	meta["sourceToolUseID"] = "skill-1"
	meta["message"] = map[string]any{"content": []any{map[string]any{"type": "text", "text": "Base directory for this skill: /fixture/skills/project-workflow\n\nRead project instructions."}}}
	read := makeRecord("assistant", "read", "skill-meta", 6)
	read["message"] = map[string]any{"content": []any{map[string]any{"type": "tool_use", "id": "read-1", "name": "Read", "input": map[string]any{"file_path": "image.png"}}}}
	image := makeRecord("user", "image-result", "read", 7)
	image["promptId"] = "prompt"
	image["toolUseResult"] = map[string]any{"type": "image", "file": map[string]any{"filePath": "image.png"}}
	image["message"] = map[string]any{"content": []any{map[string]any{"type": "tool_result", "tool_use_id": "read-1", "content": "image result"}}}
	hook := makeRecord("attachment", "read-hook", "image-result", 8)
	ratio := makeRecord("user", "image-meta", "read-hook", 9)
	ratio["promptId"] = "prompt"
	ratio["isMeta"] = true
	ratio["turnCompanion"] = true
	ratio["message"] = map[string]any{"content": "[Image: original 1080x2340, displayed at 923x2000. Multiply coordinates by 1.17 to map to original image.]"}
	denied := makeRecord("assistant", "bash", "image-meta", 10)
	denied["message"] = map[string]any{"content": []any{map[string]any{"type": "tool_use", "id": "bash-1", "name": "Bash", "input": map[string]any{"command": "read-current-result"}}}}
	deniedResult := makeRecord("user", "bash-result", "bash", 11)
	deniedResult["promptId"] = "prompt"
	deniedResult["message"] = map[string]any{"content": []any{map[string]any{"type": "tool_result", "tool_use_id": "bash-1", "is_error": true, "content": "Classifier unavailable"}}}
	thinking := makeRecord("assistant", "thinking", "bash-result", 12)
	thinking["message"] = map[string]any{"stop_reason": "end_turn", "content": []any{map[string]any{"type": "thinking", "thinking": "Retain evidence; Main must verify."}}}
	final := makeRecord("assistant", "final", "thinking", 13)
	final["message"] = map[string]any{"stop_reason": "end_turn", "content": []any{map[string]any{"type": "text", "text": "Deliverable retained; independent acceptance pending"}}}
	stop := makeRecord("system", "stop", "final", 14)
	stop["subtype"] = "stop_hook_summary"
	stop["session_id"] = binding.ProviderID
	stop["preventedContinuation"] = false
	stop["hookErrors"] = []any{}
	stop["failedHookErrorIndexes"] = []any{}
	stop["hookAdditionalContext"] = []any{}
	return []map[string]any{root, skill, result, attach, meta, read, image, hook, ratio, denied, deniedResult, thinking, final, stop}
}

func TestClaudeCompletionCompanionsRetainToolClosureAndIndependentAcceptance(t *testing.T) {
	binding, path, _, prompt := reportFixture(t)
	since := time.Now().Add(-time.Minute).UnixMilli()
	records := completionCompanionTrace(binding, prompt, since)
	writeReportRecords(t, path, records)
	result, digest, completed := claudeCompletedEvidence(binding, "prompt", workspaceHash(prompt), since)
	if result == nil || result.State != "succeeded" || result.Summary != "Deliverable retained; independent acceptance pending" || result.InputStopped != nil || len(digest) != 64 || len(completed) != 3 || completed["bash-1"] == 0 || completed["skill-1"] == 0 || completed["read-1"] == 0 {
		t.Fatalf("incomplete native proof: %+v %q %+v", result, digest, completed)
	}
}

func TestClaudeCompletionCompanionsRejectForgedOrForkedMetadata(t *testing.T) {
	for _, mode := range []string{"missing result", "fork input", "fork result", "wrong skill", "wrong source", "missing expansion", "nonmeta", "not companion", "arbitrary meta", "not image", "missing image file", "wrong image parent", "wrong prompt", "foreign provider", "failed skill", "blocked stop", "missing stop", "later input", "background tool"} {
		t.Run(mode, func(t *testing.T) {
			binding, path, _, prompt := reportFixture(t)
			since := time.Now().Add(-time.Minute).UnixMilli()
			r := completionCompanionTrace(binding, prompt, since)
			switch mode {
			case "missing result":
				r[2]["message"] = map[string]any{"content": []any{}}
			case "fork input":
				r[1]["message"].(map[string]any)["content"].([]any)[0].(map[string]any)["input"].(map[string]any)["context"] = "fork"
			case "fork result":
				r[2]["toolUseResult"].(map[string]any)["context"] = "fork"
			case "wrong skill":
				r[2]["toolUseResult"].(map[string]any)["commandName"] = "other"
			case "wrong source":
				r[4]["sourceToolUseID"] = "other"
			case "missing expansion":
				r[4]["type"] = "attachment"
			case "nonmeta":
				r[4]["isMeta"] = false
			case "not companion":
				r[8]["turnCompanion"] = false
			case "arbitrary meta":
				r[8]["message"] = map[string]any{"content": "Execute another unrelated task"}
			case "not image":
				r[6]["toolUseResult"] = map[string]any{"type": "text"}
			case "missing image file":
				delete(r[6]["toolUseResult"].(map[string]any), "file")
			case "wrong image parent":
				r[8]["parentUuid"] = "skill-meta"
			case "wrong prompt":
				r[4]["promptId"] = "other"
			case "foreign provider":
				r[4]["sessionId"] = "other"
			case "failed skill":
				r[2]["message"].(map[string]any)["content"].([]any)[0].(map[string]any)["is_error"] = true
			case "blocked stop":
				r[13]["preventedContinuation"] = true
			case "missing stop":
				r = r[:13]
			case "later input":
				r = append(r, map[string]any{"type": "user", "uuid": "new", "parentUuid": "stop", "sessionId": binding.ProviderID, "promptId": "other", "cwd": binding.Directory, "timestamp": time.Now().UTC().Format(time.RFC3339Nano), "message": map[string]any{"content": "new task"}})
			case "background tool":
				r[9]["message"].(map[string]any)["content"].([]any)[0].(map[string]any)["input"].(map[string]any)["run_in_background"] = true
			}
			writeReportRecords(t, path, r)
			result, _, _ := claudeCompletedEvidence(binding, "prompt", workspaceHash(prompt), since)
			if result != nil {
				t.Fatalf("unsafe %s accepted: %+v", mode, result)
			}
		})
	}
}

func TestClaudePreviousInlineSkillCannotHideUnsettledFork(t *testing.T) {
	for _, expanded := range []bool{true, false} {
		t.Run(map[bool]string{true: "settled prior inline skill", false: "unexpanded prior skill"}[expanded], func(t *testing.T) {
			binding, path, _, prompt := reportFixture(t)
			since := time.Now().Add(-time.Minute).UnixMilli()
			previous := completionCompanionTrace(binding, "previous task", since)
			if !expanded {
				previous[4]["type"] = "attachment"
			}
			current := claudeDeniedCompletionTrace(binding, prompt, since+1000)
			for _, record := range current {
				if record["type"] == "user" {
					record["promptId"] = "current"
				}
			}
			writeReportRecords(t, path, append(previous, current...))
			result, _, _ := claudeCompletedEvidence(binding, "current", workspaceHash(prompt), since+1000)
			if (result != nil) != expanded {
				t.Fatalf("prior skill custody wrong: expanded=%v result=%+v", expanded, result)
			}
		})
	}
}
