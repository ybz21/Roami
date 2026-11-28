package agentexecution

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ybz21/Roami/internal/modelgateway/catalog"
)

func TestClaudeSessionModelProofOnlyAcceptsBoundLocalSelection(t *testing.T) {
	binding := SessionBinding{ProviderID: completionThread, ProviderHome: t.TempDir(), Directory: "/fixture"}
	dir := filepath.Join(binding.ProviderHome, "projects", "fixture")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	transcript := filepath.Join(dir, binding.ProviderID+".jsonl")
	before := []byte(strings.Repeat("{\"type\":\"cost-state\"}\n", 1000))
	if err := os.WriteFile(transcript, before, 0600); err != nil {
		t.Fatal(err)
	}
	anchor, ok := claudeModelCheckpoint(binding)
	if !ok {
		t.Fatal("initial transcript was not anchored")
	}
	const model = "openrouter/free"
	const command = "<command-name>/model</command-name>\n  <command-message>model</command-message>\n  <command-args></command-args>"
	const selected = "<local-command-stdout>Set model to `" + model + "` for this session only</local-command-stdout>"
	record := func(prompt, content string, meta bool) string {
		t.Helper()
		data, err := json.Marshal(map[string]any{
			"type": "user", "sessionId": binding.ProviderID, "cwd": binding.Directory,
			"promptId": prompt, "isMeta": meta, "message": map[string]string{"content": content},
		})
		if err != nil {
			t.Fatal(err)
		}
		return string(data) + "\n"
	}
	prefix := record("picker", claudeLocalCommandCaveat, true) + record("picker", command, false)
	proof := prefix + record("picker", selected, false)
	commandWithArgs := strings.Replace(command, "<command-args></command-args>", "<command-args>free</command-args>", 1)
	for name, suffix := range map[string]string{
		"valid scoped selection": proof,
		"saved default":          prefix + record("picker", strings.ReplaceAll(selected, "for this session only", "and saved as your default for new sessions"), false),
		"other model":            prefix + record("picker", strings.ReplaceAll(selected, "openrouter/free", "paid"), false),
		"other prompt":           prefix + record("another-prompt", selected, false),
		"explicit model":         record("picker", claudeLocalCommandCaveat, true) + record("picker", commandWithArgs, false) + record("picker", selected, false),
		"next request":           proof + "{\"type\":\"api-request\"}\n",
		"repeated selection":     proof + proof,
		"partial record":         strings.TrimSuffix(proof, "\n"),
	} {
		t.Run(name, func(t *testing.T) {
			if err := os.WriteFile(transcript, append(append([]byte{}, before...), []byte(suffix)...), 0600); err != nil {
				t.Fatal(err)
			}
			got, ok := claudeSessionModelProof(binding, anchor, []string{model})
			if want := name == "valid scoped selection"; ok != want || want && (got.PromptID != "picker" || len(got.Digest) != 64) {
				t.Fatalf("proof = %#v, %v, want accepted = %v", got, ok, want)
			}
		})
	}
	if err := os.Rename(transcript, transcript+".old"); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(transcript, append(append([]byte{}, before...), []byte(proof)...), 0600); err != nil {
		t.Fatal(err)
	}
	if _, ok := claudeSessionModelProof(binding, anchor, []string{model}); ok {
		t.Fatal("replacement accepted as the original transcript")
	}
}

func TestClaudePickerRequiresAnExactGatewayLabelAndSessionOnlyAction(t *testing.T) {
	gateway := claudeGatewayCatalog{
		Models:            []catalog.CatalogModel{{ID: "route", Name: "openrouter/free"}, {ID: "other", Name: "openrouter/free-plus"}},
		QualifiedModelIDs: map[string]string{"route": "source/openrouter/free"},
	}
	want := claudePickerModel{Display: "openrouter/free", NativeID: "roami-claude/source/openrouter/free"}
	if got, err := claudePickerCatalogModel(gateway, "route"); err != nil || got != want {
		t.Fatalf("target = %v, %v", got, err)
	}
	gateway.Models[1].Name = want.Display
	if _, err := claudePickerCatalogModel(gateway, "route"); err == nil {
		t.Fatal("ambiguous display label accepted")
	}
	screen := "Select model\n  Your pick is the default for new sessions. For other models, use --model.\n" +
		"  ❯ 8. free ✔                          From gateway\n" +
		"    9. openrouter/free-plus             From gateway\n" +
		"   10. openrouter/free                  From gateway\n" +
		"    ↓ 12 more\n\n" + claudeModelSessionOnlyHint + "\n"
	if got, ok := claudePickerScreen(screen, want.Display); !ok || got != (claudeModelPicker{selected: 8, destination: 10, moreBelow: true}) {
		t.Fatalf("menu = %#v, %v", got, ok)
	}
	if _, ok := claudePickerScreen(strings.ReplaceAll(screen, claudeModelSessionOnlyHint, "Enter to save"), want.Display); ok {
		t.Fatal("default-only chooser accepted")
	}
	prompt := "Switch model?\n  ❯ 1. Yes, switch to openrouter/free\n    2. Cancel\n"
	if !claudePickerConfirmation(prompt, want.Display) || claudePickerConfirmation(prompt, "openrouter/free-plus") || claudePickerConfirmation(screen, want.Display) {
		t.Fatal("confirmation was not bound to exactly the selected target")
	}
}
