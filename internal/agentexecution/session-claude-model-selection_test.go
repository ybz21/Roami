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
	base := t.TempDir()
	binding := SessionBinding{ProviderID: completionThread, ProviderHome: t.TempDir(), Directory: filepath.Join(base, "fixture")}
	subdirectory := filepath.Join(binding.Directory, "materials", "snapshot")
	sibling := filepath.Join(base, "fixture-other")
	for _, path := range []string{subdirectory, sibling} {
		if err := os.MkdirAll(path, 0700); err != nil {
			t.Fatal(err)
		}
	}
	escape := filepath.Join(binding.Directory, "escape")
	if err := os.Symlink(sibling, escape); err != nil {
		t.Fatal(err)
	}
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
	atDirectory := func(data, directory string) string {
		from, _ := json.Marshal(binding.Directory)
		to, _ := json.Marshal(directory)
		return strings.ReplaceAll(data, string(from), string(to))
	}
	commandWithArgs := strings.Replace(command, "<command-args></command-args>", "<command-args>free</command-args>", 1)
	for _, tc := range []struct {
		name, suffix string
		accepted     bool
	}{
		{"valid scoped selection", proof, true},
		{"valid workspace subdirectory", atDirectory(proof, subdirectory), true},
		{"foreign sibling", atDirectory(proof, sibling), false},
		{"escaping symlink", atDirectory(proof, escape), false},
		{"relative directory", atDirectory(proof, "materials/snapshot"), false},
		{"missing directory", atDirectory(proof, ""), false},
		{"changed directory", atDirectory(prefix, subdirectory) + record("picker", selected, false), false},
		{"saved default", prefix + record("picker", strings.ReplaceAll(selected, "for this session only", "and saved as your default for new sessions"), false), false},
		{"other model", prefix + record("picker", strings.ReplaceAll(selected, "openrouter/free", "paid"), false), false},
		{"other prompt", prefix + record("another-prompt", selected, false), false},
		{"explicit model", record("picker", claudeLocalCommandCaveat, true) + record("picker", commandWithArgs, false) + record("picker", selected, false), false},
		{"next request", proof + "{\"type\":\"api-request\"}\n", false},
		{"repeated selection", proof + proof, false},
		{"partial record", strings.TrimSuffix(proof, "\n"), false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if err := os.WriteFile(transcript, append(append([]byte{}, before...), []byte(tc.suffix)...), 0600); err != nil {
				t.Fatal(err)
			}
			got, ok := claudeSessionModelProof(binding, anchor, []string{model})
			if ok != tc.accepted || tc.accepted && (got.PromptID != "picker" || len(got.Digest) != 64) {
				t.Fatalf("proof = %#v, %v, want accepted = %v", got, ok, tc.accepted)
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
