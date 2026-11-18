package agentproviders

import "testing"

func TestNativeModelIDOnlyPrefixesActiveClaudeGateway(t *testing.T) {
	v := View{ActiveID: "gateway", Current: CurrentModel{BaseURL: "http://localhost:1234"}, Profiles: []ProfileSummary{{ID: "gateway", Name: "Roami Gateway", BaseURL: "http://localhost:1234"}}}
	for _, tc := range []struct{ kind, model, want string }{
		{"claude", "free", "roami-claude/free"},
		{"claude", "roami-claude/free", "roami-claude/free"},
		{"claude", "", ""},
		{"codex", "free", "free"},
	} {
		if got := NativeModelID(tc.kind, tc.model, v); got != tc.want {
			t.Fatalf("%s/%s: %q, want %q", tc.kind, tc.model, got, tc.want)
		}
	}
	v.Current.BaseURL = "https://other.example"
	if NativeModelID("claude", "free", v) != "free" {
		t.Fatal("external provider changed")
	}
	v.Current.BaseURL = v.Profiles[0].BaseURL
	v.Profiles[0].Name = "Custom gateway"
	if NativeModelID("claude", "free", v) != "free" {
		t.Fatal("custom provider changed")
	}
}
