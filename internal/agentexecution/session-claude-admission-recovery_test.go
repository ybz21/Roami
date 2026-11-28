package agentexecution

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestClaudeRecoveryUsesBoundGatewayRefusalAndIdleCommandReceipts(t *testing.T) {
	for _, name := range []string{
		"exact", "exit", "unchanged model and exit", "saved same model and exit",
		"wrong receipt", "wrong finish", "wrong source digest", "wrong model", "partial exit",
		"foreign directory", "foreign provider", "new work", "no idle proof",
	} {
		t.Run(name, func(t *testing.T) {
			binding, path, launch, prompt := reportFixture(t)
			specPath := filepath.Join(launch, "spec.json")
			if err := os.WriteFile(specPath, []byte("{}\n"), 0600); err != nil {
				t.Fatal(err)
			}
			since := time.Now().Add(-time.Minute)
			if err := os.Chtimes(specPath, since, since); err != nil {
				t.Fatal(err)
			}
			state := sessionLifecycle{
				Binding: binding, EndedIdle: true, Model: "free", TurnID: "prompt", PromptHash: workspaceHash(prompt),
			}
			records := claudeFailureRecords(binding, prompt, state.TurnID)[:2]
			records[0]["uuid"], records[1]["parentUuid"] = "request", "request"
			records[1]["apiErrorType"], records[1]["error"] = "api_error", "unknown"
			records[1]["message"].(map[string]any)["content"] = []any{map[string]any{
				"type": "text", "text": "API Error: 400 MODEL_HTTP_400",
			}}
			writeReportRecords(t, path, records)
			rejected, evidence, _ := claudeAdmissionRejectedEvidence(binding, state.TurnID, state.PromptHash, since.UnixMilli())
			if rejected == nil {
				t.Fatal("missing original gateway refusal")
			}
			result := *rejected
			result.StopEvidence = evidence
			commandID := 0
			command := func(name string) string {
				return fmt.Sprintf("<command-name>/%s</command-name>\n <command-message>%s</command-message>\n <command-args></command-args>", name, name)
			}
			local := func(name, output string) []map[string]any {
				commandID++
				caveatID := fmt.Sprintf("00000000-0000-4000-8000-%012d", 10*commandID)
				requestID := fmt.Sprintf("00000000-0000-4000-8000-%012d", 10*commandID+1)
				outputID := fmt.Sprintf("00000000-0000-4000-8000-%012d", 10*commandID+2)
				record := func(value, id, parent string, meta bool) map[string]any {
					return map[string]any{
						"type": "user", "uuid": id, "parentUuid": parent, "sessionId": binding.ProviderID,
						"cwd": binding.Directory, "promptId": name, "isMeta": meta,
						"message": map[string]string{"content": value},
					}
				}
				return []map[string]any{
					record(claudeLocalCommandCaveat, caveatID, "", true),
					record(command(name), requestID, caveatID, false),
					record(output, outputID, requestID, false),
				}
			}
			switch name {
			case "unchanged model and exit":
				first, second := "00000000-0000-4000-8000-000000000090", "00000000-0000-4000-8000-000000000091"
				records = append(records,
					map[string]any{"type": "system", "subtype": "local_command", "uuid": first, "sessionId": binding.ProviderID, "cwd": binding.Directory, "content": command("model")},
					map[string]any{"type": "system", "subtype": "local_command", "uuid": second, "parentUuid": first, "sessionId": binding.ProviderID, "cwd": binding.Directory, "content": "<local-command-stdout>Kept model as `free`</local-command-stdout>", "commandRun": map[string]string{"command": "model", "args": ""}},
				)
			case "saved same model and exit":
				records = append(records, local("model", "<local-command-stdout>Set model to `free` and saved as your default for new sessions\x1b[2m\x1b[22m\n\x1b[2m     ANTHROPIC_MODEL is set to \x1b[22m`existing-main`\x1b[2m — new sessions use that while it is set\x1b[22m</local-command-stdout>")...)
			case "wrong model":
				records = append(records, local("model", "<local-command-stdout>Set model to `different` and saved as your default for new sessions</local-command-stdout>")...)
			case "wrong receipt":
				result.ErrorCode = "MODEL_ROUTE_NO_AVAILABLE_MEMBER"
			case "wrong finish":
				result.FinishedMS++
			case "wrong source digest":
				result.StopEvidence = strings.Repeat("a", 64)
			}
			if name != "exact" {
				exit := "<local-command-stdout>Bye!</local-command-stdout>"
				if name == "saved same model and exit" {
					exit = "<local-command-stdout>Goodbye!</local-command-stdout>"
				}
				records = append(records, local("exit", exit)...)
			}
			switch name {
			case "partial exit":
				records = records[:len(records)-1]
			case "foreign directory":
				records[len(records)-1]["cwd"] = t.TempDir()
			case "foreign provider":
				records[len(records)-1]["sessionId"] = "other"
			case "new work":
				records = append(records, map[string]any{"type": "user", "message": map[string]string{"content": "start next task"}})
			case "no idle proof":
				state.EndedIdle = false
			}
			writeReportRecords(t, path, records)
			want := name == "exact" || name == "exit" || name == "unchanged model and exit" || name == "saved same model and exit"
			if got := claudeAdmissionRecoveryProven(state, launch, result); got != want {
				t.Fatalf("recovery accepted=%v, expected=%v", got, want)
			}
		})
	}
}
