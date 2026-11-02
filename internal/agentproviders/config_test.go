package agentproviders

import (
	"bytes"
	"strings"
	"testing"
)

func TestJSONConfigPatchesPreserveCommentsAndUnrelatedSettings(t *testing.T) {
	original := []byte("{\n // keep plugin settings\n \"plugins\": [\"my-plugin\",],\n \"env\": {\"EXISTING\": \"yes\",},\n}\n")
	before := append([]byte{}, original...)
	if _, err := jsonDocument(original); err != nil || !bytes.Equal(original, before) {
		t.Fatalf("read mutated source: %s, %v", original, err)
	}
	updated, err := patchJSON(original, []string{"env", "ANTHROPIC_API_KEY"}, jsonValue("fake-key"))
	if err != nil {
		t.Fatal(err)
	}
	values, err := jsonDocument(updated)
	if err != nil || textAt(values, "env", "EXISTING") != "yes" || textAt(values, "env", "ANTHROPIC_API_KEY") != "fake-key" || !strings.Contains(string(updated), "// keep plugin settings") {
		t.Fatalf("patch lost fields or comments: %s, %v", updated, err)
	}
	if !bytes.Equal(original, before) {
		t.Fatal("patch mutated original bytes")
	}
	updated, err = patchJSON(updated, []string{"env", "ANTHROPIC_API_KEY"}, nil)
	values, _ = jsonDocument(updated)
	if err != nil || textAt(values, "env", "EXISTING") != "yes" || valueAt(values, []string{"env", "ANTHROPIC_API_KEY"}) != nil {
		t.Fatalf("remove lost neighboring fields: %s, %v", updated, err)
	}
	for _, invalid := range []string{`{"model":"first","model":"second"}`, `{"env":null}`, `[]`, `invalid`} {
		if _, err := patchJSON([]byte(invalid), []string{"env", "ANTHROPIC_API_KEY"}, jsonValue("fake-key")); err == nil {
			t.Fatalf("accepted ambiguous or invalid config: %s", invalid)
		}
	}
}

func TestTOMLConfigPatchesPreserveSharedSettingsAndQuotedTables(t *testing.T) {
	original := []byte(`# keep global preferences
model = 'old-model' # model comment
model_provider = "company"
notify = ["existing-hook"]
[mcp_servers.search]
command = "search-server"
[model_providers."company"]
name = "Company"
base_url = "https://example.com/v1"
`)
	before := append([]byte{}, original...)
	updated, err := patchTOML(original, []string{"model"}, jsonValue("custom-model"))
	if err != nil {
		t.Fatal(err)
	}
	for _, item := range []struct {
		path  []string
		value string
	}{
		{[]string{"model_provider"}, "roami_test"},
		{[]string{"model_providers", "roami_test", "name"}, "New Provider"},
		{[]string{"model_providers", "roami_test", "base_url"}, "https://custom.example/v1"},
		{[]string{"model_providers", "roami_test", "wire_api"}, "responses"},
	} {
		updated, err = patchTOML(updated, item.path, jsonValue(item.value))
		if err != nil {
			t.Fatalf("patch %v: %s, %v", item.path, updated, err)
		}
	}
	values, err := tomlDocument(updated)
	if err != nil || textAt(values, "model") != "custom-model" || textAt(values, "model_providers", "roami_test", "base_url") != "https://custom.example/v1" ||
		textAt(values, "mcp_servers", "search", "command") != "search-server" || textAt(values, "model_providers", "company", "name") != "Company" ||
		!strings.Contains(string(updated), "# model comment") || !strings.Contains(string(updated), `notify = ["existing-hook"]`) {
		t.Fatalf("TOML lost unrelated config: %s, %v", updated, err)
	}
	updated, err = patchTOML(updated, []string{"model"}, nil)
	values, _ = tomlDocument(updated)
	if err != nil || valueAt(values, []string{"model"}) != nil || textAt(values, "model_provider") != "roami_test" {
		t.Fatalf("remove failed: %s, %v", updated, err)
	}
	if !bytes.Equal(original, before) {
		t.Fatal("original mutated")
	}
}
