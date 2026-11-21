package agentexecution

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const claudeEvidenceCapability = "project_evidence_check"

func TestClaudeModelInputRetainsOnlyResultsInTheCapabilityRequest(t *testing.T) {
	binding := SessionBinding{ProviderID: "original-provider", Directory: t.TempDir()}
	records, callID, responseSHA := claudeReviewFixture(binding)
	parse := func() *ClaudeModelInputEvidence {
		var transcript bytes.Buffer
		enc := json.NewEncoder(&transcript)
		for _, record := range records {
			if err := enc.Encode(record); err != nil {
				t.Fatal(err)
			}
		}
		return claudeModelInput(&transcript, binding, "current-turn", workspaceHash("Read the frozen draft."), claudeEvidenceCapability, "approve")
	}
	evidence := parse()
	if evidence == nil || evidence.PromptID != "current-turn" || evidence.ProviderID != binding.ProviderID || evidence.RequestSHA256 != workspaceHash("request-review") ||
		len(evidence.Capabilities) != 1 || evidence.Capabilities[0] != (ClaudeInputRead{callID, responseSHA}) ||
		len(evidence.Images) != 1 || evidence.Images[0] != (ClaudeInputImage{"image/png", workspaceHash("frozen image")}) {
		t.Fatalf("unexpected input evidence: %+v", evidence)
	}

	// The image remains in the transcript, but the next request replaced its message.
	records[9]["tail"] = []string{workspaceHash("new message")}
	if evidence := parse(); evidence == nil || len(evidence.Capabilities) != 1 || len(evidence.Images) != 0 {
		t.Fatalf("dropped input was treated as visible: %+v", evidence)
	}
}

func TestClaudeModelInputRejectsUncertainReviewProvenance(t *testing.T) {
	for _, test := range []struct {
		name   string
		mutate func([]map[string]any) []map[string]any
	}{
		{"wrong provider", func(records []map[string]any) []map[string]any {
			records[9]["sessionId"] = "another-session"
			return records
		}},
		{"broken delta", func(records []map[string]any) []map[string]any {
			records[9]["keep"] = 8
			return records
		}},
		{"wrong review call", func(records []map[string]any) []map[string]any {
			command := records[10]["message"].(map[string]any)["content"].([]map[string]any)[0]["input"].(map[string]any)
			command["command"] = strings.Replace(command["command"].(string), "--call approve", "--call older", 1)
			return records
		}},
		{"another capability with the same request ID", func(records []map[string]any) []map[string]any {
			command := records[10]["message"].(map[string]any)["content"].([]map[string]any)[0]["input"].(map[string]any)
			command["command"] = strings.Replace(command["command"].(string), claudeEvidenceCapability, "other_capability", 1)
			return records
		}},
		{"unrelated review branch", func(records []map[string]any) []map[string]any {
			records[10]["parentUuid"] = "separate-conversation"
			return records
		}},
		{"turn moved on", func(records []map[string]any) []map[string]any {
			return append(records, map[string]any{"type": "user", "promptId": "next-turn", "message": map[string]any{"content": "Next request."}})
		}},
		{"native review already returned", func(records []map[string]any) []map[string]any {
			return append(records, map[string]any{"type": "user", "promptId": "current-turn", "sessionId": records[10]["sessionId"], "uuid": "returned", "parentUuid": "review", "message": map[string]any{"content": []map[string]any{{"type": "tool_result", "tool_use_id": "review-id", "content": "{}"}}}})
		}},
	} {
		t.Run(test.name, func(t *testing.T) {
			binding := SessionBinding{ProviderID: "original-provider", Directory: t.TempDir()}
			records, _, _ := claudeReviewFixture(binding)
			var transcript bytes.Buffer
			enc := json.NewEncoder(&transcript)
			for _, record := range test.mutate(records) {
				if err := enc.Encode(record); err != nil {
					t.Fatal(err)
				}
			}
			if evidence := claudeModelInput(&transcript, binding, "current-turn", workspaceHash("Read the frozen draft."), claudeEvidenceCapability, "approve"); evidence != nil {
				t.Fatalf("unproven request yielded evidence: %+v", evidence)
			}
		})
	}
}

func TestClaudeModelInputProvesParallelResultsAsOneProviderMessage(t *testing.T) {
	for _, test := range []struct {
		name   string
		order  []int
		proven bool
	}{
		{"recorded order", []int{0, 1, 2}, true},
		{"reordered", []int{1, 0, 2}, false},
		{"partial", []int{0, 1}, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			binding := SessionBinding{ProviderID: "original-provider", Directory: t.TempDir()}
			records, callID, _ := claudeReviewFixture(binding)
			body := records[4]["message"].(map[string]any)["content"].([]map[string]any)[0]
			image := records[7]["message"].(map[string]any)["content"].([]map[string]any)[0]
			other := map[string]any{"type": "tool_result", "tool_use_id": "untracked-id", "content": "Other tool output"}
			recorded := []map[string]any{body, image, other}
			var content []map[string]any
			for _, index := range test.order {
				content = append(content, recorded[index])
			}
			records[9]["base"] = "request-start"
			records[9]["keep"] = 2
			records[9]["tail"] = []string{claudeInputDigest(map[string]any{"role": "user", "content": content})}
			extra := map[string]any{
				"type": "user", "uuid": "other-result", "parentUuid": "image-result",
				"promptId": "current-turn", "sessionId": binding.ProviderID,
				"message": map[string]any{"content": []map[string]any{other}},
			}
			var raw bytes.Buffer
			enc := json.NewEncoder(&raw)
			for _, record := range append(records[:5:5], records[6], records[7], extra, records[9], records[10]) {
				if err := enc.Encode(record); err != nil {
					t.Fatal(err)
				}
			}
			got := claudeModelInput(&raw, binding, "current-turn", workspaceHash("Read the frozen draft."), claudeEvidenceCapability, "approve")
			if !test.proven {
				if got != nil {
					t.Fatalf("unmatched batch yielded evidence: %+v", got)
				}
				return
			}
			if got == nil || len(got.Capabilities) != 1 || got.Capabilities[0].ToolCallID != callID || len(got.Images) != 1 {
				t.Fatalf("parallel results were lost: %+v", got)
			}
		})
	}
}

func TestClaudeCapabilityInputUsesOnlyCurrentPreparedMain(t *testing.T) {
	service, fixture := sessionFixture(t)
	pane, err := service.paneBinding(fixture.ID, false)
	if err != nil {
		t.Fatal(err)
	}
	binding := pane
	binding.ProviderID = "29afdc4d-06db-4c6a-897c-3f761bec9cec"
	binding.ProviderHome = t.TempDir()
	binding.ProviderHomeProof = sessionDirectoryProof(binding.ProviderHome)
	processes, scope, _, err := paneProcessSnapshot(binding.PID)
	if err != nil {
		t.Fatal(err)
	}
	binding.Scope = scope
	binding.Processes = map[int]string{binding.PID: processes[binding.PID].Token}
	origin := Spec{Key: "prepared-main", Persistent: true, Executor: "claude", Model: "free"}
	spec := Spec{Key: "project-main:turn:prompt", Persistent: true, Executor: "claude", SessionID: binding.ID, PreparedFrom: origin.Key, Prompt: "Read the frozen draft."}
	workspace := &Workspace{ID: "workspace", Directory: binding.Directory}
	receipt := Receipt{Session: binding.ID, State: "running", Workspace: workspace, Binding: &binding}
	dir, _ := service.directory(spec.Key)
	originDir, _ := service.directory(origin.Key)
	for _, path := range []string{dir, originDir, filepath.Join(binding.ProviderHome, "projects", "workspace")} {
		if err := os.MkdirAll(path, 0700); err != nil {
			t.Fatal(err)
		}
	}
	statePath, err := service.lifecycleFile(binding)
	if err != nil {
		t.Fatal(err)
	}
	prompt := sessionPrompt(dir, spec)
	state := sessionLifecycle{
		State: "busy", Executor: "claude", Model: origin.Model, TurnID: "current-turn", PromptHash: workspaceHash(prompt), LaunchKey: spec.Key, Binding: binding,
	}
	stopped := true
	for path, data := range map[string]any{
		statePath: state, filepath.Join(dir, "spec.json"): spec, filepath.Join(dir, "receipt.json"): receipt,
		filepath.Join(originDir, "spec.json"): origin, filepath.Join(originDir, "receipt.json"): receipt,
		filepath.Join(originDir, "result.json"): Result{State: "succeeded", InputStopped: &stopped, OutcomeKnown: &stopped},
	} {
		if err := writeJSON(path, data); err != nil {
			t.Fatal(err)
		}
	}
	var transcript bytes.Buffer
	enc := json.NewEncoder(&transcript)
	records, _, _ := claudeReviewFixture(binding)
	records[1]["message"].(map[string]any)["content"] = prompt
	for _, record := range records {
		if err := enc.Encode(record); err != nil {
			t.Fatal(err)
		}
	}
	path := filepath.Join(binding.ProviderHome, "projects", "workspace", binding.ProviderID+".jsonl")
	if err := os.WriteFile(path, transcript.Bytes(), 0600); err != nil {
		t.Fatal(err)
	}
	evidence, err := service.ClaudeCapabilityInput(spec.Key, claudeEvidenceCapability, "approve")
	if err != nil || evidence == nil || len(evidence.Images) != 1 || len(evidence.Capabilities) != 1 {
		t.Fatalf("original active review unavailable: %+v %v", evidence, err)
	}
	if err := writeJSON(filepath.Join(dir, "result.json"), Result{State: "succeeded"}); err != nil {
		t.Fatal(err)
	}
	if evidence, err := service.ClaudeCapabilityInput(spec.Key, claudeEvidenceCapability, "approve"); err == nil || evidence != nil {
		t.Fatalf("settled turn still exposed input: %+v %v", evidence, err)
	}
}

func claudeReviewFixture(binding SessionBinding) ([]map[string]any, string, string) {
	readCall := "native-main-" + workspaceHash("current-turn:read-body")
	response := map[string]any{"data": map[string]any{
		"state": "succeeded", "result": map[string]any{"text": "当前冻结内容 <正文>."}, "requestId": "read-body",
		"toolCallId": readCall, "finishedMs": 12345,
	}}
	raw, _ := json.Marshal(response)
	body := []map[string]any{{"type": "tool_result", "tool_use_id": "read-body-id", "content": string(raw)}}
	image := []map[string]any{{"type": "tool_result", "tool_use_id": "read-image-id", "content": []map[string]any{
		{"type": "image", "source": map[string]any{"type": "base64", "media_type": "image/png", "data": "ZnJvemVuIGltYWdl"}},
	}}}
	message := func(kind, id, parent string, content any) map[string]any {
		return map[string]any{"type": kind, "uuid": id, "parentUuid": parent, "sessionId": binding.ProviderID,
			"cwd": binding.Directory, "promptId": "current-turn", "message": map[string]any{"content": content}}
	}
	call := func(name, id string, input map[string]any) []map[string]any {
		return []map[string]any{{"type": "tool_use", "id": id, "name": name, "input": input}}
	}
	result := func(id, parent string, content []map[string]any) map[string]any {
		record := message("user", id, parent, content)
		record["sourceToolAssistantUUID"] = parent
		return record
	}
	api := func(id, base string, keep int, tail ...string) map[string]any {
		return map[string]any{
			"type": "api-request", "id": id, "keep": keep, "tail": tail, "base": base, "querySource": "repl_main_thread",
			"sessionId": binding.ProviderID, "requestDigest": workspaceHash(id),
		}
	}
	msgSHA := func(content any) string { return claudeInputDigest(map[string]any{"role": "user", "content": content}) }
	return []map[string]any{
		api("history", "", 0, workspaceHash("older turn")),
		message("user", "prompt", "end-history", "Read the frozen draft."),
		api("request-start", "history", 1, workspaceHash("current prompt")),
		message("assistant", "body", "prompt", call("Bash", "read-body-id", nil)),
		result("body-result", "body", body),
		api("request-body", "request-start", 2, msgSHA(body)),
		message("assistant", "image", "body-result", call("Read", "read-image-id", nil)),
		result("image-result", "image", image),
		api("request-image", "request-body", 3, msgSHA(image)),
		api("request-review", "request-image", 3, msgSHA(image)),
		message("assistant", "review", "image-result", call("Bash", "review-id", map[string]any{
			"command": `"$ROAMI_BIN" agent capability call project_evidence_check --context "$ROAMI_MAIN_CONTEXT" --call approve --input '{}'`,
		})),
	}, readCall, claudeInputDigest(response)
}
